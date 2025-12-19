"""
Tests for merlya.agent.confirmation module.
"""

from merlya.agent.confirmation import (
    ConfirmationResult,
    ConfirmationState,
    DangerLevel,
    detect_danger_level,
    format_confirmation_prompt,
)


class TestDangerLevel:
    """Tests for danger level detection."""

    def test_rm_rf_is_dangerous(self) -> None:
        """rm -rf should be detected as dangerous."""
        assert detect_danger_level("rm -rf /tmp/test") == DangerLevel.DANGEROUS
        assert detect_danger_level("sudo rm -rf /var/log/old") == DangerLevel.DANGEROUS

    def test_rm_root_is_dangerous(self) -> None:
        """rm / should be detected as dangerous."""
        assert detect_danger_level("rm /important") == DangerLevel.DANGEROUS

    def test_reboot_is_dangerous(self) -> None:
        """reboot should be detected as dangerous."""
        assert detect_danger_level("sudo reboot") == DangerLevel.DANGEROUS
        assert detect_danger_level("shutdown -h now") == DangerLevel.DANGEROUS

    def test_dd_is_dangerous(self) -> None:
        """dd should be detected as dangerous."""
        assert detect_danger_level("dd if=/dev/zero of=/dev/sda") == DangerLevel.DANGEROUS

    def test_drop_table_is_dangerous(self) -> None:
        """DROP TABLE should be detected as dangerous."""
        assert detect_danger_level("DROP TABLE users;") == DangerLevel.DANGEROUS

    def test_systemctl_restart_is_moderate(self) -> None:
        """systemctl restart should be moderate."""
        assert detect_danger_level("systemctl restart nginx") == DangerLevel.MODERATE

    def test_kill_is_moderate(self) -> None:
        """kill should be moderate."""
        assert detect_danger_level("kill -9 1234") == DangerLevel.MODERATE
        assert detect_danger_level("pkill nginx") == DangerLevel.MODERATE

    def test_docker_rm_is_moderate(self) -> None:
        """docker rm should be moderate."""
        assert detect_danger_level("docker rm container1") == DangerLevel.MODERATE
        assert detect_danger_level("docker stop myapp") == DangerLevel.MODERATE

    def test_kubectl_delete_is_moderate(self) -> None:
        """kubectl delete should be moderate."""
        assert detect_danger_level("kubectl delete pod mypod") == DangerLevel.MODERATE

    def test_apt_remove_is_moderate(self) -> None:
        """apt remove should be moderate."""
        assert detect_danger_level("apt remove nginx") == DangerLevel.MODERATE
        assert detect_danger_level("apt-get purge apache2") == DangerLevel.MODERATE

    def test_safe_commands_default_to_moderate(self) -> None:
        """Non-matching commands should default to MODERATE for bash/ssh."""
        # All external commands require confirmation by default
        assert detect_danger_level("ls -la") == DangerLevel.MODERATE
        assert detect_danger_level("cat /etc/passwd") == DangerLevel.MODERATE
        assert detect_danger_level("uptime") == DangerLevel.MODERATE

    def test_case_insensitive(self) -> None:
        """Detection should be case insensitive."""
        assert detect_danger_level("DROP TABLE users") == DangerLevel.DANGEROUS
        assert detect_danger_level("drop table users") == DangerLevel.DANGEROUS
        assert detect_danger_level("REBOOT") == DangerLevel.DANGEROUS


class TestConfirmationState:
    """Tests for ConfirmationState."""

    def test_initial_state_not_always_yes(self) -> None:
        """Initial state should not skip confirmations."""
        state = ConfirmationState()
        assert not state.always_yes
        assert not state.should_skip("ls -la")

    def test_set_always_yes_global(self) -> None:
        """Setting global always_yes should skip all commands."""
        state = ConfirmationState()
        state.set_always_yes()
        assert state.always_yes
        assert state.should_skip("rm -rf /")
        assert state.should_skip("ls -la")

    def test_set_always_yes_for_pattern(self) -> None:
        """Setting always_yes for pattern should only skip matching commands (25-char prefix)."""
        state = ConfirmationState()
        # Store a command - first 25 chars become the pattern
        state.set_always_yes("systemctl restart nginx")

        # Should skip exact match
        assert state.should_skip("systemctl restart nginx")

        # Should NOT skip different commands
        assert not state.should_skip("rm -rf /tmp")
        assert not state.should_skip("docker stop myapp")
        assert not state.should_skip("systemctl stop nginx")  # Different action

    def test_pattern_uses_first_25_chars(self) -> None:
        """Pattern matching uses first 25 characters."""
        state = ConfirmationState()
        # "kubectl delete pod myapp-" = exactly 25 chars
        long_cmd = "kubectl delete pod myapp-deployment-12345"
        state.set_always_yes(long_cmd)

        # Should match commands with same 25-char prefix
        assert state.should_skip("kubectl delete pod myapp-deployment-67890")
        assert state.should_skip("kubectl delete pod myapp-other-pod")

        # Should NOT match different prefix
        assert not state.should_skip("kubectl delete svc myapp")

    def test_reset_clears_state(self) -> None:
        """Reset should clear all state."""
        state = ConfirmationState()
        state.set_always_yes()
        state.set_always_yes("systemctl restart nginx")

        state.reset()

        assert not state.always_yes
        assert len(state.always_yes_patterns) == 0
        assert not state.should_skip("systemctl restart nginx")


class TestFormatConfirmationPrompt:
    """Tests for format_confirmation_prompt."""

    def test_local_command_format(self) -> None:
        """Local commands should show local indicator."""
        result = format_confirmation_prompt("ls -la", target="local")
        assert "local" in result.lower() or "🔧" in result
        assert "ls -la" in result

    def test_remote_command_format(self) -> None:
        """Remote commands should show target host."""
        result = format_confirmation_prompt("systemctl status nginx", target="192.168.1.7")
        assert "192.168.1.7" in result
        assert "systemctl status nginx" in result

    def test_dangerous_command_icon(self) -> None:
        """Dangerous commands should have warning icon."""
        result = format_confirmation_prompt(
            "rm -rf /",
            target="192.168.1.7",
            danger_level=DangerLevel.DANGEROUS,
        )
        assert "🚨" in result

    def test_long_command_truncation(self) -> None:
        """Very long commands should be truncated."""
        long_cmd = "echo " + "a" * 200
        result = format_confirmation_prompt(long_cmd, target="local")
        assert "..." in result
        assert len(result) < 200  # Should be truncated


class TestConfirmationResult:
    """Tests for ConfirmationResult enum."""

    def test_enum_values(self) -> None:
        """Enum should have expected values."""
        assert ConfirmationResult.EXECUTE.value == "execute"
        assert ConfirmationResult.CANCEL.value == "cancel"
        assert ConfirmationResult.ALWAYS_YES.value == "always_yes"
