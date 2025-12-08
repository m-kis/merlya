from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from merlya.commands.handlers import model as model_cmd
from merlya.i18n.loader import I18n


class FakeProcess:
    def __init__(self, returncode: int, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True


def _ctx() -> SimpleNamespace:
    ui = MagicMock()
    ui.prompt_secret = AsyncMock(return_value="secret")
    config = SimpleNamespace(
        model=SimpleNamespace(provider="ollama", model="llama3.2", api_key_env=None, base_url=None),
        router=SimpleNamespace(),
        save=MagicMock(),
    )
    secrets = MagicMock()
    secrets.has = MagicMock(return_value=False)
    secrets.set = MagicMock()
    return SimpleNamespace(
        ui=ui,
        config=config,
        secrets=secrets,
        t=I18n("en").t,
    )


@pytest.mark.asyncio
async def test_cmd_model_model_ollama_pull_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Should pull model and report success."""
    ctx = _ctx()

    async def fake_cse(*_args: Any, **_kwargs: Any) -> FakeProcess:
        return FakeProcess(returncode=0, stdout=b"pulled")

    monkeypatch.setattr(model_cmd, "shutil", SimpleNamespace(which=lambda _: "/usr/bin/ollama"))
    monkeypatch.setattr(model_cmd.asyncio, "create_subprocess_exec", fake_cse)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)

    result = await model_cmd.cmd_model_model(ctx, ["llama3.2"])

    assert result.success is True
    ctx.ui.success.assert_called_with("✅ Ollama model `llama3.2` ready")


@pytest.mark.asyncio
async def test_cmd_model_model_ollama_pull_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Should warn user when model does not exist on Ollama."""
    ctx = _ctx()

    async def fake_cse(*_args: Any, **_kwargs: Any) -> FakeProcess:
        return FakeProcess(returncode=1, stderr=b"model not found")

    monkeypatch.setattr(model_cmd, "shutil", SimpleNamespace(which=lambda _: "/usr/bin/ollama"))
    monkeypatch.setattr(model_cmd.asyncio, "create_subprocess_exec", fake_cse)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)

    result = await model_cmd.cmd_model_model(ctx, ["ghost-model"])

    assert result.success is False
    assert "does not exist" in result.message


@pytest.mark.asyncio
async def test_cmd_model_model_ollama_cli_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Should fail fast when Ollama CLI is unavailable."""
    ctx = _ctx()
    monkeypatch.setattr(model_cmd, "shutil", SimpleNamespace(which=lambda _: None))

    result = await model_cmd.cmd_model_model(ctx, ["llama3.2"])

    assert result.success is False
    assert "Ollama CLI" in result.message


@pytest.mark.asyncio
async def test_cmd_model_model_ollama_cloud_skips_pull(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cloud models should not trigger local pull and should set cloud base URL."""
    ctx = _ctx()
    calls: list[str] = []

    async def fake_cse(*_args: Any, **_kwargs: Any) -> FakeProcess:
        calls.append("called")
        return FakeProcess(returncode=0, stdout=b"pulled")

    monkeypatch.setattr(model_cmd, "shutil", SimpleNamespace(which=lambda _: "/usr/bin/ollama"))
    monkeypatch.setattr(model_cmd.asyncio, "create_subprocess_exec", fake_cse)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)

    result = await model_cmd.cmd_model_model(ctx, ["ministral-3:14b-cloud"])

    assert result.success is True
    assert "called" not in calls  # pull not invoked
    assert ctx.config.model.base_url == "https://ollama.com/v1"
