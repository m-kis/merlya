from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from merlya.security import PermissionManager
from merlya.security.permissions import PASSWORD_CACHE_TTL, CachedPassword


class _StubUI:
    """Simple UI stub capturing prompts."""

    def __init__(self, confirm: bool = True, secrets: list[str] | None = None) -> None:
        self.confirm = confirm
        self.secrets = secrets or []
        self.secret_calls: list[str] = []

    async def prompt_confirm(
        self,
        message: str,  # noqa: ARG002
        default: bool = False,  # noqa: ARG002
    ) -> bool:
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
    """When sudo exists (no NOPASSWD) but su is available, prefer su over sudo_with_password.

    First attempt is always without password - password prompt only if su fails.
    """

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
    assert result.note == "try_without_password"  # will retry with password if fails


@pytest.mark.asyncio
async def test_su_prompts_when_no_privileged_group() -> None:
    """su is attempted passwordless first, password prompt only if it fails."""

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
    assert result.note == "try_without_password"  # will retry with password if fails


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


class TestCachedPassword:
    """Tests for CachedPassword TTL functionality."""

    def test_new_password_not_expired(self) -> None:
        """Test that a new cached password is not expired."""
        cached = CachedPassword(password="secret")
        assert not cached.is_expired()

    def test_expired_password(self) -> None:
        """Test that an old password is expired."""
        # Create a password that expired 1 minute ago
        expired_time = datetime.now(UTC) - timedelta(minutes=1)
        cached = CachedPassword(password="secret", expires_at=expired_time)
        assert cached.is_expired()

    def test_password_ttl_correct(self) -> None:
        """Test that password TTL is set correctly."""
        before = datetime.now(UTC)
        cached = CachedPassword(password="secret")
        after = datetime.now(UTC)

        # expires_at should be within PASSWORD_CACHE_TTL of now
        expected_min = before + PASSWORD_CACHE_TTL
        expected_max = after + PASSWORD_CACHE_TTL

        assert expected_min <= cached.expires_at <= expected_max


class TestPermissionManagerPasswordCache:
    """Tests for PermissionManager password cache functionality."""

    def test_get_cached_password_returns_valid(self) -> None:
        """Test that _get_cached_password returns valid password."""
        ctx = _make_ctx(_StubUI())
        pm = PermissionManager(ctx)

        # Cache a password
        pm.cache_password("host1", "secret123")

        # Should return the password
        result = pm._get_cached_password("host1")
        assert result == "secret123"

    def test_get_cached_password_returns_none_for_unknown(self) -> None:
        """Test that _get_cached_password returns None for unknown host."""
        ctx = _make_ctx(_StubUI())
        pm = PermissionManager(ctx)

        result = pm._get_cached_password("unknown-host")
        assert result is None

    def test_get_cached_password_cleans_expired(self) -> None:
        """Test that _get_cached_password cleans up expired passwords."""
        ctx = _make_ctx(_StubUI())
        pm = PermissionManager(ctx)

        # Manually insert an expired password
        expired_time = datetime.now(UTC) - timedelta(minutes=1)
        pm._password_cache["host1"] = CachedPassword(
            password="expired",
            expires_at=expired_time,
        )

        # Should return None and clean up
        result = pm._get_cached_password("host1")
        assert result is None
        assert "host1" not in pm._password_cache

    def test_clear_cache_single_host(self) -> None:
        """Test clearing cache for a single host."""
        ctx = _make_ctx(_StubUI())
        pm = PermissionManager(ctx)

        pm.cache_password("host1", "pwd1")
        pm.cache_password("host2", "pwd2")

        pm.clear_cache("host1")

        assert pm._get_cached_password("host1") is None
        assert pm._get_cached_password("host2") == "pwd2"

    def test_clear_cache_all(self) -> None:
        """Test clearing cache for all hosts."""
        ctx = _make_ctx(_StubUI())
        pm = PermissionManager(ctx)

        pm.cache_password("host1", "pwd1")
        pm.cache_password("host2", "pwd2")

        pm.clear_cache()

        assert pm._get_cached_password("host1") is None
        assert pm._get_cached_password("host2") is None


class TestPermissionManagerLocking:
    """Tests for PermissionManager locking functionality."""

    @pytest.mark.asyncio
    async def test_get_host_lock_creates_lock(self) -> None:
        """Test that _get_host_lock creates a lock for new host."""
        ctx = _make_ctx(_StubUI())
        pm = PermissionManager(ctx)

        lock = await pm._get_host_lock("host1")
        assert lock is not None
        assert "host1" in pm._detection_locks

    @pytest.mark.asyncio
    async def test_get_host_lock_returns_same_lock(self) -> None:
        """Test that _get_host_lock returns the same lock for same host."""
        ctx = _make_ctx(_StubUI())
        pm = PermissionManager(ctx)

        lock1 = await pm._get_host_lock("host1")
        lock2 = await pm._get_host_lock("host1")
        assert lock1 is lock2

    @pytest.mark.asyncio
    async def test_get_host_lock_different_hosts(self) -> None:
        """Test that _get_host_lock returns different locks for different hosts."""
        ctx = _make_ctx(_StubUI())
        pm = PermissionManager(ctx)

        lock1 = await pm._get_host_lock("host1")
        lock2 = await pm._get_host_lock("host2")
        assert lock1 is not lock2
