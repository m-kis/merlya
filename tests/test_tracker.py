"""Tests for the ToolCallTracker loop detection module."""

from merlya.agent.tracker import (
    MAX_SAME_FINGERPRINT,
    ToolCallTracker,
    _normalize_command_for_fingerprint,
)


class TestToolCallTracker:
    """Tests for ToolCallTracker."""

    def test_record_increments_count(self) -> None:
        """Recording a call increments total count."""
        tracker = ToolCallTracker()
        assert tracker.total_calls == 0

        tracker.record("192.168.1.7", "uptime")
        assert tracker.total_calls == 1

        tracker.record("192.168.1.7", "df -h")
        assert tracker.total_calls == 2

    def test_record_creates_fingerprint(self) -> None:
        """Recording a call creates a fingerprint."""
        tracker = ToolCallTracker()
        tracker.record("192.168.1.7", "systemctl status nginx")

        assert len(tracker.fingerprints) == 1
        # Fingerprint format: host:cmd_prefix[:25]
        assert tracker.fingerprints[0].startswith("192.168.1.7:systemctl status nginx")

    def test_fingerprint_truncates_long_commands(self) -> None:
        """Long commands are truncated in fingerprints."""
        tracker = ToolCallTracker()
        long_cmd = "a" * 100
        tracker.record("host", long_cmd)

        # Command prefix is 25 chars max
        fp = tracker.fingerprints[0]
        cmd_part = fp.split(":")[1]
        assert len(cmd_part) == 25

    def test_no_loop_with_diverse_commands(self) -> None:
        """Diverse commands should not trigger loop detection."""
        tracker = ToolCallTracker()

        commands = [
            "uptime",
            "df -h",
            "free -m",
            "ps aux",
            "netstat -tulpn",
            "systemctl status nginx",
        ]

        for cmd in commands:
            tracker.record("192.168.1.7", cmd)
            is_loop, _reason = tracker.is_looping()
            assert not is_loop, f"Unexpected loop for command: {cmd}"

    def test_detects_same_fingerprint_loop(self) -> None:
        """Same command repeated should trigger loop."""
        tracker = ToolCallTracker()

        # Repeat same command MAX_SAME_FINGERPRINT + 1 times
        for _i in range(MAX_SAME_FINGERPRINT + 1):
            tracker.record("192.168.1.7", "sudo systemctl restart nginx")

        is_loop, reason = tracker.is_looping()
        assert is_loop
        assert "repeated" in reason.lower() or "same command" in reason.lower()

    def test_no_loop_at_threshold(self) -> None:
        """At exactly threshold, should not trigger loop."""
        tracker = ToolCallTracker()

        # Repeat exactly MAX_SAME_FINGERPRINT times (not exceeded)
        for _i in range(MAX_SAME_FINGERPRINT):
            tracker.record("192.168.1.7", "uptime")

        is_loop, reason = tracker.is_looping()
        assert not is_loop, f"Should not loop at exactly threshold: {reason}"

    def test_detects_pattern_loop(self) -> None:
        """Repeating pattern A→B→C→D→A→B→C→D should trigger loop."""
        tracker = ToolCallTracker()

        # Pattern: cmd1 → cmd2 → cmd3 → cmd4 (repeated)
        # With PATTERN_WINDOW_SIZE=8, we need 4 commands repeated twice
        pattern = ["cmd1", "cmd2", "cmd3", "cmd4"]

        # Repeat pattern twice (A→B→C→D→A→B→C→D)
        for _ in range(2):
            for cmd in pattern:
                tracker.record("host", cmd)

        is_loop, reason = tracker.is_looping()
        assert is_loop
        assert "pattern" in reason.lower()

    def test_different_hosts_are_different_fingerprints(self) -> None:
        """Same command on different hosts = different fingerprints."""
        tracker = ToolCallTracker()

        # Same command but different hosts
        for _ in range(MAX_SAME_FINGERPRINT + 1):
            tracker.record("host1", "uptime")

        is_loop, _ = tracker.is_looping()
        assert is_loop

        # Reset and try with different hosts each time
        tracker.reset()
        hosts = ["host1", "host2", "host3", "host4", "host5"]
        for host in hosts:
            tracker.record(host, "uptime")

        is_loop, _ = tracker.is_looping()
        assert not is_loop, "Different hosts should not trigger loop"

    def test_reset_clears_state(self) -> None:
        """Reset should clear all state."""
        tracker = ToolCallTracker()

        tracker.record("host", "cmd1")
        tracker.record("host", "cmd2")

        tracker.reset()

        assert tracker.total_calls == 0
        assert len(tracker.fingerprints) == 0
        assert len(tracker.fingerprint_counts) == 0

    def test_get_summary(self) -> None:
        """Summary should show total and top fingerprints."""
        tracker = ToolCallTracker()

        tracker.record("host", "cmd1")
        tracker.record("host", "cmd1")
        tracker.record("host", "cmd2")

        summary = tracker.get_summary()
        assert "Total: 3" in summary
        assert "cmd1" in summary

    def test_local_host_for_bash(self) -> None:
        """bash commands should use 'local' as host."""
        tracker = ToolCallTracker()

        tracker.record("local", "kubectl get pods")
        tracker.record("local", "docker ps")

        assert all("local:" in fp for fp in tracker.fingerprints)

    def test_fingerprint_case_insensitive(self) -> None:
        """Fingerprints should be case-insensitive."""
        tracker = ToolCallTracker()

        tracker.record("HOST", "UPTIME")
        tracker.record("host", "uptime")

        # Both should create same fingerprint (lowercase)
        # So count should be 2 for the same fingerprint
        assert tracker.fingerprint_counts.get("HOST:uptime".lower(), 0) == 2

    def test_would_loop_prevents_execution(self) -> None:
        """would_loop() should detect loop BEFORE recording."""
        tracker = ToolCallTracker()

        # Record MAX_SAME_FINGERPRINT times (at threshold, not exceeded)
        for _i in range(MAX_SAME_FINGERPRINT):
            tracker.record("host", "same command")

        # At this point is_looping() returns False (at threshold)
        is_loop, _ = tracker.is_looping()
        assert not is_loop

        # But would_loop() should return True for the NEXT call
        would_loop, reason = tracker.would_loop("host", "same command")
        assert would_loop
        assert "already executed" in reason.lower() or "command" in reason.lower()

    def test_would_loop_allows_new_commands(self) -> None:
        """would_loop() should allow new commands."""
        tracker = ToolCallTracker()

        tracker.record("host", "cmd1")
        tracker.record("host", "cmd2")

        # New command should be allowed
        would_loop, _ = tracker.would_loop("host", "cmd3")
        assert not would_loop

    def test_would_loop_detects_pattern(self) -> None:
        """would_loop() should detect pattern about to repeat."""
        tracker = ToolCallTracker()

        # Pattern: A → B → C → D (will be checked when adding A again)
        # With PATTERN_WINDOW_SIZE=8, we need 4 commands
        pattern = ["cmd1", "cmd2", "cmd3", "cmd4"]
        for cmd in pattern:
            tracker.record("host", cmd)

        # Record first part of repeat (cmd1, cmd2, cmd3)
        tracker.record("host", "cmd1")
        tracker.record("host", "cmd2")
        tracker.record("host", "cmd3")

        # About to add cmd4 which would create pattern A→B→C→D→A→B→C→D
        would_loop, reason = tracker.would_loop("host", "cmd4")
        assert would_loop
        assert "pattern" in reason.lower()

    def test_would_loop_vs_is_looping_timing(self) -> None:
        """would_loop checks BEFORE, is_looping checks AFTER recording."""
        tracker = ToolCallTracker()

        # Record exactly MAX_SAME_FINGERPRINT times
        for _i in range(MAX_SAME_FINGERPRINT):
            tracker.record("host", "cmd")

        # is_looping: at threshold, no loop yet
        is_loop, _ = tracker.is_looping()
        assert not is_loop

        # would_loop: next call WOULD cause loop
        would_loop, _ = tracker.would_loop("host", "cmd")
        assert would_loop

        # If we record one more (ignore would_loop warning)
        tracker.record("host", "cmd")

        # Now is_looping returns True
        is_loop, _ = tracker.is_looping()
        assert is_loop

    def test_elevation_variants_same_fingerprint(self) -> None:
        """Different elevation methods should create same fingerprint."""
        tracker = ToolCallTracker()

        # All these are semantically the same: read /etc/shadow with elevation
        tracker.record("host", "sudo -S cat /etc/shadow")
        tracker.record("host", "sudo cat /etc/shadow")
        tracker.record("host", "su -c 'cat /etc/shadow'")
        tracker.record("host", "doas cat /etc/shadow")

        # All should have same normalized fingerprint, so count should be 4
        # Fingerprint should be: host:elev:cat /etc/shadow
        assert len(tracker.fingerprint_counts) == 1
        count = next(iter(tracker.fingerprint_counts.values()))
        assert count == 4

    def test_elevation_loop_detected(self) -> None:
        """Trying same command with different elevation should trigger loop."""
        tracker = ToolCallTracker()

        # Try sudo, fails, try su, fails, try sudo again = loop
        # With MAX_SAME_FINGERPRINT=5, we need 5 calls to hit threshold
        # All these normalize to the same fingerprint: ELEV:cat /etc/shadow
        tracker.record("host", "sudo cat /etc/shadow")
        tracker.record("host", "su -c 'cat /etc/shadow'")
        tracker.record("host", "sudo -S cat /etc/shadow")
        tracker.record("host", "doas cat /etc/shadow")
        tracker.record("host", "sudo -s cat /etc/shadow")  # lowercase -s also normalizes

        # At threshold (5), not looping yet
        is_loop, _ = tracker.is_looping()
        assert not is_loop

        # But one more would loop
        would_loop, reason = tracker.would_loop("host", "sudo cat /etc/shadow")
        assert would_loop
        assert "already executed" in reason.lower()


class TestNormalizeCommand:
    """Tests for command normalization."""

    def test_sudo_uppercase_s(self) -> None:
        """sudo -S should be normalized."""
        result = _normalize_command_for_fingerprint("sudo -S cat /etc/shadow")
        assert result == "ELEV:cat /etc/shadow"

    def test_sudo_lowercase_s(self) -> None:
        """sudo -s should be normalized."""
        result = _normalize_command_for_fingerprint("sudo -s cat /etc/shadow")
        assert result == "ELEV:cat /etc/shadow"

    def test_sudo_plain(self) -> None:
        """Plain sudo should be normalized."""
        result = _normalize_command_for_fingerprint("sudo cat /etc/shadow")
        assert result == "ELEV:cat /etc/shadow"

    def test_su_with_quotes(self) -> None:
        """su -c with quotes should be normalized."""
        result = _normalize_command_for_fingerprint("su -c 'cat /etc/shadow'")
        assert result == "ELEV:cat /etc/shadow"

    def test_su_with_double_quotes(self) -> None:
        """su -c with double quotes should be normalized."""
        result = _normalize_command_for_fingerprint('su -c "cat /etc/shadow"')
        assert result == "ELEV:cat /etc/shadow"

    def test_doas(self) -> None:
        """doas should be normalized."""
        result = _normalize_command_for_fingerprint("doas cat /etc/shadow")
        assert result == "ELEV:cat /etc/shadow"

    def test_no_elevation(self) -> None:
        """Command without elevation should not be changed."""
        result = _normalize_command_for_fingerprint("cat /etc/passwd")
        assert result == "cat /etc/passwd"

    def test_preserves_rest_of_command(self) -> None:
        """Rest of command after elevation prefix should be preserved."""
        result = _normalize_command_for_fingerprint("sudo systemctl restart nginx")
        assert result == "ELEV:systemctl restart nginx"
