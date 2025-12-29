"""Tests for ElevationManager (simplified from PermissionManager)."""

from unittest.mock import MagicMock

import pytest

from merlya.persistence.models import ElevationMethod, Host, SSHMode
from merlya.security import CenterMode, ElevationDeniedError, ElevationManager


class _StubUI:
    """Simple UI stub capturing prompts."""

    def __init__(
        self,
        confirm: bool | list[bool] = True,
        secrets: list[str] | None = None,
    ) -> None:
        # confirm can be a single bool or a list for sequential answers
        self._confirm_answers = [confirm] if isinstance(confirm, bool) else list(confirm)
        self.secrets = secrets or []
        self.secret_calls: list[str] = []
        self.confirm_calls: list[str] = []

    @property
    def confirm(self) -> bool:
        """Return current confirm value."""
        return self._confirm_answers[0] if self._confirm_answers else True

    @confirm.setter
    def confirm(self, value: bool) -> None:
        """Set confirm value."""
        self._confirm_answers = [value]

    async def prompt_confirm(self, message: str, default: bool = False) -> bool:
        self.confirm_calls.append(message)
        if self._confirm_answers:
            return self._confirm_answers.pop(0)
        return True

    async def prompt_secret(self, message: str) -> str:
        self.secret_calls.append(message)
        return self.secrets.pop(0) if self.secrets else ""


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


def _make_ctx(ui: _StubUI) -> MagicMock:
    ctx = MagicMock()
    ctx.ui = ui
    ctx.secrets = _StubSecrets()
    return ctx


def _make_host(
    name: str = "test-host",
    elevation_method: ElevationMethod = ElevationMethod.NONE,
    elevation_user: str = "root",
) -> Host:
    """Create a test host with configured elevation."""
    return Host(
        name=name,
        hostname="192.168.1.1",
        elevation_method=elevation_method,
        elevation_user=elevation_user,
        ssh_mode=SSHMode.READ_WRITE,
    )


class TestElevationManagerNoElevation:
    """Tests for hosts without elevation configured."""

    @pytest.mark.asyncio
    async def test_no_elevation_returns_original_command(self) -> None:
        """When elevation_method is NONE, return command unchanged."""
        ui = _StubUI(confirm=True)
        ctx = _make_ctx(ui)
        em = ElevationManager(ctx)
        host = _make_host(elevation_method=ElevationMethod.NONE)

        result = await em.prepare_command(host, "ls -la")

        assert result.command == "ls -la"
        assert result.method is None
        assert result.elevated is False
        assert result.input_data is None
        assert ui.confirm_calls == []  # No confirmation needed


class TestElevationManagerSudo:
    """Tests for sudo elevation (NOPASSWD)."""

    @pytest.mark.asyncio
    async def test_sudo_nopasswd_prefixes_command(self) -> None:
        """sudo (NOPASSWD) should prefix command with sudo -n."""
        ui = _StubUI(confirm=True)
        ctx = _make_ctx(ui)
        em = ElevationManager(ctx)
        host = _make_host(elevation_method=ElevationMethod.SUDO)

        result = await em.prepare_command(host, "systemctl restart nginx")

        assert result.command == "sudo -n systemctl restart nginx"
        assert result.method == "sudo"
        assert result.elevated is True
        assert result.input_data is None

    @pytest.mark.asyncio
    async def test_sudo_strips_existing_prefix(self) -> None:
        """Should strip existing sudo prefix before applying configured method."""
        ui = _StubUI(confirm=True)
        ctx = _make_ctx(ui)
        em = ElevationManager(ctx)
        host = _make_host(elevation_method=ElevationMethod.SUDO)

        result = await em.prepare_command(host, "sudo systemctl restart nginx")

        # Should not have double sudo
        assert result.command == "sudo -n systemctl restart nginx"


class TestElevationManagerSudoPassword:
    """Tests for sudo with password."""

    @pytest.mark.asyncio
    async def test_sudo_password_prompts_for_password(self) -> None:
        """sudo_password should prompt for password."""
        # True for elevation confirm, False for cache confirm
        ui = _StubUI(confirm=[True, False], secrets=["mypassword"])
        ctx = _make_ctx(ui)
        em = ElevationManager(ctx)
        host = _make_host(elevation_method=ElevationMethod.SUDO_PASSWORD)

        result = await em.prepare_command(host, "systemctl restart nginx")

        assert result.command == "sudo -S -p '' systemctl restart nginx"
        assert result.input_data == "mypassword\n"
        assert result.method == "sudo_password"
        assert result.elevated is True
        assert len(ui.secret_calls) == 1  # Password prompt

    @pytest.mark.asyncio
    async def test_sudo_password_uses_cached_session_password(self) -> None:
        """Should use session-cached password without prompting."""
        ui = _StubUI(confirm=True)
        ctx = _make_ctx(ui)
        em = ElevationManager(ctx)
        host = _make_host(elevation_method=ElevationMethod.SUDO_PASSWORD)

        # Pre-cache password in session
        em._session_passwords["test-host"] = "cachedpwd"

        result = await em.prepare_command(host, "systemctl restart nginx")

        assert result.input_data == "cachedpwd\n"
        assert ui.secret_calls == []  # No password prompt


class TestElevationManagerDoas:
    """Tests for doas elevation."""

    @pytest.mark.asyncio
    async def test_doas_nopasswd_prefixes_command(self) -> None:
        """doas (NOPASSWD) should prefix command with doas."""
        ui = _StubUI(confirm=True)
        ctx = _make_ctx(ui)
        em = ElevationManager(ctx)
        host = _make_host(elevation_method=ElevationMethod.DOAS)

        result = await em.prepare_command(host, "cat /etc/shadow")

        assert result.command == "doas cat /etc/shadow"
        assert result.method == "doas"
        assert result.elevated is True

    @pytest.mark.asyncio
    async def test_doas_password_escapes_command(self) -> None:
        """doas_password should escape command and use stdin."""
        # True for elevation confirm, False for cache confirm
        ui = _StubUI(confirm=[True, False], secrets=["s3cr3t"])
        ctx = _make_ctx(ui)
        em = ElevationManager(ctx)
        host = _make_host(elevation_method=ElevationMethod.DOAS_PASSWORD)

        result = await em.prepare_command(host, "cat /etc/shadow")

        assert "s3cr3t" not in result.command  # Password not in command
        assert result.input_data == "s3cr3t\n"


class TestElevationManagerSu:
    """Tests for su elevation."""

    @pytest.mark.asyncio
    async def test_su_escapes_command_and_uses_stdin(self) -> None:
        """su should escape command and pass password via stdin."""
        # True for elevation confirm, False for cache confirm
        ui = _StubUI(confirm=[True, False], secrets=["rootpwd"])
        ctx = _make_ctx(ui)
        em = ElevationManager(ctx)
        host = _make_host(elevation_method=ElevationMethod.SU)

        result = await em.prepare_command(host, "cat /etc/shadow")

        assert "su -c" in result.command
        assert "rootpwd" not in result.command  # Password not in command
        assert result.input_data == "rootpwd\n"
        assert result.method == "su"


class TestElevationManagerConfirmation:
    """Tests for elevation confirmation behavior."""

    @pytest.mark.asyncio
    async def test_declined_confirmation_raises_error(self) -> None:
        """Declining confirmation should raise ElevationDeniedError."""
        ui = _StubUI(confirm=False)
        ctx = _make_ctx(ui)
        em = ElevationManager(ctx)
        host = _make_host(elevation_method=ElevationMethod.SUDO)

        with pytest.raises(ElevationDeniedError):
            await em.prepare_command(host, "systemctl restart nginx")

    @pytest.mark.asyncio
    async def test_diagnostic_uses_simple_confirmation(self) -> None:
        """DIAGNOSTIC center should use simple confirmation with default=True."""
        ui = _StubUI(confirm=True)
        ctx = _make_ctx(ui)
        em = ElevationManager(ctx)
        host = _make_host(elevation_method=ElevationMethod.SUDO)

        await em.prepare_command(host, "ls", center=CenterMode.DIAGNOSTIC)

        assert len(ui.confirm_calls) == 1
        # DIAGNOSTIC confirmation message is simpler

    @pytest.mark.asyncio
    async def test_change_uses_detailed_confirmation(self) -> None:
        """CHANGE center should use detailed HITL confirmation."""
        ui = _StubUI(confirm=True)
        ctx = _make_ctx(ui)
        em = ElevationManager(ctx)
        host = _make_host(elevation_method=ElevationMethod.SUDO)

        await em.prepare_command(host, "rm -rf /tmp/foo", center=CenterMode.CHANGE)

        assert len(ui.confirm_calls) == 1
        # CHANGE confirmation includes "CHANGE:" prefix
        assert "CHANGE" in ui.confirm_calls[0]


class TestElevationManagerPasswordCache:
    """Tests for password caching functionality."""

    def test_store_password_saves_to_keyring(self) -> None:
        """store_password should save to secret store."""
        ctx = _make_ctx(_StubUI())
        em = ElevationManager(ctx)

        ref = em.store_password("host1", "secret123", "sudo_password")

        assert ref == "@elevation:host1:password"
        assert ctx.secrets.get("elevation:host1:password") == "secret123"

    def test_store_password_su_uses_root_key(self) -> None:
        """su passwords should use :root: in key."""
        ctx = _make_ctx(_StubUI())
        em = ElevationManager(ctx)

        ref = em.store_password("host1", "rootpwd", "su")

        assert ref == "@elevation:host1:root:password"
        assert ctx.secrets.get("elevation:host1:root:password") == "rootpwd"

    def test_clear_session_cache_single_host(self) -> None:
        """clear_session_cache should clear session password for host."""
        ctx = _make_ctx(_StubUI())
        em = ElevationManager(ctx)

        em._session_passwords["host1"] = "pwd1"
        em._session_passwords["host2"] = "pwd2"

        em.clear_session_cache("host1")

        assert "host1" not in em._session_passwords
        assert em._session_passwords.get("host2") == "pwd2"

    def test_clear_session_cache_all(self) -> None:
        """clear_session_cache without host should clear all."""
        ctx = _make_ctx(_StubUI())
        em = ElevationManager(ctx)

        em._session_passwords["host1"] = "pwd1"
        em._session_passwords["host2"] = "pwd2"

        em.clear_session_cache()

        assert em._session_passwords == {}

    def test_clear_keyring_removes_all_methods(self) -> None:
        """clear_keyring should remove all elevation passwords from keyring."""
        ctx = _make_ctx(_StubUI())
        em = ElevationManager(ctx)

        ctx.secrets.set("elevation:host1:password", "sudopwd")
        ctx.secrets.set("elevation:host1:root:password", "supwd")

        em.clear_keyring("host1")

        assert ctx.secrets.get("elevation:host1:password") is None
        assert ctx.secrets.get("elevation:host1:root:password") is None
