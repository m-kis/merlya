"""
Integration tests for HostRegistry <-> Inventory <-> CredentialManager.

These tests verify that the components work together correctly:
1. Adding hosts to inventory makes them immediately available for validation
2. SSH user from inventory metadata is used for connections
3. Cache invalidation works correctly after inventory changes
"""

from unittest.mock import MagicMock, patch

import pytest


class TestHostRegistryInventoryIntegration:
    """Test HostRegistry and Inventory integration."""

    @pytest.fixture(autouse=True)
    def reset_singletons(self):
        """Reset all singletons before each test."""
        from merlya.context.host_registry import reset_host_registry
        reset_host_registry()
        yield
        reset_host_registry()

    @pytest.fixture
    def mock_inventory_repo(self):
        """Create a mock inventory repository."""
        repo = MagicMock()
        repo.get_all_hosts.return_value = []
        repo.get_host_by_name.return_value = None
        return repo

    def test_invalidate_cache_forces_reload(self):
        """Test that invalidate_cache() forces reload on next access."""
        from merlya.context.host_registry import HostRegistry

        registry = HostRegistry()

        # Simulate loaded state
        registry._last_refresh = __import__('datetime').datetime.now()
        registry._hosts = {"test-host": MagicMock(hostname="test-host")}

        # Verify cache is valid (won't reload)
        initial_count = registry.load_all_sources()
        assert initial_count == 1  # Returns cached count

        # Invalidate cache
        registry.invalidate_cache()

        # Verify cache is now invalid
        assert registry._last_refresh is None

    def test_get_host_registry_is_singleton(self):
        """Test that get_host_registry returns the same instance."""
        from merlya.context.host_registry import get_host_registry

        with patch('merlya.context.host_registry.SQLiteSource') as mock_sqlite:
            mock_sqlite.return_value.load.return_value = []

            registry1 = get_host_registry()
            registry2 = get_host_registry()

            assert registry1 is registry2

    def test_get_host_registry_thread_safety(self):
        """Test that get_host_registry is thread-safe."""
        import threading

        from merlya.context.host_registry import get_host_registry, reset_host_registry

        reset_host_registry()
        registries = []
        errors = []

        def get_registry():
            try:
                with patch('merlya.context.host_registry.SQLiteSource') as mock_sqlite:
                    mock_sqlite.return_value.load.return_value = []
                    registries.append(get_host_registry())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=get_registry) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during threaded access: {errors}"
        # All threads should get the same instance
        assert len(set(id(r) for r in registries)) == 1


class TestSSHUserFromInventory:
    """Test SSH user resolution from inventory metadata."""

    @pytest.fixture
    def mock_repo_with_ssh_user(self):
        """Create a mock repo that returns a host with ssh_user in metadata."""
        repo = MagicMock()
        repo.get_host_by_name.return_value = {
            "hostname": "test-server",
            "ip_address": "10.0.0.1",
            "metadata": {"ssh_user": "deploy"},
        }
        return repo

    def test_get_user_for_host_checks_inventory_first(self, mock_repo_with_ssh_user):
        """Test that get_user_for_host checks inventory metadata first."""
        from pathlib import Path

        from merlya.security.ssh_credentials import SSHCredentialMixin

        # Create a mock class that uses the mixin
        class MockCredManager(SSHCredentialMixin):
            def __init__(self):
                self.ssh_dir = Path.home() / ".ssh"
                self.ssh_config = {}
                self._variables = {}

            def get_variable(self, key):
                return self._variables.get(key)

            def set_variable(self, key, value, var_type=None):
                self._variables[key] = value

        manager = MockCredManager()

        with patch(
            'merlya.memory.persistence.inventory_repository.get_inventory_repository',
            return_value=mock_repo_with_ssh_user
        ):
            user = manager.get_user_for_host("test-server")

        assert user == "deploy"

    def test_get_user_for_host_falls_back_to_ssh_config(self):
        """Test fallback to SSH config when inventory has no ssh_user."""
        from pathlib import Path

        from merlya.security.ssh_credentials import SSHCredentialMixin

        class MockCredManager(SSHCredentialMixin):
            def __init__(self):
                self.ssh_dir = Path.home() / ".ssh"
                self.ssh_config = {"test-server": {"user": "ops"}}
                self._variables = {}

            def get_variable(self, key):
                return self._variables.get(key)

            def set_variable(self, key, value, var_type=None):
                self._variables[key] = value

        manager = MockCredManager()

        # Mock repo returns host without ssh_user
        mock_repo = MagicMock()
        mock_repo.get_host_by_name.return_value = {
            "hostname": "test-server",
            "metadata": {},
        }

        with patch(
            'merlya.memory.persistence.inventory_repository.get_inventory_repository',
            return_value=mock_repo
        ):
            user = manager.get_user_for_host("test-server")

        assert user == "ops"


class TestInventoryManagerSync:
    """Test inventory manager syncs with HostRegistry."""

    @pytest.fixture
    def mock_repo(self):
        """Create mock inventory repository."""
        repo = MagicMock()
        repo.add_host.return_value = 1
        repo.get_host_by_name.return_value = None
        return repo

    def test_sync_host_registry_invalidates_cache(self, mock_repo):
        """Test that _sync_host_registry invalidates cache after adding host."""
        from merlya.context.host_registry import get_host_registry, reset_host_registry
        from merlya.repl.commands.inventory.manager import InventoryManager

        reset_host_registry()
        manager = InventoryManager(mock_repo)

        with patch('merlya.context.host_registry.SQLiteSource') as mock_sqlite:
            mock_sqlite.return_value.load.return_value = []

            # Get registry and set up a mock refresh time
            registry = get_host_registry()
            registry._last_refresh = __import__('datetime').datetime.now()

            # Sync should invalidate cache
            result = manager._sync_host_registry(
                hostname="new-host",
                ip_address="10.0.0.5",
                environment="production"
            )

            assert result is True
            assert registry._last_refresh is None  # Cache was invalidated


class TestScanHostWithUser:
    """Test scan_host tool with explicit user parameter."""

    def test_scan_host_updates_metadata_with_user(self):
        """Test that scan_host stores explicit user in inventory metadata."""
        from merlya.tools.hosts import scan_host

        # Create mocks
        mock_repo = MagicMock()
        mock_repo.get_host_by_name.return_value = {
            "hostname": "test-server",
            "metadata": {},
        }
        mock_repo.update_host_metadata.return_value = True

        mock_context_manager = MagicMock()

        # Create a proper async mock for scan_host
        async def mock_scan_host(*args, **kwargs):
            return {
                "accessible": True,
                "os": "Ubuntu 22.04",
                "kernel": "5.15.0",
            }

        mock_context_manager.scan_host = mock_scan_host

        # Create mock context
        mock_ctx = MagicMock()
        mock_ctx.inventory_repo = mock_repo
        mock_ctx.context_manager = mock_context_manager
        mock_ctx.host_registry = MagicMock()
        mock_ctx.host_registry.is_empty.return_value = False
        mock_ctx.context_memory = None

        with patch('merlya.tools.hosts.validate_host', return_value=(True, "OK")):
            with patch('merlya.tools.hosts.get_tool_context', return_value=mock_ctx):
                with patch('merlya.tools.base.get_status_manager') as mock_status:
                    mock_status.return_value = MagicMock()
                    # Call with explicit user - this should store in metadata
                    try:
                        scan_host("test-server", user="deploy")
                    except Exception:
                        pass  # May fail in mock context, but we're testing metadata update

        # Verify metadata update was called with ssh_user
        assert mock_repo.update_host_metadata.called, "update_host_metadata should have been called"
        call_args = mock_repo.update_host_metadata.call_args
        assert call_args[0][0] == "test-server"
        assert "ssh_user" in call_args[0][1]
        assert call_args[0][1]["ssh_user"] == "deploy"
