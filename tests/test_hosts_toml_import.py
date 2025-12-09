"""Tests for TOML hosts import functionality."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from merlya.commands.handlers.hosts_io import (
    _import_toml,
    detect_import_format,
)


class TestDetectImportFormat:
    """Tests for detect_import_format function."""

    def test_detects_toml_extension(self):
        """Test that .toml files are detected."""
        path = Path("/tmp/hosts.toml")
        result = detect_import_format(path, [])
        assert result == "toml"

    def test_detects_tml_extension(self):
        """Test that .tml files are detected as TOML."""
        path = Path("/tmp/hosts.tml")
        result = detect_import_format(path, [])
        assert result == "toml"

    def test_format_arg_overrides_extension(self):
        """Test that --format argument takes precedence."""
        path = Path("/tmp/hosts.json")
        result = detect_import_format(path, ["hosts.json", "--format=toml"])
        assert result == "toml"

    def test_detects_yaml_extension(self):
        """Test YAML detection still works."""
        path = Path("/tmp/hosts.yaml")
        result = detect_import_format(path, [])
        assert result == "yaml"

    def test_detects_ssh_config(self):
        """Test SSH config detection."""
        path = Path("/home/user/.ssh/config")
        result = detect_import_format(path, [])
        assert result == "ssh"


class TestImportToml:
    """Tests for _import_toml function."""

    @pytest.fixture
    def mock_ctx(self):
        """Create mock context."""
        ctx = MagicMock()
        ctx.hosts = AsyncMock()
        ctx.hosts.get_by_name = AsyncMock(return_value=None)
        ctx.hosts.create = AsyncMock()
        return ctx

    @pytest.mark.asyncio
    async def test_imports_hosts_section(self, mock_ctx):
        """Test importing hosts from [hosts.xxx] format."""
        content = """
[hosts.internal-db]
hostname = "10.0.1.50"
user = "dbadmin"
jump_host = "bastion.example.com"
port = 22

[hosts.bastion]
hostname = "bastion.example.com"
user = "admin"
"""
        imported, errors = await _import_toml(mock_ctx, content)

        assert imported == 2
        assert len(errors) == 0
        assert mock_ctx.hosts.create.call_count == 2

    @pytest.mark.asyncio
    async def test_imports_with_tags(self, mock_ctx):
        """Test importing hosts with tags."""
        content = """
[hosts.webserver]
hostname = "192.168.1.100"
user = "www"
tags = ["production", "web"]
"""
        imported, _errors = await _import_toml(mock_ctx, content)

        assert imported == 1
        # Check the host was created with correct data
        call_args = mock_ctx.hosts.create.call_args[0][0]
        assert call_args.name == "webserver"
        assert "production" in call_args.tags

    @pytest.mark.asyncio
    async def test_skips_existing_hosts(self, mock_ctx):
        """Test that existing hosts are skipped."""
        mock_ctx.hosts.get_by_name = AsyncMock(return_value=MagicMock())  # Host exists

        content = """
[hosts.existing]
hostname = "10.0.0.1"
"""
        imported, errors = await _import_toml(mock_ctx, content)

        assert imported == 0
        assert len(errors) == 1
        assert "already exists" in errors[0]

    @pytest.mark.asyncio
    async def test_handles_missing_hostname(self, mock_ctx):
        """Test error handling for missing hostname."""
        content = """
[hosts.invalid]
user = "admin"
"""
        imported, errors = await _import_toml(mock_ctx, content)

        assert imported == 0
        assert len(errors) == 1
        assert "missing hostname" in errors[0]

    @pytest.mark.asyncio
    async def test_supports_host_alias(self, mock_ctx):
        """Test that 'host' is accepted as alias for 'hostname'."""
        content = """
[hosts.server]
host = "10.0.0.1"
"""
        imported, _errors = await _import_toml(mock_ctx, content)

        assert imported == 1

    @pytest.mark.asyncio
    async def test_supports_bastion_alias(self, mock_ctx):
        """Test that 'bastion' is accepted as alias for 'jump_host'."""
        content = """
[hosts.internal]
hostname = "10.0.0.1"
bastion = "jump.example.com"
"""
        imported, _errors = await _import_toml(mock_ctx, content)

        assert imported == 1
        call_args = mock_ctx.hosts.create.call_args[0][0]
        assert call_args.jump_host == "jump.example.com"

    @pytest.mark.asyncio
    async def test_flat_structure(self, mock_ctx):
        """Test importing hosts at root level (no [hosts] section)."""
        content = """
[webserver]
hostname = "10.0.0.1"
user = "web"

[database]
hostname = "10.0.0.2"
user = "db"
"""
        imported, _errors = await _import_toml(mock_ctx, content)

        assert imported == 2
