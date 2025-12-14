"""
Merlya Tools - Action verification system.

Verify that actions produce expected results.
"""

from __future__ import annotations

import re
import shlex
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from merlya.tools.core.models import ToolResult


@dataclass(frozen=True)
class VerificationRule:
    """Rule for verifying an action's result."""

    pattern: re.Pattern[str]
    verify_cmd: str  # Use $1, $2 for capture groups
    expect_stdout: str | None = None  # Expected stdout (substring match)
    expect_exit_code: int = 0
    description: str = ""


# Verification rules for common sysadmin actions
VERIFICATION_RULES: tuple[VerificationRule, ...] = (
    # === Systemd service management ===
    VerificationRule(
        pattern=re.compile(r"systemctl\s+(restart|start)\s+(\S+)", re.IGNORECASE),
        verify_cmd="systemctl is-active $2",
        expect_stdout="active",
        description="Service should be active after start/restart",
    ),
    VerificationRule(
        pattern=re.compile(r"systemctl\s+stop\s+(\S+)", re.IGNORECASE),
        verify_cmd="systemctl is-active $1",
        expect_stdout="inactive",
        description="Service should be inactive after stop",
    ),
    VerificationRule(
        pattern=re.compile(r"systemctl\s+enable\s+(\S+)", re.IGNORECASE),
        verify_cmd="systemctl is-enabled $1",
        expect_stdout="enabled",
        description="Service should be enabled",
    ),
    VerificationRule(
        pattern=re.compile(r"systemctl\s+disable\s+(\S+)", re.IGNORECASE),
        verify_cmd="systemctl is-enabled $1",
        expect_stdout="disabled",
        description="Service should be disabled",
    ),
    # === File operations ===
    VerificationRule(
        pattern=re.compile(r"mkdir\s+(?:-p\s+)?(\S+)", re.IGNORECASE),
        verify_cmd="test -d $1 && echo exists",
        expect_stdout="exists",
        description="Directory should exist after mkdir",
    ),
    VerificationRule(
        pattern=re.compile(r"rm\s+(?:-rf?\s+)?(\S+)", re.IGNORECASE),
        verify_cmd="test -e $1 && echo exists || echo removed",
        expect_stdout="removed",
        description="Path should not exist after rm",
    ),
    VerificationRule(
        pattern=re.compile(r"touch\s+(\S+)", re.IGNORECASE),
        verify_cmd="test -f $1 && echo exists",
        expect_stdout="exists",
        description="File should exist after touch",
    ),
    VerificationRule(
        pattern=re.compile(r"chmod\s+(\d+)\s+(\S+)", re.IGNORECASE),
        verify_cmd="stat -c %a $2",
        expect_stdout="$1",
        description="File permissions should match",
    ),
    VerificationRule(
        pattern=re.compile(r"chown\s+(\S+):?(\S*)\s+(\S+)", re.IGNORECASE),
        verify_cmd="stat -c %U $3",
        expect_stdout="$1",
        description="File owner should match",
    ),
    # === Package management (apt) ===
    VerificationRule(
        pattern=re.compile(r"apt(?:-get)?\s+install\s+(?:-y\s+)?(\S+)", re.IGNORECASE),
        verify_cmd="dpkg -l $1 | grep -q '^ii' && echo installed",
        expect_stdout="installed",
        description="Package should be installed",
    ),
    VerificationRule(
        pattern=re.compile(r"apt(?:-get)?\s+remove\s+(?:-y\s+)?(\S+)", re.IGNORECASE),
        verify_cmd="dpkg -l $1 2>/dev/null | grep -q '^ii' && echo installed || echo removed",
        expect_stdout="removed",
        description="Package should be removed",
    ),
    # === Package management (yum/dnf) ===
    VerificationRule(
        pattern=re.compile(r"(?:yum|dnf)\s+install\s+(?:-y\s+)?(\S+)", re.IGNORECASE),
        verify_cmd="rpm -q $1 >/dev/null && echo installed",
        expect_stdout="installed",
        description="Package should be installed",
    ),
    # === Network ===
    VerificationRule(
        pattern=re.compile(r"ufw\s+allow\s+(\d+)", re.IGNORECASE),
        verify_cmd="ufw status | grep -q '$1.*ALLOW' && echo allowed",
        expect_stdout="allowed",
        description="Port should be allowed in firewall",
    ),
    # === Docker ===
    VerificationRule(
        pattern=re.compile(r"docker\s+start\s+(\S+)", re.IGNORECASE),
        verify_cmd="docker inspect -f '{{.State.Running}}' $1",
        expect_stdout="true",
        description="Container should be running",
    ),
    VerificationRule(
        pattern=re.compile(r"docker\s+stop\s+(\S+)", re.IGNORECASE),
        verify_cmd="docker inspect -f '{{.State.Running}}' $1",
        expect_stdout="false",
        description="Container should be stopped",
    ),
)


@dataclass(frozen=True)
class VerificationHint:
    """Hint for verifying an action's result."""

    command: str
    expect_stdout: str | None
    expect_exit_code: int
    description: str


def get_verification_hint(command: str) -> VerificationHint | None:
    """
    Get verification hint for a command.

    Args:
        command: The command that was executed.

    Returns:
        VerificationHint if a matching rule exists, None otherwise.
    """
    for rule in VERIFICATION_RULES:
        match = rule.pattern.search(command)
        if match:
            # Substitute capture groups in verify_cmd
            verify_cmd = rule.verify_cmd
            expect_stdout = rule.expect_stdout

            for i, group in enumerate(match.groups(), 1):
                # Always replace the placeholder, using empty string if group is None
                safe_group = group or ""
                # Escape for shell command context
                verify_cmd = verify_cmd.replace(f"${i}", shlex.quote(safe_group))
                # For expect_stdout, decide based on context
                if expect_stdout:
                    # If expect_stdout contains shell patterns (grep, etc.), escape it
                    # Otherwise keep raw value for direct comparison
                    if any(
                        shell_keyword in expect_stdout
                        for shell_keyword in [
                            "grep",
                            "test",
                            "echo",
                            "stat",
                            "dpkg",
                            "rpm",
                            "ufw",
                            "docker",
                        ]
                    ):
                        expect_stdout = expect_stdout.replace(f"${i}", shlex.quote(safe_group))
                    else:
                        expect_stdout = expect_stdout.replace(f"${i}", safe_group)

            return VerificationHint(
                command=verify_cmd,
                expect_stdout=expect_stdout,
                expect_exit_code=rule.expect_exit_code,
                description=rule.description,
            )

    return None


def check_verification_result(
    hint: VerificationHint,
    stdout: str,
    exit_code: int,
) -> tuple[bool, str]:
    """
    Check if verification result matches expectations.

    Args:
        hint: The verification hint.
        stdout: Actual stdout from verification command.
        exit_code: Actual exit code from verification command.

    Returns:
        Tuple of (success, message).
    """
    stdout_clean = stdout.strip().lower()

    # Check exit code
    if exit_code != hint.expect_exit_code:
        return False, f"Expected exit code {hint.expect_exit_code}, got {exit_code}"

    # Check stdout if expected
    if hint.expect_stdout:
        expected = hint.expect_stdout.lower()
        if expected not in stdout_clean:
            return False, f"Expected '{hint.expect_stdout}' in output, got '{stdout.strip()}'"

    return True, hint.description


def add_verification_to_result(
    result: ToolResult,
    command: str,
) -> ToolResult:
    """
    Add verification hint to tool result if applicable.

    Args:
        result: The original tool result.
        command: The command that was executed.

    Returns:
        Tool result with verification hint added to data.
        Returns a new ToolResult object without mutating the input.
    """
    hint = get_verification_hint(command)
    if hint and result.success:
        # Create a deep copy to avoid mutating the input parameter
        new_result = deepcopy(result)

        # Initialize data if it's None or empty
        if not new_result.data:
            new_result.data = {}

        new_result.data["_verification_hint"] = {
            "command": hint.command,
            "expect_stdout": hint.expect_stdout,
            "description": hint.description,
        }
        logger.debug(f"🔍 Verification hint: {hint.command}")
        return new_result

    return result
