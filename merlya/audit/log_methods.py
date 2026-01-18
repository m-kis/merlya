"""
Merlya Audit - Specialized logging methods.

Contains methods for logging specific event types.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .formatters import sanitize_args
from .models import AuditEvent, AuditEventType

if TYPE_CHECKING:
    from .logger import AuditLogger


async def log_command(
    logger: AuditLogger,
    command: str,
    host: str | None = None,
    output: str | None = None,
    exit_code: int | None = None,
    success: bool = True,
) -> None:
    """Log a command execution."""
    details: dict[str, Any] = {}
    if output:
        # Truncate output for storage
        details["output_preview"] = output[:200] if len(output) > 200 else output
        details["output_length"] = len(output)
    if exit_code is not None:
        details["exit_code"] = exit_code

    await logger.log(
        AuditEvent(
            event_type=AuditEventType.COMMAND_EXECUTED,
            action=command[:100],  # Truncate command
            target=host,
            details=details,
            success=success,
        )
    )


async def log_skill(
    logger: AuditLogger,
    skill_name: str,
    hosts: list[str],
    task: str | None = None,
    success: bool = True,
    duration_ms: int | None = None,
) -> None:
    """Log a skill invocation."""
    details: dict[str, Any] = {
        "hosts": hosts,
        "host_count": len(hosts),
    }
    if task:
        details["task"] = task[:100]
    if duration_ms is not None:
        details["duration_ms"] = duration_ms

    await logger.log(
        AuditEvent(
            event_type=AuditEventType.SKILL_INVOKED,
            action=skill_name,
            target=", ".join(hosts[:3]) + ("..." if len(hosts) > 3 else ""),
            details=details,
            success=success,
        )
    )


async def log_tool(
    logger: AuditLogger,
    tool_name: str,
    host: str | None = None,
    args: dict[str, Any] | None = None,
    success: bool = True,
) -> None:
    """Log a tool usage."""
    details: dict[str, Any] = {}
    if args:
        # Sanitize args (remove sensitive data)
        details["args"] = sanitize_args(args)

    await logger.log(
        AuditEvent(
            event_type=AuditEventType.TOOL_USED,
            action=tool_name,
            target=host,
            details=details,
            success=success,
        )
    )


async def log_destructive(
    logger: AuditLogger,
    operation: str,
    target: str,
    confirmed: bool = False,
    success: bool | None = None,
) -> None:
    """Log a destructive operation."""
    if success is None:
        # Just requesting confirmation
        await logger.log(
            AuditEvent(
                event_type=AuditEventType.CONFIRMATION_REQUESTED,
                action=operation,
                target=target,
            )
        )
    elif confirmed:
        await logger.log(
            AuditEvent(
                event_type=AuditEventType.DESTRUCTIVE_OPERATION,
                action=operation,
                target=target,
                success=success,
                details={"confirmed": True},
            )
        )
    else:
        await logger.log(
            AuditEvent(
                event_type=AuditEventType.CONFIRMATION_DENIED,
                action=operation,
                target=target,
                success=False,
            )
        )


__all__ = [
    "log_command",
    "log_destructive",
    "log_skill",
    "log_tool",
]
