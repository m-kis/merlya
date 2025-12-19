"""Tests for SSH pattern detection functions."""

from __future__ import annotations

import pytest

from merlya.tools.core.ssh_patterns import (
    is_auth_error,
    is_expected_exit_code,
    needs_elevation,
    should_trigger_elevation,
    strip_sudo_prefix,
)


class TestIsAuthError:
    """Tests for is_auth_error function."""

    # Real authentication failures - should return True
    @pytest.mark.parametrize(
        "stderr",
        [
            "sudo: 3 incorrect password attempts",
            "sudo: a password is required",
            "Sorry, try again.",
            "su: Authentication failure",
            "Permission denied, please try again.",
            "pam_unix(sudo:auth): authentication failure",
            "user is not in the sudoers file",
            "doas: authentication failed",
        ],
    )
    def test_real_auth_failures_detected(self, stderr: str) -> None:
        """Real authentication failures should be detected."""
        assert is_auth_error(stderr) is True

    # Shell file permission errors - should return False (NOT auth errors)
    @pytest.mark.parametrize(
        "stderr",
        [
            "zsh:1: permission denied: /etc/cloudflared/config.yml",
            "bash: /etc/foo: Permission denied",
            "sh: /root/.bashrc: Permission denied",
            "-bash: /etc/passwd: Permission denied",
            "ksh: /var/log/secure: Permission denied",
            "fish: /etc/shadow: Permission denied",
            "dash: /home/user/.ssh/authorized_keys: Permission denied",
            "zsh: permission denied: ~/test.txt",
        ],
    )
    def test_shell_file_permission_not_auth_error(self, stderr: str) -> None:
        """Shell file permission errors should NOT be treated as auth failures.

        These occur when shell redirection (>) fails BEFORE sudo runs.
        For example: `sudo cat > /etc/foo` - the > redirection is done by the
        shell as the current user, not by sudo.
        """
        assert is_auth_error(stderr) is False

    def test_empty_stderr_not_auth_error(self) -> None:
        """Empty stderr should not be auth error."""
        assert is_auth_error("") is False

    def test_unrelated_error_not_auth_error(self) -> None:
        """Unrelated errors should not be auth errors."""
        assert is_auth_error("command not found") is False
        assert is_auth_error("Connection refused") is False
        assert is_auth_error("No such file or directory") is False


class TestNeedsElevation:
    """Tests for needs_elevation function."""

    @pytest.mark.parametrize(
        "stderr",
        [
            "Permission denied",
            "permission denied",
            "Operation not permitted",
            "must be root",
            "interactive authentication required",
            "Access denied",
        ],
    )
    def test_permission_errors_need_elevation(self, stderr: str) -> None:
        """Permission errors should trigger elevation."""
        assert needs_elevation(stderr) is True

    def test_normal_output_no_elevation(self) -> None:
        """Normal output should not trigger elevation."""
        assert needs_elevation("command completed successfully") is False
        assert needs_elevation("") is False


class TestStripSudoPrefix:
    """Tests for strip_sudo_prefix function."""

    def test_strip_sudo(self) -> None:
        """Strip sudo prefix."""
        cmd, prefix = strip_sudo_prefix("sudo systemctl restart nginx")
        assert cmd == "systemctl restart nginx"
        assert prefix == "sudo"

    def test_strip_sudo_n(self) -> None:
        """Strip sudo -n prefix."""
        cmd, prefix = strip_sudo_prefix("sudo -n cat /etc/shadow")
        assert cmd == "cat /etc/shadow"
        assert prefix == "sudo -n"

    def test_strip_doas(self) -> None:
        """Strip doas prefix."""
        cmd, prefix = strip_sudo_prefix("doas reboot")
        assert cmd == "reboot"
        assert prefix == "doas"

    def test_strip_su_c(self) -> None:
        """Strip su -c prefix."""
        cmd, prefix = strip_sudo_prefix("su -c 'whoami'")
        assert cmd == "'whoami'"
        assert prefix == "su -c"

    def test_no_prefix(self) -> None:
        """No prefix to strip."""
        cmd, prefix = strip_sudo_prefix("ls -la")
        assert cmd == "ls -la"
        assert prefix is None

    def test_case_insensitive(self) -> None:
        """Prefix detection is case insensitive."""
        cmd, prefix = strip_sudo_prefix("SUDO systemctl status")
        assert cmd == "systemctl status"
        assert prefix == "sudo"


class TestIsExpectedExitCode:
    """Tests for is_expected_exit_code function."""

    def test_exit_zero_always_expected(self) -> None:
        """Exit code 0 is always expected."""
        assert is_expected_exit_code("any command", 0) is True
        assert is_expected_exit_code("systemctl is-active foo", 0) is True

    @pytest.mark.parametrize(
        "command,exit_code",
        [
            ("systemctl is-active nginx", 1),  # inactive
            ("systemctl is-active nginx", 3),  # unknown
            ("systemctl is-active nginx", 4),  # no such unit
            ("systemctl is-enabled sshd", 1),  # disabled
            ("systemctl is-failed mysql", 1),  # not failed
        ],
    )
    def test_systemctl_status_expected(self, command: str, exit_code: int) -> None:
        """systemctl is-* returns non-zero for normal conditions."""
        assert is_expected_exit_code(command, exit_code) is True

    @pytest.mark.parametrize(
        "command,exit_code",
        [
            ("grep pattern file", 1),  # no matches
            ("grep -r 'foo' /var/log", 1),  # no matches
            ("cat file | grep error", 1),  # no matches in pipe
        ],
    )
    def test_grep_no_match_expected(self, command: str, exit_code: int) -> None:
        """grep returns 1 when no matches found."""
        assert is_expected_exit_code(command, exit_code) is True

    @pytest.mark.parametrize(
        "command,exit_code",
        [
            ("test -f /etc/foo", 1),  # file doesn't exist
            ("[ -d /var/mydir ]", 1),  # dir doesn't exist
        ],
    )
    def test_test_command_expected(self, command: str, exit_code: int) -> None:
        """test/[ returns 1 when condition is false."""
        assert is_expected_exit_code(command, exit_code) is True

    def test_diff_expected(self) -> None:
        """diff returns 1 when files differ."""
        assert is_expected_exit_code("diff file1 file2", 1) is True

    def test_which_expected(self) -> None:
        """which returns 1 when command not found."""
        assert is_expected_exit_code("which nonexistent", 1) is True
        assert is_expected_exit_code("type nonexistent", 1) is True

    def test_pgrep_expected(self) -> None:
        """pgrep returns 1 when no processes match."""
        assert is_expected_exit_code("pgrep nginx", 1) is True

    def test_unexpected_exit_codes(self) -> None:
        """Non-zero exit codes for non-whitelisted commands are NOT expected."""
        assert is_expected_exit_code("cat /etc/passwd", 1) is False
        assert is_expected_exit_code("ls /root", 2) is False
        assert is_expected_exit_code("systemctl restart nginx", 1) is False


class TestShouldTriggerElevation:
    """Tests for should_trigger_elevation function."""

    def test_success_never_triggers(self) -> None:
        """Exit code 0 never triggers elevation."""
        assert should_trigger_elevation("systemctl restart nginx", 0, "") is False
        assert should_trigger_elevation("cat /etc/shadow", 0, "") is False

    def test_expected_exit_code_no_trigger(self) -> None:
        """Expected non-zero exit codes should NOT trigger elevation."""
        # systemctl is-active returns 1 for inactive service - NOT a permission error
        assert should_trigger_elevation("systemctl is-active nginx", 1, "") is False
        # grep returns 1 for no matches - NOT a permission error
        assert should_trigger_elevation("grep pattern file", 1, "") is False
        # test returns 1 for false condition - NOT a permission error
        assert should_trigger_elevation("test -f /nonexistent", 1, "") is False

    def test_permission_denied_triggers(self) -> None:
        """Permission denied in stderr SHOULD trigger elevation."""
        assert (
            should_trigger_elevation("cat /etc/shadow", 1, "cat: /etc/shadow: Permission denied")
            is True
        )
        assert (
            should_trigger_elevation(
                "ls /root", 2, "ls: cannot open directory '/root': Permission denied"
            )
            is True
        )

    def test_real_failure_no_permission_no_trigger(self) -> None:
        """Real failures without permission errors should NOT trigger elevation."""
        # File not found is not a permission error
        assert (
            should_trigger_elevation("cat /nonexistent", 1, "cat: /nonexistent: No such file")
            is False
        )
        # Connection refused is not a permission error
        assert should_trigger_elevation("curl http://localhost", 7, "Connection refused") is False


class TestPasswordPromptPatterns:
    """Tests for PASSWORD_PROMPT_PATTERNS used in SSH PTY execution."""

    def test_patterns_importable(self) -> None:
        """Verify PASSWORD_PROMPT_PATTERNS can be imported."""
        from merlya.ssh.pool import PASSWORD_PROMPT_PATTERNS

        assert isinstance(PASSWORD_PROMPT_PATTERNS, tuple)
        assert len(PASSWORD_PROMPT_PATTERNS) > 0

    @pytest.mark.parametrize(
        "prompt",
        [
            "[sudo] password for user:",
            "Password:",
            "password:",
            "Password for user@host:",
            "[sudo] mot de passe de user:",
            "mot de passe :",
            "Contraseña:",
            "Passwort:",
            "user's password:",
            "Password for user:",
            "Authenticate:",
        ],
    )
    def test_common_prompts_detected(self, prompt: str) -> None:
        """Common password prompts should be detected."""
        from merlya.ssh.pool import PASSWORD_PROMPT_PATTERNS

        prompt_lower = prompt.lower()
        assert any(p in prompt_lower for p in PASSWORD_PROMPT_PATTERNS), (
            f"Prompt '{prompt}' not detected by patterns"
        )

    @pytest.mark.parametrize(
        "output",
        [
            "Connection established",
            "Last login: Mon Dec 16 10:00:00 2024",
            "Welcome to Ubuntu 22.04",
            "total 42",
            "drwxr-xr-x 2 root root 4096",
            "nginx: configuration file /etc/nginx/nginx.conf test is successful",
            "Error: command not found",
        ],
    )
    def test_non_prompts_not_detected(self, output: str) -> None:
        """Non-password outputs should NOT trigger prompt detection."""
        from merlya.ssh.pool import PASSWORD_PROMPT_PATTERNS

        output_lower = output.lower()
        assert not any(p in output_lower for p in PASSWORD_PROMPT_PATTERNS), (
            f"Output '{output}' incorrectly detected as password prompt"
        )


class TestElevationMethodCache:
    """Tests for elevation method caching."""

    def test_cache_set_and_get(self) -> None:
        """Setting and getting cached elevation method."""
        from merlya.tools.core.ssh_patterns import (
            clear_elevation_method_cache,
            get_cached_elevation_method,
            set_cached_elevation_method,
        )

        # Clear cache first
        clear_elevation_method_cache()

        # Initially no cached method
        assert get_cached_elevation_method("192.168.1.7") is None

        # Set and verify
        set_cached_elevation_method("192.168.1.7", "su")
        assert get_cached_elevation_method("192.168.1.7") == "su"

        # Different host has no cached method
        assert get_cached_elevation_method("192.168.1.8") is None

        # Clear specific host
        clear_elevation_method_cache("192.168.1.7")
        assert get_cached_elevation_method("192.168.1.7") is None

    def test_cache_clear_all(self) -> None:
        """Clearing all cached elevation methods."""
        from merlya.tools.core.ssh_patterns import (
            clear_elevation_method_cache,
            get_cached_elevation_method,
            set_cached_elevation_method,
        )

        set_cached_elevation_method("host1", "sudo")
        set_cached_elevation_method("host2", "su")

        clear_elevation_method_cache()

        assert get_cached_elevation_method("host1") is None
        assert get_cached_elevation_method("host2") is None


class TestFormatElevatedCommand:
    """Tests for format_elevated_command function."""

    def test_format_sudo(self) -> None:
        """Format command with passwordless sudo."""
        from merlya.tools.core.ssh_patterns import format_elevated_command

        result = format_elevated_command("cat /etc/shadow", "sudo")
        assert result == "sudo cat /etc/shadow"

    def test_format_sudo_s(self) -> None:
        """Format command with sudo -S."""
        from merlya.tools.core.ssh_patterns import format_elevated_command

        result = format_elevated_command("systemctl restart nginx", "sudo-S")
        assert result == "sudo -S systemctl restart nginx"

    def test_format_su(self) -> None:
        """Format command with su -c."""
        from merlya.tools.core.ssh_patterns import format_elevated_command

        result = format_elevated_command("journalctl -u nginx", "su")
        assert result == "su -c 'journalctl -u nginx'"

    def test_format_su_escapes_quotes(self) -> None:
        """su -c properly escapes single quotes in command."""
        from merlya.tools.core.ssh_patterns import format_elevated_command

        result = format_elevated_command("echo 'hello world'", "su")
        assert "su -c" in result
        # Quotes should be escaped
        assert "'" in result

    def test_format_doas(self) -> None:
        """Format command with doas."""
        from merlya.tools.core.ssh_patterns import format_elevated_command

        result = format_elevated_command("reboot", "doas")
        assert result == "doas reboot"

    def test_strips_existing_prefix(self) -> None:
        """Existing elevation prefix is stripped before adding new one."""
        from merlya.tools.core.ssh_patterns import format_elevated_command

        # If command already has sudo, strip it and use su instead
        result = format_elevated_command("sudo cat /etc/shadow", "su")
        assert result == "su -c 'cat /etc/shadow'"
        assert "sudo" not in result
