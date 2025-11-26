"""
Command execution tools.
"""
from typing import Annotated

from athena_ai.core.hooks import HookEvent
from athena_ai.knowledge.ops_knowledge_manager import get_knowledge_manager
from athena_ai.tools.base import emit_hook, get_tool_context, validate_host
from athena_ai.utils.logger import logger


def execute_command(
    target: Annotated[str, "Target host (hostname, IP, or 'local')"],
    command: Annotated[str, "Shell command to execute"],
    reason: Annotated[str, "Why this command is needed (for audit trail)"]
) -> str:
    """
    Execute a shell command on a target host (local or remote via SSH).

    IMPORTANT: The target host MUST exist in the inventory. Use list_hosts() first.

    Args:
        target: Target host - use 'local' for local machine
        command: Shell command to execute
        reason: Why this command is needed (for audit trail)

    Returns:
        Command output with success/failure status
    """
    ctx = get_tool_context()
    logger.info(f"Tool: execute_command on {target} - {reason}")

    # Validate host
    is_valid, message = validate_host(target)
    if not is_valid:
        logger.warning(f"BLOCKED: execute_command on invalid host '{target}'")
        return f"❌ BLOCKED: Cannot execute on '{target}'\n\n{message}\n\n💡 Use list_hosts()"

    # Hook: Pre-execution
    hook_ctx = emit_hook(HookEvent.TOOL_EXECUTE_START, {
        "tool": "execute_command", "target": target, "command": command, "reason": reason
    })
    if hook_ctx and hook_ctx.cancelled:
        return f"❌ BLOCKED by hook: {hook_ctx.cancel_reason}"

    # Just-in-time scanning
    if target not in ["local", "localhost"]:
        try:
            ctx.context_manager.scan_host(target)
        except Exception as e:
            logger.warning(f"Could not scan {target}: {e}")

    # Auto-elevation
    original_command = command
    permissions_info = None
    try:
        permissions_info = ctx.permissions.detect_capabilities(target)
        if ctx.permissions.requires_elevation(command):
            if not permissions_info['is_root']:
                if permissions_info['elevation_method'] in ['sudo', 'sudo_with_password', 'doas', 'su']:
                    command = ctx.permissions.elevate_command(command, target)
    except Exception as e:
        logger.warning(f"Permission detection failed: {e}")

    # Resolve @variable references
    if ctx.credentials and '@' in command:
        resolved = ctx.credentials.resolve_variables(command, warn_missing=True)
        if resolved != command:
            command = resolved

    # Execute with retry
    max_retries = 2
    attempt = 0
    result = None
    corrected_command = None

    while attempt <= max_retries:
        result = ctx.executor.execute(target, command, confirm=True)

        if result['success']:
            output = result['stdout'] or "(no output)"
            retry_note = f" (succeeded after {attempt} retries)" if attempt > 0 else ""

            emit_hook(HookEvent.TOOL_EXECUTE_END, {
                "tool": "execute_command", "target": target,
                "command": original_command, "success": True
            })

            # Audit log
            try:
                get_knowledge_manager().log_action(
                    action="execute_command", target=target,
                    command=original_command, result="success", details=reason
                )
            except Exception:
                pass

            return f"✅ SUCCESS{retry_note}\n\nOutput:\n{output}"

        attempt += 1
        if attempt > max_retries:
            break

        error = result.get('error', result.get('stderr', 'Unknown error'))
        exit_code = result.get('exit_code', 1)

        if not ctx.error_correction:
            break
        if not ctx.error_correction.should_retry(error, exit_code):
            break

        corrected_command = ctx.error_correction.analyze_and_correct(
            command, error, exit_code, target,
            {"permissions_info": permissions_info, "original_command": original_command}
        )
        if not corrected_command:
            break

        command = corrected_command

    # Failed
    error = result.get('error', result.get('stderr', 'Unknown error'))
    exit_code = result.get('exit_code', 1)

    emit_hook(HookEvent.TOOL_EXECUTE_ERROR, {
        "tool": "execute_command", "target": target,
        "command": original_command, "error": error[:500], "exit_code": exit_code
    })

    if ctx.error_correction:
        return ctx.error_correction.explain_error_to_user(
            original_command, error, exit_code, target,
            corrected_command if attempt > 1 else None
        )

    return f"❌ FAILED (after {attempt} attempts)\n\nError:\n{error}"


def add_route(
    network_cidr: Annotated[str, "Network CIDR (e.g. 10.0.0.0/8)"],
    gateway: Annotated[str, "Gateway/Bastion hostname"]
) -> str:
    """
    Teach the system a new network route.

    Args:
        network_cidr: The target network (e.g. 10.0.0.0/8)
        gateway: The jump host to use
    """
    ctx = get_tool_context()
    logger.info(f"Tool: add_route {network_cidr} via {gateway}")

    if ctx.context_memory and ctx.context_memory.knowledge_store:
        try:
            ctx.context_memory.knowledge_store.add_route(network_cidr, gateway)
            return f"✅ Route added: Traffic to {network_cidr} will go through {gateway}"
        except Exception as e:
            return f"❌ Failed to add route: {e}"

    return "❌ Memory system not available"
