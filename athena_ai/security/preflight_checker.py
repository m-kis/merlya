"""
Preflight Checker for Command Safety.

Validates commands BEFORE execution to:
- Prevent destructive operations without confirmation
- Block dangerous patterns
- Suggest safer alternatives
- Enforce environment-specific policies
"""

import re
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from enum import Enum

from athena_ai.utils.logger import logger


class CheckResult(Enum):
    """Result of a preflight check."""
    ALLOW = "allow"
    WARN = "warn"
    BLOCK = "block"
    REQUIRE_CONFIRM = "require_confirm"


@dataclass
class PreflightResult:
    """Result of preflight checks."""
    result: CheckResult
    command: str
    reason: str = ""
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    blocked_patterns: List[str] = field(default_factory=list)
    risk_level: str = "low"  # low, moderate, high, critical


# Patterns that should ALWAYS be blocked (destructive without recovery)
BLOCKED_PATTERNS = [
    # Filesystem destruction
    (r"rm\s+-rf?\s+/\s*$", "Recursive delete of root filesystem"),
    (r"rm\s+-rf?\s+/\*", "Recursive delete of all root contents"),
    (r"rm\s+-rf?\s+/home\s*$", "Recursive delete of home directories"),
    (r"rm\s+-rf?\s+/var\s*$", "Recursive delete of var directory"),
    (r"rm\s+-rf?\s+/etc\s*$", "Recursive delete of etc directory"),

    # Fork bombs and system destruction
    (r":\(\)\s*{\s*:\|:&\s*}", "Fork bomb detected"),
    (r"dd\s+if=/dev/zero\s+of=/dev/[sh]d[a-z]", "Disk overwrite with zeros"),
    (r"mkfs\s+.*\s+/dev/[sh]d[a-z]", "Filesystem creation on disk device"),

    # Network destruction
    (r"iptables\s+-F", "Flush all firewall rules"),
    (r"iptables\s+-X", "Delete all firewall chains"),

    # Shutdown without explicit confirmation
    (r"shutdown\s+-h\s+now", "Immediate system shutdown"),
    (r"init\s+0", "System halt via init"),
    (r"poweroff", "System poweroff"),

    # History destruction
    (r"history\s+-c.*history\s+-w", "History deletion and persistence"),

    # Chmod disasters
    (r"chmod\s+-R\s+777\s+/", "World-writable permissions on root"),
    (r"chown\s+-R.*:\s+/", "Ownership change on root filesystem"),
]

# Patterns that require confirmation
CONFIRM_PATTERNS = [
    # Service management
    (r"systemctl\s+(restart|stop)", "Service state change", "Consider using 'reload' for zero-downtime"),
    (r"service\s+.*\s+(restart|stop)", "Service state change", "Consider using 'reload' if available"),

    # File operations
    (r"rm\s+-r", "Recursive deletion", "Double-check the path before executing"),
    (r"rm\s+.*\*", "Wildcard deletion", "Verify wildcard expansion first"),

    # Package management
    (r"apt\s+remove|apt-get\s+remove", "Package removal", "Check dependencies before removing"),
    (r"yum\s+remove|dnf\s+remove", "Package removal", "Check dependencies before removing"),
    (r"pip\s+uninstall", "Python package removal", "Check if other packages depend on it"),

    # Database operations
    (r"drop\s+database|drop\s+table", "Database/table deletion", "Ensure backup exists"),
    (r"truncate\s+table", "Table truncation", "This cannot be undone"),

    # Config changes
    (r"mv\s+.*\.(conf|cfg|yaml|yml|json)\s+", "Config file move", "Backup original first"),
    (r">\s+.*\.(conf|cfg|yaml|yml|json)\s*$", "Config file overwrite", "Backup original first"),
]

# Patterns that should warn but allow
WARN_PATTERNS = [
    (r"kill\s+-9", "SIGKILL doesn't allow graceful shutdown", "Try SIGTERM first"),
    (r"chmod\s+777", "World-writable permissions are insecure", "Use more restrictive permissions"),
    (r"curl.*\|.*sh", "Piping remote script to shell", "Download and review script first"),
    (r"wget.*\|.*sh", "Piping remote script to shell", "Download and review script first"),
    (r"sudo\s+su\s*$", "Switching to root shell", "Use 'sudo command' for specific operations"),
]


class PreflightChecker:
    """
    Pre-execution command safety checker.

    Validates commands before execution to prevent destructive operations.
    Ops-first approach: warns but doesn't block unnecessarily.
    """

    def __init__(
        self,
        environment: str = "dev",
        strict_mode: bool = False,
    ):
        self.environment = environment
        self.strict_mode = strict_mode  # Prod is always strict

        # Compile patterns for efficiency
        self._blocked = [
            (re.compile(p, re.IGNORECASE), desc)
            for p, desc in BLOCKED_PATTERNS
        ]
        self._confirm = [
            (re.compile(p, re.IGNORECASE), desc, suggestion)
            for p, desc, suggestion in CONFIRM_PATTERNS
        ]
        self._warn = [
            (re.compile(p, re.IGNORECASE), desc, suggestion)
            for p, desc, suggestion in WARN_PATTERNS
        ]

    def check(self, command: str) -> PreflightResult:
        """
        Check a command before execution.

        Args:
            command: Command to validate

        Returns:
            PreflightResult with decision and details
        """
        warnings = []
        suggestions = []
        blocked_patterns = []
        risk_level = "low"

        # Check blocked patterns (always block these)
        for pattern, desc in self._blocked:
            if pattern.search(command):
                return PreflightResult(
                    result=CheckResult.BLOCK,
                    command=command,
                    reason=f"Blocked: {desc}",
                    blocked_patterns=[desc],
                    risk_level="critical",
                )

        # Check confirmation patterns
        for pattern, desc, suggestion in self._confirm:
            if pattern.search(command):
                risk_level = "high"
                warnings.append(desc)
                if suggestion:
                    suggestions.append(suggestion)

        # Check warning patterns
        for pattern, desc, suggestion in self._warn:
            if pattern.search(command):
                if risk_level == "low":
                    risk_level = "moderate"
                warnings.append(desc)
                if suggestion:
                    suggestions.append(suggestion)

        # Environment-specific checks
        if self.environment in ("prod", "production"):
            # Production is always strict
            if warnings:
                return PreflightResult(
                    result=CheckResult.REQUIRE_CONFIRM,
                    command=command,
                    reason="Production environment requires confirmation for this operation",
                    warnings=warnings,
                    suggestions=suggestions,
                    risk_level=risk_level,
                )
        elif self.strict_mode and warnings:
            return PreflightResult(
                result=CheckResult.REQUIRE_CONFIRM,
                command=command,
                reason="Strict mode requires confirmation",
                warnings=warnings,
                suggestions=suggestions,
                risk_level=risk_level,
            )

        # Determine final result
        if warnings and risk_level in ("high", "critical"):
            return PreflightResult(
                result=CheckResult.REQUIRE_CONFIRM,
                command=command,
                reason="Operation requires confirmation",
                warnings=warnings,
                suggestions=suggestions,
                risk_level=risk_level,
            )
        elif warnings:
            return PreflightResult(
                result=CheckResult.WARN,
                command=command,
                reason="Proceed with caution",
                warnings=warnings,
                suggestions=suggestions,
                risk_level=risk_level,
            )
        else:
            return PreflightResult(
                result=CheckResult.ALLOW,
                command=command,
                reason="Command appears safe",
                risk_level=risk_level,
            )

    def check_batch(self, commands: List[str]) -> List[PreflightResult]:
        """Check multiple commands."""
        return [self.check(cmd) for cmd in commands]

    def get_safe_alternative(self, command: str) -> Optional[str]:
        """
        Suggest a safer alternative for a command.

        Returns:
            Safer alternative command or None
        """
        # rm -rf -> rm with confirmation
        if re.search(r"rm\s+-rf", command):
            return re.sub(r"rm\s+-rf", "rm -ri", command)

        # kill -9 -> kill with SIGTERM
        if re.search(r"kill\s+-9", command):
            return re.sub(r"kill\s+-9", "kill -15", command)

        # chmod 777 -> chmod 755
        if re.search(r"chmod\s+777", command):
            return re.sub(r"chmod\s+777", "chmod 755", command)

        # systemctl restart -> systemctl reload
        if re.search(r"systemctl\s+restart", command):
            return re.sub(r"systemctl\s+restart", "systemctl reload", command)

        return None

    def explain_risk(self, command: str) -> str:
        """
        Get a human-readable explanation of command risks.

        Returns:
            Explanation string
        """
        result = self.check(command)

        if result.result == CheckResult.ALLOW:
            return f"✅ Command appears safe (risk: {result.risk_level})"

        lines = [f"⚠️ Risk Level: {result.risk_level.upper()}"]

        if result.warnings:
            lines.append("\nWarnings:")
            for w in result.warnings:
                lines.append(f"  • {w}")

        if result.suggestions:
            lines.append("\nSuggestions:")
            for s in result.suggestions:
                lines.append(f"  • {s}")

        alternative = self.get_safe_alternative(command)
        if alternative:
            lines.append(f"\nSafer alternative: {alternative}")

        return "\n".join(lines)


def get_preflight_checker(
    environment: str = "dev",
    strict_mode: bool = False,
) -> PreflightChecker:
    """Get a PreflightChecker instance."""
    return PreflightChecker(environment=environment, strict_mode=strict_mode)
