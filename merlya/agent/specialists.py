"""
Merlya Agent - Specialist agents.

Four specialist agents that perform the actual work:
- DiagnosticAgent: Investigation, read-only checks (40 tool calls)
- ExecutionAgent: Actions that modify state (30 tool calls)
- SecurityAgent: Security scans, compliance (25 tool calls)
- QueryAgent: Quick inventory queries (15 tool calls)
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from loguru import logger
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.usage import UsageLimits

from merlya.agent.confirmation import (
    ConfirmationResult,
    ConfirmationState,
    confirm_command,
)
from merlya.agent.tracker import ToolCallTracker
from merlya.config.providers import get_model_for_role, get_pydantic_model_string

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


# =============================================================================
# AUTO-ELEVATION HELPER
# =============================================================================
#
# This helper automatically handles credential collection when an elevation
# command (sudo -S, su -c) is detected without stdin. Instead of requiring
# the agent to call request_credentials() first, we handle it transparently.
# =============================================================================


def _needs_elevation_stdin(command: str) -> bool:
    """
    Check if a command requires stdin for elevation.

    Args:
        command: The command to check.

    Returns:
        True if command uses sudo -S, su -c, or similar patterns that need password via stdin.

    Note:
        - sudo -S (uppercase S) = read password from stdin (needs stdin)
        - sudo -s (lowercase s) = run a shell (does NOT need stdin)
        - su -c = run command as another user (needs stdin for password)
    """
    import re

    # Case-sensitive check for sudo -S (uppercase S = stdin mode)
    # Must be at start of command or after a pipe/semicolon (not inside quotes)
    # Pattern: start of string or after | ; && || followed by optional whitespace
    sudo_s_pattern = re.compile(r"(?:^|[|;&])\s*sudo\s+-S\b")
    has_sudo_stdin = bool(sudo_s_pattern.search(command))

    # Case-insensitive check for su commands at command boundaries
    # su at start or after pipe/semicolon
    su_pattern = re.compile(r"(?:^|[|;&])\s*su\s+", re.IGNORECASE)
    has_su = bool(su_pattern.search(command))

    return has_sudo_stdin or has_su


async def _auto_collect_elevation_credentials(
    ctx: SharedContext,
    host: str,
    command: str,
) -> str | None:
    """
    Automatically collect elevation credentials when needed.

    This function:
    1. Checks if credentials are already stored for this host
    2. If not, prompts the user for a password
    3. Returns the stdin reference to use for the command

    The password is verified and stored automatically.

    Args:
        ctx: Shared context.
        host: Target host.
        command: Command that needs elevation.

    Returns:
        The stdin reference (e.g., '@root:hostname:password') or None if user cancels.
    """
    from merlya.tools.interaction import request_credentials

    # PRIORITY 1: Check host's configured elevation_method from database
    host_entry = await ctx.hosts.get_by_name(host)
    elevation_method = host_entry.elevation_method if host_entry else None

    # Determine service type based on host config, then fall back to command analysis
    if elevation_method in {"su", "root"}:
        service = "root"
    elif elevation_method in {"sudo", "sudo-S"}:
        service = "sudo"
    else:
        # Fall back to command analysis
        cmd_lower = command.lower()
        service = "root" if "su " in cmd_lower or "su -c" in cmd_lower else "sudo"

    # PRIORITY 2: Check if credentials already exist before prompting
    # Check both sudo and root keys - user may have stored under either
    for candidate_service in (service, "root" if service == "sudo" else "sudo"):
        secret_key = f"{candidate_service}:{host}:password"
        existing = ctx.secrets.get(secret_key)
        if existing:
            logger.debug(f"✅ Found existing credentials: @{secret_key}")
            return f"@{secret_key}"

    # PRIORITY 3: No stored credentials - prompt user
    logger.info(f"🔐 Auto-prompting for {service} credentials on {host}")
    ctx.ui.info(f"🔐 Commande nécessite élévation: {command[:50]}...")

    result = await request_credentials(
        ctx,
        service=service,
        host=host,
        fields=["password"],
    )

    if result.success and result.data:
        bundle = result.data
        password_ref = bundle.values.get("password", "")
        if password_ref and isinstance(password_ref, str):
            logger.debug(f"✅ Credentials collected, using reference: {password_ref[:20]}...")
            return str(password_ref)  # Explicit str() to satisfy mypy

    logger.warning(f"❌ Could not collect credentials for {host}")
    return None


# System prompts for specialists - short and focused (~50 lines max)

DIAGNOSTIC_PROMPT = """You are Merlya's Diagnostic Agent.

## Your Mission
Investigate issues on infrastructure. Find root causes. Report findings.

## Tools Available
- ssh_execute: Run commands on remote hosts (READ-ONLY operations)
- bash: Run local commands (kubectl, docker, aws - READ-ONLY)
- read_file: Read configuration files

## Rules
1. NEVER modify state - you are READ-ONLY
2. Investigate systematically: logs → config → resources → network
3. Report clear findings with evidence
4. If you need to FIX something, tell the orchestrator to delegate to Execution
5. Be AUTONOMOUS - don't ask questions, just investigate

## Elevation (sudo/su)
For privileged operations, just use the command naturally:
- `sudo cat /etc/shadow` or `su -c 'cat /etc/shadow'`
- The system will automatically prompt for password if needed
- If one method fails (sudo), try the other (su -c 'command')
- No special handling required on your part

## Investigation Pattern
1. Check service status
2. Read recent logs (may need elevation)
3. Check resource usage (CPU, memory, disk)
4. Check network connectivity
5. Review configuration

Be thorough but efficient. Focus on the user's specific issue.
Complete the investigation without asking questions.
"""

EXECUTION_PROMPT = """You are Merlya's Execution Agent.

## Your Mission
Perform actions that modify infrastructure state. Fix issues. Deploy changes.

## Tools Available
- ssh_execute: Run commands on remote hosts (with confirmation)
- bash: Run local commands (kubectl, docker, aws)
- write_file: Modify configuration files

## Rules
1. Destructive actions require confirmation (rm, stop, restart) - the system handles this
2. Verify success after each action
3. Create backups before modifying config files
4. Report what was done and the outcome
5. Be DECISIVE - don't ask unnecessary questions, just execute

## Elevation (sudo/su)
For privileged operations, just use the command naturally:
- `sudo systemctl restart nginx` or `su -c 'service nginx restart'`
- The system will automatically prompt for password if needed
- If one method fails (sudo), try the other (su -c 'command')
- No special handling required on your part

## Execution Pattern
1. Understand current state (quickly)
2. Execute the action (confirmation handled by system)
3. Verify success
4. Report outcome

Be DECISIVE and complete the task. Don't ask questions.
"""

SECURITY_PROMPT = """You are Merlya's Security Agent.

## Your Mission
Audit security posture. Find vulnerabilities. Check compliance.

## Tools Available
- ssh_execute: Run security commands on hosts
- bash: Run local security tools
- scan_host: Run comprehensive security scan

## Rules
1. Be thorough - security requires completeness
2. Prioritize findings by severity (Critical > High > Medium > Low)
3. Provide actionable remediation steps
4. Check common vulnerabilities: outdated packages, weak permissions, exposed services

## Elevation (sudo/su)
For privileged operations, just use the command naturally:
- `sudo cat /etc/shadow` or `su -c 'cat /etc/passwd'`
- The system will automatically prompt for password if needed

## Security Check Pattern
1. Check patch level and updates
2. Review user accounts and permissions
3. Check network exposure (open ports, services)
4. Review security configurations
5. Check for known vulnerabilities

Report findings clearly with severity and remediation.
"""

QUERY_PROMPT = """You are Merlya's Query Agent.

## Your Mission
Answer quick questions about inventory and system status.

## Tools Available
- list_hosts: List hosts from inventory
- get_host: Get host details
- ask_user: Ask for clarification

## Rules
1. Be FAST - queries should be quick
2. NO SSH or bash - only inventory operations
3. Present information clearly
4. If you need to run commands, tell orchestrator to delegate

## Response Format
- Answer directly and concisely
- Use tables for host lists
- Include relevant details (tags, status)

Quick and accurate.
"""


async def run_diagnostic_agent(
    context: SharedContext,
    tracker: ToolCallTracker,
    confirmation_state: ConfirmationState,
    target: str,
    task: str,
    usage_limits: UsageLimits | None = None,
    **_kwargs: Any,
) -> str:
    """
    Run the Diagnostic agent.

    Args:
        context: Shared context.
        tracker: Tool call tracker.
        confirmation_state: Confirmation state.
        target: Target host.
        task: Task description.
        usage_limits: Optional usage limits.

    Returns:
        Agent output as string.
    """
    provider = context.config.model.provider
    model_id = get_model_for_role(provider, "reasoning")
    model_string = get_pydantic_model_string(provider, model_id)

    agent = Agent(
        model_string,
        deps_type=_SpecialistDeps,
        system_prompt=DIAGNOSTIC_PROMPT,
        defer_model_check=True,
        retries=3,  # Allow more retries for loop detection ModelRetry
    )

    _register_diagnostic_tools(agent)

    deps = _SpecialistDeps(
        context=context,
        tracker=tracker,
        confirmation_state=confirmation_state,
        target=target,
    )

    limits = usage_limits or UsageLimits(tool_calls_limit=40)
    prompt = f"Target: {target}\n\nTask: {task}"

    try:
        result = await agent.run(prompt, deps=deps, usage_limits=limits)
        return str(result.output)
    except Exception as e:
        logger.error(f"❌ Diagnostic agent error: {e}")
        return f"Error: {e}"


async def run_execution_agent(
    context: SharedContext,
    tracker: ToolCallTracker,
    confirmation_state: ConfirmationState,
    target: str,
    task: str,
    usage_limits: UsageLimits | None = None,
    require_confirmation: bool = True,
    **_kwargs: Any,
) -> str:
    """
    Run the Execution agent.

    Args:
        context: Shared context.
        tracker: Tool call tracker.
        confirmation_state: Confirmation state.
        target: Target host.
        task: Task description.
        usage_limits: Optional usage limits.
        require_confirmation: Whether to require confirmation.

    Returns:
        Agent output as string.
    """
    provider = context.config.model.provider
    model_id = get_model_for_role(provider, "fast")
    model_string = get_pydantic_model_string(provider, model_id)

    agent = Agent(
        model_string,
        deps_type=_SpecialistDeps,
        system_prompt=EXECUTION_PROMPT,
        defer_model_check=True,
        retries=3,  # Allow more retries for loop detection ModelRetry
    )

    _register_execution_tools(agent, require_confirmation)

    deps = _SpecialistDeps(
        context=context,
        tracker=tracker,
        confirmation_state=confirmation_state,
        target=target,
    )

    limits = usage_limits or UsageLimits(tool_calls_limit=30)
    prompt = f"Target: {target}\n\nTask: {task}"

    try:
        result = await agent.run(prompt, deps=deps, usage_limits=limits)
        return str(result.output)
    except Exception as e:
        logger.error(f"❌ Execution agent error: {e}")
        return f"Error: {e}"


async def run_security_agent(
    context: SharedContext,
    tracker: ToolCallTracker,
    confirmation_state: ConfirmationState,
    target: str,
    task: str,
    usage_limits: UsageLimits | None = None,
    **_kwargs: Any,
) -> str:
    """
    Run the Security agent.

    Args:
        context: Shared context.
        tracker: Tool call tracker.
        confirmation_state: Confirmation state.
        target: Target host.
        task: Task description.
        usage_limits: Optional usage limits.

    Returns:
        Agent output as string.
    """
    provider = context.config.model.provider
    model_id = get_model_for_role(provider, "reasoning")
    model_string = get_pydantic_model_string(provider, model_id)

    agent = Agent(
        model_string,
        deps_type=_SpecialistDeps,
        system_prompt=SECURITY_PROMPT,
        defer_model_check=True,
        retries=3,  # Allow more retries for loop detection ModelRetry
    )

    _register_security_tools(agent)

    deps = _SpecialistDeps(
        context=context,
        tracker=tracker,
        confirmation_state=confirmation_state,
        target=target,
    )

    limits = usage_limits or UsageLimits(tool_calls_limit=25)
    prompt = f"Target: {target}\n\nTask: {task}"

    try:
        result = await agent.run(prompt, deps=deps, usage_limits=limits)
        return str(result.output)
    except Exception as e:
        logger.error(f"❌ Security agent error: {e}")
        return f"Error: {e}"


async def run_query_agent(
    context: SharedContext,
    tracker: ToolCallTracker,
    confirmation_state: ConfirmationState,
    target: str,
    task: str,
    usage_limits: UsageLimits | None = None,
    **_kwargs: Any,
) -> str:
    """
    Run the Query agent.

    Args:
        context: Shared context.
        tracker: Tool call tracker.
        confirmation_state: Confirmation state.
        target: Target host (unused for query).
        task: Question to answer.
        usage_limits: Optional usage limits.

    Returns:
        Agent output as string.
    """
    _ = target  # Unused for query agent

    provider = context.config.model.provider
    model_id = get_model_for_role(provider, "fast")
    model_string = get_pydantic_model_string(provider, model_id)

    agent = Agent(
        model_string,
        deps_type=_SpecialistDeps,
        system_prompt=QUERY_PROMPT,
        defer_model_check=True,
        retries=3,  # Allow more retries for loop detection ModelRetry
    )

    _register_query_tools(agent)

    deps = _SpecialistDeps(
        context=context,
        tracker=tracker,
        confirmation_state=confirmation_state,
        target="local",
    )

    limits = usage_limits or UsageLimits(tool_calls_limit=15)

    try:
        result = await agent.run(task, deps=deps, usage_limits=limits)
        return str(result.output)
    except Exception as e:
        logger.error(f"❌ Query agent error: {e}")
        return f"Error: {e}"


# Internal deps type for specialists


@dataclass
class _SpecialistDeps:
    """Dependencies for specialist agents."""

    context: SharedContext
    tracker: ToolCallTracker = field(default_factory=ToolCallTracker)
    confirmation_state: ConfirmationState = field(default_factory=ConfirmationState)
    target: str = "local"


def _register_diagnostic_tools(agent: Agent[_SpecialistDeps, str]) -> None:
    """Register diagnostic tools (read-only)."""

    @agent.tool
    async def ssh_execute(
        ctx: RunContext[_SpecialistDeps],
        host: str,
        command: str,
        timeout: int = 60,
        stdin: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute a command on a remote host via SSH (read-only investigation).

        For elevated access (su/sudo), just use the command naturally.
        The system will automatically prompt for password if needed.
        """
        from merlya.tools.core import ssh_execute as _ssh_execute

        # AUTO-ELEVATION: If command needs elevation stdin, collect credentials automatically
        effective_stdin = stdin
        if _needs_elevation_stdin(command) and not stdin:
            logger.debug(f"🔐 Auto-elevation: {command[:40]}... needs credentials")
            effective_stdin = await _auto_collect_elevation_credentials(
                ctx.deps.context, host, command
            )
            if not effective_stdin:
                # User cancelled or error - return without executing
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": "Credentials required but not provided",
                    "exit_code": -1,
                    "error": "User cancelled credential prompt",
                }

        # Check for loop BEFORE recording (prevents executing duplicate commands)
        would_loop, reason = ctx.deps.tracker.would_loop(host, command)
        if would_loop:
            raise ModelRetry(f"{reason}. Try a DIFFERENT command or approach.")

        # Only record after passing the check
        ctx.deps.tracker.record(host, command)

        result = await _ssh_execute(ctx.deps.context, host, command, timeout, stdin=effective_stdin)

        response = {
            "success": result.success,
            "stdout": result.data.get("stdout", "") if result.data else "",
            "stderr": result.data.get("stderr", "") if result.data else "",
            "exit_code": result.data.get("exit_code", -1) if result.data else -1,
        }
        # Include hint if present (for permission denied guidance)
        if result.data and result.data.get("hint"):
            response["hint"] = result.data["hint"]
        if result.error:
            response["error"] = result.error
        return response

    @agent.tool
    async def bash(
        ctx: RunContext[_SpecialistDeps],
        command: str,
        timeout: int = 60,
    ) -> dict[str, Any]:
        """Execute a local command (kubectl, docker, aws, etc.)."""
        from merlya.tools.core import bash_execute as _bash_execute

        # Check for loop BEFORE recording
        would_loop, reason = ctx.deps.tracker.would_loop("local", command)
        if would_loop:
            raise ModelRetry(f"{reason}. Try a DIFFERENT command or approach.")

        ctx.deps.tracker.record("local", command)

        result = await _bash_execute(ctx.deps.context, command, timeout)
        return {
            "success": result.success,
            "stdout": result.data.get("stdout", "") if result.data else "",
            "stderr": result.data.get("stderr", "") if result.data else "",
            "exit_code": result.data.get("exit_code", -1) if result.data else -1,
        }

    @agent.tool
    async def read_file(
        ctx: RunContext[_SpecialistDeps],
        host: str,
        path: str,
    ) -> dict[str, Any]:
        """Read a file from a remote host."""
        from merlya.tools.core import ssh_execute as _ssh_execute

        # SECURITY: Escape the path to prevent command injection
        # Use shlex.quote to safely escape shell metacharacters
        quoted_path = shlex.quote(path)
        command = f"cat -- {quoted_path}"
        result = await _ssh_execute(ctx.deps.context, host, command, timeout=30)
        return {
            "success": result.success,
            "content": result.data.get("stdout", "") if result.data else "",
            "error": result.data.get("stderr", "") if result.data else "",
        }


def _register_execution_tools(
    agent: Agent[_SpecialistDeps, str],
    require_confirmation: bool = True,
) -> None:
    """Register execution tools (with confirmation)."""

    @agent.tool
    async def ssh_execute(
        ctx: RunContext[_SpecialistDeps],
        host: str,
        command: str,
        timeout: int = 60,
        stdin: str | None = None,
    ) -> dict[str, Any]:
        """Execute a command on a remote host via SSH."""
        from merlya.tools.core import ssh_execute as _ssh_execute

        # Confirmation for external commands (before auto-elevation prompt)
        if require_confirmation and not ctx.deps.confirmation_state.should_skip(command):
            ui = ctx.deps.context.ui
            confirm_result = await confirm_command(
                ui=ui,
                command=command,
                target=host,
                state=ctx.deps.confirmation_state,
            )
            if confirm_result == ConfirmationResult.CANCEL:
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": "Cancelled by user",
                    "exit_code": -1,
                }

        # AUTO-ELEVATION: If command needs elevation stdin, collect credentials automatically
        effective_stdin = stdin
        if _needs_elevation_stdin(command) and not stdin:
            logger.debug(f"🔐 Auto-elevation: {command[:40]}... needs credentials")
            effective_stdin = await _auto_collect_elevation_credentials(
                ctx.deps.context, host, command
            )
            if not effective_stdin:
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": "Credentials required but not provided",
                    "exit_code": -1,
                    "error": "User cancelled credential prompt",
                }

        # Check for loop BEFORE recording
        would_loop, reason = ctx.deps.tracker.would_loop(host, command)
        if would_loop:
            raise ModelRetry(f"{reason}. Try a DIFFERENT command or approach.")

        ctx.deps.tracker.record(host, command)

        exec_result = await _ssh_execute(
            ctx.deps.context, host, command, timeout, stdin=effective_stdin
        )

        return {
            "success": exec_result.success,
            "stdout": exec_result.data.get("stdout", "") if exec_result.data else "",
            "stderr": exec_result.data.get("stderr", "") if exec_result.data else "",
            "exit_code": exec_result.data.get("exit_code", -1) if exec_result.data else -1,
        }

    @agent.tool
    async def bash(
        ctx: RunContext[_SpecialistDeps],
        command: str,
        timeout: int = 60,
    ) -> dict[str, Any]:
        """Execute a local command (kubectl, docker, aws, etc.)."""
        from merlya.tools.core import bash_execute as _bash_execute

        # Check for loop BEFORE confirmation (don't ask user for duplicate commands)
        would_loop, reason = ctx.deps.tracker.would_loop("local", command)
        if would_loop:
            raise ModelRetry(f"{reason}. Try a DIFFERENT command or approach.")

        # Confirmation for external commands
        if require_confirmation and not ctx.deps.confirmation_state.should_skip(command):
            ui = ctx.deps.context.ui
            confirm_result = await confirm_command(
                ui=ui,
                command=command,
                target="local",
                state=ctx.deps.confirmation_state,
            )
            if confirm_result == ConfirmationResult.CANCEL:
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": "Cancelled by user",
                    "exit_code": -1,
                }

        ctx.deps.tracker.record("local", command)

        exec_result = await _bash_execute(ctx.deps.context, command, timeout)
        return {
            "success": exec_result.success,
            "stdout": exec_result.data.get("stdout", "") if exec_result.data else "",
            "stderr": exec_result.data.get("stderr", "") if exec_result.data else "",
            "exit_code": exec_result.data.get("exit_code", -1) if exec_result.data else -1,
        }


def _register_security_tools(agent: Agent[_SpecialistDeps, str]) -> None:
    """Register security tools."""

    @agent.tool
    async def ssh_execute(
        ctx: RunContext[_SpecialistDeps],
        host: str,
        command: str,
        timeout: int = 60,
        stdin: str | None = None,
    ) -> dict[str, Any]:
        """Execute a security command on a remote host."""
        from merlya.tools.core import ssh_execute as _ssh_execute

        # AUTO-ELEVATION: If command needs elevation stdin, collect credentials automatically
        effective_stdin = stdin
        if _needs_elevation_stdin(command) and not stdin:
            logger.debug(f"🔐 Auto-elevation: {command[:40]}... needs credentials")
            effective_stdin = await _auto_collect_elevation_credentials(
                ctx.deps.context, host, command
            )
            if not effective_stdin:
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": "Credentials required but not provided",
                    "exit_code": -1,
                    "error": "User cancelled credential prompt",
                }

        # Check for loop BEFORE recording
        would_loop, reason = ctx.deps.tracker.would_loop(host, command)
        if would_loop:
            raise ModelRetry(f"{reason}. Try a DIFFERENT command or approach.")

        ctx.deps.tracker.record(host, command)

        result = await _ssh_execute(ctx.deps.context, host, command, timeout, stdin=effective_stdin)

        return {
            "success": result.success,
            "stdout": result.data.get("stdout", "") if result.data else "",
            "stderr": result.data.get("stderr", "") if result.data else "",
            "exit_code": result.data.get("exit_code", -1) if result.data else -1,
        }

    @agent.tool
    async def bash(
        ctx: RunContext[_SpecialistDeps],
        command: str,
        timeout: int = 60,
    ) -> dict[str, Any]:
        """Execute a local security command."""
        from merlya.tools.core import bash_execute as _bash_execute

        # Check for loop BEFORE recording
        would_loop, reason = ctx.deps.tracker.would_loop("local", command)
        if would_loop:
            raise ModelRetry(f"{reason}. Try a DIFFERENT command or approach.")

        ctx.deps.tracker.record("local", command)

        result = await _bash_execute(ctx.deps.context, command, timeout)
        return {
            "success": result.success,
            "stdout": result.data.get("stdout", "") if result.data else "",
            "stderr": result.data.get("stderr", "") if result.data else "",
            "exit_code": result.data.get("exit_code", -1) if result.data else -1,
        }

    @agent.tool
    async def scan_host(
        ctx: RunContext[_SpecialistDeps],
        host: str,
        scan_type: str = "security",
    ) -> dict[str, Any]:
        """Run a security scan on a host."""
        from merlya.commands.handlers.scan_format import ScanOptions
        from merlya.commands.handlers.system import _scan_hosts_parallel

        try:
            opts = ScanOptions(scan_type=scan_type)
            result = await _scan_hosts_parallel(
                ctx.deps.context,
                [host],
                opts,
            )
            return {
                "success": result.success,
                "message": result.message,
                "data": result.data,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


def _register_query_tools(agent: Agent[_SpecialistDeps, str]) -> None:
    """Register query tools (inventory only, no SSH)."""

    @agent.tool
    async def list_hosts(
        ctx: RunContext[_SpecialistDeps],
        tag: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List hosts from inventory."""
        from merlya.tools.core import list_hosts as _list_hosts

        result = await _list_hosts(ctx.deps.context, tag=tag, limit=limit)
        if result.success:
            return {"hosts": result.data, "count": len(result.data)}
        return {"hosts": [], "count": 0, "error": result.error}

    @agent.tool
    async def get_host(
        ctx: RunContext[_SpecialistDeps],
        name: str,
    ) -> dict[str, Any]:
        """Get details about a specific host."""
        from merlya.tools.core import get_host as _get_host

        result = await _get_host(ctx.deps.context, name)
        if result.success:
            return cast("dict[str, Any]", result.data)
        raise ModelRetry(f"Host not found: {result.error}")

    @agent.tool
    async def ask_user(
        ctx: RunContext[_SpecialistDeps],
        question: str,
        choices: list[str] | None = None,
    ) -> str:
        """Ask the user a question."""
        from merlya.tools.core import ask_user as _ask_user

        result = await _ask_user(ctx.deps.context, question, choices=choices)
        if result.success:
            return cast("str", result.data) or ""
        return ""
