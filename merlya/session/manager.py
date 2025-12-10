"""
Merlya Session - Session Manager.

Manages conversation context, token budgets, and automatic summarization.
Integrates TokenEstimator, ContextTierPredictor, and SessionSummarizer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.session.context_tier import (
    TIER_CONFIG,
    ContextTier,
    ContextTierPredictor,
    TierLimits,
)
from merlya.session.summarizer import SessionSummarizer, SummaryResult
from merlya.session.token_estimator import TokenEstimate, TokenEstimator

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage

    from merlya.persistence.database import Database
    from merlya.router.classifier import RouterResult


@dataclass
class SessionState:
    """Current session state."""

    id: str
    conversation_id: str | None
    tier: ContextTier
    messages: list[ModelMessage] = field(default_factory=list)
    summary: str | None = None
    token_count: int = 0
    message_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for persistence."""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "tier": self.tier.value,
            "summary": self.summary,
            "token_count": self.token_count,
            "message_count": self.message_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class ContextWindow:
    """Current context window for LLM."""

    messages: list[ModelMessage]
    summary: str | None
    token_estimate: TokenEstimate
    tier: ContextTier
    limits: TierLimits


class SessionManager:
    """
    Manages session context and token budgets.

    Responsibilities:
    - Track messages and token counts
    - Auto-detect optimal context tier
    - Trigger summarization when needed
    - Persist session state to database
    """

    def __init__(
        self,
        db: Database | None = None,
        model: str = "gpt-4",
        default_tier: ContextTier = ContextTier.STANDARD,
    ) -> None:
        """
        Initialize the session manager.

        Args:
            db: Database for persistence.
            model: LLM model name.
            default_tier: Default context tier.
        """
        self.db = db
        self.model = model
        self.default_tier = default_tier

        # Components
        self.token_estimator = TokenEstimator(model=model)
        self.tier_predictor = ContextTierPredictor()
        self.summarizer = SessionSummarizer()

        # Current session
        self._session: SessionState | None = None

        logger.debug(f"📋 SessionManager initialized (model={model})")

    @property
    def session(self) -> SessionState | None:
        """Get current session."""
        return self._session

    @property
    def tier(self) -> ContextTier:
        """Get current tier."""
        if self._session:
            return self._session.tier
        return self.default_tier

    @property
    def limits(self) -> TierLimits:
        """Get current tier limits."""
        return TIER_CONFIG[self.tier]

    async def start_session(
        self,
        conversation_id: str | None = None,
        tier: ContextTier | None = None,
    ) -> SessionState:
        """
        Start a new session.

        Args:
            conversation_id: Optional conversation to associate with.
            tier: Optional tier override.

        Returns:
            New SessionState.
        """
        session_id = str(uuid.uuid4())

        self._session = SessionState(
            id=session_id,
            conversation_id=conversation_id,
            tier=tier or self.default_tier,
        )

        logger.info(f"📋 Session started: {session_id[:8]}... (tier={self._session.tier.value})")

        # Persist if db available
        if self.db:
            await self._persist_session()

        return self._session

    async def add_message(
        self,
        message: ModelMessage,
        router_result: RouterResult | None = None,
    ) -> None:
        """
        Add a message to the session.

        Args:
            message: Message to add.
            router_result: Optional router result for tier prediction.
        """
        if not self._session:
            await self.start_session()

        assert self._session is not None

        # Add message
        self._session.messages.append(message)
        self._session.message_count += 1
        self._session.updated_at = datetime.now()

        # Update token count
        content = self._extract_content(message)
        tokens = self.token_estimator.estimate_tokens(content)
        self._session.token_count += tokens

        # Check if tier adjustment needed (first message)
        if self._session.message_count == 1 and router_result:
            new_tier = await self.tier_predictor.predict(content, router_result)
            if new_tier != self._session.tier:
                logger.info(
                    f"🎯 Tier adjusted: {self._session.tier.value} → {new_tier.value}"
                )
                self._session.tier = new_tier

        # Check if summarization needed
        if self._should_summarize():
            await self._trigger_summarization()

        logger.debug(
            f"📋 Message added: {self._session.message_count} messages, "
            f"{self._session.token_count} tokens"
        )

    def _extract_content(self, msg: ModelMessage) -> str:
        """Extract text content from message."""
        if hasattr(msg, "content"):
            content = msg.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for part in content:
                    if hasattr(part, "text"):
                        parts.append(part.text)
                    elif isinstance(part, str):
                        parts.append(part)
                return " ".join(parts)
        return str(msg)

    def _should_summarize(self) -> bool:
        """Check if summarization is needed."""
        if not self._session:
            return False

        limits = self.limits
        threshold = limits.summarize_threshold

        messages_pct = self._session.message_count / limits.max_messages
        tokens_pct = self._session.token_count / limits.max_tokens

        return messages_pct > threshold or tokens_pct > threshold

    async def _trigger_summarization(self) -> None:
        """Trigger automatic summarization."""
        if not self._session or not self._session.messages:
            return

        logger.info("📉 Triggering automatic summarization...")

        # Keep last few messages
        keep_count = min(5, len(self._session.messages))
        to_summarize = self._session.messages[:-keep_count]
        to_keep = self._session.messages[-keep_count:]

        if not to_summarize:
            return

        # Summarize older messages
        result = await self.summarizer.summarize(to_summarize)

        # Update session
        old_summary = self._session.summary or ""
        if old_summary:
            self._session.summary = f"{old_summary}\n\n{result.summary}"
        else:
            self._session.summary = result.summary

        # Replace messages with kept ones
        self._session.messages = to_keep

        # Recalculate token count
        self._session.token_count = self.token_estimator.estimate_tokens(
            self._session.summary or ""
        )
        for msg in to_keep:
            content = self._extract_content(msg)
            self._session.token_count += self.token_estimator.estimate_tokens(content)

        self._session.message_count = len(to_keep)

        logger.info(self.summarizer.estimate_savings(result))

        # Persist
        if self.db:
            await self._persist_session()

    async def get_context_window(self) -> ContextWindow:
        """
        Get the current context window for LLM.

        Returns:
            ContextWindow with messages and metadata.
        """
        if not self._session:
            await self.start_session()

        assert self._session is not None

        # Estimate tokens
        estimate = self.token_estimator.estimate_messages(self._session.messages)

        # Add summary tokens if present
        if self._session.summary:
            summary_tokens = self.token_estimator.estimate_tokens(self._session.summary)
            estimate = TokenEstimate(
                total_tokens=estimate.total_tokens + summary_tokens,
                prompt_tokens=estimate.prompt_tokens + summary_tokens,
                completion_estimate=estimate.completion_estimate,
                model=estimate.model,
                method=estimate.method,
            )

        return ContextWindow(
            messages=self._session.messages,
            summary=self._session.summary,
            token_estimate=estimate,
            tier=self._session.tier,
            limits=self.limits,
        )

    async def get_effective_messages(self) -> list[Any]:
        """
        Get messages ready for LLM, including summary as system message.

        Returns:
            List of messages with summary prepended if available.
        """
        if not self._session:
            return []

        messages = []

        # Add summary as context
        if self._session.summary:
            # This would be formatted as a system message
            # The actual format depends on the model being used
            messages.append({
                "role": "system",
                "content": f"Previous conversation summary:\n{self._session.summary}",
            })

        # Add current messages
        messages.extend(self._session.messages)

        return messages

    async def estimate_next_call(self, new_content: str) -> dict[str, Any]:
        """
        Estimate tokens for next LLM call.

        Args:
            new_content: New content to add.

        Returns:
            Dict with estimates and warnings.
        """
        context = await self.get_context_window()

        new_tokens = self.token_estimator.estimate_tokens(new_content)
        total = context.token_estimate.total_tokens + new_tokens

        limit = context.limits.max_tokens
        pct = (total / limit) * 100

        result = {
            "current_tokens": context.token_estimate.total_tokens,
            "new_tokens": new_tokens,
            "total_tokens": total,
            "limit": limit,
            "usage_percent": pct,
            "will_exceed": total > limit,
            "should_summarize": pct > (context.limits.summarize_threshold * 100),
        }

        if result["will_exceed"]:
            logger.warning(
                f"⚠️ Token limit will be exceeded: {total:,} > {limit:,}"
            )

        return result

    async def _persist_session(self) -> None:
        """Persist session to database."""
        if not self.db or not self._session:
            return

        try:
            # Check if session exists
            async with await self.db.execute(
                "SELECT id FROM sessions WHERE id = ?",
                (self._session.id,),
            ) as cursor:
                exists = await cursor.fetchone()

            if exists:
                # Update
                await self.db.execute(
                    """
                    UPDATE sessions
                    SET summary = ?, token_count = ?, context_tier = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        self._session.summary,
                        self._session.token_count,
                        self._session.tier.value,
                        datetime.now(),
                        self._session.id,
                    ),
                )
            else:
                # Insert
                await self.db.execute(
                    """
                    INSERT INTO sessions (id, conversation_id, summary, token_count,
                                         context_tier, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._session.id,
                        self._session.conversation_id,
                        self._session.summary,
                        self._session.token_count,
                        self._session.tier.value,
                        self._session.created_at,
                        self._session.updated_at,
                    ),
                )

            await self.db.connection.commit()

        except Exception as e:
            logger.warning(f"⚠️ Failed to persist session: {e}")

    async def load_session(self, session_id: str) -> SessionState | None:
        """
        Load a session from database.

        Args:
            session_id: Session ID to load.

        Returns:
            SessionState or None if not found.
        """
        if not self.db:
            return None

        try:
            async with await self.db.execute(
                "SELECT * FROM sessions WHERE id = ?",
                (session_id,),
            ) as cursor:
                row = await cursor.fetchone()

            if not row:
                return None

            self._session = SessionState(
                id=row["id"],
                conversation_id=row["conversation_id"],
                tier=ContextTier(row["context_tier"]),
                summary=row["summary"],
                token_count=row["token_count"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

            logger.info(f"📋 Session loaded: {session_id[:8]}...")
            return self._session

        except Exception as e:
            logger.error(f"❌ Failed to load session: {e}")
            return None

    async def end_session(self) -> SummaryResult | None:
        """
        End the current session.

        Returns:
            Final summary if messages exist.
        """
        if not self._session:
            return None

        result = None

        # Final summarization
        if self._session.messages:
            result = await self.summarizer.summarize(self._session.messages)
            self._session.summary = result.summary

            # Persist final state
            if self.db:
                await self._persist_session()

        logger.info(f"📋 Session ended: {self._session.id[:8]}...")
        self._session = None

        return result

    def get_stats(self) -> dict[str, Any]:
        """Get current session statistics."""
        if not self._session:
            return {"active": False}

        limits = self.limits

        return {
            "active": True,
            "id": self._session.id[:8],
            "tier": self._session.tier.value,
            "messages": self._session.message_count,
            "tokens": self._session.token_count,
            "max_messages": limits.max_messages,
            "max_tokens": limits.max_tokens,
            "messages_pct": (self._session.message_count / limits.max_messages) * 100,
            "tokens_pct": (self._session.token_count / limits.max_tokens) * 100,
            "has_summary": self._session.summary is not None,
        }
