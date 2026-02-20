"""
Merlya Agent - Tool call tracker for loop detection.

Tracks tool calls independently of history truncation to detect
unproductive loops (same commands repeated on same hosts).

This is a SEPARATE mechanism from history.py - it persists across
history truncation and provides reliable loop detection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from merlya.ui.console import ConsoleUI

# Thresholds for loop detection
MAX_SAME_FINGERPRINT = 3  # Same host+command > 3 times = loop
MAX_PATTERN_REPEAT = 2  # A→B→C→A→B→C pattern = loop
PATTERN_WINDOW_SIZE = 6  # Window for detecting repeating patterns
MAX_CATEGORY_COMMANDS = 5  # Max commands in same category (e.g., systemctl) before warning
MAX_TOTAL_CALLS_SESSION = 50  # Hard limit on total calls per session

# Command categories for detecting repetitive behavior with DIFFERENT but similar commands
# Agent trying many variations of systemctl/docker/apt is likely stuck
COMMAND_CATEGORIES = [
    (re.compile(r"^(?:sudo\s+)?systemctl\s+", re.IGNORECASE), "systemctl"),
    (re.compile(r"^(?:sudo\s+)?(?:docker|podman)\s+", re.IGNORECASE), "docker"),
    (re.compile(r"^(?:sudo\s+)?kubectl\s+", re.IGNORECASE), "kubectl"),
    (re.compile(r"^(?:sudo\s+)?(?:apt|apt-get|dpkg)\s+", re.IGNORECASE), "apt"),
    (re.compile(r"^(?:sudo\s+)?(?:yum|dnf|rpm)\s+", re.IGNORECASE), "yum"),
    (re.compile(r"^(?:sudo\s+)?service\s+", re.IGNORECASE), "service"),
]

# Regex patterns to normalize elevation prefixes for fingerprinting
# This ensures sudo -S, sudo, su -c, doas are treated as equivalent
ELEVATION_PATTERNS = [
    (re.compile(r"^sudo\s+-[sS]\s+", re.IGNORECASE), "ELEV:"),  # sudo -S / sudo -s
    (re.compile(r"^sudo\s+", re.IGNORECASE), "ELEV:"),  # sudo
    (re.compile(r"^su\s+-c\s+['\"]?", re.IGNORECASE), "ELEV:"),  # su -c '...'
    (re.compile(r"^doas\s+", re.IGNORECASE), "ELEV:"),  # doas
]


def _normalize_command_for_fingerprint(command: str) -> str:
    """
    Normalize command for fingerprinting.

    Replaces elevation prefixes (sudo, su -c, doas) with a common prefix
    so that semantically equivalent commands are detected as loops.

    Examples:
        "sudo -S cat /etc/shadow" → "ELEV:cat /etc/shadow"
        "su -c 'cat /etc/shadow'" → "ELEV:cat /etc/shadow"
        "doas cat /etc/shadow" → "ELEV:cat /etc/shadow"
    """
    cmd = command.strip()
    for pattern, replacement in ELEVATION_PATTERNS:
        if pattern.match(cmd):
            cmd = pattern.sub(replacement, cmd)
            # Remove trailing quote if present (from su -c)
            cmd = cmd.rstrip("'\"")
            break
    return cmd


def _get_command_category(command: str) -> str | None:
    """
    Extract command category for grouping similar commands.

    Returns category name if command matches a known pattern, None otherwise.
    Used to detect when agent is trying many variations of same tool.
    """
    cmd = command.strip()
    for pattern, category in COMMAND_CATEGORIES:
        if pattern.match(cmd):
            return category
    return None


@dataclass
class ToolCallTracker:
    """
    Tracks tool calls to detect unproductive loops.

    Independent of history truncation - counts persist across the entire
    agent run. Uses fingerprinting to detect repetitive patterns.

    Fingerprint format: "host:command_prefix[:25]"
    Example: "192.168.1.7:sudo systemctl rest"

    Also tracks command categories (systemctl, docker, etc.) to detect
    when agent is trying many variations of the same tool.
    """

    total_calls: int = 0
    fingerprints: list[str] = field(default_factory=list)
    fingerprint_counts: dict[str, int] = field(default_factory=dict)
    # Category counts per host: {"host:category": count}
    category_counts: dict[str, int] = field(default_factory=dict)
    # Optional UI callback for displaying tool calls in real-time
    _ui_callback: Callable[[str, str], None] | None = field(default=None, repr=False)

    def set_ui(self, ui: ConsoleUI) -> None:
        """Set UI for real-time tool call display."""
        self._ui_callback = ui.tool_call

    def record(self, host: str, command: str) -> None:
        """
        Record a tool call.

        Args:
            host: Target host (e.g., "192.168.1.7", "local" for bash).
            command: Command executed.
        """
        self.total_calls += 1

        # Create fingerprint: host + normalized command prefix (first 25 chars)
        # Normalize elevation prefixes so sudo/su/doas variants are treated as equivalent
        host_lower = host.lower()
        normalized = _normalize_command_for_fingerprint(command)
        cmd_prefix = normalized[:25].lower()
        fingerprint = f"{host_lower}:{cmd_prefix}"

        self.fingerprints.append(fingerprint)
        self.fingerprint_counts[fingerprint] = self.fingerprint_counts.get(fingerprint, 0) + 1

        # Track command category (systemctl, docker, etc.)
        category = _get_command_category(command)
        if category:
            category_key = f"{host_lower}:{category}"
            self.category_counts[category_key] = self.category_counts.get(category_key, 0) + 1

        logger.debug(f"🔢 Tool call #{self.total_calls}: {fingerprint}")

        # Show in UI if callback is set (real-time visibility like Claude Code)
        if self._ui_callback:
            self._ui_callback(host, command)

    def would_loop(self, host: str, command: str) -> tuple[bool, str]:
        """
        Check if recording this command WOULD trigger a loop.

        Call this BEFORE record() to prevent executing looping commands.

        Args:
            host: Target host.
            command: Command to check.

        Returns:
            Tuple of (would_loop, reason).
        """
        # Check global session limit FIRST
        if self.total_calls >= MAX_TOTAL_CALLS_SESSION:
            return True, (
                f"🛑 Session limit reached ({self.total_calls} tool calls). "
                "You've made too many attempts. Stop and summarize what you've learned."
            )

        # Create fingerprint for the prospective call (normalized)
        host_lower = host.lower()
        normalized = _normalize_command_for_fingerprint(command)
        cmd_prefix = normalized[:25].lower()
        fingerprint = f"{host_lower}:{cmd_prefix}"

        # Check if this specific fingerprint would exceed threshold
        current_count = self.fingerprint_counts.get(fingerprint, 0)
        if current_count >= MAX_SAME_FINGERPRINT:
            return True, f"🛑 Command already executed {current_count}x: {fingerprint}"

        # Check if this command category is being overused
        # (e.g., many different systemctl commands = agent is stuck trying variations)
        category = _get_command_category(command)
        if category:
            category_key = f"{host_lower}:{category}"
            category_count = self.category_counts.get(category_key, 0)
            if category_count >= MAX_CATEGORY_COMMANDS:
                return True, (
                    f"🛑 Too many '{category}' commands ({category_count}x). "
                    "You've tried many variations without success. "
                    "Summarize findings and try a completely different approach."
                )

        # Check if adding this would create a repeating pattern
        if len(self.fingerprints) >= PATTERN_WINDOW_SIZE - 1:
            prospective = [*self.fingerprints[-(PATTERN_WINDOW_SIZE - 1) :], fingerprint]
            half = PATTERN_WINDOW_SIZE // 2
            first_half = prospective[:half]
            second_half = prospective[half:]

            if first_half == second_half:
                pattern = " → ".join(first_half)
                return True, f"🛑 Would create repeating pattern: {pattern}"

        return False, ""

    def is_looping(self) -> tuple[bool, str]:
        """
        Check if the agent is ALREADY in a loop.

        Returns:
            Tuple of (is_looping, reason).
        """
        # Check 0: Session limit exceeded
        if self.total_calls > MAX_TOTAL_CALLS_SESSION:
            return True, f"🔄 Session limit exceeded ({self.total_calls} calls)"

        # Check 1: Same fingerprint repeated too many times
        for fp, count in self.fingerprint_counts.items():
            if count > MAX_SAME_FINGERPRINT:
                return True, f"🔄 Same command repeated {count}x: {fp}"

        # Check 2: Repeating pattern (A→B→C→A→B→C)
        if len(self.fingerprints) >= PATTERN_WINDOW_SIZE:
            half = PATTERN_WINDOW_SIZE // 2
            recent = self.fingerprints[-PATTERN_WINDOW_SIZE:]
            first_half = recent[:half]
            second_half = recent[half:]

            if first_half == second_half:
                pattern = " → ".join(first_half)
                return True, f"🔄 Repeating pattern detected: {pattern}"

        return False, ""

    def get_summary(self) -> str:
        """Get a summary of tool calls for debugging."""
        top_3 = sorted(
            self.fingerprint_counts.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:3]
        top_str = ", ".join(f"{fp}({c})" for fp, c in top_3)
        return f"Total: {self.total_calls}, Top: {top_str}"

    def reset(self) -> None:
        """Reset tracker for new conversation/run."""
        self.total_calls = 0
        self.fingerprints.clear()
        self.fingerprint_counts.clear()
        self.category_counts.clear()
        # Don't reset UI callback - keep it across resets
        logger.debug("🔄 ToolCallTracker reset")
