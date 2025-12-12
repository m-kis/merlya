"""
Merlya Session - Session Manager.

Manages conversation context, token budgets, and automatic summarization.
Integrates TokenEstimator, ContextTierPredictor, and SessionSummarizer.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic_ai import ModelMessagesTypeAdapter
from pydantic_ai.messages import ModelMessage, ModelRequest, SystemPromptPart

from merlya.session.context_tier import (
    TIER_CONFIG,
    ContextTier,
    ContextTierPredictor,
    TierLimits,
)
from merlya.session.summarizer import SessionSummarizer, SummaryResult
from merlya.session.token_estimator import TokenEstimate, TokenEstimator

if TYPE_CHECKING:
    from merlya.persistence.database import Database
    from merlya.router.classifier import RouterResult

# UUID validation pattern
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# Session limits
MAX_MESSAGES_IN_MEMORY = 1000


def _utc_now() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


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
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

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

    _instance: SessionManager | None = None

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

        # Lock for concurrent access (M3)
        self._lock = asyncio.Lock()

        # Store as singleton
        SessionManager._instance = self

        logger.debug(f"📋 SessionManager initialized (model={model})")

    @classmethod
    def get_instance(cls) -> SessionManager | None:
        """Get the singleton instance."""
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (for testing)."""
        cls._instance = None

    @property
    def current_tier(self) -> ContextTier | None:
        """Get current context tier."""
        if self._session:
            return self._session.tier
        return self.default_tier

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
        async with self._lock:
            return await self._start_session_unlocked(conversation_id, tier)

    async def _start_session_unlocked(
        self,
        conversation_id: str | None = None,
        tier: ContextTier | None = None,
    ) -> SessionState:
        """Internal start_session without lock (for use within locked contexts)."""
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
        async with self._lock:
            if not self._session:
                await self._start_session_unlocked()

            assert self._session is not None

            # Check memory limit (M4)
            if len(self._session.messages) >= MAX_MESSAGES_IN_MEMORY:
                logger.warning(
                    f"⚠️ Memory limit reached ({MAX_MESSAGES_IN_MEMORY} messages), "
                    "forcing summarization"
                )
                await self._trigger_summarization()

            # Add message
            self._session.messages.append(message)
            self._session.message_count += 1
            self._session.updated_at = _utc_now()

            # Update token count
            content = self._extract_content(message)
            tokens = self.token_estimator.estimate_tokens(content)
            self._session.token_count += tokens

            # Check if tier adjustment needed (first message)
            if self._session.message_count == 1 and router_result:
                new_tier = await self.tier_predictor.predict(content, router_result)
                if new_tier != self._session.tier:
                    logger.info(f"🎯 Tier adjusted: {self._session.tier.value} → {new_tier.value}")
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
                parts: list[str] = []
                for part in content:
                    # Type-safe extraction with None check
                    if isinstance(part, str):
                        parts.append(part)
                    elif hasattr(part, "text"):
                        text = getattr(part, "text", None)
                        if isinstance(text, str):
                            parts.append(text)
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

    async def get_effective_messages(self) -> list[ModelMessage]:
        """
        Get messages ready for LLM, including summary as system message.

        Returns:
            List of ModelMessage with summary prepended if available.
        """
        async with self._lock:
            if not self._session:
                return []

            messages: list[ModelMessage] = []

            # Add summary as context using ModelRequest with SystemPromptPart
            if self._session.summary:
                summary_part = SystemPromptPart(
                    content=f"Previous conversation summary:\n{self._session.summary}",
                )
                messages.append(ModelRequest(parts=[summary_part]))

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
            logger.warning(f"⚠️ Token limit will be exceeded: {total:,} > {limit:,}")

        return result

    async def _persist_session(self) -> None:
        """Persist session and messages to database using UPSERT."""
        if not self.db or not self._session:
            return

        try:
            # Use transaction context manager for automatic rollback on error
            async with self.db.transaction():
                # Persist session metadata
                await self.db.execute(
                    """
                    INSERT OR REPLACE INTO sessions (
                        id, conversation_id, summary, token_count, message_count,
                        context_tier, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._session.id,
                        self._session.conversation_id,
                        self._session.summary,
                        self._session.token_count,
                        self._session.message_count,
                        self._session.tier.value,
                        self._session.created_at,
                        _utc_now(),
                    ),
                )

                # Persist messages - delete existing and insert current state
                await self.db.execute(
                    "DELETE FROM session_messages WHERE session_id = ?",
                    (self._session.id,),
                )

                if self._session.messages:
                    # Serialize each message individually for granular storage
                    message_rows = []
                    for seq_num, msg in enumerate(self._session.messages):
                        # Serialize single message to JSON
                        msg_data = ModelMessagesTypeAdapter.dump_json([msg]).decode("utf-8")
                        message_rows.append((self._session.id, seq_num, msg_data))

                    await self.db.executemany(
                        """
                        INSERT INTO session_messages (session_id, sequence_num, message_data)
                        VALUES (?, ?, ?)
                        """,
                        message_rows,
                    )
                # Commit is handled by transaction context manager

        except Exception as e:
            logger.warning(f"⚠️ Failed to persist session: {e}")

    async def load_session(self, session_id: str) -> SessionState | None:
        """
        Load a session from database, including message history.

        Args:
            session_id: Session ID to load.

        Returns:
            SessionState with restored messages, or None if not found.

        Raises:
            ValueError: If session_id is not a valid UUID.
        """
        # M1: Validate UUID format
        if not UUID_PATTERN.match(session_id):
            raise ValueError(f"Invalid session ID format: {session_id}")

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

            # Safe enum deserialization with fallback
            try:
                tier = ContextTier(row["context_tier"])
            except ValueError:
                logger.warning(
                    f"⚠️ Invalid context_tier '{row['context_tier']}', defaulting to STANDARD"
                )
                tier = ContextTier.STANDARD

            self._session = SessionState(
                id=row["id"],
                conversation_id=row["conversation_id"],
                tier=tier,
                summary=row["summary"],
                token_count=row["token_count"] or 0,
                message_count=row["message_count"] or 0,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

            # Load messages from session_messages table
            messages = await self._load_session_messages(session_id)
            self._session.messages = messages

            # Apply retention limit if needed
            if len(self._session.messages) > MAX_MESSAGES_IN_MEMORY:
                self._session.messages = self._session.messages[-MAX_MESSAGES_IN_MEMORY:]
                logger.debug(f"📋 Trimmed loaded messages to {MAX_MESSAGES_IN_MEMORY}")

            logger.info(
                f"📋 Session loaded: {session_id[:8]}... ({len(self._session.messages)} messages)"
            )
            return self._session

        # M2: Catch specific exceptions
        except (KeyError, TypeError) as e:
            logger.error(f"❌ Invalid session data: {e}")
            return None
        except OSError as e:
            logger.error(f"❌ Database I/O error: {e}")
            return None

    async def _load_session_messages(self, session_id: str) -> list[ModelMessage]:
        """
        Load messages for a session from database.

        Args:
            session_id: Session ID to load messages for.

        Returns:
            List of ModelMessage in chronological order.
        """
        if not self.db:
            return []

        messages: list[ModelMessage] = []

        try:
            async with await self.db.execute(
                """
                SELECT message_data FROM session_messages
                WHERE session_id = ?
                ORDER BY sequence_num ASC
                """,
                (session_id,),
            ) as cursor:
                rows = await cursor.fetchall()

            for row in rows:
                try:
                    # Deserialize message from JSON
                    msg_list = ModelMessagesTypeAdapter.validate_json(row["message_data"])
                    # Each row contains a single message serialized as a list
                    if msg_list:
                        messages.extend(msg_list)
                except Exception as e:
                    logger.warning(f"⚠️ Failed to deserialize message: {e}")
                    # Skip corrupted messages but continue loading others

        except Exception as e:
            logger.warning(f"⚠️ Failed to load session messages: {e}")

        return messages

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
