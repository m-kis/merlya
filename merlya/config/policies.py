"""
Merlya Config - Policy Manager.

Manages execution policies with automatic context tier detection.
Integrates with ContextTierPredictor for dynamic policy adjustment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from merlya.config.models import PolicyConfig
from merlya.session.context_tier import (
    TIER_CONFIG,
    ContextTier,
    ContextTierPredictor,
    TierLimits,
)

if TYPE_CHECKING:
    from merlya.router.classifier import RouterResult


@dataclass
class EffectivePolicy:
    """Effective policy after context tier resolution.

    Combines PolicyConfig defaults with tier-specific limits.
    """

    # Resolved context tier
    context_tier: ContextTier

    # Tier-specific limits
    max_messages: int
    max_tokens: int
    parser_backend: str
    summarize_threshold: float

    # From PolicyConfig
    max_tokens_per_call: int
    parser_confidence_threshold: float
    max_hosts_per_skill: int
    max_parallel_subagents: int
    subagent_timeout: int
    require_confirmation_for_write: bool
    audit_logging: bool
    max_messages_in_memory: int
    auto_summarize: bool

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary."""
        return {
            "context_tier": self.context_tier.value,
            "max_messages": self.max_messages,
            "max_tokens": self.max_tokens,
            "parser_backend": self.parser_backend,
            "summarize_threshold": self.summarize_threshold,
            "max_tokens_per_call": self.max_tokens_per_call,
            "parser_confidence_threshold": self.parser_confidence_threshold,
            "max_hosts_per_skill": self.max_hosts_per_skill,
            "max_parallel_subagents": self.max_parallel_subagents,
            "subagent_timeout": self.subagent_timeout,
            "require_confirmation_for_write": self.require_confirmation_for_write,
            "audit_logging": self.audit_logging,
            "max_messages_in_memory": self.max_messages_in_memory,
            "auto_summarize": self.auto_summarize,
        }


class PolicyManager:
    """Manages execution policies with automatic context tier detection.

    Uses ContextTierPredictor when context_tier is "auto", otherwise
    respects the manual override from PolicyConfig.

    Example:
        >>> manager = PolicyManager(config)
        >>> policy = await manager.get_effective_policy(user_input, router_result)
        >>> print(f"Using tier: {policy.context_tier.value}")
    """

    def __init__(self, config: PolicyConfig | None = None) -> None:
        """
        Initialize the policy manager.

        Args:
            config: Policy configuration. Uses defaults if None.
        """
        self.config = config or PolicyConfig()
        self.tier_predictor = ContextTierPredictor()

        logger.debug(
            f"PolicyManager initialized (tier={self.config.context_tier}, "
            f"auto_summarize={self.config.auto_summarize})"
        )

    async def get_effective_policy(
        self,
        user_input: str | None = None,
        router_result: RouterResult | None = None,
    ) -> EffectivePolicy:
        """
        Get effective policy for the current context.

        Args:
            user_input: User message for tier prediction.
            router_result: Router classification result.

        Returns:
            EffectivePolicy with resolved tier limits.
        """
        # Resolve context tier
        tier = await self._resolve_tier(user_input, router_result)

        # Get tier-specific limits
        tier_limits = TIER_CONFIG[tier]

        # Use config's summarize_threshold if manual, else tier's
        summarize_threshold = (
            self.config.summarize_threshold
            if self.config.context_tier != "auto"
            else tier_limits.summarize_threshold
        )

        return EffectivePolicy(
            context_tier=tier,
            max_messages=tier_limits.max_messages,
            max_tokens=tier_limits.max_tokens,
            parser_backend=tier_limits.parser_backend,
            summarize_threshold=summarize_threshold,
            max_tokens_per_call=self.config.max_tokens_per_call,
            parser_confidence_threshold=self.config.parser_confidence_threshold,
            max_hosts_per_skill=self.config.max_hosts_per_skill,
            max_parallel_subagents=self.config.max_parallel_subagents,
            subagent_timeout=self.config.subagent_timeout,
            require_confirmation_for_write=self.config.require_confirmation_for_write,
            audit_logging=self.config.audit_logging,
            max_messages_in_memory=self.config.max_messages_in_memory,
            auto_summarize=self.config.auto_summarize,
        )

    async def _resolve_tier(
        self,
        user_input: str | None,
        router_result: RouterResult | None,
    ) -> ContextTier:
        """
        Resolve the context tier.

        Args:
            user_input: User message for prediction.
            router_result: Router classification result.

        Returns:
            Resolved ContextTier.
        """
        tier_setting = self.config.context_tier.lower()

        # Manual override
        if tier_setting == "minimal":
            return ContextTier.MINIMAL
        if tier_setting == "standard":
            return ContextTier.STANDARD
        if tier_setting == "extended":
            return ContextTier.EXTENDED

        # Auto detection
        if user_input:
            tier = await self.tier_predictor.predict(user_input, router_result)
            logger.debug(f"Auto-detected tier: {tier.value}")
            return tier

        # Default for auto without input
        return ContextTier.STANDARD

    def should_summarize(
        self,
        current_messages: int,
        current_tokens: int,
        tier: ContextTier | None = None,
    ) -> bool:
        """
        Check if summarization should be triggered.

        Args:
            current_messages: Current message count.
            current_tokens: Current token count.
            tier: Optional tier override (uses config default if None).

        Returns:
            True if summarization should be triggered.
        """
        if not self.config.auto_summarize:
            return False

        # Get limits for tier
        effective_tier = tier or self._get_default_tier()
        limits = TIER_CONFIG[effective_tier]

        # Use config threshold
        threshold = self.config.summarize_threshold

        # Protect against division by zero
        if limits.max_messages <= 0 or limits.max_tokens <= 0:
            logger.warning("Invalid tier limits (zero or negative), skipping summarization check")
            return False

        messages_pct = current_messages / limits.max_messages
        tokens_pct = current_tokens / limits.max_tokens

        return messages_pct > threshold or tokens_pct > threshold

    def should_confirm(self, operation: str) -> bool:
        """
        Check if an operation requires confirmation.

        Args:
            operation: Operation type (e.g., "write", "delete", "restart").

        Returns:
            True if confirmation is required.
        """
        if not self.config.require_confirmation_for_write:
            return False

        # Destructive operations that require confirmation
        destructive_ops = {
            "write",
            "delete",
            "remove",
            "restart",
            "stop",
            "kill",
            "reboot",
            "shutdown",
            "truncate",
            "drop",
        }

        return operation.lower() in destructive_ops

    def validate_hosts_count(self, host_count: int) -> tuple[bool, str | None]:
        """
        Validate number of hosts for skill execution.

        Args:
            host_count: Number of hosts to execute on.

        Returns:
            Tuple of (is_valid, error_message).
        """
        if host_count < 0:
            return (False, f"Host count cannot be negative ({host_count}).")
        if host_count == 0:
            return (False, "Host count cannot be zero.")
        if host_count > self.config.max_hosts_per_skill:
            return (
                False,
                f"Host count ({host_count}) exceeds maximum "
                f"({self.config.max_hosts_per_skill}). "
                f"Adjust policy.max_hosts_per_skill to increase.",
            )
        return True, None

    def validate_tokens(self, estimated_tokens: int) -> tuple[bool, str | None]:
        """
        Validate token count for LLM call.

        Args:
            estimated_tokens: Estimated token count.

        Returns:
            Tuple of (is_valid, error_message).
        """
        if estimated_tokens < 0:
            return (False, f"Token count cannot be negative ({estimated_tokens}).")
        if estimated_tokens > self.config.max_tokens_per_call:
            return (
                False,
                f"Token count ({estimated_tokens:,}) exceeds maximum "
                f"({self.config.max_tokens_per_call:,}). "
                f"Consider summarizing context.",
            )
        return True, None

    def _get_default_tier(self) -> ContextTier:
        """Get default tier based on config."""
        tier_setting = self.config.context_tier.lower()

        if tier_setting == "minimal":
            return ContextTier.MINIMAL
        if tier_setting == "extended":
            return ContextTier.EXTENDED

        return ContextTier.STANDARD

    def get_tier_limits(self, tier: ContextTier | None = None) -> TierLimits:
        """
        Get limits for a tier.

        Args:
            tier: Tier to get limits for. Uses default if None.

        Returns:
            TierLimits for the tier.
        """
        effective_tier = tier or self._get_default_tier()
        return TIER_CONFIG[effective_tier]

    def get_stats(self) -> dict[str, object]:
        """Get current policy statistics."""
        return {
            "context_tier": self.config.context_tier,
            "max_tokens_per_call": self.config.max_tokens_per_call,
            "max_hosts_per_skill": self.config.max_hosts_per_skill,
            "max_parallel_subagents": self.config.max_parallel_subagents,
            "auto_summarize": self.config.auto_summarize,
            "require_confirmation_for_write": self.config.require_confirmation_for_write,
            "audit_logging": self.config.audit_logging,
        }
