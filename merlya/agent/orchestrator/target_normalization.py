"""
Target normalization for the orchestrator.

Contains logic to normalize target hosts and prevent random host selection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


async def normalize_target(target: str, task: str, context: SharedContext | None = None) -> str:
    """
    Normalize target to ensure local operations don't use random hosts.

    If the LLM picks a random host but the task doesn't explicitly mention
    that host, we default to "local" to prevent SSH attempts to unreachable hosts.

    Args:
        target: Target provided by LLM.
        task: Original task description.
        context: Optional SharedContext for session context checks.

    Returns:
        Normalized target ("local" if no specific host in task).
    """
    # Already local
    if target.lower() in ("local", "localhost", "127.0.0.1", "::1"):
        return "local"

    # Check if target is explicitly mentioned in the task
    task_lower = task.lower()
    target_lower = target.lower()

    # Target is explicitly in task text
    if target_lower in task_lower:
        return target

    # CONVERSATION CONTEXT: Check if target matches last_remote_target from session
    if context:
        last_target = context.last_remote_target
        if last_target:
            # Direct match
            if target_lower == last_target.lower():
                logger.debug(f"Target '{target}' matches session context (last_remote_target)")
                return target

            # Check if both resolve to the same inventory entry
            # Try both get_by_name and get_by_hostname for flexibility
            last_entry = await context.hosts.get_by_name(
                last_target
            ) or await context.hosts.get_by_hostname(last_target)
            current_entry = await context.hosts.get_by_name(
                target
            ) or await context.hosts.get_by_hostname(target)
            if last_entry and current_entry and last_entry.id == current_entry.id:
                logger.debug(
                    f"Target '{target}' resolves to same inventory as context '{last_target}'"
                )
                return target

    # If the target hostname/IP is NOT mentioned in the task and not in session context,
    # the LLM is picking a random host - default to local
    logger.warning(
        f"LLM picked target '{target}' not mentioned in task. Defaulting to 'local' for safety."
    )
    return "local"
