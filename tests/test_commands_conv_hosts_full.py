"""
Tests for additional /conv and /hosts subcommands.

Tests conversation management (delete, rename, export) and
hosts management (edit, import, export) commands.
"""

from __future__ import annotations

import tempfile
from datetime import datetime
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
    ctx.config.save = MagicMock()

    # Mock secrets
    ctx.secrets = MagicMock()
    ctx.secrets.list_keys = MagicMock(return_value=[])
    ctx.secrets.set = MagicMock()
    ctx.secrets.get = MagicMock(return_value=None)
    ctx.secrets.delete = MagicMock()
    ctx.secrets.has = MagicMock(return_value=False)

    return ctx


@pytest.fixture
def mock_conversations_repo(mock_context: MagicMock) -> MagicMock:
    """Configure conversations repository mock."""
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


# =============================================================================
# Additional Conversation Commands Tests
# =============================================================================


class TestConvDeleteCommand:
    """Tests for /conv delete command."""

    async def test_conv_delete_no_args(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_conversations_repo: MagicMock,
    ):
        """Test /conv delete without args shows usage."""
        result = await registry.execute(mock_context, "/conv delete")
        assert result is not None
        assert result.success is False
        assert "Usage" in result.message

    async def test_conv_delete_not_found(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_conversations_repo: MagicMock
    ):
        """Test /conv delete with non-existent conversation."""
        mock_conversations_repo.get_by_id = AsyncMock(return_value=None)
        result = await registry.execute(mock_context, "/conv delete nonexistent")
        assert result is not None
        assert result.success is False
        assert "not found" in result.message.lower()

    async def test_conv_delete_success(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_conversations_repo: MagicMock
    ):
        """Test /conv delete with valid conversation."""
        result = await registry.execute(mock_context, "/conv delete conv-123")
        assert result is not None
        assert result.success is True
        mock_conversations_repo.delete.assert_called_once()


class TestConvRenameCommand:
    """Tests for /conv rename command."""

    async def test_conv_rename_no_args(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_conversations_repo: MagicMock,
    ):
        """Test /conv rename without args shows usage."""
        result = await registry.execute(mock_context, "/conv rename")
        assert result is not None
        assert result.success is False
        assert "Usage" in result.message

    async def test_conv_rename_no_title(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_conversations_repo: MagicMock,
    ):
        """Test /conv rename with id but no title."""
        result = await registry.execute(mock_context, "/conv rename conv-123")
        assert result is not None
        assert result.success is False
        assert "Usage" in result.message

    async def test_conv_rename_not_found(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_conversations_repo: MagicMock
    ):
        """Test /conv rename with non-existent conversation."""
        mock_conversations_repo.get_by_id = AsyncMock(return_value=None)
        result = await registry.execute(mock_context, "/conv rename nonexistent New Title")
        assert result is not None
        assert result.success is False
        assert "not found" in result.message.lower()

    async def test_conv_rename_success(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_conversations_repo: MagicMock
    ):
        """Test /conv rename with valid conversation."""
        result = await registry.execute(mock_context, "/conv rename conv-123 New Title")
        assert result is not None
        assert result.success is True
        mock_conversations_repo.update.assert_called_once()


class TestConvExportCommand:
    """Tests for /conv export command."""

    async def test_conv_export_no_args(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_conversations_repo: MagicMock,
    ):
        """Test /conv export without args shows usage."""
        result = await registry.execute(mock_context, "/conv export")
        assert result is not None
        assert result.success is False
        assert "Usage" in result.message

    async def test_conv_export_no_file(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_conversations_repo: MagicMock,
    ):
        """Test /conv export with id but no file."""
        result = await registry.execute(mock_context, "/conv export conv-123")
        assert result is not None
        assert result.success is False
        assert "Usage" in result.message

    async def test_conv_export_not_found(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_conversations_repo: MagicMock
    ):
        """Test /conv export with non-existent conversation."""
        mock_conversations_repo.get_by_id = AsyncMock(return_value=None)
        result = await registry.execute(mock_context, "/conv export nonexistent output.json")
        assert result is not None
        assert result.success is False
        assert "not found" in result.message.lower()

    async def test_conv_export_success(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_conversations_repo: MagicMock,
    ):
        """Test /conv export with valid conversation."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            result = await registry.execute(mock_context, f"/conv export conv-123 {f.name}")
            assert result is not None
            assert result.success is True


# =============================================================================
# Additional Hosts Commands Tests
# =============================================================================


class TestHostsEditCommand:
    """Tests for /hosts edit command."""

    async def test_hosts_edit_no_args(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
    ):
        """Test /hosts edit without args shows usage."""
        result = await registry.execute(mock_context, "/hosts edit")
        assert result is not None
        assert result.success is False
        assert "Usage" in result.message

    async def test_hosts_edit_not_found(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_hosts_repo: MagicMock
    ):
        """Test /hosts edit with non-existent host."""
        mock_hosts_repo.get_by_name = AsyncMock(return_value=None)
        result = await registry.execute(mock_context, "/hosts edit unknown")
        assert result is not None
        assert result.success is False
        assert "not found" in result.message.lower()

    async def test_hosts_edit_success(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_hosts_repo: MagicMock
    ):
        """Test /hosts edit with valid host."""
        # User provides new values for all prompts (hostname, port, username, tags, private_key, jump_host)
        mock_context.ui.prompt = AsyncMock(
            side_effect=["192.168.1.2", "2222", "newuser", "web,prod", "", ""]
        )
        result = await registry.execute(mock_context, "/hosts edit test-host")
        assert result is not None
        assert result.success is True
        mock_hosts_repo.update.assert_called_once()


class TestHostsImportCommand:
    """Tests for /hosts import command."""

    async def test_hosts_import_no_args(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
    ):
        """Test /hosts import without args shows usage."""
        result = await registry.execute(mock_context, "/hosts import")
        assert result is not None
        assert result.success is False
        assert "Usage" in result.message

    async def test_hosts_import_file_not_found(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
    ):
        """Test /hosts import with non-existent file."""
        result = await registry.execute(mock_context, "/hosts import /nonexistent/file.yaml")
        assert result is not None
        assert result.success is False
        assert "not found" in result.message.lower() or "error" in result.message.lower()

    async def test_hosts_import_yaml_success(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
    ):
        """Test /hosts import with valid YAML file."""

        import yaml

        file_path = Path("/tmp/test_hosts_import.yaml")
        with file_path.open("w") as f:
            yaml.dump(
                [
                    {"name": "host1", "hostname": "192.168.1.1", "port": 22, "username": "admin"},
                    {"name": "host2", "hostname": "192.168.1.2", "port": 22, "username": "admin"},
                ],
                f,
            )

        try:
            # Mock the import function to return success
            with patch(
                "merlya.commands.handlers.hosts.import_hosts", new_callable=AsyncMock
            ) as mock_import:
                mock_import.return_value = (2, [])  # 2 hosts imported, no errors
                result = await registry.execute(mock_context, f"/hosts import {file_path}")
                assert result is not None
                assert result.success is True
                assert "2" in result.message
        finally:
            if file_path.exists():
                file_path.unlink()


class TestHostsExportCommand:
    """Tests for /hosts export command."""

    async def test_hosts_export_no_args(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
    ):
        """Test /hosts export without args shows usage."""
        result = await registry.execute(mock_context, "/hosts export")
        assert result is not None
        assert result.success is False
        assert "Usage" in result.message

    async def test_hosts_export_yaml_success(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
    ):
        """Test /hosts export to YAML file."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            result = await registry.execute(mock_context, f"/hosts export {f.name}")
            assert result is not None
            assert result.success is True

    async def test_hosts_export_json_success(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
    ):
        """Test /hosts export to JSON file."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            result = await registry.execute(mock_context, f"/hosts export {f.name} --format=json")
            assert result is not None
            assert result.success is True

    async def test_hosts_export_empty_list(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_hosts_repo: MagicMock
    ):
        """Test /hosts export with no hosts returns error."""
        mock_hosts_repo.get_all = AsyncMock(return_value=[])
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            result = await registry.execute(mock_context, f"/hosts export {f.name}")
            assert result is not None
            # Should fail when there are no hosts to export
            assert result.success is False
            assert "No hosts" in result.message
