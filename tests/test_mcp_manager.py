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
    resolved = manager._resolve_env({
        "PORT": "${MISSING_VAR:-8080}",
        "HOST": "${MISSING_HOST:-localhost}",
    })

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
