"""
SSH command execution tool for Merlya agent.

Provides remote command execution via SSH.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic_ai import Agent, ModelRetry, RunContext

from merlya.agent.tools_common import check_recoverable_error

if TYPE_CHECKING:
    from merlya.agent.main import AgentDependencies
    from merlya.core.context import SharedContext
    from merlya.persistence import HostRepository
    from merlya.router import RouterResult
else:
    AgentDependencies = Any

# Constants for local host detection
LOCAL_HOSTS = frozenset(("local", "localhost", "127.0.0.1", "::1"))


def _is_local_target(host: str) -> bool:
    """Check if host refers to local machine."""
    return host.lower() in LOCAL_HOSTS if host else False


def _check_host_in_entities(
    host: str,
    router_result: RouterResult | None,
    original_request: str,
) -> bool:
    """Check if host is mentioned in router entities or original request."""
    host_lower = host.lower()
    user_mentioned_hosts = router_result.entities.get("hosts", []) if router_result else []
    return (
        host_lower in [h.lower() for h in user_mentioned_hosts]
        or host_lower in original_request.lower()
        or host in original_request  # case-sensitive for IPs
    )


async def _resolve_host_from_inventory(
    host: str,
    hosts_manager: HostRepository,
    original_request: str,
) -> bool:
    """Check if host resolves to an inventory entry mentioned in request."""
    host_entry = await hosts_manager.get_by_name(host)
    if host_entry and host_entry.name.lower() in original_request.lower():
        logger.debug(f"✅ Host '{host}' (name) found in request")
        return True

    host_by_hostname = await hosts_manager.get_by_hostname(host)
    if host_by_hostname and host_by_hostname.name.lower() in original_request.lower():
        logger.debug(f"✅ Host '{host}' resolves to '{host_by_hostname.name}' which is in request")
        return True

    return False


async def _check_conversation_context(
    host: str,
    context: SharedContext,
    hosts_manager: HostRepository,
) -> bool:
    """Check if host matches the last remote target in conversation context."""
    last_target = context.last_remote_target
    if not last_target:
        return False

    if host.lower() == last_target.lower():
        logger.debug(f"✅ Host '{host}' matches conversation context (last_remote_target)")
        return True

    # Check if both resolve to the same inventory entry
    last_entry = await hosts_manager.get_by_name(
        last_target
    ) or await hosts_manager.get_by_hostname(last_target)
    current_entry = await hosts_manager.get_by_name(host) or await hosts_manager.get_by_hostname(
        host
    )
    if last_entry and current_entry and last_entry.id == current_entry.id:
        logger.debug(f"✅ Host '{host}' resolves to same inventory as context '{last_target}'")
        return True

    return False


def _make_loop_error_response(reason: str, host: str = "local") -> dict[str, Any]:
    """Create a standardized loop detection error response."""
    host_msg = "on this host " if host != "local" else ""
    return {
        "success": False,
        "stdout": "",
        "stderr": "",
        "exit_code": -1,
        "loop_detected": True,
        "error": f"🛑 LOOP DETECTED: {reason}\n"
        f"You have repeated this command too many times {host_msg}. "
        "Try a DIFFERENT approach or report your findings to the user.",
    }


def _make_circuit_breaker_response(host: str) -> dict[str, Any]:
    """Create a circuit breaker error response."""
    return {
        "success": False,
        "stdout": "",
        "stderr": "",
        "exit_code": -1,
        "circuit_breaker": True,
        "error": f"🔌 CIRCUIT BREAKER OPEN for {host}: Too many SSH failures.\n"
        "STOP trying to connect to this host. Wait for the retry window or "
        "try a different host. The connection appears unstable.",
    }


def _validate_host_not_credential(host: str) -> None:
    """Raise ModelRetry if host looks like a credential reference."""
    credential_keywords = ("secret", "password", "sudo", "root", "cred")
    if host.startswith("@") and any(kw in host.lower() for kw in credential_keywords):
        raise ModelRetry(
            f"❌ WRONG: '{host}' is a password reference, not a host!\n"
            "host = machine IP/name (e.g., '192.168.1.7')\n"
            "stdin = password reference (e.g., '@secret-sudo')\n"
            "CORRECT: ssh_execute(host='192.168.1.7', command='sudo -S cmd', "
            "stdin='@secret-sudo')"
        )


def _detect_elevation_needs(command: str) -> bool:
    """Detect if command needs stdin for elevation (sudo -S or su)."""
    has_sudo_s = (
        "sudo -S " in command
        or "sudo -S" in command
        or ("-S" in command and "sudo" in command.lower())
    )
    has_su = command.strip().startswith("su ") or " su -c" in command.lower()
    return has_sudo_s or has_su


async def _resolve_elevation_credentials(
    ctx: RunContext[AgentDependencies],
    host: str,
    command: str,
    stdin: str | None,
) -> str | None:
    """Resolve elevation credentials, either from LLM-provided stdin or auto-lookup."""
    from merlya.agent.specialists.elevation import auto_collect_elevation_credentials

    if stdin and stdin.startswith("@"):
        secret_key = stdin[1:]
        if ctx.deps.context.secrets.get(secret_key):
            logger.debug(f"✅ LLM-provided credential exists: {stdin[:30]}...")
            return stdin
        logger.debug(f"⚠️ LLM-provided credential not found: {stdin[:30]}... trying alternatives")
    else:
        logger.debug(f"🔐 Auto-elevation: looking up credentials for {host}")

    effective_stdin = await auto_collect_elevation_credentials(ctx.deps.context, host, command)

    if effective_stdin:
        logger.debug(f"✅ Found stored credentials for elevation on {host}")
        return effective_stdin

    raise ModelRetry(
        f"❌ MISSING credentials for elevation on '{host}'.\n"
        f"No stored credentials found. First call:\n"
        f"request_credentials(service='sudo', host='{host}')\n"
        f"Then retry with: ssh_execute(host='{host}', command='{command[:40]}...', "
        f"stdin='@sudo:{host}:password')"
    )


def _build_ssh_response(
    result: Any,
    command: str,
    get_verification_hint: Any,
) -> dict[str, Any]:
    """Build the SSH execution response dictionary."""
    response: dict[str, Any] = {
        "success": result.success,
        "stdout": result.data.get("stdout", "") if result.data else "",
        "stderr": result.data.get("stderr", "") if result.data else "",
        "exit_code": result.data.get("exit_code", -1) if result.data else -1,
        "via": result.data.get("via") if result.data else None,
    }

    if result.success:
        hint = get_verification_hint(command)
        if hint:
            response["verification"] = {
                "command": hint.command,
                "expect": hint.expect_stdout,
                "description": hint.description,
            }

    return response


async def _determine_execution_target(
    ctx: RunContext[AgentDependencies],
    host: str,
) -> bool:
    """Determine if execution should be local. Returns True if local."""
    if _is_local_target(host):
        return True

    user_input = ctx.deps.user_input or ""
    host_in_request = _check_host_in_entities(host, ctx.deps.router_result, user_input)

    if not host_in_request:
        host_in_request = await _resolve_host_from_inventory(
            host, ctx.deps.context.hosts, user_input
        )
    if not host_in_request:
        host_in_request = await _check_conversation_context(
            host, ctx.deps.context, ctx.deps.context.hosts
        )

    if not host_in_request:
        logger.warning(
            f"⚠️ LLM picked target '{host}' not mentioned in task. Defaulting to 'local' for safety."
        )
        return True

    return False


async def ssh_execute(
    ctx: RunContext[AgentDependencies],
    host: str,
    command: str,
    timeout: int = 60,
    via: str | None = None,
    stdin: str | None = None,
) -> dict[str, Any]:
    """Execute a command on a host via SSH.

    Args:
        host: Target machine IP or hostname (NOT a password reference).
        command: Command to execute. Add sudo/doas/su prefix if elevation needed.
        timeout: Command timeout in seconds (default: 60).
        via: Jump host/bastion for tunneling.
        stdin: Password reference for su/sudo -S (format: @service:host:password).

    Returns:
        Command output with stdout, stderr, exit_code, and verification hint.
    """
    from merlya.subagents.timeout import touch_activity
    from merlya.tools.core import bash_execute as _bash_execute
    from merlya.tools.core import ssh_execute as _ssh_execute
    from merlya.tools.core.security import mask_sensitive_command
    from merlya.tools.core.verification import get_verification_hint

    is_local = await _determine_execution_target(ctx, host)

    if is_local:
        return await _execute_local(ctx, command, timeout, _bash_execute, touch_activity)

    _validate_host_not_credential(host)

    effective_stdin = stdin
    if _detect_elevation_needs(command):
        effective_stdin = await _resolve_elevation_credentials(ctx, host, command, stdin)

    return await _execute_remote(
        ctx,
        host,
        command,
        timeout,
        via,
        effective_stdin,
        _ssh_execute,
        touch_activity,
        mask_sensitive_command,
        get_verification_hint,
    )


async def _execute_local(
    ctx: RunContext[AgentDependencies],
    command: str,
    timeout: int,
    bash_execute_fn: Any,
    touch_activity_fn: Any,
) -> dict[str, Any]:
    """Execute command locally via bash."""
    logger.info(f"🖥️ Running locally (not via SSH): {command[:60]}...")

    would_loop, reason = ctx.deps.tracker.would_loop("local", command)
    if would_loop:
        logger.warning(f"🛑 Loop prevented for local: {reason}")
        return _make_loop_error_response(reason)

    ctx.deps.tracker.record("local", command)

    touch_activity_fn()
    result = await bash_execute_fn(ctx.deps.context, command, timeout)
    touch_activity_fn()

    return {
        "success": result.success,
        "stdout": result.data.get("stdout", "") if result.data else "",
        "stderr": result.data.get("stderr", "") if result.data else "",
        "exit_code": result.data.get("exit_code", -1) if result.data else -1,
    }


async def _execute_remote(
    ctx: RunContext[AgentDependencies],
    host: str,
    command: str,
    timeout: int,
    via: str | None,
    stdin: str | None,
    ssh_execute_fn: Any,
    touch_activity_fn: Any,
    mask_fn: Any,
    get_hint_fn: Any,
) -> dict[str, Any]:
    """Execute command remotely via SSH."""
    via_info = f" via {via}" if via else ""
    safe_log_command = mask_fn(command)
    logger.info(f"Executing on {host}{via_info}: {safe_log_command[:50]}...")

    would_loop, reason = ctx.deps.tracker.would_loop(host, command)
    if would_loop:
        logger.warning(f"🛑 Loop prevented for {host}: {reason}")
        return _make_loop_error_response(reason, host)

    ctx.deps.tracker.record(host, command)
    ctx.deps.context.last_remote_target = host
    logger.debug(f"📍 Conversation context updated: last_remote_target = {host}")

    touch_activity_fn()
    result = await ssh_execute_fn(ctx.deps.context, host, command, timeout, via=via, stdin=stdin)
    touch_activity_fn()

    if not result.success and result.error and "circuit breaker open" in result.error.lower():
        logger.warning(f"🔌 Circuit breaker open for {host}")
        return _make_circuit_breaker_response(host)

    if not result.success and check_recoverable_error(result.error):
        raise ModelRetry(f"Host '{host}' not found. Check the name or use list_hosts().")

    return _build_ssh_response(result, command, get_hint_fn)


def register(agent: Agent[Any, Any]) -> None:
    """Register SSH tool on agent."""
    agent.tool(ssh_execute)
