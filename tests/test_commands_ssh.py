"""Tests for SSH command handlers."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

import asyncssh
import pytest

from merlya.commands.handlers.ssh import (
    _candidate_passphrase_keys,
    _lookup_passphrase,
    _prompt_private_key,
    _prompt_ssh_config,
    cmd_ssh_connect,
)
from merlya.persistence.models import Host


@pytest.mark.asyncio
async def test_prompt_ssh_config_requests_passphrase_on_encrypted_key(tmp_path: Path) -> None:
    """Ensure encrypted keys trigger passphrase prompt and secure storage."""
    key_path = tmp_path / "id_rsa"
    key_path.write_text("dummy")
    host = Host(name="deploy", hostname="example.com", port=22, username="cedric")

    ctx = MagicMock()
    ctx.ui = MagicMock()
    ctx.ui.prompt = AsyncMock(side_effect=["", str(host.port), str(key_path), ""])
    ctx.ui.prompt_secret = AsyncMock(return_value="pass123")
    ctx.ui.warning = MagicMock()
    ctx.ui.success = MagicMock()
    ctx.ui.error = MagicMock()
    ctx.secrets = MagicMock()
    ctx.secrets.get = MagicMock(return_value=None)
    ctx.secrets.set = MagicMock()

    with patch(
        "merlya.commands.handlers.ssh.asyncssh.read_private_key",
        side_effect=[
            asyncssh.KeyImportError(
                "Passphrase must be specified to import encrypted private keys"
            ),
            MagicMock(),
        ],
    ):
        await _prompt_ssh_config(ctx, host)

    assert host.private_key == str(key_path)
    ctx.ui.prompt_secret.assert_called_once_with(f"🔐 Passphrase for {key_path}")
    ctx.secrets.set.assert_any_call(f"ssh:passphrase:{host.name}", "pass123")
    ctx.secrets.set.assert_any_call(f"ssh:passphrase:{key_path.name}", "pass123")
    ctx.secrets.set.assert_any_call(f"ssh:passphrase:{key_path!s}", "pass123")


@pytest.mark.asyncio
async def test_prompt_private_key_reuses_cached_passphrase(tmp_path: Path) -> None:
    """Use cached passphrase without prompting user again."""
    key_path = tmp_path / "id_ed25519"
    key_path.write_text("dummy")
    host = Host(name="cache-host", hostname="cached.example", port=22)

    ctx = MagicMock()
    ctx.ui = MagicMock()
    ctx.ui.prompt = AsyncMock(return_value=str(key_path))
    ctx.ui.prompt_secret = AsyncMock()
    ctx.ui.warning = MagicMock()
    ctx.ui.success = MagicMock()
    ctx.ui.error = MagicMock()
    ctx.secrets = MagicMock()
    ctx.secrets.get = MagicMock(return_value="cached-pass")
    ctx.secrets.set = MagicMock()

    with patch("merlya.commands.handlers.ssh.asyncssh.read_private_key") as read_key:
        read_key.return_value = MagicMock()
        passphrase = await _prompt_private_key(ctx, host)

    read_key.assert_called_once_with(str(key_path), "cached-pass")
    ctx.ui.prompt_secret.assert_not_called()
    assert passphrase == "cached-pass"
    assert host.private_key == str(key_path)


@pytest.mark.asyncio
async def test_cmd_ssh_connect_installs_passphrase_callback() -> None:
    """Ensure /ssh connect sets passphrase callback and reuses stored secret."""
    host = Host(
        name="deploy",
        hostname="example.com",
        port=22,
        username="cedric",
        private_key="/tmp/id_rsa",
    )

    ctx = MagicMock()
    ctx.ui = MagicMock()
    ctx.ui.info = MagicMock()
    ctx.ui.muted = MagicMock()
    ctx.ui.success = MagicMock()
    ctx.ui.warning = MagicMock()
    ctx.ui.error = MagicMock()
    ctx.ui.prompt_secret = AsyncMock()

    ctx.secrets = MagicMock()
    ctx.secrets.get = MagicMock(return_value="cached-pass")
    ctx.secrets.set = MagicMock()

    ctx.hosts = MagicMock()
    ctx.hosts.get_by_name = AsyncMock(return_value=host)

    passphrase_cb_holder: dict[str, object] = {}

    async def fake_get_connection(**_kwargs):
        return MagicMock()

    pool = MagicMock()
    pool.has_passphrase_callback.return_value = False
    pool.has_mfa_callback.return_value = True
    pool.set_passphrase_callback.side_effect = lambda cb: passphrase_cb_holder.update({"cb": cb})
    pool.get_connection = AsyncMock(side_effect=fake_get_connection)

    ctx.get_ssh_pool = AsyncMock(return_value=pool)

    result = await cmd_ssh_connect(ctx, ["deploy"])
    assert result.success is True
    assert "Connected" in result.message
    assert "cb" in passphrase_cb_holder
    cb = passphrase_cb_holder["cb"]
    assert cb("/tmp/id_rsa") == "cached-pass"
    ctx.ui.prompt_secret.assert_not_called()


def test_lookup_passphrase_falls_back_to_keyring(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Direct keyring lookup is used if SecretStore returns nothing."""
    collected: dict[str, str] = {"called": "false"}

    class DummySecrets:
        def get(self, _name: str) -> str | None:
            return None

    def fake_get_password(service: str, name: str) -> str | None:  # type: ignore[override]
        collected["called"] = f"{service}:{name}"
        return "from-keyring" if "id_ed25519" in name else None

    from types import SimpleNamespace

    keyring_stub = SimpleNamespace(get_password=fake_get_password)
    monkeypatch.setitem(sys.modules, "keyring", keyring_stub)

    ctx = SimpleNamespace(secrets=DummySecrets())
    keys = _candidate_passphrase_keys("host", str(tmp_path / "id_ed25519"), tmp_path / "id_ed25519")
    secret = _lookup_passphrase(ctx, keys)

    assert secret == "from-keyring"
    assert "merlya:ssh:passphrase" in collected["called"]
