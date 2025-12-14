"""Tests for MCP manager utilities."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from merlya.config.loader import Config
from merlya.mcp.manager import MCPManager


class DummySecrets:
    """Simple secret store stub."""

    def __init__(self, value: str | None = None) -> None:
        self.value = value

    def get(self, _name: str) -> str | None:  # pragma: no cover - trivial
        return self.value if self.value is not None else None


@pytest.mark.asyncio
async def test_resolve_env_prefers_secret_store():
    """Ensure templated env vars pull from secrets when available."""
    config = Config()
    config._path = Path(tempfile.mkdtemp()) / "config.yaml"
    secrets = DummySecrets(value="secret-token")

    manager = MCPManager(config, secrets)
    resolved = manager._resolve_env({"TOKEN": "${GITHUB_TOKEN}", "PLAIN": "abc"})

    assert resolved["TOKEN"] == "secret-token"
    assert resolved["PLAIN"] == "abc"


@pytest.mark.asyncio
async def test_add_server_persists_config(tmp_path: Path):
    """Ensure add_server stores configuration."""
    config = Config()
    config._path = tmp_path / "config.yaml"
    secrets = DummySecrets()
    manager = MCPManager(config, secrets)

    await manager.add_server("github", "npx", ["-y", "pkg"], {"TOKEN": "${GITHUB_TOKEN}"})

    assert "github" in config.mcp.servers
    stored = config.mcp.servers["github"]
    assert stored.command == "npx"
    assert stored.args == ["-y", "pkg"]
    assert stored.env["TOKEN"] == "${GITHUB_TOKEN}"


@pytest.mark.asyncio
async def test_resolve_env_uses_default_value(monkeypatch: pytest.MonkeyPatch):
    """Ensure ${VAR:-default} syntax falls back to default."""
    monkeypatch.delenv("MISSING_VAR", raising=False)
    monkeypatch.delenv("MISSING_HOST", raising=False)

    config = Config()
    config._path = Path(tempfile.mkdtemp()) / "config.yaml"
    secrets = DummySecrets(value=None)  # No secret available

    manager = MCPManager(config, secrets)
    resolved = manager._resolve_env(
        {
            "PORT": "${MISSING_VAR:-8080}",
            "HOST": "${MISSING_HOST:-localhost}",
        }
    )

    assert resolved["PORT"] == "8080"
    assert resolved["HOST"] == "localhost"


@pytest.mark.asyncio
async def test_resolve_env_prefers_value_over_default(monkeypatch: pytest.MonkeyPatch):
    """Ensure actual value takes precedence over default."""
    monkeypatch.setenv("MY_PORT", "9090")

    config = Config()
    config._path = Path(tempfile.mkdtemp()) / "config.yaml"
    secrets = DummySecrets(value=None)

    manager = MCPManager(config, secrets)
    resolved = manager._resolve_env({"PORT": "${MY_PORT:-8080}"})

    assert resolved["PORT"] == "9090"


@pytest.mark.asyncio
async def test_build_server_params_merges_with_default_env():
    """Ensure custom env vars are merged with default MCP environment (PATH, HOME, etc.)."""
    from mcp.client.stdio import get_default_environment

    from merlya.config.models import MCPServerConfig

    config = Config()
    config._path = Path(tempfile.mkdtemp()) / "config.yaml"
    secrets = DummySecrets(value="my-token")

    manager = MCPManager(config, secrets)
    server_config = MCPServerConfig(
        command="npx",
        args=["-y", "some-mcp-server"],
        env={"API_KEY": "${TOKEN}"},
    )

    params = manager._build_server_params("test", server_config)

    # Should have merged custom env with default
    assert params.env is not None
    assert "API_KEY" in params.env
    assert params.env["API_KEY"] == "my-token"
    # Should also have PATH from default environment
    assert "PATH" in params.env
    assert params.env["PATH"] == get_default_environment()["PATH"]


@pytest.mark.asyncio
async def test_build_server_params_uses_none_when_no_custom_env():
    """Ensure env=None when no custom env, letting SDK use defaults."""
    from merlya.config.models import MCPServerConfig

    config = Config()
    config._path = Path(tempfile.mkdtemp()) / "config.yaml"
    secrets = DummySecrets(value=None)

    manager = MCPManager(config, secrets)
    server_config = MCPServerConfig(
        command="npx",
        args=["-y", "some-mcp-server"],
        env={},  # Empty env
    )

    params = manager._build_server_params("test", server_config)

    # Should be None to let SDK use get_default_environment()
    assert params.env is None


def test_mcp_tool_info_includes_schema():
    """Ensure MCPToolInfo can store input schema for LLM usage."""
    from merlya.mcp.manager import MCPToolInfo

    # Test with schema
    tool_with_schema = MCPToolInfo(
        name="context7.get-library-docs",
        description="Get documentation for a library",
        server="context7",
        input_schema={
            "type": "object",
            "properties": {
                "context7CompatibleLibraryID": {"type": "string"},
                "topic": {"type": "string"},
            },
            "required": ["context7CompatibleLibraryID"],
        },
    )

    assert tool_with_schema.input_schema is not None
    assert "required" in tool_with_schema.input_schema
    assert "context7CompatibleLibraryID" in tool_with_schema.input_schema["required"]

    # Test without schema (backwards compatibility)
    tool_without_schema = MCPToolInfo(
        name="simple.tool",
        description="A simple tool",
        server="simple",
    )
    assert tool_without_schema.input_schema is None
