from unittest.mock import MagicMock

import pytest

from merlya.security import PermissionManager


class _StubUI:
    """Simple UI stub capturing prompts."""

    def __init__(self, confirm: bool = True, secrets: list[str] | None = None) -> None:
        self.confirm = confirm
        self.secrets = secrets or []
        self.secret_calls: list[str] = []

    async def prompt_confirm(self, message: str, default: bool = False) -> bool:
        return self.confirm

    async def prompt_secret(self, message: str) -> str:
        self.secret_calls.append(message)
        return self.secrets.pop(0) if self.secrets else ""

    def info(self, *_: object, **__: object) -> None:
        return None

    def muted(self, *_: object, **__: object) -> None:
        return None

    def success(self, *_: object, **__: object) -> None:
        return None


class _StubResult:
    def __init__(self, stdout: str = "", exit_code: int = 0) -> None:
        self.stdout = stdout
        self.exit_code = exit_code


def _make_ctx(ui: _StubUI) -> MagicMock:
    ctx = MagicMock()
    ctx.ui = ui
    return ctx


@pytest.mark.asyncio
async def test_su_without_password_when_privileged_group() -> None:
    """When sudo exists (no NOPASSWD) but su is available, prefer su over sudo_with_password."""

    ui = _StubUI(confirm=True, secrets=["pw"])
    ctx = _make_ctx(ui)

    async def fake_execute(_host: str, cmd: str):
        mapping = {
            "whoami": _StubResult("cedric"),
            "groups": _StubResult("wheel users"),
            "which sudo": _StubResult("/usr/bin/sudo"),
            "sudo -n true": _StubResult("", exit_code=1),
            "which doas": _StubResult("", exit_code=1),
            "which su": _StubResult("/bin/su"),
        }
        return mapping.get(cmd, _StubResult("", exit_code=1))

    pm = PermissionManager(ctx)
    pm._execute = fake_execute  # type: ignore[assignment]

    result = await pm.prepare_command("host", "systemctl restart nginx")

    assert result.method == "su"
    assert result.input_data is None  # first attempt is passwordless
    assert result.note == "password_optional"


@pytest.mark.asyncio
async def test_su_prompts_when_no_privileged_group() -> None:
    """su is attempted passwordless first, marked as password_optional."""

    ui = _StubUI(confirm=True, secrets=["pw123"])
    ctx = _make_ctx(ui)

    async def fake_execute(_host: str, cmd: str):
        mapping = {
            "whoami": _StubResult("user"),
            "groups": _StubResult("users"),
            "which sudo": _StubResult("", exit_code=1),
            "which doas": _StubResult("", exit_code=1),
            "which su": _StubResult("/bin/su"),
        }
        return mapping.get(cmd, _StubResult("", exit_code=1))

    pm = PermissionManager(ctx)
    pm._execute = fake_execute  # type: ignore[assignment]

    result = await pm.prepare_command("host", "systemctl restart nginx")

    assert result.method == "su"
    assert result.input_data is None  # first attempt without password
    assert result.note == "password_optional"


@pytest.mark.asyncio
async def test_sudo_nopasswd_avoids_prompt() -> None:
    """sudo -n success should avoid any password prompt."""

    ui = _StubUI(confirm=True)
    ctx = _make_ctx(ui)

    async def fake_execute(_host: str, cmd: str):
        mapping = {
            "whoami": _StubResult("cedric"),
            "groups": _StubResult("sudo users"),
            "which sudo": _StubResult("/usr/bin/sudo"),
            "sudo -n true": _StubResult("", exit_code=0),
        }
        return mapping.get(cmd, _StubResult("", exit_code=1))

    pm = PermissionManager(ctx)
    pm._execute = fake_execute  # type: ignore[assignment]

    result = await pm.prepare_command("host", "systemctl restart nginx")

    assert result.method == "sudo"
    assert result.input_data is None
    assert ui.secret_calls == []
