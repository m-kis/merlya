"""
Tests for SQLiteSource - loads hosts from InventoryRepository.
"""
import pytest
from unittest.mock import MagicMock, patch


class TestSQLiteSource:
    """Tests for SQLiteSource inventory loader."""

    def test_load_returns_hosts_from_repository(self):
        """Test: SQLiteSource loads hosts from InventoryRepository."""
        from merlya.context.sources.sqlite import SQLiteSource

        mock_hosts = [
            {
                "hostname": "web-server-01",
                "ip_address": "10.0.0.1",
                "environment": "production",
                "groups": ["webservers", "production"],
                "aliases": ["web01"],
                "metadata": {"ssh_key_path": "~/.ssh/id_ed25519"},
            },
            {
                "hostname": "db-server-01",
                "ip_address": "10.0.0.2",
                "environment": "production",
                "groups": ["databases"],
                "aliases": [],
                "metadata": {},
            },
        ]

        with patch(
            'merlya.memory.persistence.inventory_repository.get_inventory_repository'
        ) as mock_get_repo:
            mock_repo = MagicMock()
            mock_repo.get_all_hosts.return_value = mock_hosts
            mock_get_repo.return_value = mock_repo

            source = SQLiteSource({})
            hosts = source.load()

            assert len(hosts) == 2
            assert hosts[0].hostname == "web-server-01"
            assert hosts[0].ip_address == "10.0.0.1"
            assert hosts[0].environment == "production"
            assert "webservers" in hosts[0].groups
            assert "web01" in hosts[0].aliases

            assert hosts[1].hostname == "db-server-01"
            assert hosts[1].ip_address == "10.0.0.2"

    def test_load_handles_empty_repository(self):
        """Test: SQLiteSource handles empty repository gracefully."""
        from merlya.context.sources.sqlite import SQLiteSource

        with patch(
            'merlya.memory.persistence.inventory_repository.get_inventory_repository'
        ) as mock_get_repo:
            mock_repo = MagicMock()
            mock_repo.get_all_hosts.return_value = []
            mock_get_repo.return_value = mock_repo

            source = SQLiteSource({})
            hosts = source.load()

            assert len(hosts) == 0

    def test_load_handles_import_error(self):
        """Test: SQLiteSource handles missing repository gracefully."""
        from merlya.context.sources.sqlite import SQLiteSource

        with patch(
            'merlya.memory.persistence.inventory_repository.get_inventory_repository'
        ) as mock_get_repo:
            mock_get_repo.side_effect = ImportError("Module not found")

            source = SQLiteSource({})
            hosts = source.load()

            # Should return empty list, not raise
            assert len(hosts) == 0

    def test_load_handles_repository_error(self):
        """Test: SQLiteSource handles repository errors gracefully."""
        from merlya.context.sources.sqlite import SQLiteSource

        with patch(
            'merlya.memory.persistence.inventory_repository.get_inventory_repository'
        ) as mock_get_repo:
            mock_repo = MagicMock()
            mock_repo.get_all_hosts.side_effect = Exception("DB connection failed")
            mock_get_repo.return_value = mock_repo

            source = SQLiteSource({})
            hosts = source.load()

            # Should return empty list, not raise
            assert len(hosts) == 0

    def test_convert_handles_json_string_groups(self):
        """Test: SQLiteSource handles JSON-encoded groups."""
        from merlya.context.sources.sqlite import SQLiteSource

        mock_host = {
            "hostname": "test-server",
            "groups": '["group1", "group2"]',  # JSON string
            "aliases": '["alias1"]',
            "metadata": '{"key": "value"}',
        }

        with patch(
            'merlya.memory.persistence.inventory_repository.get_inventory_repository'
        ) as mock_get_repo:
            mock_repo = MagicMock()
            mock_repo.get_all_hosts.return_value = [mock_host]
            mock_get_repo.return_value = mock_repo

            source = SQLiteSource({})
            hosts = source.load()

            assert len(hosts) == 1
            assert hosts[0].hostname == "test-server"
            assert "group1" in hosts[0].groups
            assert "alias1" in hosts[0].aliases
            assert hosts[0].metadata.get("key") == "value"

    def test_convert_handles_malformed_data(self):
        """Test: SQLiteSource skips hosts with missing hostname."""
        from merlya.context.sources.sqlite import SQLiteSource

        mock_hosts = [
            {"hostname": None},  # Missing hostname
            {"not_hostname": "test"},  # No hostname key
            {"hostname": "valid-host"},  # Valid
        ]

        with patch(
            'merlya.memory.persistence.inventory_repository.get_inventory_repository'
        ) as mock_get_repo:
            mock_repo = MagicMock()
            mock_repo.get_all_hosts.return_value = mock_hosts
            mock_get_repo.return_value = mock_repo

            source = SQLiteSource({})
            hosts = source.load()

            # Only the valid host should be returned
            assert len(hosts) == 1
            assert hosts[0].hostname == "valid-host"


class TestHostRegistrySQLiteIntegration:
    """Tests for HostRegistry integration with SQLiteSource."""

    def test_host_registry_loads_sqlite_source(self):
        """Test: HostRegistry includes SQLiteSource in loaded sources."""
        from merlya.context.host_registry import HostRegistry
        from merlya.context.sources.base import InventorySource

        # Mock all sources to return empty to test source loading
        with patch('merlya.context.sources.sqlite.SQLiteSource.load') as mock_sqlite:
            with patch('merlya.context.sources.local.EtcHostsSource.load') as mock_etc:
                with patch('merlya.context.sources.local.SSHConfigSource.load') as mock_ssh:
                    with patch('merlya.context.sources.ansible.AnsibleSource.load') as mock_ansible:
                        mock_sqlite.return_value = []
                        mock_etc.return_value = []
                        mock_ssh.return_value = []
                        mock_ansible.return_value = []

                        registry = HostRegistry({})
                        registry.load_all_sources()

                        # SQLiteSource.load should have been called
                        mock_sqlite.assert_called_once()

    def test_manual_hosts_visible_in_registry(self):
        """Test: Hosts from SQLite are accessible via HostRegistry."""
        from merlya.context.host_registry import HostRegistry
        from merlya.context.sources.base import Host, InventorySource

        mock_host = Host(
            hostname="my-server",
            ip_address="192.168.1.100",
            source=InventorySource.MANUAL,
            environment="staging",
        )

        with patch('merlya.context.sources.sqlite.SQLiteSource.load') as mock_sqlite:
            with patch('merlya.context.sources.local.EtcHostsSource.load') as mock_etc:
                with patch('merlya.context.sources.local.SSHConfigSource.load') as mock_ssh:
                    with patch('merlya.context.sources.ansible.AnsibleSource.load') as mock_ansible:
                        mock_sqlite.return_value = [mock_host]
                        mock_etc.return_value = []
                        mock_ssh.return_value = []
                        mock_ansible.return_value = []

                        registry = HostRegistry({})
                        registry.load_all_sources()

                        # Host should be findable
                        result = registry.validate("my-server")
                        assert result.is_valid is True
                        assert result.host.hostname == "my-server"
                        assert result.host.ip_address == "192.168.1.100"
