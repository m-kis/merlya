"""
Tests for /model command and subcommands.

Tests model management commands including provider switching,
model configuration, router settings, and connection testing.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.commands.handlers import init_commands
from merlya.commands.registry import CommandRegistry, get_registry
from merlya.i18n.loader import I18n


@pytest.fixture
def registry() -> CommandRegistry:
    """Get initialized command registry."""
    init_commands()
    return get_registry()


@pytest.fixture
def mock_context() -> MagicMock:
    """Create a mock SharedContext with all required attributes."""
    ctx = MagicMock(
        spec=["ui", "hosts", "variables", "conversations", "secrets", "i18n", "config", "t"]
    )

    # Mock UI
    ctx.ui = MagicMock()
    ctx.ui.prompt = AsyncMock(return_value="test_value")
    ctx.ui.prompt_confirm = AsyncMock(return_value=True)
    ctx.ui.prompt_secret = AsyncMock(return_value="secret_value")
    ctx.ui.info = MagicMock()
    ctx.ui.muted = MagicMock()
    ctx.ui.success = MagicMock()
    ctx.ui.warning = MagicMock()
    ctx.ui.error = MagicMock()
    ctx.ui.spinner = MagicMock(return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()))

    # Mock i18n
    ctx.i18n = I18n("en")
    ctx.t = ctx.i18n.t

    # Mock config
    ctx.config = MagicMock()
    ctx.config.general = MagicMock()
    ctx.config.general.data_dir = Path(tempfile.mkdtemp())
    ctx.config.model = MagicMock()
    ctx.config.model.provider = "openrouter"
    ctx.config.model.model = "z-ai/glm-4.6"
    ctx.config.model.reasoning_model = None
    ctx.config.model.fast_model = None
    ctx.config.model.api_key_env = "OPENROUTER_API_KEY"
    ctx.config.model.base_url = None
    # Mock the model getter methods for brain/fast
    ctx.config.model.get_orchestrator_model = MagicMock(return_value="z-ai/glm-4.6")
    ctx.config.model.get_fast_model = MagicMock(
        return_value="mistralai/mistral-small-3.1-24b-instruct:free"
    )
    ctx.config.router = MagicMock()
    ctx.config.router.type = "local"
    ctx.config.router.tier = None
    ctx.config.router.model = None
    ctx.config.router.llm_fallback = "openrouter:openrouter/auto"
    ctx.config.save = MagicMock()

    # Mock secrets
    ctx.secrets = MagicMock()
    ctx.secrets.list_keys = MagicMock(return_value=["OPENROUTER_API_KEY"])
    ctx.secrets.set = MagicMock()
    ctx.secrets.get = MagicMock(return_value="secret")
    ctx.secrets.delete = MagicMock()
    ctx.secrets.has = MagicMock(return_value=True)

    return ctx


class TestModelShowCommand:
    """Tests for /model show command."""

    async def test_model_show(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /model show displays current configuration with brain/fast models."""
        result = await registry.execute(mock_context, "/model show")
        assert result is not None
        assert result.success is True
        assert "Model Configuration" in result.message
        assert "openrouter" in result.message
        # New format shows brain and fast models
        assert "brain" in result.message
        assert "fast" in result.message
        assert "z-ai/glm-4.6" in result.message

    async def test_model_no_args_shows_config(
        self, registry: CommandRegistry, mock_context: MagicMock
    ):
        """Test /model without args defaults to show."""
        result = await registry.execute(mock_context, "/model")
        assert result is not None
        assert result.success is True
        assert "Model Configuration" in result.message


class TestModelProviderCommand:
    """Tests for /model provider command."""

    async def test_provider_no_args(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /model provider without args shows usage."""
        result = await registry.execute(mock_context, "/model provider")
        assert result is not None
        assert result.success is False
        assert "Usage" in result.message
        assert "openrouter" in result.message

    async def test_provider_unknown(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /model provider with unknown provider."""
        result = await registry.execute(mock_context, "/model provider unknown")
        assert result is not None
        assert result.success is False
        assert "Unknown provider" in result.message

    async def test_provider_anthropic_with_key(
        self, registry: CommandRegistry, mock_context: MagicMock
    ):
        """Test /model provider anthropic when API key exists."""
        mock_context.secrets.has = MagicMock(return_value=True)
        result = await registry.execute(mock_context, "/model provider anthropic")
        assert result is not None
        assert result.success is True
        assert "anthropic" in result.message.lower()
        mock_context.config.save.assert_called()
        assert result.data == {"reload_agent": True}

    async def test_provider_anthropic_prompts_key(
        self, registry: CommandRegistry, mock_context: MagicMock
    ):
        """Test /model provider anthropic prompts for API key if missing."""
        mock_context.secrets.has = MagicMock(return_value=False)
        mock_context.ui.prompt_secret = AsyncMock(return_value="sk-ant-xxx")
        result = await registry.execute(mock_context, "/model provider anthropic")
        assert result is not None
        assert result.success is True
        mock_context.secrets.set.assert_called_with("ANTHROPIC_API_KEY", "sk-ant-xxx")

    async def test_provider_ollama_no_key_needed(
        self, registry: CommandRegistry, mock_context: MagicMock
    ):
        """Test /model provider ollama doesn't require API key."""
        with patch("merlya.commands.handlers.model.ensure_provider_env"):
            result = await registry.execute(mock_context, "/model provider ollama")
            assert result is not None
            assert result.success is True
            # Ollama doesn't prompt for API key
            mock_context.ui.prompt_secret.assert_not_called()


class TestModelBrainFastCommands:
    """Tests for /model brain and /model fast commands."""

    async def test_model_brain_no_args(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /model brain without args shows current brain model."""
        result = await registry.execute(mock_context, "/model brain")
        assert result is not None
        assert result.success is True
        assert "Brain Model" in result.message
        assert "z-ai/glm-4.6" in result.message
        assert "reasoning" in result.message.lower()

    async def test_model_brain_change(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /model brain changes the brain model."""
        with patch("merlya.commands.handlers.model.ensure_provider_env"):
            result = await registry.execute(mock_context, "/model brain gpt-4o")
            assert result is not None
            assert result.success is True
            assert "brain" in result.message.lower()
            assert mock_context.config.model.model == "gpt-4o"
            mock_context.config.save.assert_called()
            assert result.data == {"reload_agent": True}

    async def test_model_fast_no_args(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /model fast without args shows current fast model."""
        result = await registry.execute(mock_context, "/model fast")
        assert result is not None
        assert result.success is True
        assert "Fast Model" in result.message
        assert "routing" in result.message.lower()

    async def test_model_fast_change(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /model fast changes the fast model."""
        with patch("merlya.commands.handlers.model.ensure_provider_env"):
            result = await registry.execute(mock_context, "/model fast gpt-4o-mini")
            assert result is not None
            assert result.success is True
            assert "fast" in result.message.lower()
            assert mock_context.config.model.fast_model == "gpt-4o-mini"
            mock_context.config.save.assert_called()
            assert result.data == {"reload_agent": True}


class TestModelModelCommand:
    """Tests for /model model command - DEPRECATED."""

    async def test_model_model_no_args(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /model model without args shows deprecation message."""
        result = await registry.execute(mock_context, "/model model")
        assert result is not None
        assert result.success is False
        # Now shows deprecation message instead of Usage
        assert "DEPRECATED" in result.message
        assert "brain" in result.message
        assert "fast" in result.message

    async def test_model_model_change(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /model model changes the model (redirects to brain)."""
        with patch("merlya.commands.handlers.model.ensure_provider_env"):
            result = await registry.execute(mock_context, "/model model gpt-4o")
            assert result is not None
            assert result.success is True
            # Redirects to brain model
            assert mock_context.config.model.model == "gpt-4o"
            mock_context.config.save.assert_called()
            assert result.data == {"reload_agent": True}


class TestModelRouterCommand:
    """Tests for /model router command - DEPRECATED."""

    async def test_router_shows_deprecation(
        self, registry: CommandRegistry, mock_context: MagicMock
    ):
        """Test /model router shows deprecation message."""
        result = await registry.execute(mock_context, "/model router")
        assert result is not None
        assert result.success is False
        assert "deprecated" in result.message.lower()
        assert "Orchestrator" in result.message

    async def test_router_any_args_shows_deprecation(
        self, registry: CommandRegistry, mock_context: MagicMock
    ):
        """Test /model router with any args shows deprecation."""
        result = await registry.execute(mock_context, "/model router show")
        assert result is not None
        assert result.success is False
        assert "deprecated" in result.message.lower()
        assert "orchestrator" in result.message.lower()


class TestModelTestCommand:
    """Tests for /model test command."""

    async def test_model_test_success(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /model test with successful connection."""
        with patch("pydantic_ai.Agent") as mock_agent_class:
            mock_result = MagicMock(spec=[])  # Empty spec to avoid auto-creating attributes
            mock_result.data = "OK"
            mock_result.output = "OK"
            mock_agent = MagicMock()
            mock_agent.run = AsyncMock(return_value=mock_result)
            mock_agent_class.return_value = mock_agent

            result = await registry.execute(mock_context, "/model test")
            assert result is not None
            assert result.success is True
            assert "LLM connection OK" in result.message

    async def test_model_test_failure(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /model test with failed connection."""
        with patch("pydantic_ai.Agent") as mock_agent_class:
            mock_agent_class.side_effect = Exception("Connection refused")

            result = await registry.execute(mock_context, "/model test")
            assert result is not None
            assert result.success is False
            assert "failed" in result.message.lower()


class TestOllamaIntegration:
    """Tests for Ollama-specific functionality."""

    async def test_ollama_brain_model_pulls(
        self, registry: CommandRegistry, mock_context: MagicMock
    ):
        """Test /model brain triggers ollama pull for ollama provider."""
        mock_context.config.model.provider = "ollama"
        mock_context.config.model.base_url = "http://localhost:11434/v1"

        with (
            patch("shutil.which", return_value="/usr/local/bin/ollama"),
            patch("asyncio.create_subprocess_exec") as mock_subprocess,
            patch("merlya.commands.handlers.model.ensure_provider_env"),
            patch("merlya.commands.handlers.model.ollama_requires_api_key", return_value=False),
        ):
            mock_proc = MagicMock()
            mock_proc.communicate = AsyncMock(return_value=(b"success", b""))
            mock_proc.returncode = 0
            mock_subprocess.return_value = mock_proc

            result = await registry.execute(mock_context, "/model brain llama3.2")
            assert result is not None
            assert result.success is True
            mock_subprocess.assert_called_once()

    async def test_ollama_fast_model_pulls(
        self, registry: CommandRegistry, mock_context: MagicMock
    ):
        """Test /model fast triggers ollama pull for ollama provider."""
        mock_context.config.model.provider = "ollama"
        mock_context.config.model.base_url = "http://localhost:11434/v1"

        with (
            patch("shutil.which", return_value="/usr/local/bin/ollama"),
            patch("asyncio.create_subprocess_exec") as mock_subprocess,
            patch("merlya.commands.handlers.model.ensure_provider_env"),
            patch("merlya.commands.handlers.model.ollama_requires_api_key", return_value=False),
        ):
            mock_proc = MagicMock()
            mock_proc.communicate = AsyncMock(return_value=(b"success", b""))
            mock_proc.returncode = 0
            mock_subprocess.return_value = mock_proc

            result = await registry.execute(mock_context, "/model fast mistral:7b")
            assert result is not None
            assert result.success is True
            mock_subprocess.assert_called_once()

    async def test_ollama_pull_model_not_found(
        self, registry: CommandRegistry, mock_context: MagicMock
    ):
        """Test /model brain with non-existent ollama model."""
        mock_context.config.model.provider = "ollama"
        mock_context.config.model.base_url = "http://localhost:11434/v1"

        with (
            patch("shutil.which", return_value="/usr/local/bin/ollama"),
            patch("asyncio.create_subprocess_exec") as mock_subprocess,
            patch("merlya.commands.handlers.model.ensure_provider_env"),
            patch("merlya.commands.handlers.model.ollama_requires_api_key", return_value=False),
        ):
            mock_proc = MagicMock()
            mock_proc.communicate = AsyncMock(return_value=(b"", b"model not found"))
            mock_proc.returncode = 1
            mock_subprocess.return_value = mock_proc

            result = await registry.execute(mock_context, "/model brain nonexistent-model")
            assert result is not None
            assert result.success is False
