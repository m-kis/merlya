"""
Command execution tools.
"""
from typing import Annotated, Any, Dict

from athena_ai.core.hooks import HookEvent
from athena_ai.domains.tools.selector import ToolAction, get_tool_selector
from athena_ai.knowledge.ops_knowledge_manager import get_knowledge_manager
from athena_ai.tools.base import emit_hook, get_tool_context, validate_host
from athena_ai.triage import ErrorType
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
    logger.info(f"⚡ Tool: execute_command on {target} - {reason}")

    # Validate host
    is_valid, message = validate_host(target)
    if not is_valid:
        logger.warning(f"🚫 BLOCKED: execute_command on invalid host '{target}'")
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
            # Handle async context manager call
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    from concurrent.futures import ThreadPoolExecutor
                    with ThreadPoolExecutor() as pool:
                        pool.submit(asyncio.run, ctx.context_manager.scan_host(target)).result()
                else:
                    asyncio.run(ctx.context_manager.scan_host(target))
            except RuntimeError:
                asyncio.run(ctx.context_manager.scan_host(target))
            except Exception:
                asyncio.run(ctx.context_manager.scan_host(target))
        except Exception as e:
            logger.warning(f"⚠️ Could not scan {target}: {e}")

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
        logger.warning(f"⚠️ Permission detection failed: {e}")

    # Resolve @variable references
    if ctx.credentials and '@' in command:
        resolved = ctx.credentials.resolve_variables(command, warn_missing=True)
        if resolved != command:
            command = resolved

    # Execute with retry
    max_retries = 2
    attempt = 0
    # Initialize with failure state - will be overwritten by executor
    result: Dict[str, Any] = {'success': False, 'error': 'Not executed', 'exit_code': -1}
    corrected_command = None

    while attempt <= max_retries:
        result = ctx.executor.execute(target, command, confirm=True)

        if result.get('success'):
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

    # Failed - use ToolSelector for intelligent recommendation
    error = result.get('error', result.get('stderr', 'Unknown error'))
    exit_code = result.get('exit_code', 1)

    emit_hook(HookEvent.TOOL_EXECUTE_ERROR, {
        "tool": "execute_command", "target": target,
        "command": original_command, "error": error[:500], "exit_code": exit_code
    })

    # Analyze error and get tool recommendation
    error_analysis = result.get('error_analysis', {})
    error_type = None
    if error_analysis:
        try:
            error_type = ErrorType(error_analysis.get('type', 'unknown'))
        except ValueError:
            error_type = None

    # Use ToolSelector for intelligent recommendation
    tool_selector = get_tool_selector()
    recommendation = tool_selector.select(
        error_type=error_type,
        error_message=error,
        context={
            "target": target,
            "command": original_command,
            "exit_code": exit_code,
            "elevation_method": permissions_info.get('elevation_method') if permissions_info else None,
        }
    )

    # Build response with tool recommendation
    if ctx.error_correction:
        base_response = ctx.error_correction.explain_error_to_user(
            original_command, error, exit_code, target,
            corrected_command if attempt > 1 else None
        )
    else:
        base_response = f"❌ FAILED (after {attempt} attempts)\n\nError:\n{error}"

    # Add intelligent tool recommendation if actionable
    if recommendation.action != ToolAction.NO_ACTION and recommendation.confidence >= 0.65:
        tool_hint = f"\n\n💡 **Recommended action**: Use `{recommendation.tool_name}` tool"
        if recommendation.tool_params:
            params_str = ", ".join(f"{k}={v!r}" for k, v in recommendation.tool_params.items() if v)
            tool_hint += f"\n   Parameters: {params_str}"
        tool_hint += f"\n   Reason: {recommendation.reason}"

        # For permission errors, add explicit instruction for the agent
        if recommendation.action == ToolAction.REQUEST_ELEVATION:
            tool_hint += (
                "\n\n🔐 **IMPORTANT**: This is a permission error. "
                "Call `request_elevation()` to ask the user for elevated privileges."
            )

        base_response += tool_hint

    return base_response


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
    logger.info(f"🌐 Tool: add_route {network_cidr} via {gateway}")

    if ctx.context_memory and ctx.context_memory.knowledge_store:
        try:
            ctx.context_memory.knowledge_store.add_route(network_cidr, gateway)
            return f"✅ Route added: Traffic to {network_cidr} will go through {gateway}"
        except Exception as e:
            return f"❌ Failed to add route: {e}"

    return "❌ Memory system not available"
