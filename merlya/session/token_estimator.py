"""
Merlya Session - Token Estimator.

Provides token count estimation for messages and context management.
Uses tiktoken when available, falls back to character-based estimation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from loguru import logger

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage


# Constants (N3)
DEFAULT_CHARS_PER_TOKEN = 4.0  # Conservative estimate for plain text
CODE_CHARS_PER_TOKEN = 3.0  # Code is often more token-dense
JSON_CHARS_PER_TOKEN = 2.5  # JSON has many small tokens
MESSAGE_OVERHEAD_TOKENS = 4  # Tokens added per message (role, formatting)
COMPLETION_RATIO = 0.25  # Estimate completion as 25% of prompt
MAX_COMPLETION_ESTIMATE = 2000  # Cap completion estimate
DEFAULT_CONTEXT_LIMIT = 8192  # Default if model not found


@dataclass
class TokenEstimate:
    """Token estimation result."""

    total_tokens: int
    prompt_tokens: int
    completion_estimate: int
    model: str
    method: str  # "tiktoken" or "heuristic"


class TokenEstimator:
    """
    Estimates token counts for messages.

    Uses tiktoken for accurate counts when available,
    falls back to heuristic estimation otherwise.

    Example:
        >>> estimator = TokenEstimator(model="gpt-4")
        >>> tokens = estimator.estimate_tokens("Hello, world!")
        >>> print(f"Estimated tokens: {tokens}")
    """

    # Model-specific context limits
    MODEL_LIMITS: ClassVar[dict[str, int]] = {
        "gpt-4": 8192,
        "gpt-4-32k": 32768,
        "gpt-4-turbo": 128000,
        "gpt-4o": 128000,
        "gpt-3.5-turbo": 4096,
        "gpt-3.5-turbo-16k": 16384,
        "claude-3-opus": 200000,
        "claude-3-sonnet": 200000,
        "claude-3-haiku": 200000,
        "claude-3.5-sonnet": 200000,
        "mistral-small": 32000,
        "mistral-medium": 32000,
        "mistral-large": 128000,
        "groq-llama": 8192,
        "groq-mixtral": 32768,
    }

    def __init__(self, model: str = "gpt-4") -> None:
        """
        Initialize the token estimator.

        Args:
            model: Model name for context limits.
        """
        self.model = model
        self._encoder = None
        self._tiktoken_available = False

        # Try to load tiktoken
        try:
            import tiktoken

            # Try to get encoding for the specified model, fall back to cl100k_base
            try:
                self._encoder = tiktoken.encoding_for_model(model)
            except KeyError:
                # Model not recognized, use cl100k_base (GPT-4/Claude compatible)
                self._encoder = tiktoken.get_encoding("cl100k_base")
            self._tiktoken_available = True
            logger.debug("📊 TokenEstimator: Using tiktoken for accurate counts")
        except ImportError:
            logger.debug("📊 TokenEstimator: Using heuristic estimation")

    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for a text string.

        Args:
            text: Text to estimate.

        Returns:
            Estimated token count.
        """
        if not text:
            return 0

        if self._tiktoken_available and self._encoder:
            return len(self._encoder.encode(text))

        # Heuristic estimation
        return self._estimate_heuristic(text)

    def _estimate_heuristic(self, text: str) -> int:
        """
        Heuristic token estimation based on content type.

        Args:
            text: Text to estimate.

        Returns:
            Estimated token count.
        """
        # Detect content type
        has_code = "```" in text or bool(re.search(r"^\s{4,}", text, re.MULTILINE))
        has_json = "{" in text and "}" in text and '"' in text

        if has_json:
            chars_per_token = JSON_CHARS_PER_TOKEN
        elif has_code:
            chars_per_token = CODE_CHARS_PER_TOKEN
        else:
            chars_per_token = DEFAULT_CHARS_PER_TOKEN

        # Base estimate (content only, overhead added by estimate_messages)
        base_tokens = len(text) / chars_per_token
        return int(base_tokens)

    def estimate_messages(self, messages: list[ModelMessage]) -> TokenEstimate:
        """
        Estimate tokens for a list of messages.

        Args:
            messages: List of model messages.

        Returns:
            TokenEstimate with breakdown.

        Example:
            >>> from dataclasses import dataclass
            >>> @dataclass
            ... class MockMsg:
            ...     content: str
            >>> msgs = [MockMsg(content="Hello"), MockMsg(content="World")]
            >>> estimate = estimator.estimate_messages(msgs)
        """
        prompt_tokens = 0

        for msg in messages:
            # Extract text content from message
            content = self._extract_content(msg)
            prompt_tokens += self.estimate_tokens(content)

            # Add message overhead (role, formatting)
            prompt_tokens += MESSAGE_OVERHEAD_TOKENS

        # Estimate completion (typically 20-30% of prompt for assistant)
        completion_estimate = min(
            int(prompt_tokens * COMPLETION_RATIO),
            MAX_COMPLETION_ESTIMATE,
        )

        return TokenEstimate(
            total_tokens=prompt_tokens + completion_estimate,
            prompt_tokens=prompt_tokens,
            completion_estimate=completion_estimate,
            model=self.model,
            method="tiktoken" if self._tiktoken_available else "heuristic",
        )

    def _extract_content(self, msg: ModelMessage) -> str:
        """Extract text content from a model message."""
        # Handle different message types
        if hasattr(msg, "content"):
            content = msg.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                # Multi-part content
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

    def get_context_limit(self, model: str | None = None) -> int:
        """
        Get the context limit for a model.

        Args:
            model: Model name (uses default if None).

        Returns:
            Maximum context tokens.

        Example:
            >>> estimator = TokenEstimator()
            >>> limit = estimator.get_context_limit("gpt-4")
            >>> print(f"Context limit: {limit}")
        """
        model_name = model or self.model

        # Try exact match
        if model_name in self.MODEL_LIMITS:
            return self.MODEL_LIMITS[model_name]

        # Try partial match
        model_lower = model_name.lower()
        for key, limit in self.MODEL_LIMITS.items():
            if key in model_lower or model_lower in key:
                return limit

        # Default conservative limit
        return DEFAULT_CONTEXT_LIMIT

    def estimate_remaining(
        self,
        messages: list[ModelMessage],
        model: str | None = None,
    ) -> int:
        """
        Estimate remaining tokens in context window.

        Args:
            messages: Current messages.
            model: Model name.

        Returns:
            Estimated remaining tokens.
        """
        estimate = self.estimate_messages(messages)
        limit = self.get_context_limit(model)

        remaining = limit - estimate.total_tokens
        return max(0, remaining)

    def will_exceed_limit(
        self,
        messages: list[ModelMessage],
        new_content: str,
        model: str | None = None,
        buffer: int = 1000,
    ) -> bool:
        """
        Check if adding content would exceed context limit.

        Args:
            messages: Current messages.
            new_content: Content to add.
            model: Model name.
            buffer: Safety buffer tokens.

        Returns:
            True if would exceed limit.
        """
        current = self.estimate_messages(messages)
        new_tokens = self.estimate_tokens(new_content)

        limit = self.get_context_limit(model)

        return (current.total_tokens + new_tokens + buffer) > limit

    def summarize_estimate(self, estimate: TokenEstimate) -> str:
        """
        Create a human-readable summary of token estimate.

        Args:
            estimate: Token estimate.

        Returns:
            Formatted string.
        """
        limit = self.get_context_limit(estimate.model)

        if limit:
            pct = (estimate.total_tokens / limit) * 100
            pct_str = f"{pct:.1f}%"
        else:
            pct_str = "N/A"

        return (
            f"📊 Tokens: {estimate.prompt_tokens:,} prompt + "
            f"~{estimate.completion_estimate:,} completion = "
            f"{estimate.total_tokens:,} ({pct_str} of {limit:,} limit)"
        )
