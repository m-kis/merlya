from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from merlya.persistence.models import Host
from merlya.tools.interaction import request_credentials


class _StubUI:
    def __init__(self) -> None:
        self.secret_prompts: list[str] = []
        self.confirm_calls = 0
        self.auto_confirm = False  # Simulate interactive mode

    async def prompt_secret(self, message: str) -> str:
        self.secret_prompts.append(message)
        return "asked"

    async def prompt_confirm(self, *_: object, **__: object) -> bool:
        self.confirm_calls += 1
        return False

    def info(self, *_: object, **__: object) -> None:
        return None

    def muted(self, *_: object, **__: object) -> None:
        return None

    def success(self, *_: object, **__: object) -> None:
        return None


class _StubSecrets:
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self.store = initial or {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str) -> None:
        self.store[key] = value


class _StubConfig:
    class SSH:
        def __init__(self, default_user: str | None = None, default_key: str | None = None) -> None:
            self.default_user = default_user
            self.default_key = Path(default_key) if default_key else None

    def __init__(self, default_user: str | None = None, default_key: str | None = None) -> None:
        self.ssh = self.SSH(default_user=default_user, default_key=default_key)


@pytest.mark.asyncio
async def test_request_credentials_prefers_host_inventory_username() -> None:
    ui = _StubUI()
    secrets = _StubSecrets()
    cfg = _StubConfig()
    host = Host(name="preprodlb", hostname="1.1.1.1", username="cedric")

    ctx = MagicMock()
    ctx.ui = ui
    ctx.secrets = secrets
    ctx.config = cfg
    ctx.auto_confirm = False  # Interactive mode
    ctx.hosts.get_by_name = AsyncMock(return_value=host)

    result = await request_credentials(ctx, service="ssh", host="preprodlb", fields=["username"])

    assert result.success
    assert result.data.values["username"] == "cedric"
    assert ui.secret_prompts == []  # no interactive prompt


@pytest.mark.asyncio
async def test_request_credentials_ssh_key_based_skips_password_prompt() -> None:
    """When a key is configured, only ask for username (no password prompt)."""
    ui = _StubUI()
    secrets = _StubSecrets()
    cfg = _StubConfig(default_key="~/.ssh/id_rsa")
    host = Host(name="preprodmongo6-1", hostname="1.1.1.1", private_key="~/.ssh/id_rsa")

    ctx = MagicMock()
    ctx.ui = ui
    ctx.secrets = secrets
    ctx.config = cfg
    ctx.auto_confirm = False  # Interactive mode
    ctx.hosts.get_by_name = AsyncMock(return_value=host)

    result = await request_credentials(ctx, service="ssh", host="preprodmongo6-1")

    assert result.success
    assert result.data.values.get("username") is not None  # from default or prompt
    # Password should not be prompted because key is available
    assert ui.secret_prompts in ([], ["Username"])


@pytest.mark.asyncio
async def test_request_credentials_prefills_from_secret_store() -> None:
    ui = _StubUI()
    secrets = _StubSecrets({"mysql:db:username": "dbuser", "mysql:db:password": "pwd"})
    cfg = _StubConfig()

    ctx = MagicMock()
    ctx.ui = ui
    ctx.secrets = secrets
    ctx.config = cfg
    ctx.auto_confirm = False  # Interactive mode
    ctx.hosts.get_by_name = AsyncMock(return_value=None)

    result = await request_credentials(ctx, service="mysql", host="db")

    assert result.success
    assert result.data.values["username"] == "dbuser"
    assert result.data.values["password"] == "pwd"
    assert ui.secret_prompts == []  # no prompt since secrets exist


@pytest.mark.asyncio
async def test_request_credentials_ssh_skip_password_without_hint() -> None:
    """SSH without password hint should not prompt for password."""
    ui = _StubUI()
    secrets = _StubSecrets()
    cfg = _StubConfig(default_user="cedric")
    ctx = MagicMock()
    ctx.ui = ui
    ctx.secrets = secrets
    ctx.config = cfg
    ctx.auto_confirm = False  # Interactive mode
    ctx.hosts.get_by_name = AsyncMock(return_value=None)

    result = await request_credentials(ctx, service="ssh", host="no-key-host")

    assert result.success
    assert ui.secret_prompts in ([], ["Username"])  # only username at most
    assert "password" not in result.data.values


@pytest.mark.asyncio
async def test_request_credentials_ssh_prompts_password_when_hint() -> None:
    """SSH password prompt occurs only when explicitly requested via format_hint."""
    ui = _StubUI()
    secrets = _StubSecrets()
    cfg = _StubConfig(default_user="cedric")
    ctx = MagicMock()
    ctx.ui = ui
    ctx.secrets = secrets
    ctx.config = cfg
    ctx.auto_confirm = False  # Interactive mode
    ctx.hosts.get_by_name = AsyncMock(return_value=None)

    result = await request_credentials(
        ctx, service="ssh", host="no-key-host", format_hint="password"
    )

    assert result.success
    # Username may be prefilled from default_user; password must be prompted
    assert ui.secret_prompts == ["Password"]
    assert "password" in result.data.values


@pytest.mark.asyncio
async def test_request_credentials_fails_in_non_interactive_mode() -> None:
    """Non-interactive mode should fail early when credentials are missing."""
    ui = _StubUI()
    ui.auto_confirm = True  # Non-interactive mode
    secrets = _StubSecrets()  # Empty - no stored credentials
    cfg = _StubConfig(default_user="cedric")
    ctx = MagicMock()
    ctx.ui = ui
    ctx.secrets = secrets
    ctx.config = cfg
    ctx.auto_confirm = True  # Non-interactive mode
    ctx.hosts.get_by_name = AsyncMock(return_value=None)

    result = await request_credentials(ctx, service="sudo", host="server01")

    # Should fail because we can't prompt in non-interactive mode
    assert not result.success
    assert "non-interactive mode" in result.message.lower()
    assert result.data["non_interactive"] is True
    assert "password" in result.data["missing_fields"]
    # Should NOT have called any prompts
    assert ui.secret_prompts == []


@pytest.mark.asyncio
async def test_request_credentials_succeeds_in_non_interactive_with_stored_creds() -> None:
    """Non-interactive mode should succeed when credentials are already stored."""
    ui = _StubUI()
    ui.auto_confirm = True  # Non-interactive mode
    secrets = _StubSecrets({"sudo:server01:password": "stored_pwd"})
    cfg = _StubConfig(default_user="cedric")
    ctx = MagicMock()
    ctx.ui = ui
    ctx.secrets = secrets
    ctx.config = cfg
    ctx.auto_confirm = True  # Non-interactive mode
    ctx.hosts.get_by_name = AsyncMock(return_value=None)

    result = await request_credentials(ctx, service="sudo", host="server01")

    # Should succeed because credentials are already stored
    assert result.success
    assert result.data.values.get("password") == "stored_pwd"
    # Should NOT have called any prompts
    assert ui.secret_prompts == []
