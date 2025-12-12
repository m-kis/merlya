"""
Tests for Security submodules.

Tests security tools: base, users, ports, keys.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.tools.security.base import (
    PortInfo,
    SecurityResult,
    SSHKeyInfo,
    _is_safe_ssh_key_path,
)
from merlya.tools.security.keys import (
    _detect_key_type,
    _severity_higher,
    audit_ssh_keys,
)
from merlya.tools.security.ports import (
    _create_port_entry,
    _extract_port,
    _extract_process,
    _parse_port_output,
    _should_skip_line,
    check_open_ports,
)
from merlya.tools.security.users import (
    _parse_passwd_line,
    check_sudo_config,
    check_users,
)


class TestSecurityResult:
    """Tests for SecurityResult dataclass."""

    def test_success_result(self):
        """Test successful result."""
        result = SecurityResult(success=True, data={"key": "value"})

        assert result.success is True
        assert result.data == {"key": "value"}
        assert result.error is None
        assert result.severity == "info"

    def test_error_result(self):
        """Test error result."""
        result = SecurityResult(success=False, error="Something failed")

        assert result.success is False
        assert result.error == "Something failed"

    def test_severity_levels(self):
        """Test different severity levels."""
        info = SecurityResult(success=True, severity="info")
        warning = SecurityResult(success=True, severity="warning")
        critical = SecurityResult(success=True, severity="critical")

        assert info.severity == "info"
        assert warning.severity == "warning"
        assert critical.severity == "critical"


class TestPortInfo:
    """Tests for PortInfo dataclass."""

    def test_basic_port_info(self):
        """Test basic port info creation."""
        port = PortInfo(
            port=80,
            protocol="tcp",
            state="listen",
            service="http",
        )

        assert port.port == 80
        assert port.protocol == "tcp"
        assert port.pid is None

    def test_port_with_process(self):
        """Test port info with process details."""
        port = PortInfo(
            port=443,
            protocol="tcp",
            state="listen",
            service="https",
            pid=1234,
            process="nginx",
        )

        assert port.pid == 1234
        assert port.process == "nginx"


class TestSSHKeyInfo:
    """Tests for SSHKeyInfo dataclass."""

    def test_basic_key_info(self):
        """Test basic SSH key info."""
        key = SSHKeyInfo(
            path="/root/.ssh/id_rsa",
            type="RSA",
        )

        assert key.path == "/root/.ssh/id_rsa"
        assert key.type == "RSA"
        assert key.issues == []

    def test_key_with_issues(self):
        """Test key info with security issues."""
        key = SSHKeyInfo(
            path="/root/.ssh/id_rsa",
            type="RSA",
            permissions="644",
            is_encrypted=False,
            issues=["Insecure permissions", "Not encrypted"],
        )

        assert len(key.issues) == 2


class TestIsSafeSshKeyPath:
    """Tests for _is_safe_ssh_key_path function."""

    def test_home_ssh_allowed(self):
        """Test home .ssh paths are allowed."""
        assert _is_safe_ssh_key_path("/home/user/.ssh/id_rsa") is True
        assert _is_safe_ssh_key_path("/home/admin/.ssh/id_ed25519") is True

    def test_root_ssh_allowed(self):
        """Test root .ssh paths are allowed."""
        assert _is_safe_ssh_key_path("/root/.ssh/id_rsa") is True

    def test_etc_ssh_allowed(self):
        """Test /etc/ssh paths are allowed."""
        assert _is_safe_ssh_key_path("/etc/ssh/ssh_host_rsa_key") is True

    def test_tilde_ssh_allowed(self):
        """Test ~ .ssh paths are allowed."""
        assert _is_safe_ssh_key_path("~/.ssh/id_rsa") is True

    def test_disallowed_paths(self):
        """Test disallowed paths are rejected."""
        assert _is_safe_ssh_key_path("/etc/passwd") is False
        assert _is_safe_ssh_key_path("/tmp/key") is False
        assert _is_safe_ssh_key_path("/var/log/syslog") is False

    def test_path_traversal_blocked(self):
        """Test path traversal attempts are blocked after canonicalization."""
        # These don't start with allowed prefixes
        assert _is_safe_ssh_key_path("/../etc/shadow") is False
        assert _is_safe_ssh_key_path("../etc/passwd") is False

    def test_path_traversal_with_allowed_prefix_blocked(self):
        """Test path traversal attempts that start with allowed prefix are blocked.

        Critical security test: paths like /home/user/../../etc/passwd start with
        /home/ but after canonicalization resolve to /etc/passwd which is not allowed.
        """
        # These start with allowed prefixes but traverse outside
        # Use paths that escape via /root since macOS /home is special
        assert _is_safe_ssh_key_path("/home/user/../../etc/passwd") is False
        assert _is_safe_ssh_key_path("/root/../etc/passwd") is False
        assert _is_safe_ssh_key_path("/root/.ssh/../../../etc/shadow") is False
        assert _is_safe_ssh_key_path("/etc/ssh/../../tmp/malicious") is False

    def test_path_traversal_with_mock_resolution(self):
        """Test path traversal using mocked resolution for consistent cross-platform behavior.

        This test mocks Path.resolve() to simulate Linux filesystem semantics
        where /home/user/../../etc/passwd resolves to /etc/passwd.
        """
        import posixpath
        from unittest.mock import patch

        def mock_resolve_linux(path_str: str) -> str:
            """Simulate Linux-style path resolution (pure, no symlink resolution)."""
            return posixpath.normpath(path_str)

        # Test cases: (input_path, expected_resolved, expected_result)
        # Note: posixpath.normpath follows path segments literally
        test_cases = [
            # Traversal escaping /home to /etc - should be blocked
            ("/home/user/../../etc/passwd", "/etc/passwd", False),
            # /home/user/.ssh/../.. = /home, then /etc/shadow = /home/etc/shadow (stays in /home)
            ("/home/user/.ssh/../../etc/shadow", "/home/etc/shadow", True),
            # Traversal escaping /root to /etc - should be blocked
            ("/root/../etc/passwd", "/etc/passwd", False),
            # Deep traversal to /etc - should be blocked
            ("/root/.ssh/../../../etc/shadow", "/etc/shadow", False),
            # Valid path staying within /home/.ssh - should pass
            ("/home/user/.ssh/../.ssh/id_rsa", "/home/user/.ssh/id_rsa", True),
            # Valid /etc/ssh path - should pass
            ("/etc/ssh/ssh_host_key", "/etc/ssh/ssh_host_key", True),
            # More escape attempts that should be blocked
            ("/home/a/../../../tmp/evil", "/tmp/evil", False),
            ("/root/../../var/log/auth.log", "/var/log/auth.log", False),
        ]

        # Verify our mock produces expected Linux-style resolution
        for input_path, expected_resolved, _ in test_cases:
            resolved = mock_resolve_linux(input_path)
            assert resolved == expected_resolved, (
                f"Mock resolution of {input_path} produced {resolved}, expected {expected_resolved}"
            )

        # Now test the actual function with mocked Path.resolve
        from pathlib import Path

        def patched_resolve(self):
            """Return a Path with Linux-style normalized path."""
            normalized = mock_resolve_linux(str(self))
            return Path(normalized)

        with patch.object(Path, "resolve", patched_resolve):
            for input_path, _, expected in test_cases:
                result = _is_safe_ssh_key_path(input_path)
                assert result is expected, (
                    f"Path {input_path} returned {result}, expected {expected}"
                )

    def test_path_traversal_staying_in_allowed_directory(self):
        """Test path traversal that stays within allowed directories is accepted."""
        # These traverse but stay within allowed directories
        assert _is_safe_ssh_key_path("/home/user/.ssh/../.ssh/id_rsa") is True
        assert _is_safe_ssh_key_path("/root/.ssh/../.ssh/id_ed25519") is True


class TestCheckOpenPorts:
    """Tests for check_open_ports function."""

    @pytest.fixture
    def mock_context(self):
        """Create mock context."""
        ctx = MagicMock()
        ctx.hosts = MagicMock()
        ctx.get_ssh_pool = AsyncMock()
        return ctx

    @pytest.mark.asyncio
    async def test_check_ports_success(self, mock_context):
        """Test successful port check."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = "tcp   LISTEN 0      128         0.0.0.0:22          0.0.0.0:*\n"

        with patch(
            "merlya.tools.security.ports.execute_security_command",
            AsyncMock(return_value=mock_result),
        ):
            result = await check_open_ports(mock_context, "web-01")

            assert result.success is True
            assert isinstance(result.data, list)

    @pytest.mark.asyncio
    async def test_check_ports_fallback_to_netstat(self, mock_context):
        """Test fallback to netstat when ss fails."""
        ss_result = MagicMock()
        ss_result.exit_code = 1
        ss_result.stdout = ""

        netstat_result = MagicMock()
        netstat_result.exit_code = 0
        netstat_result.stdout = "tcp   0   0   0.0.0.0:22   0.0.0.0:*   LISTEN\n"

        with patch(
            "merlya.tools.security.ports.execute_security_command",
            AsyncMock(side_effect=[ss_result, netstat_result]),
        ):
            result = await check_open_ports(mock_context, "web-01")

            assert result.success is True

    @pytest.mark.asyncio
    async def test_check_ports_both_fail(self, mock_context):
        """Test when both ss and netstat fail."""
        fail_result = MagicMock()
        fail_result.exit_code = 1
        fail_result.stdout = ""

        with patch(
            "merlya.tools.security.ports.execute_security_command",
            AsyncMock(return_value=fail_result),
        ):
            result = await check_open_ports(mock_context, "web-01")

            assert result.success is False
            assert "not available" in result.error


class TestPortParsing:
    """Tests for port output parsing functions."""

    def test_should_skip_line_empty(self):
        """Test empty lines are skipped."""
        assert _should_skip_line("") is True
        assert _should_skip_line("   ") is False  # Non-empty whitespace

    def test_should_skip_line_headers(self):
        """Test header lines are skipped."""
        assert _should_skip_line("Netid State") is True
        assert _should_skip_line("Proto Recv-Q") is True
        assert _should_skip_line("Active Internet connections") is True

    def test_extract_port_ipv4(self):
        """Test extracting port from IPv4 address."""
        assert _extract_port("0.0.0.0:22") == 22
        assert _extract_port("192.168.1.1:443") == 443

    def test_extract_port_ipv6(self):
        """Test extracting port from IPv6 address."""
        assert _extract_port("[::]:22") == 22
        assert _extract_port("[::1]:8080") == 8080

    def test_extract_port_wildcard(self):
        """Test wildcard port returns None."""
        assert _extract_port("*") is None
        assert _extract_port("0.0.0.0:*") is None

    def test_extract_port_service_name(self):
        """Test service name port."""
        port = _extract_port("0.0.0.0:http")
        assert port == "http"

    def test_extract_process_with_pid(self):
        """Test extracting process with PID."""
        pid, proc = _extract_process('users:(("sshd",pid=1234,fd=3))')
        assert pid == 1234
        assert proc == "sshd"

    def test_extract_process_slash_format(self):
        """Test extracting process in pid/name format."""
        pid, proc = _extract_process("1234/nginx")
        assert pid == 1234
        assert proc == "nginx"

    def test_extract_process_empty(self):
        """Test extracting from empty string."""
        pid, proc = _extract_process("")
        assert pid is None
        assert proc is None

    def test_create_port_entry(self):
        """Test creating port entry."""
        entry = _create_port_entry(
            port_value=22,
            protocol="tcp",
            state="LISTEN",
            address="0.0.0.0:22",
            pid=1234,
            process="sshd",
        )

        assert entry["port"] == 22
        assert entry["protocol"] == "tcp"
        assert entry["state"] == "listen"
        assert entry["pid"] == 1234
        assert entry["process"] == "sshd"

    def test_parse_port_output_ss(self):
        """Test parsing ss output."""
        output = """tcp   LISTEN 0      128         0.0.0.0:22          0.0.0.0:*     users:(("sshd",pid=1234,fd=3))
tcp   LISTEN 0      128         0.0.0.0:80          0.0.0.0:*     users:(("nginx",pid=5678,fd=5))"""

        ports = _parse_port_output(output)

        assert len(ports) == 2
        assert any(p["port"] == 22 for p in ports)
        assert any(p["port"] == 80 for p in ports)


class TestCheckUsers:
    """Tests for check_users function."""

    @pytest.fixture
    def mock_context(self):
        """Create mock context."""
        ctx = MagicMock()
        return ctx

    @pytest.mark.asyncio
    async def test_check_users_success(self, mock_context):
        """Test successful user check."""
        passwd_result = MagicMock()
        passwd_result.exit_code = 0
        passwd_result.stdout = (
            "root:x:0:0:root:/root:/bin/bash\nuser:x:1000:1000::/home/user:/bin/bash\n"
        )

        shadow_result = MagicMock()
        shadow_result.exit_code = 1
        shadow_result.stdout = ""

        with patch(
            "merlya.tools.security.users.execute_security_command",
            AsyncMock(side_effect=[passwd_result, shadow_result]),
        ):
            result = await check_users(mock_context, "web-01")

            assert result.success is True
            assert "users" in result.data
            assert len(result.data["users"]) == 2

    @pytest.mark.asyncio
    async def test_check_users_detects_uid0(self, mock_context):
        """Test detection of non-root UID 0 users."""
        passwd_result = MagicMock()
        passwd_result.exit_code = 0
        passwd_result.stdout = "hacker:x:0:0::/root:/bin/bash\n"

        shadow_result = MagicMock()
        shadow_result.exit_code = 1
        shadow_result.stdout = ""

        with patch(
            "merlya.tools.security.users.execute_security_command",
            AsyncMock(side_effect=[passwd_result, shadow_result]),
        ):
            result = await check_users(mock_context, "web-01")

            assert result.success is True
            assert result.severity == "critical"
            user = result.data["users"][0]
            assert "UID 0" in user["issues"][0]


class TestParsePasswdLine:
    """Tests for _parse_passwd_line function."""

    def test_parse_valid_line(self):
        """Test parsing valid passwd line."""
        line = "root:x:0:0:root:/root:/bin/bash"
        user_info, _severity = _parse_passwd_line(line)

        assert user_info is not None
        assert user_info["username"] == "root"
        assert user_info["uid"] == 0
        assert user_info["gid"] == 0
        assert user_info["home"] == "/root"
        assert user_info["shell"] == "/bin/bash"

    def test_parse_regular_user(self):
        """Test parsing regular user line."""
        line = "deploy:x:1000:1000:Deploy User:/home/deploy:/bin/zsh"
        user_info, severity = _parse_passwd_line(line)

        assert user_info["username"] == "deploy"
        assert user_info["uid"] == 1000
        assert severity == "info"

    def test_parse_uid0_non_root(self):
        """Test detecting non-root UID 0."""
        line = "toor:x:0:0::/root:/bin/bash"
        user_info, severity = _parse_passwd_line(line)

        assert severity == "critical"
        assert "UID 0" in user_info["issues"][0]

    def test_parse_invalid_line(self):
        """Test parsing invalid line."""
        user_info, _severity = _parse_passwd_line("invalid")

        assert user_info is None

    def test_parse_invalid_uid(self):
        """Test parsing line with invalid UID."""
        line = "user:x:abc:1000::/home/user:/bin/bash"
        user_info, _severity = _parse_passwd_line(line)

        assert user_info is None


class TestCheckSudoConfig:
    """Tests for check_sudo_config function."""

    @pytest.fixture
    def mock_context(self):
        """Create mock context."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_check_sudo_no_nopasswd(self, mock_context):
        """Test sudo check with no NOPASSWD entries."""
        nopasswd_result = MagicMock()
        nopasswd_result.exit_code = 1
        nopasswd_result.stdout = ""

        dangerous_result = MagicMock()
        dangerous_result.exit_code = 1
        dangerous_result.stdout = ""

        with patch(
            "merlya.tools.security.users.execute_security_command",
            AsyncMock(side_effect=[nopasswd_result, dangerous_result]),
        ):
            result = await check_sudo_config(mock_context, "web-01")

            assert result.success is True
            assert result.severity == "info"

    @pytest.mark.asyncio
    async def test_check_sudo_with_nopasswd(self, mock_context):
        """Test sudo check with NOPASSWD entries."""
        nopasswd_result = MagicMock()
        nopasswd_result.exit_code = 0
        nopasswd_result.stdout = "deploy ALL=(ALL) NOPASSWD: ALL\n"

        dangerous_result = MagicMock()
        dangerous_result.exit_code = 1
        dangerous_result.stdout = ""

        with patch(
            "merlya.tools.security.users.execute_security_command",
            AsyncMock(side_effect=[nopasswd_result, dangerous_result]),
        ):
            result = await check_sudo_config(mock_context, "web-01")

            assert result.success is True
            assert result.severity == "warning"
            assert len(result.data["nopasswd_entries"]) == 1


class TestAuditSshKeys:
    """Tests for audit_ssh_keys function."""

    @pytest.fixture
    def mock_context(self):
        """Create mock context."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_audit_keys_success(self, mock_context):
        """Test successful SSH key audit."""
        find_result = MagicMock()
        find_result.exit_code = 0
        find_result.stdout = "/root/.ssh/id_rsa\n"

        stat_result = MagicMock()
        stat_result.exit_code = 0
        stat_result.stdout = "600"

        head_result = MagicMock()
        head_result.exit_code = 0
        head_result.stdout = "-----BEGIN OPENSSH PRIVATE KEY-----"

        with patch(
            "merlya.tools.security.keys.execute_security_command",
            AsyncMock(side_effect=[find_result, stat_result, head_result]),
        ):
            result = await audit_ssh_keys(mock_context, "web-01")

            assert result.success is True
            assert "keys" in result.data

    @pytest.mark.asyncio
    async def test_audit_keys_skips_pub_files(self, mock_context):
        """Test that .pub files are skipped."""
        find_result = MagicMock()
        find_result.exit_code = 0
        find_result.stdout = "/root/.ssh/id_rsa.pub\n/root/.ssh/id_rsa\n"

        stat_result = MagicMock()
        stat_result.exit_code = 0
        stat_result.stdout = "600"

        head_result = MagicMock()
        head_result.exit_code = 0
        head_result.stdout = "-----BEGIN RSA PRIVATE KEY-----"

        with patch(
            "merlya.tools.security.keys.execute_security_command",
            AsyncMock(side_effect=[find_result, stat_result, head_result]),
        ):
            result = await audit_ssh_keys(mock_context, "web-01")

            # Should only have the private key, not .pub
            assert len(result.data["keys"]) == 1

    @pytest.mark.asyncio
    async def test_audit_keys_skips_unsafe_paths(self, mock_context):
        """Test that unsafe paths are skipped."""
        find_result = MagicMock()
        find_result.exit_code = 0
        find_result.stdout = "/tmp/suspicious_key\n/root/.ssh/id_rsa\n"

        stat_result = MagicMock()
        stat_result.exit_code = 0
        stat_result.stdout = "600"

        head_result = MagicMock()
        head_result.exit_code = 0
        head_result.stdout = "-----BEGIN RSA PRIVATE KEY-----"

        with patch(
            "merlya.tools.security.keys.execute_security_command",
            AsyncMock(side_effect=[find_result, stat_result, head_result]),
        ):
            result = await audit_ssh_keys(mock_context, "web-01")

            # Should only have the valid path
            assert len(result.data["keys"]) == 1
            assert result.data["keys"][0]["path"] == "/root/.ssh/id_rsa"


class TestDetectKeyType:
    """Tests for _detect_key_type function."""

    def test_detect_rsa(self):
        """Test detecting RSA key."""
        # Function checks for uppercase "RSA" in header
        assert _detect_key_type("-----BEGIN RSA PRIVATE KEY-----") == "RSA"
        assert _detect_key_type("RSA PRIVATE KEY") == "RSA"

    def test_detect_ecdsa(self):
        """Test detecting ECDSA key."""
        # Function checks for "EC" or "ECDSA" uppercase
        assert _detect_key_type("-----BEGIN EC PRIVATE KEY-----") == "ECDSA"
        assert _detect_key_type("ECDSA key content") == "ECDSA"

    def test_detect_ed25519(self):
        """Test detecting ED25519 key."""
        # Function checks for uppercase "ED25519"
        assert _detect_key_type("-----BEGIN OPENSSH PRIVATE KEY-----\nED25519") == "ED25519"
        assert _detect_key_type("ED25519 key") == "ED25519"

    def test_detect_dsa(self):
        """Test detecting DSA key."""
        assert _detect_key_type("-----BEGIN DSA PRIVATE KEY-----") == "DSA"
        assert _detect_key_type("DSA PRIVATE") == "DSA"

    def test_detect_unknown(self):
        """Test unknown key type."""
        assert _detect_key_type("unknown format") == "unknown"
        # Lowercase variants don't match (case-sensitive)
        assert _detect_key_type("ssh-rsa AAAA...") == "unknown"
        assert _detect_key_type("ssh-ed25519 AAAA...") == "unknown"


class TestSeverityHigher:
    """Tests for _severity_higher function."""

    def test_critical_higher_than_warning(self):
        """Test critical is higher than warning."""
        assert _severity_higher("critical", "warning") is True

    def test_critical_higher_than_info(self):
        """Test critical is higher than info."""
        assert _severity_higher("critical", "info") is True

    def test_warning_higher_than_info(self):
        """Test warning is higher than info."""
        assert _severity_higher("warning", "info") is True

    def test_info_not_higher_than_warning(self):
        """Test info is not higher than warning."""
        assert _severity_higher("info", "warning") is False

    def test_same_severity_not_higher(self):
        """Test same severity is not higher."""
        assert _severity_higher("warning", "warning") is False

    def test_unknown_severity(self):
        """Test unknown severity defaults to 0."""
        assert _severity_higher("unknown", "info") is False
