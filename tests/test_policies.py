"""
Tests for Policy configuration and PolicyManager.

Tests PolicyConfig model, PolicyManager, and EffectivePolicy.
"""

from __future__ import annotations

import pytest

from merlya.config.models import PolicyConfig
from merlya.config.policies import EffectivePolicy, PolicyManager
from merlya.session.context_tier import TIER_CONFIG, ContextTier


class TestPolicyConfig:
    """Tests for PolicyConfig model."""

    def test_default_values(self):
        """Test default configuration values."""
        config = PolicyConfig()

        assert config.context_tier == "auto"
        assert config.max_tokens_per_call == 8000
        assert config.parser_confidence_threshold == 0.6
        assert config.max_hosts_per_skill == 10
        assert config.max_parallel_subagents == 5
        assert config.subagent_timeout == 120
        assert config.require_confirmation_for_write is True
        assert config.audit_logging is True
        assert config.max_messages_in_memory == 1000
        assert config.auto_summarize is True
        assert config.summarize_threshold == 0.75

    def test_custom_values(self):
        """Test custom configuration values."""
        config = PolicyConfig(
            context_tier="extended",
            max_tokens_per_call=16000,
            max_hosts_per_skill=20,
            require_confirmation_for_write=False,
        )

        assert config.context_tier == "extended"
        assert config.max_tokens_per_call == 16000
        assert config.max_hosts_per_skill == 20
        assert config.require_confirmation_for_write is False

    def test_validation_min_max(self):
        """Test validation of min/max constraints."""
        from pydantic import ValidationError

        # max_tokens_per_call too low
        with pytest.raises(ValidationError):
            PolicyConfig(max_tokens_per_call=500)

        # max_hosts_per_skill too high
        with pytest.raises(ValidationError):
            PolicyConfig(max_hosts_per_skill=200)

        # summarize_threshold out of range
        with pytest.raises(ValidationError):
            PolicyConfig(summarize_threshold=0.3)

    def test_valid_context_tiers(self):
        """Test all valid context tier values."""
        for tier in ["auto", "minimal", "standard", "extended"]:
            config = PolicyConfig(context_tier=tier)
            assert config.context_tier == tier


class TestPolicyManager:
    """Tests for PolicyManager."""

    @pytest.fixture
    def manager(self):
        """Create a policy manager with defaults."""
        return PolicyManager()

    @pytest.fixture
    def custom_manager(self):
        """Create a policy manager with custom config."""
        config = PolicyConfig(
            context_tier="extended",
            max_tokens_per_call=16000,
            max_hosts_per_skill=20,
        )
        return PolicyManager(config)

    @pytest.mark.asyncio
    async def test_get_effective_policy_auto(self, manager):
        """Test getting effective policy with auto tier."""
        policy = await manager.get_effective_policy(
            user_input="List all hosts",
        )

        assert isinstance(policy, EffectivePolicy)
        assert policy.context_tier in (ContextTier.MINIMAL, ContextTier.STANDARD)
        assert policy.max_tokens_per_call == 8000

    @pytest.mark.asyncio
    async def test_get_effective_policy_manual_tier(self, custom_manager):
        """Test getting effective policy with manual tier."""
        policy = await custom_manager.get_effective_policy()

        assert policy.context_tier == ContextTier.EXTENDED
        assert policy.max_tokens == TIER_CONFIG[ContextTier.EXTENDED].max_tokens
        assert policy.max_messages == TIER_CONFIG[ContextTier.EXTENDED].max_messages

    @pytest.mark.asyncio
    async def test_effective_policy_to_dict(self, manager):
        """Test EffectivePolicy.to_dict()."""
        policy = await manager.get_effective_policy()

        d = policy.to_dict()

        assert "context_tier" in d
        assert "max_messages" in d
        assert "max_tokens" in d
        assert "auto_summarize" in d

    def test_should_summarize_disabled(self):
        """Test should_summarize when disabled."""
        config = PolicyConfig(auto_summarize=False)
        manager = PolicyManager(config)

        # Should never summarize when disabled
        assert not manager.should_summarize(100, 10000)

    def test_should_summarize_below_threshold(self, manager):
        """Test should_summarize below threshold."""
        # STANDARD tier: 30 messages, 4000 tokens
        # With 0.75 threshold: 22.5 messages, 3000 tokens
        assert not manager.should_summarize(
            current_messages=10,
            current_tokens=1000,
            tier=ContextTier.STANDARD,
        )

    def test_should_summarize_above_threshold(self, manager):
        """Test should_summarize above threshold."""
        # STANDARD tier: 30 messages, 4000 tokens
        # With 0.75 threshold: 22.5 messages, 3000 tokens
        assert manager.should_summarize(
            current_messages=25,
            current_tokens=3500,
            tier=ContextTier.STANDARD,
        )

    def test_should_confirm_destructive(self, manager):
        """Test should_confirm for destructive operations."""
        assert manager.should_confirm("delete")
        assert manager.should_confirm("restart")
        assert manager.should_confirm("kill")
        assert manager.should_confirm("DROP")  # Case insensitive

    def test_should_confirm_safe(self, manager):
        """Test should_confirm for safe operations."""
        assert not manager.should_confirm("read")
        assert not manager.should_confirm("list")
        assert not manager.should_confirm("status")

    def test_should_confirm_disabled(self):
        """Test should_confirm when disabled."""
        config = PolicyConfig(require_confirmation_for_write=False)
        manager = PolicyManager(config)

        # Should never require confirmation when disabled
        assert not manager.should_confirm("delete")
        assert not manager.should_confirm("restart")

    def test_validate_hosts_count_valid(self, manager):
        """Test validate_hosts_count with valid count."""
        is_valid, error = manager.validate_hosts_count(5)
        assert is_valid is True
        assert error is None

    def test_validate_hosts_count_invalid(self, manager):
        """Test validate_hosts_count with count exceeding limit."""
        is_valid, error = manager.validate_hosts_count(20)
        assert is_valid is False
        assert "exceeds maximum" in error

    def test_validate_hosts_count_negative(self, manager):
        """Test validate_hosts_count with negative value."""
        is_valid, error = manager.validate_hosts_count(-1)
        assert is_valid is False
        assert "negative" in error

    def test_validate_hosts_count_zero(self, manager):
        """Test validate_hosts_count with zero value."""
        is_valid, error = manager.validate_hosts_count(0)
        assert is_valid is False
        assert "zero" in error

    def test_validate_tokens_valid(self, manager):
        """Test validate_tokens with valid count."""
        is_valid, error = manager.validate_tokens(4000)
        assert is_valid is True
        assert error is None

    def test_validate_tokens_invalid(self, manager):
        """Test validate_tokens with count exceeding limit."""
        is_valid, error = manager.validate_tokens(10000)
        assert is_valid is False
        assert "exceeds maximum" in error

    def test_validate_tokens_negative(self, manager):
        """Test validate_tokens with negative value."""
        is_valid, error = manager.validate_tokens(-100)
        assert is_valid is False
        assert "negative" in error

    def test_get_tier_limits(self, manager):
        """Test get_tier_limits."""
        limits = manager.get_tier_limits(ContextTier.MINIMAL)

        assert limits.max_messages == 10
        assert limits.max_tokens == 2000

    def test_get_stats(self, manager):
        """Test get_stats."""
        stats = manager.get_stats()

        assert "context_tier" in stats
        assert "max_tokens_per_call" in stats
        assert "auto_summarize" in stats
        assert stats["context_tier"] == "auto"


class TestEffectivePolicy:
    """Tests for EffectivePolicy dataclass."""

    def test_creation(self):
        """Test creating an EffectivePolicy."""
        policy = EffectivePolicy(
            context_tier=ContextTier.STANDARD,
            max_messages=30,
            max_tokens=4000,
            parser_backend="balanced",
            summarize_threshold=0.75,
            max_tokens_per_call=8000,
            parser_confidence_threshold=0.6,
            max_hosts_per_skill=10,
            max_parallel_subagents=5,
            subagent_timeout=120,
            require_confirmation_for_write=True,
            audit_logging=True,
            max_messages_in_memory=1000,
            auto_summarize=True,
        )

        assert policy.context_tier == ContextTier.STANDARD
        assert policy.max_messages == 30
        assert policy.auto_summarize is True

    def test_to_dict(self):
        """Test to_dict serialization."""
        policy = EffectivePolicy(
            context_tier=ContextTier.EXTENDED,
            max_messages=100,
            max_tokens=8000,
            parser_backend="performance",
            summarize_threshold=0.7,
            max_tokens_per_call=16000,
            parser_confidence_threshold=0.7,
            max_hosts_per_skill=20,
            max_parallel_subagents=10,
            subagent_timeout=180,
            require_confirmation_for_write=False,
            audit_logging=True,
            max_messages_in_memory=2000,
            auto_summarize=True,
        )

        d = policy.to_dict()

        assert d["context_tier"] == "extended"
        assert d["max_messages"] == 100
        assert d["max_tokens_per_call"] == 16000
        assert d["require_confirmation_for_write"] is False


class TestPolicyManagerTierResolution:
    """Tests for tier resolution logic."""

    @pytest.mark.asyncio
    async def test_resolve_minimal(self):
        """Test resolving minimal tier."""
        config = PolicyConfig(context_tier="minimal")
        manager = PolicyManager(config)

        policy = await manager.get_effective_policy()

        assert policy.context_tier == ContextTier.MINIMAL
        assert policy.max_messages == 10

    @pytest.mark.asyncio
    async def test_resolve_standard(self):
        """Test resolving standard tier."""
        config = PolicyConfig(context_tier="standard")
        manager = PolicyManager(config)

        policy = await manager.get_effective_policy()

        assert policy.context_tier == ContextTier.STANDARD
        assert policy.max_messages == 30

    @pytest.mark.asyncio
    async def test_resolve_extended(self):
        """Test resolving extended tier."""
        config = PolicyConfig(context_tier="extended")
        manager = PolicyManager(config)

        policy = await manager.get_effective_policy()

        assert policy.context_tier == ContextTier.EXTENDED
        assert policy.max_messages == 100

    @pytest.mark.asyncio
    async def test_resolve_auto_simple_query(self):
        """Test auto tier resolution for simple query."""
        config = PolicyConfig(context_tier="auto")
        manager = PolicyManager(config)

        policy = await manager.get_effective_policy(
            user_input="List hosts",
        )

        # Simple query should get MINIMAL or STANDARD
        assert policy.context_tier in (ContextTier.MINIMAL, ContextTier.STANDARD)

    @pytest.mark.asyncio
    async def test_resolve_auto_complex_query(self):
        """Test auto tier resolution for complex query."""
        config = PolicyConfig(context_tier="auto")
        manager = PolicyManager(config)

        complex_input = """
        Multiple hosts are showing errors:
        @web-01, @web-02, @db-01

        Error logs:
        ```
        ERROR 2024-01-15 connection refused
        ERROR 2024-01-15 timeout on db connection
        ```

        Need to diagnose and fix this incident.
        """

        policy = await manager.get_effective_policy(user_input=complex_input)

        # Complex query should get STANDARD or EXTENDED
        assert policy.context_tier in (ContextTier.STANDARD, ContextTier.EXTENDED)
