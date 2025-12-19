"""Tests for the specialist agent helper functions."""

from merlya.agent.specialists.elevation import needs_elevation_stdin as _needs_elevation_stdin


class TestNeedsElevationStdin:
    """Tests for _needs_elevation_stdin() function."""

    # ==========================================================================
    # sudo -S (uppercase S) - SHOULD trigger (reads password from stdin)
    # ==========================================================================

    def test_sudo_uppercase_s_triggers(self) -> None:
        """sudo -S (uppercase) should trigger - reads from stdin."""
        assert _needs_elevation_stdin("sudo -S cat /etc/shadow")

    def test_sudo_uppercase_s_with_path(self) -> None:
        """sudo -S with full path should trigger."""
        assert _needs_elevation_stdin("sudo -S /usr/bin/cat /etc/shadow")

    def test_sudo_uppercase_s_systemctl(self) -> None:
        """sudo -S systemctl should trigger."""
        assert _needs_elevation_stdin("sudo -S systemctl restart nginx")

    # ==========================================================================
    # sudo -s (lowercase s) - should NOT trigger (runs a shell, no stdin needed)
    # ==========================================================================

    def test_sudo_lowercase_s_does_not_trigger(self) -> None:
        """sudo -s (lowercase) should NOT trigger - runs a shell."""
        assert not _needs_elevation_stdin("sudo -s")

    def test_sudo_lowercase_s_with_command(self) -> None:
        """sudo -s with command should NOT trigger."""
        assert not _needs_elevation_stdin("sudo -s cat /etc/shadow")

    def test_sudo_lowercase_s_interactive(self) -> None:
        """sudo -s for interactive shell should NOT trigger."""
        assert not _needs_elevation_stdin("sudo -s -u postgres")

    # ==========================================================================
    # Plain sudo (no -S or -s) - should NOT trigger
    # ==========================================================================

    def test_plain_sudo_does_not_trigger(self) -> None:
        """Plain sudo without -S should NOT trigger."""
        assert not _needs_elevation_stdin("sudo cat /etc/shadow")

    def test_sudo_with_user_does_not_trigger(self) -> None:
        """sudo -u user should NOT trigger."""
        assert not _needs_elevation_stdin("sudo -u postgres psql")

    def test_sudo_preserve_env_does_not_trigger(self) -> None:
        """sudo -E should NOT trigger."""
        assert not _needs_elevation_stdin("sudo -E cat /etc/shadow")

    # ==========================================================================
    # su -c commands - SHOULD trigger (needs password)
    # ==========================================================================

    def test_su_c_with_single_quotes_triggers(self) -> None:
        """su -c with single quotes should trigger."""
        assert _needs_elevation_stdin("su -c 'cat /etc/shadow'")

    def test_su_c_with_double_quotes_triggers(self) -> None:
        """su -c with double quotes should trigger."""
        assert _needs_elevation_stdin('su -c "cat /etc/shadow"')

    def test_su_c_with_user_triggers(self) -> None:
        """su - root -c should trigger."""
        assert _needs_elevation_stdin("su - root -c 'cat /etc/shadow'")

    def test_su_at_start_triggers(self) -> None:
        """su at start of command should trigger."""
        assert _needs_elevation_stdin("su -c 'systemctl restart nginx'")

    def test_su_with_pipe_triggers(self) -> None:
        """Command with su -c after pipe should trigger."""
        assert _needs_elevation_stdin("echo password | su -c 'cat /etc/shadow'")

    # ==========================================================================
    # Non-elevation commands - should NOT trigger
    # ==========================================================================

    def test_regular_command_does_not_trigger(self) -> None:
        """Regular command should NOT trigger."""
        assert not _needs_elevation_stdin("cat /etc/passwd")

    def test_ls_command_does_not_trigger(self) -> None:
        """ls command should NOT trigger."""
        assert not _needs_elevation_stdin("ls -la /etc")

    def test_systemctl_without_sudo_does_not_trigger(self) -> None:
        """systemctl without sudo should NOT trigger."""
        assert not _needs_elevation_stdin("systemctl status nginx")

    def test_grep_with_sudo_in_pattern_does_not_trigger(self) -> None:
        """grep for 'sudo' in output should NOT trigger."""
        assert not _needs_elevation_stdin("grep 'sudo -S' /var/log/auth.log")

    def test_echo_with_su_in_text_does_not_trigger(self) -> None:
        """echo with 'su' in text should NOT trigger (not at boundary)."""
        # This should NOT trigger because "resultat" contains "su" but not as command
        assert not _needs_elevation_stdin("echo resultat")

    # ==========================================================================
    # Edge cases
    # ==========================================================================

    def test_empty_command_does_not_trigger(self) -> None:
        """Empty command should NOT trigger."""
        assert not _needs_elevation_stdin("")

    def test_whitespace_command_does_not_trigger(self) -> None:
        """Whitespace-only command should NOT trigger."""
        assert not _needs_elevation_stdin("   ")

    def test_sudo_in_path_does_not_trigger(self) -> None:
        """Path containing 'sudo' should NOT trigger."""
        assert not _needs_elevation_stdin("cat /var/log/sudo.log")

    def test_case_sensitivity_su(self) -> None:
        """su commands are case-insensitive."""
        assert _needs_elevation_stdin("SU -c 'cat /etc/shadow'")
        assert _needs_elevation_stdin("Su -C 'cat /etc/shadow'")
