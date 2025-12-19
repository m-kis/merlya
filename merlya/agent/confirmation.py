"""
Merlya Agent - Command confirmation UX.

Handles user confirmation for bash/ssh commands before execution.
Format: [y] Execute  [n] Cancel  [a] Always yes for session

Dangerous patterns are auto-detected and flagged.

SECURITY WARNING: Command logging may expose sensitive data (passwords, API keys, tokens).
Ensure log level is appropriate for your security requirements.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from merlya.ui.console import ConsoleUI


class DangerLevel(Enum):
    """Command danger level."""

    SAFE = "safe"  # Read-only commands
    MODERATE = "moderate"  # State-changing but recoverable
    DANGEROUS = "dangerous"  # Destructive or irreversible


class ConfirmationResult(Enum):
    """Result of confirmation prompt."""

    EXECUTE = "execute"  # User confirmed
    CANCEL = "cancel"  # User cancelled
    ALWAYS_YES = "always_yes"  # User chose "always yes" for session


# Dangerous command patterns (case-insensitive)
# NOTE: Order matters! More specific patterns (docker/podman) must come BEFORE generic ones (rm)
DANGEROUS_PATTERNS: list[tuple[str, DangerLevel]] = [
    # Docker/containers - MUST be before generic rm pattern
    (r"\bdocker\s+(rm|rmi|prune|stop|kill)", DangerLevel.MODERATE),
    (r"\bpodman\s+(rm|rmi|prune|stop|kill)", DangerLevel.MODERATE),
    (r"\bkubectl\s+delete", DangerLevel.MODERATE),
    # Destructive file operations
    # Match rm with flags containing r or f (e.g., -rf, -r, -f, -r -f)
    # Uses lookahead to find -FLAG containing r or f anywhere in command
    (r"\brm\s+(?=.*-\S*[rf])", DangerLevel.DANGEROUS),
    # Match rm targeting root directory only (/ followed by whitespace or end)
    (r"\brm\s+(?:-\S+\s+)*/(?:\s|$)", DangerLevel.DANGEROUS),
    # Match rm targeting critical system directories (with optional flags)
    (r"\brm\s+(?:-\S+\s+)*/(bin|boot|etc|lib|lib64|sbin|sys|usr|var)\b", DangerLevel.DANGEROUS),
    (r"\brmdir\s+", DangerLevel.MODERATE),
    (r"\bdd\s+", DangerLevel.DANGEROUS),
    (r"\bmkfs\s+", DangerLevel.DANGEROUS),
    (r"\bshred\s+", DangerLevel.DANGEROUS),
    # Service control
    (r"\bsystemctl\s+(stop|restart|disable|mask)", DangerLevel.MODERATE),
    (r"\bservice\s+\S+\s+(stop|restart)", DangerLevel.MODERATE),
    (r"\bkill\s+", DangerLevel.MODERATE),
    (r"\bkillall\s+", DangerLevel.MODERATE),
    (r"\bpkill\s+", DangerLevel.MODERATE),
    # System control
    (r"\breboot\b", DangerLevel.DANGEROUS),
    (r"\bshutdown\b", DangerLevel.DANGEROUS),
    (r"\bpoweroff\b", DangerLevel.DANGEROUS),
    (r"\bhalt\b", DangerLevel.DANGEROUS),
    (r"\binit\s+[0-6]", DangerLevel.DANGEROUS),
    # Package management
    (r"\bapt\s+(remove|purge|autoremove)", DangerLevel.MODERATE),
    (r"\byum\s+(remove|erase)", DangerLevel.MODERATE),
    (r"\bdnf\s+(remove|erase)", DangerLevel.MODERATE),
    (r"\bpacman\s+-R", DangerLevel.MODERATE),
    # Database operations
    (r"\bDROP\s+(TABLE|DATABASE|INDEX)", DangerLevel.DANGEROUS),
    (r"\bTRUNCATE\s+", DangerLevel.DANGEROUS),
    (r"\bDELETE\s+FROM", DangerLevel.MODERATE),
    # Network
    (r"\biptables\s+-(?:[A-Z]*[FXZ][A-Z]*)", DangerLevel.DANGEROUS),
    (r"\bip\s+route\s+(del|flush)", DangerLevel.DANGEROUS),
    # User management
    (r"\buserdel\s+", DangerLevel.DANGEROUS),
    (r"\bgroupdel\s+", DangerLevel.DANGEROUS),
    (r"\bpasswd\s+", DangerLevel.MODERATE),
    # Permissions
    (r"\bchmod\s+777", DangerLevel.DANGEROUS),
    (r"\bchmod\s+-R", DangerLevel.MODERATE),
    (r"\bchown\s+-R", DangerLevel.MODERATE),
]


@dataclass
class ConfirmationState:
    """
    Session-wide confirmation state.

    Tracks confirmations to avoid re-asking for the same command.
    """

    always_yes: bool = False  # Global "always yes" for all commands
    always_yes_patterns: set[str] = field(default_factory=set)  # Specific patterns
    confirmed_commands: set[str] = field(default_factory=set)  # Commands already confirmed with "y"

    def should_skip(self, command: str) -> bool:
        """Check if confirmation should be skipped for this command."""
        if self.always_yes:
            return True
        # Check if command matches any "always yes" pattern
        cmd_prefix = command.strip()[:25].lower()
        if cmd_prefix in self.always_yes_patterns:
            return True
        # Check if this exact command was already confirmed
        full_command = command.strip().lower()
        if full_command in self.confirmed_commands:
            logger.trace(
                f"⚡ Skipping confirmation (already confirmed): {command[:50]}..."
            )  # Truncated to avoid sensitive data exposure
            return True
        return False

    def mark_confirmed(self, command: str) -> None:
        """Mark a command as confirmed (user said 'y')."""
        full_command = command.strip().lower()
        self.confirmed_commands.add(full_command)
        logger.trace(
            f"✅ Command confirmed: {command[:50]}..."
        )  # Truncated to avoid sensitive data exposure

    def set_always_yes(self, command: str | None = None) -> None:
        """Set "always yes" for session or specific command prefix."""
        if command is None:
            self.always_yes = True
            logger.info("✅ Auto-confirm enabled for this session")
        else:
            cmd_prefix = command.strip()[:25].lower()
            self.always_yes_patterns.add(cmd_prefix)
            logger.trace(
                f"✅ Auto-confirm enabled for: {cmd_prefix}..."
            )  # Truncated to avoid sensitive data exposure

    def reset(self) -> None:
        """Reset confirmation state (for tests)."""
        self.always_yes = False
        self.always_yes_patterns.clear()
        self.confirmed_commands.clear()


def detect_danger_level(command: str) -> DangerLevel:
    """
    Detect the danger level of a command.

    Args:
        command: Command to analyze.

    Returns:
        DangerLevel (SAFE, MODERATE, DANGEROUS).
    """
    for pattern, level in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            # Only log pattern match, not command content to avoid sensitive data exposure
            logger.debug(f"⚠️ Command matched dangerous pattern '{pattern}': {level.value}")
            return level

    # Default: moderate for all external commands (requires confirmation)
    return DangerLevel.MODERATE


def format_confirmation_prompt(
    command: str,
    target: str = "local",
    danger_level: DangerLevel = DangerLevel.MODERATE,
) -> str:
    """
    Format the confirmation prompt with visual styling.

    Args:
        command: Command to execute.
        target: Target host (or "local" for bash).
        danger_level: Danger level of the command.

    Returns:
        Formatted prompt string.
    """
    # Icon based on danger level
    icon = {
        DangerLevel.SAFE: "🔧",
        DangerLevel.MODERATE: "⚡",
        DangerLevel.DANGEROUS: "🚨",
    }.get(danger_level, "🔧")

    # Target display
    target_line = f"{icon} Local command:" if target == "local" else f"{icon} Command on {target}:"

    # Truncate very long commands
    display_cmd = command if len(command) <= 80 else command[:77] + "..."

    return f"{target_line}\n   {display_cmd}"


async def confirm_command(
    ui: ConsoleUI,
    command: str,
    target: str = "local",
    state: ConfirmationState | None = None,
    auto_confirm: bool = False,
) -> ConfirmationResult:
    """
    Prompt user for command confirmation.

    Args:
        ui: ConsoleUI instance.
        command: Command to confirm.
        target: Target host (or "local").
        state: Session confirmation state.
        auto_confirm: If True, skip confirmation (--yes mode).

    Returns:
        ConfirmationResult indicating user choice.
    """
    # Check auto-confirm modes
    if auto_confirm or ui.auto_confirm:
        logger.trace(
            f"⚡ Auto-confirmed: {command[:50]}..."
        )  # Truncated to avoid sensitive data exposure
        return ConfirmationResult.EXECUTE

    # Check session state
    if state and state.should_skip(command):
        logger.trace(
            f"⚡ Auto-confirmed (session): {command[:50]}..."
        )  # Truncated to avoid sensitive data exposure
        return ConfirmationResult.EXECUTE

    # Detect danger level
    danger_level = detect_danger_level(command)

    # Format and display prompt
    prompt_text = format_confirmation_prompt(command, target, danger_level)
    ui.console.print()
    ui.console.print(prompt_text)
    ui.console.print()

    # Show danger warning for dangerous commands
    if danger_level == DangerLevel.DANGEROUS:
        ui.warning("⚠️ This command is potentially destructive!")
        ui.console.print()

    # Prompt with [y]/[n]/[a] options - escape brackets for Rich markup
    ui.console.print(
        "[accent]\\[y][/accent] ✅ Execute  [accent]\\[n][/accent] ❌ Cancel  [accent]\\[a][/accent] 🔓 Always yes"
    )

    # Get user input - NO DEFAULT, user must explicitly choose
    try:
        while True:
            session_result = await ui.prompt("Choice", default="")
            choice = session_result.strip().lower()

            # User must provide a valid choice
            if choice in ("y", "yes", "oui", "o"):
                # Mark command as confirmed so we don't re-ask on retry
                if state:
                    state.mark_confirmed(command)
                return ConfirmationResult.EXECUTE

            if choice in ("a", "always", "toujours"):
                if state:
                    state.set_always_yes()
                return ConfirmationResult.ALWAYS_YES

            if choice in ("n", "no", "non"):
                return ConfirmationResult.CANCEL

            # Invalid choice - prompt again
            if choice:
                ui.warning(f"Invalid choice: '{choice}'. Type y, n, or a.")
            else:
                ui.muted("Type y (execute), n (cancel), or a (always yes)")

    except (KeyboardInterrupt, EOFError):
        logger.trace("User cancelled confirmation (KeyboardInterrupt/EOFError)")
        return ConfirmationResult.CANCEL
    except Exception:
        # Log unexpected errors for debugging while maintaining safety
        logger.exception("Unexpected error in command confirmation, cancelling for safety")
        return ConfirmationResult.CANCEL


async def confirm_batch_commands(
    ui: ConsoleUI,
    commands: list[tuple[str, str]],  # [(command, target), ...]
    state: ConfirmationState | None = None,
    auto_confirm: bool = False,
) -> list[ConfirmationResult]:
    """
    Confirm multiple commands at once.

    Args:
        ui: ConsoleUI instance.
        commands: List of (command, target) tuples.
        state: Session confirmation state.
        auto_confirm: If True, skip all confirmations.

    Returns:
        List of ConfirmationResult for each command.
    """
    results: list[ConfirmationResult] = []

    for command, target in commands:
        result = await confirm_command(
            ui=ui,
            command=command,
            target=target,
            state=state,
            auto_confirm=auto_confirm,
        )
        results.append(result)

        # If user cancelled or set "always yes", apply to rest
        if result == ConfirmationResult.CANCEL:
            # Cancel all remaining
            results.extend([ConfirmationResult.CANCEL] * (len(commands) - len(results)))
            break
        if result == ConfirmationResult.ALWAYS_YES:
            # Auto-confirm remaining
            results.extend([ConfirmationResult.EXECUTE] * (len(commands) - len(results)))
            break

    return results
