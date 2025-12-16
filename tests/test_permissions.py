from unittest.mock import AsyncMock, MagicMock

import pytest

from merlya.security import PermissionManager


class _StubUI:
    """Simple UI stub capturing prompts."""

    def __init__(self, confirm: bool = True, secrets: list[str] | None = None) -> None:
        self.confirm = confirm
        self.secrets = secrets or []
        self.secret_calls: list[str] = []

    async def prompt_confirm(
        self,
        message: str,
        default: bool = False,
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


class _StubSecrets:
    """In-memory secret store stub."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def remove(self, key: str) -> None:
        self._data.pop(key, None)

    def list_names(self) -> list[str]:
        return list(self._data.keys())


def _make_ctx(ui: _StubUI) -> MagicMock:
    ctx = MagicMock()
    ctx.ui = ui
    ctx.secrets = _StubSecrets()
    ctx.hosts = AsyncMock()
    ctx.hosts.get_by_name = AsyncMock(return_value=None)
    return ctx


@pytest.mark.asyncio
async def test_su_without_password_when_privileged_group() -> None:
    """When sudo exists but needs password, prefer sudo_with_password over su."""

    ui = _StubUI(confirm=True, secrets=["pw"])
    ctx = _make_ctx(ui)

    async def fake_execute(_host: str, cmd: str):
        mapping = {
            "whoami": _StubResult("cedric"),
            "groups": _StubResult("wheel users"),
            "which sudo": _StubResult("/usr/bin/sudo"),
            "sudo -n true": _StubResult("", exit_code=1),
            "sudo -l -n 2>&1": _StubResult("sudo: a password is required", exit_code=1),
            "which doas": _StubResult("", exit_code=1),
            "which su": _StubResult("/bin/su"),
        }
        return mapping.get(cmd, _StubResult("", exit_code=1))

    pm = PermissionManager(ctx)
    pm._execute = fake_execute  # type: ignore[assignment]

    result = await pm.prepare_command("host", "systemctl restart nginx")

    assert result.method == "sudo_with_password"
    assert result.needs_password is True
    assert result.input_data is None
    assert result.note == "password_needed"


@pytest.mark.asyncio
async def test_su_prompts_when_no_privileged_group() -> None:
    """When only su is available, return needs_password prompt."""

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
    assert result.needs_password is True
    assert result.input_data is None
    assert result.note == "password_needed"


@pytest.mark.asyncio
async def test_sudo_not_in_sudoers_falls_back_to_su() -> None:
    """When sudo exists but user is not in sudoers, fall back to su."""

    ui = _StubUI(confirm=True, secrets=["rootpw"])
    ctx = _make_ctx(ui)

    async def fake_execute(_host: str, cmd: str):
        mapping = {
            "whoami": _StubResult("cedric"),
            "groups": _StubResult("users"),  # Not in privileged group
            "which sudo": _StubResult("/usr/bin/sudo"),
            "sudo -n true": _StubResult("", exit_code=1),
            # User NOT in sudoers - different error message
            "sudo -l -n 2>&1": _StubResult(
                "cedric is not in the sudoers file. This incident will be reported.",
                exit_code=1,
            ),
            "which doas": _StubResult("", exit_code=1),
            "which su": _StubResult("/bin/su"),
        }
        return mapping.get(cmd, _StubResult("", exit_code=1))

    pm = PermissionManager(ctx)
    pm._execute = fake_execute  # type: ignore[assignment]

    result = await pm.prepare_command("host", "systemctl restart nginx")

    # Should fall back to su since user is not in sudoers
    assert result.method == "su"
    assert result.needs_password is True


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


def test_doas_with_password_uses_stdin_not_command_injection() -> None:
    """doas_with_password must not embed the password in the command string."""
    ctx = _make_ctx(_StubUI())
    pm = PermissionManager(ctx)

    cmd, input_data = pm.elevate_command(
        "cat /etc/shadow",
        capabilities={"is_root": False},
        method="doas_with_password",
        password="s3cr3t",
    )

    assert "s3cr3t" not in cmd
    assert input_data == "s3cr3t\n"


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


class TestPermissionManagerFailedMethods:
    """Tests for failed method tracking (prevents retry loops)."""

    def test_mark_method_failed_tracks_failure(self) -> None:
        """Test that mark_method_failed tracks the failed method."""
        ctx = _make_ctx(_StubUI())
        pm = PermissionManager(ctx)

        assert not pm.is_method_failed("host1", "sudo_with_password")

        pm.mark_method_failed("host1", "sudo_with_password")

        assert pm.is_method_failed("host1", "sudo_with_password")
        assert not pm.is_method_failed("host1", "su")  # Other methods not affected
        assert not pm.is_method_failed("host2", "sudo_with_password")  # Other hosts not affected

    def test_mark_method_failed_clears_password(self) -> None:
        """Test that mark_method_failed clears cached password from keyring."""
        ctx = _make_ctx(_StubUI())
        pm = PermissionManager(ctx)

        # Cache a password first
        pm.cache_password("host1", "wrongpassword", "sudo_with_password")
        assert pm._get_cached_password("host1") is not None

        # Mark as failed should clear the password
        pm.mark_method_failed("host1", "sudo_with_password")

        assert pm._get_cached_password("host1") is None

    def test_mark_method_failed_clears_su_root_password(self) -> None:
        """Test that mark_method_failed clears root password for su method."""
        ctx = _make_ctx(_StubUI())
        pm = PermissionManager(ctx)

        # Cache root password for su
        pm.cache_password("host1", "wrongrootpwd", "su")
        # Verify it's stored with the root key
        assert ctx.secrets.get("elevation:host1:root:password") is not None

        # Mark su as failed should clear the root password
        pm.mark_method_failed("host1", "su")

        assert ctx.secrets.get("elevation:host1:root:password") is None

    def test_mark_method_failed_clears_consented_method(self) -> None:
        """Test that mark_method_failed clears the consented method."""
        ctx = _make_ctx(_StubUI())
        pm = PermissionManager(ctx)

        # Simulate a consented method
        pm._consented_methods["host1"] = "sudo_with_password"
        assert pm._consented_methods.get("host1") == "sudo_with_password"

        # Mark as failed should clear the consented method
        pm.mark_method_failed("host1", "sudo_with_password")

        assert "host1" not in pm._consented_methods

    def test_mark_method_failed_does_not_clear_other_consented_method(self) -> None:
        """Test that mark_method_failed doesn't clear consented if different method."""
        ctx = _make_ctx(_StubUI())
        pm = PermissionManager(ctx)

        # Simulate consented to su
        pm._consented_methods["host1"] = "su"

        # Mark sudo_with_password as failed should not affect su consent
        pm.mark_method_failed("host1", "sudo_with_password")

        assert pm._consented_methods.get("host1") == "su"

    def test_clear_failed_methods_single_host(self) -> None:
        """Test clearing failed methods for a single host."""
        ctx = _make_ctx(_StubUI())
        pm = PermissionManager(ctx)

        pm.mark_method_failed("host1", "sudo_with_password")
        pm.mark_method_failed("host1", "su")
        pm.mark_method_failed("host2", "sudo_with_password")

        pm.clear_failed_methods("host1")

        assert not pm.is_method_failed("host1", "sudo_with_password")
        assert not pm.is_method_failed("host1", "su")
        assert pm.is_method_failed("host2", "sudo_with_password")  # Other host not affected

    def test_clear_failed_methods_all_hosts(self) -> None:
        """Test clearing failed methods for all hosts."""
        ctx = _make_ctx(_StubUI())
        pm = PermissionManager(ctx)

        pm.mark_method_failed("host1", "sudo_with_password")
        pm.mark_method_failed("host2", "su")

        pm.clear_failed_methods()

        assert not pm.is_method_failed("host1", "sudo_with_password")
        assert not pm.is_method_failed("host2", "su")

    def test_clear_cache_also_clears_failed_methods(self) -> None:
        """Test that clear_cache also clears failed method tracking."""
        ctx = _make_ctx(_StubUI())
        pm = PermissionManager(ctx)

        pm.mark_method_failed("host1", "sudo_with_password")

        pm.clear_cache("host1")

        assert not pm.is_method_failed("host1", "sudo_with_password")
