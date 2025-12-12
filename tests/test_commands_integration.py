"""
Integration tests for all slash commands.

Tests each command with their subcommands and options to ensure
they execute without errors.
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

    # Mock i18n
    ctx.i18n = I18n("en")
    ctx.i18n.set_language = MagicMock(wraps=ctx.i18n.set_language)
    ctx.t = ctx.i18n.t

    # Mock config
    ctx.config = MagicMock()
    ctx.config.logging = MagicMock()
    ctx.config.logging.file_level = "info"
    ctx.config.logging.max_size_mb = 10
    ctx.config.logging.retention_days = 7
    ctx.config.logging.max_files = 5
    ctx.config.general = MagicMock()
    ctx.config.general.data_dir = Path(tempfile.mkdtemp())
    ctx.config.general.language = "en"
    ctx.config.model = MagicMock()
    ctx.config.model.provider = "openrouter"
    ctx.config.model.model = "x-ai/grok-4.1-fast:free"
    ctx.config.model.api_key_env = "OPENROUTER_API_KEY"
    ctx.config.model.base_url = None
    ctx.config.router = MagicMock()
    ctx.config.router.type = "local"
    ctx.config.router.tier = None
    ctx.config.router.llm_fallback = "openrouter:x-ai/grok-4.1-fast:free"
    ctx.config.save = MagicMock()

    # Mock secrets
    ctx.secrets = MagicMock()
    ctx.secrets.list_keys = MagicMock(return_value=["API_KEY"])
    ctx.secrets.set = MagicMock()
    ctx.secrets.get = MagicMock(return_value="secret")
    ctx.secrets.delete = MagicMock()
    ctx.secrets.has = MagicMock(return_value=True)

    return ctx


@pytest.fixture
def mock_hosts_repo(mock_context: MagicMock) -> MagicMock:
    """Configure hosts repository mock."""
    from merlya.persistence.models import Host

    test_host = Host(
        name="test-host",
        hostname="192.168.1.1",
        port=22,
        username="admin",
        tags=["web", "prod"],
        health_status="healthy",
    )

    mock_context.hosts = MagicMock()
    mock_context.hosts.get_all = AsyncMock(return_value=[test_host])
    mock_context.hosts.get_by_name = AsyncMock(return_value=test_host)
    mock_context.hosts.get_by_tag = AsyncMock(return_value=[test_host])
    mock_context.hosts.create = AsyncMock(return_value=test_host)
    mock_context.hosts.update = AsyncMock(return_value=test_host)
    mock_context.hosts.delete = AsyncMock(return_value=True)
    mock_context.hosts.count = AsyncMock(return_value=1)

    return mock_context.hosts


@pytest.fixture
def mock_variables_repo(mock_context: MagicMock) -> MagicMock:
    """Configure variables repository mock."""
    from merlya.persistence.models import Variable

    test_var = Variable(name="test_var", value="test_value", is_env=False)

    mock_context.variables = MagicMock()
    mock_context.variables.get_all = AsyncMock(return_value=[test_var])
    mock_context.variables.get = AsyncMock(return_value=test_var)
    mock_context.variables.set = AsyncMock(return_value=test_var)
    mock_context.variables.delete = AsyncMock(return_value=True)

    return mock_context.variables


@pytest.fixture
def mock_conversations_repo(mock_context: MagicMock) -> MagicMock:
    """Configure conversations repository mock."""
    from datetime import datetime

    from merlya.persistence.models import Conversation

    test_conv = Conversation(
        id="conv-123",
        title="Test conversation",
        messages=[{"role": "user", "content": "Hello"}],
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_context.conversations = MagicMock()
    mock_context.conversations.get_recent = AsyncMock(return_value=[test_conv])
    mock_context.conversations.get_by_id = AsyncMock(return_value=test_conv)
    mock_context.conversations.create = AsyncMock(return_value=test_conv)
    mock_context.conversations.update = AsyncMock(return_value=test_conv)
    mock_context.conversations.delete = AsyncMock(return_value=True)
    mock_context.conversations.search = AsyncMock(return_value=[test_conv])

    return mock_context.conversations


# =============================================================================
# Core Commands Tests
# =============================================================================


class TestHelpCommand:
    """Tests for /help command."""

    async def test_help_no_args(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /help without arguments."""
        result = await registry.execute(mock_context, "/help")
        assert result is not None
        assert result.success is True
        # Help uses ui.table() for displaying commands
        mock_context.ui.table.assert_called_once()

    async def test_help_with_command(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /help with specific command."""
        result = await registry.execute(mock_context, "/help hosts")
        assert result is not None
        assert result.success is True
        # Help uses ui.panel() for specific command details
        mock_context.ui.panel.assert_called_once()

    async def test_help_unknown_command(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /help with unknown command."""
        result = await registry.execute(mock_context, "/help nonexistent")
        assert result is not None
        assert result.success is False


class TestExitCommand:
    """Tests for /exit command."""

    async def test_exit(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /exit command."""
        result = await registry.execute(mock_context, "/exit")
        assert result is not None
        assert result.success is True
        assert result.data == {"exit": True}


class TestNewCommand:
    """Tests for /new command."""

    async def test_new(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /new command."""
        result = await registry.execute(mock_context, "/new")
        assert result is not None
        assert result.success is True
        assert result.data == {"new_conversation": True}


class TestLanguageCommand:
    """Tests for /language command."""

    async def test_language_show_current(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /language without args shows current."""
        result = await registry.execute(mock_context, "/language")
        assert result is not None
        assert result.success is True
        assert "en" in result.message

    async def test_language_change(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /language fr changes language."""
        result = await registry.execute(mock_context, "/language fr")
        assert result is not None
        assert result.success is True
        mock_context.i18n.set_language.assert_called_with("fr")

    async def test_language_invalid(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /language with invalid language."""
        result = await registry.execute(mock_context, "/language de")
        assert result is not None
        assert result.success is False


# =============================================================================
# Variable Commands Tests
# =============================================================================


class TestVariableCommand:
    """Tests for /variable command."""

    async def test_variable_list(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_variables_repo: MagicMock,
    ):
        """Test /variable list."""
        result = await registry.execute(mock_context, "/variable list")
        assert result is not None
        assert result.success is True
        # Variable list uses ui.table() for display
        mock_context.ui.table.assert_called_once()

    async def test_variable_no_args(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_variables_repo: MagicMock,
    ):
        """Test /variable without args defaults to list."""
        result = await registry.execute(mock_context, "/variable")
        assert result is not None
        assert result.success is True

    async def test_variable_set(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_variables_repo: MagicMock
    ):
        """Test /variable set name value."""
        result = await registry.execute(mock_context, "/variable set myvar myvalue")
        assert result is not None
        assert result.success is True
        mock_variables_repo.set.assert_called_once()

    async def test_variable_set_with_env(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_variables_repo: MagicMock
    ):
        """Test /variable set name value --env."""
        result = await registry.execute(mock_context, "/variable set myvar myvalue --env")
        assert result is not None
        assert result.success is True
        mock_variables_repo.set.assert_called_with("myvar", "myvalue", is_env=True)

    async def test_variable_get(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_variables_repo: MagicMock,
    ):
        """Test /variable get name."""
        result = await registry.execute(mock_context, "/variable get test_var")
        assert result is not None
        assert result.success is True
        assert result.data == "test_value"

    async def test_variable_delete(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_variables_repo: MagicMock,
    ):
        """Test /variable delete name."""
        result = await registry.execute(mock_context, "/variable delete test_var")
        assert result is not None
        assert result.success is True


# =============================================================================
# Secret Commands Tests
# =============================================================================


class TestSecretCommand:
    """Tests for /secret command."""

    async def test_secret_list(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /secret list."""
        result = await registry.execute(mock_context, "/secret list")
        assert result is not None
        assert result.success is True
        assert "API_KEY" in result.message

    async def test_secret_set(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /secret set name."""
        result = await registry.execute(mock_context, "/secret set MY_SECRET")
        assert result is not None
        assert result.success is True
        mock_context.secrets.set.assert_called()

    async def test_secret_delete(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /secret delete name."""
        result = await registry.execute(mock_context, "/secret delete MY_SECRET")
        assert result is not None
        assert result.success is True


# =============================================================================
# Hosts Commands Tests
# =============================================================================


class TestHostsCommand:
    """Tests for /hosts command."""

    async def test_hosts_list(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
    ):
        """Test /hosts list."""
        result = await registry.execute(mock_context, "/hosts list")
        assert result is not None
        assert result.success is True
        # Hosts list uses ui.table() for display
        mock_context.ui.table.assert_called_once()

    async def test_hosts_list_with_tag(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_hosts_repo: MagicMock
    ):
        """Test /hosts list --tag=web."""
        result = await registry.execute(mock_context, "/hosts list --tag=web")
        assert result is not None
        assert result.success is True
        mock_hosts_repo.get_by_tag.assert_called_with("web")

    async def test_hosts_show(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
    ):
        """Test /hosts show name."""
        result = await registry.execute(mock_context, "/hosts show test-host")
        assert result is not None
        assert result.success is True
        assert "test-host" in result.message

    async def test_hosts_show_not_found(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_hosts_repo: MagicMock
    ):
        """Test /hosts show with non-existent host."""
        mock_hosts_repo.get_by_name = AsyncMock(return_value=None)
        result = await registry.execute(mock_context, "/hosts show unknown")
        assert result is not None
        assert result.success is False

    async def test_hosts_add(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_hosts_repo: MagicMock
    ):
        """Test /hosts add name."""
        mock_hosts_repo.get_by_name = AsyncMock(return_value=None)
        mock_context.ui.prompt = AsyncMock(side_effect=["192.168.1.100", "22", "admin"])

        result = await registry.execute(mock_context, "/hosts add new-host")
        assert result is not None
        assert result.success is True
        mock_hosts_repo.create.assert_called_once()

    async def test_hosts_delete(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_hosts_repo: MagicMock
    ):
        """Test /hosts delete name."""
        result = await registry.execute(mock_context, "/hosts delete test-host")
        assert result is not None
        assert result.success is True
        mock_hosts_repo.delete.assert_called_once()

    async def test_hosts_tag(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_hosts_repo: MagicMock
    ):
        """Test /hosts tag name tag."""
        result = await registry.execute(mock_context, "/hosts tag test-host staging")
        assert result is not None
        assert result.success is True
        mock_hosts_repo.update.assert_called_once()

    async def test_hosts_untag(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
    ):
        """Test /hosts untag name tag."""
        result = await registry.execute(mock_context, "/hosts untag test-host web")
        assert result is not None
        assert result.success is True


# =============================================================================
# Conversation Commands Tests
# =============================================================================


class TestConversationCommand:
    """Tests for /conv command."""

    async def test_conv_list(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_conversations_repo: MagicMock,
    ):
        """Test /conv list."""
        result = await registry.execute(mock_context, "/conv list")
        assert result is not None
        assert result.success is True
        assert "Test conversation" in result.message

    async def test_conv_list_with_limit(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_conversations_repo: MagicMock
    ):
        """Test /conv list --limit=5."""
        result = await registry.execute(mock_context, "/conv list --limit=5")
        assert result is not None
        assert result.success is True
        mock_conversations_repo.get_recent.assert_called_with(limit=5)

    async def test_conv_show(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_conversations_repo: MagicMock,
    ):
        """Test /conv show id."""
        result = await registry.execute(mock_context, "/conv show conv-123")
        assert result is not None
        assert result.success is True
        assert "Test conversation" in result.message

    async def test_conv_load(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_conversations_repo: MagicMock,
    ):
        """Test /conv load id."""
        result = await registry.execute(mock_context, "/conv load conv-123")
        assert result is not None
        assert result.success is True
        assert "load_conversation" in result.data

    async def test_conv_search(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_conversations_repo: MagicMock,
    ):
        """Test /conv search query."""
        result = await registry.execute(mock_context, "/conv search hello")
        assert result is not None
        assert result.success is True


# =============================================================================
# System Commands Tests
# =============================================================================


class TestHealthCommand:
    """Tests for /health command."""

    async def test_health(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /health command."""
        with patch("merlya.health.checks.run_startup_checks") as mock_checks:
            from merlya.core.types import CheckStatus, HealthCheck
            from merlya.health import StartupHealth

            mock_health = StartupHealth(
                checks=[
                    HealthCheck(name="ram", status=CheckStatus.OK, message="RAM OK"),
                    HealthCheck(name="disk", status=CheckStatus.OK, message="Disk OK"),
                ],
                capabilities={"ssh": True},
            )
            mock_checks.return_value = mock_health

            result = await registry.execute(mock_context, "/health")
            assert result is not None
            assert result.success is True
            assert "Health Status" in result.message


class TestLogCommand:
    """Tests for /log command."""

    async def test_log_show_config(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /log without args shows config."""
        result = await registry.execute(mock_context, "/log")
        assert result is not None
        assert result.success is True
        assert "Logging Configuration" in result.message

    async def test_log_set_level(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /log level debug."""
        with patch("merlya.core.logging.configure_logging"):
            result = await registry.execute(mock_context, "/log level debug")
            assert result is not None
            assert result.success is True
            mock_context.config.save.assert_called()


# =============================================================================
# Scan Command Tests
# =============================================================================


class TestScanCommand:
    """Tests for /scan command."""

    async def test_scan_no_args(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
    ):
        """Test /scan without args shows usage."""
        result = await registry.execute(mock_context, "/scan")
        assert result is not None
        assert result.success is False
        assert "Usage" in result.message

    async def test_scan_host_not_found(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_hosts_repo: MagicMock
    ):
        """Test /scan with unknown host."""
        mock_hosts_repo.get_by_name = AsyncMock(return_value=None)
        result = await registry.execute(mock_context, "/scan unknown-host")
        assert result is not None
        assert result.success is False
        assert "not found" in result.message


# =============================================================================
# Registry Tests
# =============================================================================


class TestCommandRegistry:
    """Tests for command registry functionality."""

    def test_get_command(self, registry: CommandRegistry):
        """Test getting a command by name."""
        cmd = registry.get("help")
        assert cmd is not None
        assert cmd.name == "help"

    def test_get_command_by_alias(self, registry: CommandRegistry):
        """Test getting a command by alias."""
        cmd = registry.get("h")  # alias for help
        assert cmd is not None
        assert cmd.name == "help"

    def test_get_unknown_command(self, registry: CommandRegistry):
        """Test getting unknown command returns None."""
        cmd = registry.get("nonexistent")
        assert cmd is None

    def test_parse_command(self, registry: CommandRegistry):
        """Test parsing command input."""
        result = registry.parse("/help hosts")
        assert result is not None
        assert result[0] == "help"
        assert result[1] == ["hosts"]

    def test_parse_non_command(self, registry: CommandRegistry):
        """Test parsing non-command input."""
        result = registry.parse("just some text")
        assert result is None

    def test_completions(self, registry: CommandRegistry):
        """Test command completions."""
        completions = registry.get_completions("/he")
        assert "/help" in completions
        assert "/health" in completions

    async def test_execute_unknown_command(
        self, registry: CommandRegistry, mock_context: MagicMock
    ):
        """Test executing unknown command."""
        result = await registry.execute(mock_context, "/nonexistent")
        assert result is not None
        assert result.success is False
        assert "Unknown command" in result.message


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    async def test_empty_host_list(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_hosts_repo: MagicMock
    ):
        """Test /hosts list with no hosts."""
        mock_hosts_repo.get_all = AsyncMock(return_value=[])
        result = await registry.execute(mock_context, "/hosts list")
        assert result is not None
        assert result.success is True
        assert "No hosts found" in result.message

    async def test_empty_variable_list(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_variables_repo: MagicMock
    ):
        """Test /variable list with no variables."""
        mock_variables_repo.get_all = AsyncMock(return_value=[])
        result = await registry.execute(mock_context, "/variable list")
        assert result is not None
        assert result.success is True
        assert "No variables set" in result.message

    async def test_empty_secret_list(self, registry: CommandRegistry, mock_context: MagicMock):
        """Test /secret list with no secrets."""
        mock_context.secrets.list_keys = MagicMock(return_value=[])
        result = await registry.execute(mock_context, "/secret list")
        assert result is not None
        assert result.success is True
        assert "No secrets stored" in result.message

    async def test_empty_conversation_list(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_conversations_repo: MagicMock
    ):
        """Test /conv list with no conversations."""
        mock_conversations_repo.get_recent = AsyncMock(return_value=[])
        result = await registry.execute(mock_context, "/conv list")
        assert result is not None
        assert result.success is True
        assert "No conversations yet" in result.message

    async def test_variable_get_not_found(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_variables_repo: MagicMock
    ):
        """Test /variable get with non-existent variable."""
        mock_variables_repo.get = AsyncMock(return_value=None)
        result = await registry.execute(mock_context, "/variable get unknown")
        assert result is not None
        assert result.success is False
        assert "not found" in result.message

    async def test_hosts_tag_invalid_format(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
    ):
        """Test /hosts tag with invalid tag format."""
        result = await registry.execute(mock_context, "/hosts tag test-host invalid@tag!")
        assert result is not None
        assert result.success is False
        assert "Invalid tag format" in result.message
