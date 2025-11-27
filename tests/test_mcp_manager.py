"""
Tests for MCPManager - MCP server configuration management.
"""
from pathlib import Path

import pytest


class TestMCPManager:
    """Test MCPManager class."""

    @pytest.fixture
    def temp_config_dir(self, tmp_path):
        """Create temporary config directory."""
        config_dir = tmp_path / ".athena"
        config_dir.mkdir()
        return config_dir

    @pytest.fixture
    def manager(self, temp_config_dir, monkeypatch):
        """Create MCPManager with temporary config."""
        monkeypatch.setattr(Path, "home", lambda: temp_config_dir.parent)
        from athena_ai.mcp.manager import MCPManager
        return MCPManager()

    def test_create_manager(self, manager):
        """Should create MCPManager instance."""
        assert manager.servers == {}

    def test_add_server_stdio(self, manager):
        """Should add stdio server configuration."""
        result = manager.add_server("filesystem", {
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem"]
        })

        assert result is True
        assert "filesystem" in manager.servers
        assert manager.servers["filesystem"]["type"] == "stdio"

    def test_add_server_with_env(self, manager):
        """Should add server with environment variables."""
        result = manager.add_server("github", {
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "env": {"GITHUB_TOKEN": "test-token"}
        })

        assert result is True
        assert manager.servers["github"]["env"]["GITHUB_TOKEN"] == "test-token"

    def test_add_server_missing_type(self, manager):
        """Should reject config without type."""
        result = manager.add_server("bad", {
            "command": "npx"
        })

        assert result is False
        assert "bad" not in manager.servers

    def test_add_server_stdio_missing_command(self, manager):
        """Should reject stdio config without command."""
        result = manager.add_server("bad", {
            "type": "stdio"
        })

        assert result is False
        assert "bad" not in manager.servers

    def test_delete_server(self, manager):
        """Should delete server configuration."""
        manager.add_server("test", {
            "type": "stdio",
            "command": "test"
        })

        result = manager.delete_server("test")
        assert result is True
        assert "test" not in manager.servers

    def test_delete_nonexistent_server(self, manager):
        """Should return False for nonexistent server."""
        result = manager.delete_server("nonexistent")
        assert result is False

    def test_get_server(self, manager):
        """Should get server configuration."""
        manager.add_server("test", {
            "type": "stdio",
            "command": "test"
        })

        config = manager.get_server("test")
        assert config is not None
        assert config["type"] == "stdio"

    def test_get_nonexistent_server(self, manager):
        """Should return None for nonexistent server."""
        config = manager.get_server("nonexistent")
        assert config is None

    def test_list_servers(self, manager):
        """Should list all servers."""
        manager.add_server("server1", {"type": "stdio", "command": "cmd1"})
        manager.add_server("server2", {"type": "stdio", "command": "cmd2"})

        servers = manager.list_servers()
        assert len(servers) == 2
        assert "server1" in servers
        assert "server2" in servers

    def test_list_servers_returns_copy(self, manager):
        """Should return copy of servers dict."""
        manager.add_server("test", {"type": "stdio", "command": "test"})

        servers = manager.list_servers()
        servers["modified"] = {"type": "stdio", "command": "bad"}

        assert "modified" not in manager.servers


class TestMCPReference:
    """Test @mcp reference parsing."""

    @pytest.fixture
    def manager(self, tmp_path, monkeypatch):
        """Create MCPManager with temporary config."""
        config_dir = tmp_path / ".athena"
        config_dir.mkdir()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from athena_ai.mcp.manager import MCPManager
        return MCPManager()

    def test_parse_mcp_reference(self, manager):
        """Should parse @mcp reference."""
        result = manager.parse_mcp_reference("@mcp filesystem list files in /tmp")

        assert result is not None
        server_name, remaining = result
        assert server_name == "filesystem"
        assert remaining == "list files in /tmp"

    def test_parse_mcp_reference_no_query(self, manager):
        """Should parse @mcp reference without query."""
        result = manager.parse_mcp_reference("@mcp filesystem")

        assert result is not None
        server_name, remaining = result
        assert server_name == "filesystem"
        assert remaining == ""

    def test_parse_non_mcp_query(self, manager):
        """Should return None for non-@mcp query."""
        result = manager.parse_mcp_reference("check disk space")
        assert result is None

    def test_parse_empty_mcp(self, manager):
        """Should return None for empty @mcp."""
        result = manager.parse_mcp_reference("@mcp")
        assert result is None


class TestExampleConfigs:
    """Test example configurations."""

    @pytest.fixture
    def manager(self, tmp_path, monkeypatch):
        """Create MCPManager with temporary config."""
        config_dir = tmp_path / ".athena"
        config_dir.mkdir()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from athena_ai.mcp.manager import MCPManager
        return MCPManager()

    def test_get_example_configs(self, manager):
        """Should return example configurations."""
        examples = manager.get_example_configs()

        assert "filesystem" in examples
        assert "git" in examples
        assert "github" in examples
        assert "postgres" in examples
        assert "brave-search" in examples

    def test_example_configs_valid(self, manager):
        """Example configs should be valid."""
        examples = manager.get_example_configs()

        for name, config in examples.items():
            # Each example should be addable
            result = manager.add_server(f"test_{name}", config)
            assert result is True, f"Invalid example config: {name}"


class TestPersistence:
    """Test configuration persistence."""

    def test_configs_persisted(self, tmp_path, monkeypatch):
        """Should persist configs to disk."""
        tmp_path / ".athena"
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        from athena_ai.mcp.manager import MCPManager

        # Create and add server
        manager1 = MCPManager()
        manager1.add_server("test", {"type": "stdio", "command": "test"})

        # Create new manager - should load from disk
        manager2 = MCPManager()
        assert "test" in manager2.servers

    def test_load_corrupted_config(self, tmp_path, monkeypatch):
        """Should handle corrupted config file."""
        config_dir = tmp_path / ".athena"
        config_dir.mkdir()
        config_file = config_dir / "mcp_servers.json"
        config_file.write_text("invalid json{{{")

        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        from athena_ai.mcp.manager import MCPManager

        # Should not raise, should have empty servers
        manager = MCPManager()
        assert manager.servers == {}
