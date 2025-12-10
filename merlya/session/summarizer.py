"""
Merlya Session - Session Summarizer.

Hybrid summarization using ONNX extractive → LLM fallback → truncation.
Preserves key information while reducing token usage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage


@dataclass
class SummaryResult:
    """Result of summarization."""

    summary: str
    original_tokens: int
    summary_tokens: int
    compression_ratio: float
    method: str  # "onnx", "llm", "truncate"
    key_entities: list[str] = field(default_factory=list)
    key_actions: list[str] = field(default_factory=list)


class SessionSummarizer:
    """
    Hybrid session summarizer.

    Uses a cascade approach:
    1. ONNX extractive summarization (key sentences)
    2. LLM summarization (if ONNX output too long)
    3. Smart truncation (last resort)
    """

    # Key patterns to preserve in summaries
    KEY_PATTERNS = [
        r"@\w+",  # Host references
        r"error|failed|success|completed",  # Status indicators
        r"executed|ran|checked|found",  # Action verbs
        r"\d+\.\d+\.\d+\.\d+",  # IP addresses
        r"/[\w/.-]+",  # Paths
    ]

    def __init__(
        self,
        tier: str = "balanced",
        fallback_model: str | None = None,
        main_model: str | None = None,
        max_summary_tokens: int = 500,
    ) -> None:
        """
        Initialize the summarizer.

        Args:
            tier: ONNX model tier.
            fallback_model: Mini-LLM for summarization.
            main_model: Main LLM (last resort).
            max_summary_tokens: Target summary size.
        """
        self.tier = tier
        self.fallback_model = fallback_model
        self.main_model = main_model
        self.max_summary_tokens = max_summary_tokens

        self._onnx_extractor = None
        self._init_onnx_extractor()

    def _init_onnx_extractor(self) -> None:
        """Initialize ONNX extractive model if available."""
        try:
            # TODO: Load ONNX extractive summarization model
            # For now, use heuristic extraction
            logger.debug("📝 SessionSummarizer: Using heuristic extraction")
        except Exception as e:
            logger.debug(f"📝 SessionSummarizer: ONNX not available: {e}")

    def _estimate_tokens(self, text: str) -> int:
        """Quick token estimation."""
        return len(text) // 4  # ~4 chars per token

    def _extract_content(self, msg: ModelMessage) -> tuple[str, str]:
        """
        Extract role and content from message.

        Returns:
            Tuple of (role, content).
        """
        role = "unknown"
        content = ""

        if hasattr(msg, "kind"):
            role = msg.kind

        if hasattr(msg, "content"):
            if isinstance(msg.content, str):
                content = msg.content
            elif isinstance(msg.content, list):
                parts = []
                for part in msg.content:
                    if hasattr(part, "text"):
                        parts.append(part.text)
                    elif isinstance(part, str):
                        parts.append(part)
                content = " ".join(parts)

        return role, content

    def _extract_key_sentences(self, text: str, max_sentences: int = 10) -> list[str]:
        """
        Extract key sentences from text.

        Args:
            text: Input text.
            max_sentences: Maximum sentences to extract.

        Returns:
            List of key sentences.
        """
        # Split into sentences
        sentences = re.split(r"[.!?\n]+", text)
        sentences = [s.strip() for s in sentences if s.strip()]

        # Score sentences by key patterns
        scored: list[tuple[float, str]] = []

        for sentence in sentences:
            score = 0.0

            # Check for key patterns
            for pattern in self.KEY_PATTERNS:
                if re.search(pattern, sentence, re.IGNORECASE):
                    score += 0.2

            # Prefer shorter sentences (more likely to be key info)
            if len(sentence) < 100:
                score += 0.1

            # Prefer sentences with specific indicators
            if any(w in sentence.lower() for w in ["host", "server", "service"]):
                score += 0.15
            if any(w in sentence.lower() for w in ["error", "warning", "failed"]):
                score += 0.2
            if any(w in sentence.lower() for w in ["success", "completed", "done"]):
                score += 0.15

            scored.append((score, sentence))

        # Sort by score and take top sentences
        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:max_sentences]]

    def _extract_entities(self, messages: list[ModelMessage]) -> list[str]:
        """Extract key entities from messages."""
        entities: set[str] = set()

        for msg in messages:
            _, content = self._extract_content(msg)

            # Extract hosts
            hosts = re.findall(r"@(\w+)", content)
            entities.update(hosts)

            # Extract IPs
            ips = re.findall(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", content)
            entities.update(ips)

            # Extract services
            services = re.findall(
                r"\b(nginx|mysql|postgres|redis|docker)\b", content, re.IGNORECASE
            )
            entities.update(s.lower() for s in services)

        return list(entities)[:20]

    def _extract_actions(self, messages: list[ModelMessage]) -> list[str]:
        """Extract key actions from messages."""
        actions: list[str] = []

        action_patterns = [
            r"(executed|ran|checked|found|created|deleted|updated|fixed)",
            r"(ssh.*?to.*?@\w+)",
            r"(installed|configured|restarted|stopped|started)",
        ]

        for msg in messages:
            _, content = self._extract_content(msg)

            for pattern in action_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches:
                    if isinstance(match, tuple):
                        actions.append(match[0])
                    else:
                        actions.append(match)

        return list(dict.fromkeys(actions))[:10]  # Unique, preserve order

    async def summarize(
        self,
        messages: list[ModelMessage],
        context: str | None = None,
    ) -> SummaryResult:
        """
        Summarize a list of messages.

        Args:
            messages: Messages to summarize.
            context: Optional additional context.

        Returns:
            SummaryResult with compressed content.
        """
        if not messages:
            return SummaryResult(
                summary="",
                original_tokens=0,
                summary_tokens=0,
                compression_ratio=1.0,
                method="empty",
            )

        # Combine message content
        parts: list[str] = []
        for msg in messages:
            role, content = self._extract_content(msg)
            if content:
                parts.append(f"[{role}] {content}")

        full_text = "\n".join(parts)
        original_tokens = self._estimate_tokens(full_text)

        # Extract metadata
        key_entities = self._extract_entities(messages)
        key_actions = self._extract_actions(messages)

        # 1. ONNX extractive (heuristic for now)
        key_sentences = self._extract_key_sentences(full_text)
        extracted = " ".join(key_sentences)

        # If short enough, use extraction
        if self._estimate_tokens(extracted) <= self.max_summary_tokens:
            summary = self._format_summary(extracted, key_entities, key_actions)
            summary_tokens = self._estimate_tokens(summary)

            return SummaryResult(
                summary=summary,
                original_tokens=original_tokens,
                summary_tokens=summary_tokens,
                compression_ratio=summary_tokens / max(original_tokens, 1),
                method="extractive",
                key_entities=key_entities,
                key_actions=key_actions,
            )

        # 2. Try LLM summarization if available
        if self.fallback_model:
            try:
                llm_summary = await self._summarize_with_llm(
                    extracted, self.fallback_model
                )
                if llm_summary:
                    summary = self._format_summary(llm_summary, key_entities, key_actions)
                    summary_tokens = self._estimate_tokens(summary)

                    return SummaryResult(
                        summary=summary,
                        original_tokens=original_tokens,
                        summary_tokens=summary_tokens,
                        compression_ratio=summary_tokens / max(original_tokens, 1),
                        method="llm_fallback",
                        key_entities=key_entities,
                        key_actions=key_actions,
                    )
            except Exception as e:
                logger.warning(f"⚠️ LLM summarization failed: {e}")

        # 3. Smart truncation as last resort
        summary = self._smart_truncate(extracted, key_entities, key_actions)
        summary_tokens = self._estimate_tokens(summary)

        return SummaryResult(
            summary=summary,
            original_tokens=original_tokens,
            summary_tokens=summary_tokens,
            compression_ratio=summary_tokens / max(original_tokens, 1),
            method="truncate",
            key_entities=key_entities,
            key_actions=key_actions,
        )

    def _format_summary(
        self,
        text: str,
        entities: list[str],
        actions: list[str],
    ) -> str:
        """Format summary with metadata."""
        parts = []

        if entities:
            parts.append(f"Hosts/Services: {', '.join(entities[:5])}")

        if actions:
            parts.append(f"Actions: {', '.join(actions[:5])}")

        parts.append(f"Summary: {text}")

        return "\n".join(parts)

    def _smart_truncate(
        self,
        text: str,
        entities: list[str],
        actions: list[str],
    ) -> str:
        """
        Smart truncation preserving key info.

        Args:
            text: Text to truncate.
            entities: Key entities to preserve.
            actions: Key actions to preserve.

        Returns:
            Truncated text.
        """
        max_chars = self.max_summary_tokens * 4  # ~4 chars per token

        # Start with metadata
        header_parts = []
        if entities:
            header_parts.append(f"Hosts: {', '.join(entities[:5])}")
        if actions:
            header_parts.append(f"Actions: {', '.join(actions[:3])}")

        header = " | ".join(header_parts) if header_parts else ""
        remaining = max_chars - len(header) - 20  # Buffer

        # Truncate main text
        if len(text) > remaining:
            # Keep start and end
            half = remaining // 2
            text = text[:half] + " [...] " + text[-half:]

        return f"{header}\n{text}" if header else text

    async def _summarize_with_llm(self, text: str, model: str) -> str | None:
        """
        Summarize using LLM.

        Args:
            text: Text to summarize.
            model: Model to use.

        Returns:
            Summary or None if failed.
        """
        # TODO: Implement LLM summarization
        # This would call the model with a summarization prompt
        return None

    def estimate_savings(self, result: SummaryResult) -> str:
        """
        Generate human-readable savings estimate.

        Args:
            result: Summarization result.

        Returns:
            Formatted string.
        """
        saved = result.original_tokens - result.summary_tokens
        pct = (1 - result.compression_ratio) * 100

        return (
            f"📉 Summarized: {result.original_tokens:,} → {result.summary_tokens:,} tokens "
            f"(saved {saved:,}, {pct:.1f}% reduction, method={result.method})"
        )
