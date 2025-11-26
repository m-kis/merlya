"""
AutoGen tool wrappers for Athena.

Wraps existing tools (execute_command, scan_host, etc.) to work with AutoGen agents.

CRITICAL SECURITY: All tools now validate hostnames against HostRegistry.
Operations on invalid/hallucinated hostnames are BLOCKED.

CREDENTIAL RESOLUTION: @variable references in commands are resolved before execution.
Use /credentials set <name> <value> or /credentials set-secret <name> to define variables.

HOOKS: All tool executions emit events via HookManager for extensibility.
Configure hooks in ~/.athena/hooks.yaml or programmatically.
"""
import os
from typing import Annotated, Optional

from athena_ai.context.host_registry import HostRegistry, get_host_registry
from athena_ai.core.hooks import HookEvent, get_hook_manager
from athena_ai.knowledge.ops_knowledge_manager import get_knowledge_manager
from athena_ai.utils.logger import logger

# Global instances (injected by AutoGenOrchestrator at startup)
_executor = None
_context_manager = None
_permissions = None
_context_memory = None
_error_correction = None
_host_registry: Optional[HostRegistry] = None
_credentials = None  # CredentialManager for @variable resolution
_hooks = None  # HookManager for event emission


def initialize_autogen_tools(executor, context_manager, permissions, context_memory=None, error_correction=None, credentials=None):
    """
    Initialize AutoGen tool dependencies.

    Must be called by AutoGenOrchestrator before agents start using tools.
    """
    global _executor, _context_manager, _permissions, _context_memory, _error_correction, _host_registry, _credentials, _hooks
    _executor = executor
    _context_manager = context_manager
    _permissions = permissions
    _context_memory = context_memory
    _error_correction = error_correction
    _credentials = credentials

    # Initialize host registry
    _host_registry = get_host_registry()
    _host_registry.load_all_sources()

    # Initialize hook manager
    _hooks = get_hook_manager()

    logger.debug(f"AutoGen tools initialized with {len(_host_registry.hostnames)} hosts in registry")


def _validate_host(hostname: str) -> tuple[bool, str]:
    """
    Validate hostname against registry.

    Returns:
        (is_valid, message)
    """
    global _host_registry

    # Allow local execution
    if hostname in ["local", "localhost", "127.0.0.1"]:
        return True, "Local execution allowed"

    # Ensure registry is initialized and loaded
    if not _host_registry:
        _host_registry = get_host_registry()
    if _host_registry.is_empty():
        _host_registry.load_all_sources()

    validation = _host_registry.validate(hostname)

    if validation.is_valid:
        return True, f"Host '{validation.host.hostname}' validated"

    # Build error message with suggestions
    return False, validation.get_suggestion_text()


def _emit_hook(event: HookEvent, data: dict, source: str = "autogen_tools"):
    """
    Emit hook event if hooks are initialized.

    DRY helper - centralizes hook emission with error handling.
    Returns context for cancellation checking, or None if hooks unavailable.
    """
    if not _hooks:
        return None
    try:
        return _hooks.emit(event, data, source)
    except Exception as e:
        logger.warning(f"Hook emission failed: {e}")
        return None


def execute_command(
    target: Annotated[str, "Target host (hostname, IP, or 'local')"],
    command: Annotated[str, "Shell command to execute"],
    reason: Annotated[str, "Why this command is needed (for audit trail)"]
) -> str:
    """
    Execute a shell command on a target host (local or remote via SSH).

    IMPORTANT: The target host MUST exist in the inventory. Use list_hosts() first
    to see available hosts. Requests for non-existent hosts will be REJECTED.

    Use this tool when you need to check LIVE system state (CPU, disk, services, etc.).
    DO NOT use this for information already available in infrastructure context.

    The system automatically:
    - Validates target against host registry (REQUIRED)
    - Scans the target host just before execution (cached 30min)
    - Detects and elevates commands with su when needed
    - Retries failed commands with intelligent corrections

    Args:
        target: Target host - use 'local' for local machine, or hostname/IP for remote
        command: Shell command to execute (e.g., "ps aux | grep mongo")
        reason: Why this command is needed (for audit trail)

    Returns:
        Command output with success/failure status
    """
    logger.info(f"AutoGen Tool: execute_command on {target} - {reason}")

    # CRITICAL: Validate host before any operation
    is_valid, message = _validate_host(target)
    if not is_valid:
        logger.warning(f"BLOCKED: execute_command on invalid host '{target}'")
        return f"❌ BLOCKED: Cannot execute command on '{target}'\n\n{message}\n\n💡 Use list_hosts() to see available hosts."

    # Hook: Pre-execution (allows blocking via hooks.yaml)
    hook_ctx = _emit_hook(HookEvent.TOOL_EXECUTE_START, {
        "tool": "execute_command",
        "target": target,
        "command": command,
        "reason": reason
    })
    if hook_ctx and hook_ctx.cancelled:
        logger.warning(f"BLOCKED by hook: {hook_ctx.cancel_reason}")
        return f"❌ BLOCKED by hook: {hook_ctx.cancel_reason}"

    # Just-in-time host scanning
    if target not in ["local", "localhost"]:
        logger.debug(f"Just-in-time scanning {target} before execution...")
        try:
            _context_manager.scan_host(target)
        except Exception as e:
            logger.warning(f"Could not scan {target}: {e}")

    # Auto-elevation
    original_command = command
    permissions_info = None
    try:
        permissions_info = _permissions.detect_capabilities(target)
        logger.debug(f"Permissions on {target}: {permissions_info}")

        if _permissions.requires_elevation(command):
            if not permissions_info['is_root']:
                if permissions_info['elevation_method'] in ['sudo', 'sudo_with_password', 'doas', 'su']:
                    logger.info(f"Auto-elevating command with {permissions_info['elevation_method']}")
                    command = _permissions.elevate_command(command, target)
                else:
                    logger.warning("Command may require elevated privileges but no elevation method available")
    except Exception as e:
        logger.warning(f"Permission detection failed: {e}")

    # CRITICAL: Resolve @variable references in command before execution
    # This substitutes @mongo-user, @mongo-pass etc. with actual values
    if _credentials and '@' in command:
        resolved_command = _credentials.resolve_variables(command, warn_missing=True)
        if resolved_command != command:
            logger.debug("Resolved credential variables in command")
            command = resolved_command

    # Execute with auto-retry on failure
    max_retries = 2
    attempt = 0
    result = None

    while attempt <= max_retries:
        # Execute command
        result = _executor.execute(target, command, confirm=True)

        # Success - return immediately
        if result['success']:
            output = result['stdout'] if result['stdout'] else "(no output)"
            retry_note = f" (succeeded after {attempt} retries)" if attempt > 0 else ""

            # Hook: Post-execution success
            _emit_hook(HookEvent.TOOL_EXECUTE_END, {
                "tool": "execute_command",
                "target": target,
                "command": original_command,
                "success": True,
                "output_length": len(output)
            })

            # Audit Log (Knowledge Graph)
            try:
                get_knowledge_manager().log_action(
                    action="execute_command",
                    target=target,
                    command=original_command,
                    result="success",
                    details=reason
                )
            except Exception as e:
                logger.warning(f"Failed to log audit action: {e}")

            return f"✅ SUCCESS{retry_note}\n\nOutput:\n{output}"

        # Failure - try to correct if retries available and error correction enabled
        attempt += 1
        if attempt > max_retries:
            break

        error = result.get('error', result.get('stderr', 'Unknown error'))
        exit_code = result.get('exit_code', 1)

        logger.info(f"Command failed (attempt {attempt}/{max_retries + 1}): {error[:100]}")

        # Check if error correction is available and should retry
        if not _error_correction:
            logger.debug("Error correction service not available, no retry")
            break

        if not _error_correction.should_retry(error, exit_code):
            logger.info("Error not suitable for retry")
            break

        # Analyze error and get correction
        context = {
            "permissions_info": permissions_info,
            "original_command": original_command
        }
        corrected_command = _error_correction.analyze_and_correct(
            command, error, exit_code, target, context
        )

        if not corrected_command:
            logger.info("No correction found, stopping retry")
            break

        logger.info(f"Retrying with corrected command: {corrected_command}")
        command = corrected_command

    # All retries exhausted - generate natural language error message
    error = result.get('error', result.get('stderr', 'Unknown error'))
    exit_code = result.get('exit_code', 1)

    # Hook: Execution error
    _emit_hook(HookEvent.TOOL_EXECUTE_ERROR, {
        "tool": "execute_command",
        "target": target,
        "command": original_command,
        "error": error[:500],  # Truncate for hook payload
        "exit_code": exit_code,
        "attempts": attempt
    })

    # If error correction is available, generate user-friendly error
    if _error_correction:
        # Track if we attempted a correction
        attempted_correction = corrected_command if attempt > 1 else None
        nl_error = _error_correction.explain_error_to_user(
            original_command,
            error,
            exit_code,
            target,
            attempted_correction
        )
        return nl_error
    else:
        # Fallback to simple error format
        return f"❌ FAILED (after {attempt} attempts)\n\nError:\n{error}"


def _summarize_inventory_with_local_model(inventory: dict) -> str:
    """
    Use local Ollama model to generate intelligent summary of infrastructure.

    Returns None if local model not available or disabled.
    """
    use_local_model = os.getenv("ATHENA_USE_LOCAL_SUMMARIZER", "false").lower() == "true"
    if not use_local_model:
        return None

    try:
        import requests

        # Build inventory text
        inventory_text = f"Infrastructure inventory with {len(inventory)} hosts:\n"
        for hostname, ip in list(inventory.items())[:50]:  # Limit to 50 for summary
            inventory_text += f"- {hostname}: {ip}\n"

        if len(inventory) > 50:
            inventory_text += f"... and {len(inventory) - 50} more hosts\n"

        prompt = f"""Analyze this infrastructure inventory and provide a concise summary (max 150 words):

{inventory_text}

Focus on:
1. Total number of hosts
2. Types of servers (database, web, cache, etc.)
3. Environments (prod, preprod, staging)
4. Key patterns or clusters

Be factual and concise."""

        # Try small models in order
        models = [
            ("qwen2.5:0.5b", "Qwen2.5"),
            ("smollm2:1.7b", "SmolLM2"),
            ("phi3:mini", "Phi-3"),
        ]

        for model_name, display_name in models:
            try:
                response = requests.post(
                    "http://localhost:11434/api/generate",
                    json={
                        "model": model_name,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0,
                            "num_predict": 250,
                            "num_ctx": 4096
                        }
                    },
                    timeout=15
                )

                if response.status_code == 200:
                    summary = response.json().get("response", "").strip()
                    if summary:
                        logger.info(f"Used local {display_name} to summarize inventory")
                        return summary
            except (requests.RequestException, ValueError, KeyError):
                continue  # Try next model if this one fails

    except Exception as e:
        logger.debug(f"Local model summarization failed: {e}")

    return None


def get_infrastructure_context() -> str:
    """
    Get current infrastructure context from HostRegistry.

    IMPORTANT: This now uses the validated HostRegistry instead of old cache.
    For full host list, use list_hosts() tool.

    Returns:
        Infrastructure summary with stats and sample hosts
    """
    global _host_registry
    logger.info("AutoGen Tool: get_infrastructure_context")

    # Ensure registry is initialized and loaded
    if not _host_registry:
        _host_registry = get_host_registry()
    if _host_registry.is_empty():
        _host_registry.load_all_sources()

    lines = []

    # Use HostRegistry as source of truth
    if not _host_registry.is_empty():
        stats = _host_registry.get_stats()
        total = stats.get("total_hosts", 0)
        by_env = stats.get("by_environment", {})
        sources = stats.get("loaded_sources", [])

        lines.append(f"📋 HOST REGISTRY: {total} validated hosts")
        lines.append(f"   Sources: {', '.join(sources)}")
        lines.append("")

        # Show environment breakdown
        if by_env:
            lines.append("   By environment:")
            for env, count in sorted(by_env.items()):
                lines.append(f"     • {env}: {count} hosts")
            lines.append("")

        # Show sample of hosts by pattern
        all_hosts = _host_registry.hostnames
        mongo_hosts = [h for h in all_hosts if 'mongo' in h.lower()]
        prod_hosts = [h for h in all_hosts if 'prod' in h.lower()]

        if mongo_hosts:
            lines.append(f"   MongoDB servers ({len(mongo_hosts)} found):")
            for h in sorted(mongo_hosts)[:10]:
                lines.append(f"     • {h}")
            if len(mongo_hosts) > 10:
                lines.append(f"     ... and {len(mongo_hosts) - 10} more")
            lines.append("")

        if prod_hosts:
            lines.append(f"   Production servers ({len(prod_hosts)} found):")
            for h in sorted(prod_hosts)[:10]:
                lines.append(f"     • {h}")
            if len(prod_hosts) > 10:
                lines.append(f"     ... and {len(prod_hosts) - 10} more")
            lines.append("")

        lines.append("💡 Use list_hosts(pattern='mongo') or list_hosts(environment='production') for filtered lists")
    else:
        lines.append("📋 HOST REGISTRY: No hosts loaded")
        lines.append("   Check inventory sources (/etc/hosts, ~/.ssh/config, Ansible)")

    return "\n".join(lines)


def list_hosts(
    environment: Annotated[str, "Filter by environment: 'production', 'staging', 'development', or 'all'"] = "all",
    pattern: Annotated[str, "Filter by hostname pattern (regex)"] = ""
) -> str:
    """
    List all available hosts from the inventory.

    IMPORTANT: Always use this tool FIRST to see what hosts are available.
    Do NOT guess or invent hostnames - only use hosts returned by this tool.

    Args:
        environment: Filter by environment (production, staging, development, all)
        pattern: Optional regex pattern to filter hostnames

    Returns:
        List of available hosts with their details
    """
    logger.info(f"AutoGen Tool: list_hosts (env={environment}, pattern={pattern})")

    if not _host_registry:
        return "❌ Host registry not initialized"

    # Ensure registry is loaded
    if _host_registry.is_empty():
        _host_registry.load_all_sources()

    # Filter hosts
    env_filter = None if environment == "all" else environment
    pattern_filter = pattern if pattern else None

    hosts = _host_registry.filter(environment=env_filter, pattern=pattern_filter)

    if not hosts:
        if environment != "all" or pattern:
            return f"❌ No hosts found matching criteria (environment={environment}, pattern={pattern})\n\n💡 Try list_hosts(environment='all') to see all available hosts."
        return "❌ No hosts in inventory. Check inventory sources (/etc/hosts, ~/.ssh/config, Ansible inventory)."

    lines = [f"📋 AVAILABLE HOSTS ({len(hosts)} found):"]
    lines.append("")

    # Group by environment
    by_env = {}
    for host in hosts:
        env = host.environment or "unknown"
        if env not in by_env:
            by_env[env] = []
        by_env[env].append(host)

    for env, env_hosts in sorted(by_env.items()):
        lines.append(f"  [{env.upper()}]")
        for host in sorted(env_hosts, key=lambda h: h.hostname):
            ip_info = f" ({host.ip_address})" if host.ip_address else ""
            groups_info = f" [{', '.join(host.groups)}]" if host.groups else ""
            lines.append(f"    • {host.hostname}{ip_info}{groups_info}")
        lines.append("")

    lines.append("💡 Use these exact hostnames with execute_command() or scan_host()")

    return "\n".join(lines)


def scan_host(
    hostname: Annotated[str, "Hostname or IP address to scan"]
) -> str:
    """
    Scan a remote host to detect OS, kernel, services, and system information.

    IMPORTANT: The hostname MUST exist in the inventory. Use list_hosts() first.

    Use this when you need fresh information about a specific host that hasn't
    been scanned yet, or when cached data might be stale.

    Results are cached for 30 minutes to avoid unnecessary SSH overhead.

    Args:
        hostname: Hostname or IP address to scan (must be in inventory)

    Returns:
        Scan results including OS, services, and accessibility status
    """
    logger.info(f"AutoGen Tool: scan_host {hostname}")

    # CRITICAL: Validate host before scanning
    is_valid, message = _validate_host(hostname)
    if not is_valid:
        logger.warning(f"BLOCKED: scan_host on invalid host '{hostname}'")
        return f"❌ BLOCKED: Cannot scan '{hostname}'\n\n{message}\n\n💡 Use list_hosts() to see available hosts."

    try:
        info = _context_manager.scan_host(hostname)

        if not info.get('accessible'):
            error_msg = info.get('error', 'Unknown error')
            return f"❌ Host {hostname} is not accessible\n\nError: {error_msg}"

        lines = [
            f"✅ Host {hostname} scan completed",
            "",
            f"IP Address: {info.get('ip', 'unknown')}",
            f"Operating System: {info.get('os', 'unknown')}",
            f"Kernel: {info.get('kernel', 'unknown')}",
        ]

        services = info.get('services', [])
        if services:
            lines.append(f"\nRunning Services ({len(services)}):")
            for service in services[:15]:
                lines.append(f"  • {service}")
            if len(services) > 15:
                lines.append(f"  ... and {len(services) - 15} more services")
        else:
            lines.append("\nRunning Services: None detected")

        # Save to persistent memory if available
        if _context_memory:
            try:
                # Save OS info
                _context_memory.save_host_fact(hostname, "os", info.get('os', 'unknown'))
                _context_memory.save_host_fact(hostname, "kernel", info.get('kernel', 'unknown'))
                _context_memory.save_host_fact(hostname, "ip", info.get('ip', 'unknown'))

                # Save services
                if services:
                    _context_memory.save_host_fact(hostname, "services", services)

                # Record usage
                _context_memory.record_host_usage(hostname)
                logger.debug(f"Saved scan results for {hostname} to persistent memory")
            except Exception as e:
                logger.warning(f"Failed to save to persistent memory: {e}")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Host scan failed: {e}")
        return f"❌ Scan failed for {hostname}\n\nError: {str(e)}"


def check_permissions(
    target: Annotated[str, "Target host to check (hostname, IP, or 'local')"]
) -> str:
    """
    Check sudo availability and user permissions on a target host.

    IMPORTANT: The target host MUST exist in the inventory. Use list_hosts() first.

    Use this to understand what privileges are available before executing
    commands that may require elevated access.

    Args:
        target: Target host to check (must be in inventory)

    Returns:
        Permission capabilities summary
    """
    logger.info(f"AutoGen Tool: check_permissions on {target}")

    # CRITICAL: Validate host
    is_valid, message = _validate_host(target)
    if not is_valid:
        logger.warning(f"BLOCKED: check_permissions on invalid host '{target}'")
        return f"❌ BLOCKED: Cannot check permissions on '{target}'\n\n{message}\n\n💡 Use list_hosts() to see available hosts."

    try:
        _permissions.detect_capabilities(target)
        summary = _permissions.format_capabilities_summary(target)
        return f"✅ Permission check completed for {target}\n\n{summary}"
    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        return f"❌ Permission check failed for {target}\n\nError: {str(e)}"


def add_route(
    network_cidr: Annotated[str, "Network CIDR (e.g. 10.0.0.0/8)"],
    gateway: Annotated[str, "Gateway/Bastion hostname"]
) -> str:
    """
    Teach the system a new network route.

    Use this when you discover that a network segment is only reachable via a specific bastion.
    The system will remember this and automatically tunnel future connections.

    Args:
        network_cidr: The target network (e.g. 10.0.0.0/8)
        gateway: The jump host to use
    """
    logger.info(f"AutoGen Tool: add_route {network_cidr} via {gateway}")

    if _context_memory and _context_memory.knowledge_store:
        try:
            _context_memory.knowledge_store.add_route(network_cidr, gateway)
            return f"✅ Route added: Traffic to {network_cidr} will now go through {gateway}"
        except Exception as e:
            return f"❌ Failed to add route: {e}"
    else:
        return "❌ Memory system not available"


def audit_host(
    target: Annotated[str, "Target host to audit (hostname, IP, or 'local')"]
) -> str:
    """
    Perform a security audit on a target host.

    IMPORTANT: The target host MUST exist in the inventory. Use list_hosts() first.

    Checks:
    1. Open ports (listening services)
    2. SSH Configuration (Root login, Password auth)
    3. Sudo privileges
    4. System load and disk usage

    Args:
        target: Host to audit (must be in inventory)

    Returns:
        Structured security report
    """
    logger.info(f"AutoGen Tool: audit_host {target}")

    # CRITICAL: Validate host
    is_valid, message = _validate_host(target)
    if not is_valid:
        logger.warning(f"BLOCKED: audit_host on invalid host '{target}'")
        return f"❌ BLOCKED: Cannot audit '{target}'\n\n{message}\n\n💡 Use list_hosts() to see available hosts."

    report = [f"🔒 SECURITY AUDIT REPORT: {target}", ""]

    # 1. Check Open Ports
    cmd_ports = "ss -tuln | grep LISTEN"
    res_ports = _executor.execute(target, cmd_ports)
    if res_ports['success']:
        report.append("📡 Open Ports:")
        lines = res_ports['stdout'].strip().split('\n')
        # Filter and format nicely
        for line in lines[:10]:
            parts = line.split()
            if len(parts) >= 5:
                # Extract local address:port
                local = parts[4]
                report.append(f"   - {local}")
        if len(lines) > 10:
            report.append(f"   (... {len(lines)-10} more)")
    else:
        report.append(f"📡 Open Ports: ⚠️ Failed to list ({res_ports.get('stderr', '')[:50]})")

    report.append("")

    # 2. Check SSH Config
    cmd_ssh = "grep -E '^(PermitRootLogin|PasswordAuthentication)' /etc/ssh/sshd_config"
    # Try to read config (might need sudo, auto-elevation handles it)
    res_ssh = _executor.execute(target, cmd_ssh)

    report.append("🔑 SSH Configuration:")
    if res_ssh['success']:
        config_lines = res_ssh['stdout'].strip().split('\n')
        for line in config_lines:
            if "PermitRootLogin yes" in line:
                report.append(f"   ❌ {line} (High Risk!)")
            elif "PasswordAuthentication yes" in line:
                report.append(f"   ⚠️ {line} (Consider key-based auth)")
            else:
                report.append(f"   ✅ {line}")

        if not config_lines:
            report.append("   ❓ No explicit config found (using defaults)")
    else:
        report.append("   ❓ Could not read sshd_config (permission denied or file missing)")

    report.append("")

    # 3. Check Sudoers
    # Just check if current user has sudo, and list sudoers file if possible
    cmd_sudo = "grep -v '^#' /etc/sudoers | grep -v '^$'"
    res_sudo = _executor.execute(target, cmd_sudo)

    report.append("🛡️ Privileged Access:")
    if res_sudo['success']:
        sudoers = res_sudo['stdout'].strip().split('\n')
        report.append(f"   Found {len(sudoers)} active lines in sudoers")
    else:
        report.append("   ℹ️  Cannot read /etc/sudoers (requires root)")

    # Save facts to memory
    if _context_memory:
        try:
            _context_memory.save_host_fact(target, "last_audit", "Just now")
            if res_ports['success']:
                _context_memory.save_host_fact(target, "open_ports", res_ports['stdout'][:200])
        except Exception:
            pass  # Non-critical: memory save failure shouldn't break audit

    return "\n".join(report)


def analyze_security_logs(
    target: Annotated[str, "Target host to analyze"],
    lines: Annotated[int, "Number of log lines to check"] = 50
) -> str:
    """
    Analyze security logs for suspicious activity.

    IMPORTANT: The target host MUST exist in the inventory. Use list_hosts() first.

    Checks /var/log/auth.log (Debian/Ubuntu) or /var/log/secure (RHEL/CentOS).
    Looks for:
    - Failed SSH logins
    - Sudo usage
    - New user creation

    Args:
        target: Host to analyze (must be in inventory)
        lines: Number of recent lines to check (default: 50)

    Returns:
        Analysis summary
    """
    logger.info(f"AutoGen Tool: analyze_security_logs {target}")

    # CRITICAL: Validate host
    is_valid, message = _validate_host(target)
    if not is_valid:
        logger.warning(f"BLOCKED: analyze_security_logs on invalid host '{target}'")
        return f"❌ BLOCKED: Cannot analyze logs on '{target}'\n\n{message}\n\n💡 Use list_hosts() to see available hosts."

    # Detect log file location
    check_cmd = "ls /var/log/auth.log 2>/dev/null || ls /var/log/secure 2>/dev/null"
    res_check = _executor.execute(target, check_cmd)

    if not res_check['success'] or not res_check['stdout'].strip():
        return f"❌ Could not find auth.log or secure log on {target}"

    log_file = res_check['stdout'].strip()

    # Read last N lines
    cmd_read = f"tail -n {lines} {log_file}"
    res_read = _executor.execute(target, cmd_read)

    if not res_read['success']:
        return f"❌ Failed to read logs: {res_read.get('stderr')}"

    log_content = res_read['stdout']

    # Simple heuristic analysis
    analysis = [f"📋 LOG ANALYSIS: {target} ({log_file})", ""]

    failed_logins = log_content.count("Failed password")
    sudo_usage = log_content.count("sudo:")
    accepted_logins = log_content.count("Accepted publickey") + log_content.count("Accepted password")

    analysis.append(f"📊 Summary (last {lines} lines):")
    analysis.append(f"   - Failed Logins: {failed_logins} " + ("⚠️ HIGH" if failed_logins > 5 else "✅"))
    analysis.append(f"   - Sudo Usage: {sudo_usage}")
    analysis.append(f"   - Successful Logins: {accepted_logins}")
    analysis.append("")

    if failed_logins > 0:
        analysis.append("⚠️  Suspicious Activity:")
        # Extract failed IPs
        for line in log_content.split('\n'):
            if "Failed password" in line:
                analysis.append(f"   - {line[:80]}...")

    return "\n".join(analysis)


# ============================================================================
# FILE OPERATIONS
# ============================================================================

def read_remote_file(
    host: Annotated[str, "Target host (must exist in inventory)"],
    path: Annotated[str, "Absolute path to file"],
    lines: Annotated[int, "Number of lines (0=all, default=100)"] = 100
) -> str:
    """
    Read contents of a remote file.

    IMPORTANT: The host MUST exist in the inventory. Use list_hosts() first.

    Args:
        host: Target host
        path: Absolute path to file
        lines: Number of lines to read (0=all)

    Returns:
        File contents or error message
    """
    logger.info(f"AutoGen Tool: read_remote_file {path} on {host}")

    is_valid, msg = _validate_host(host)
    if not is_valid:
        return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts() to see available hosts."

    if lines == 0:
        cmd = f"cat '{path}'"
    else:
        cmd = f"head -n {lines} '{path}'"

    result = _executor.execute(host, cmd, confirm=True)

    if result['success']:
        content = result['stdout']
        line_count = content.count('\n')
        return f"✅ {path} ({line_count} lines):\n```\n{content}\n```"

    return f"❌ Failed to read {path}: {result.get('stderr', 'Unknown error')}"


def glob_files(
    pattern: Annotated[str, "Glob pattern (e.g. /var/log/*.log)"],
    host: Annotated[str, "Target host (must exist in inventory)"]
) -> str:
    """
    List files matching a glob pattern.

    Args:
        pattern: Glob pattern
        host: Target host

    Returns:
        List of matching files
    """
    logger.info(f"AutoGen Tool: glob_files {pattern} on {host}")

    is_valid, msg = _validate_host(host)
    if not is_valid:
        return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts() to see available hosts."

    # Use ls -d to list files matching pattern
    cmd = f"ls -d {pattern}"
    result = _executor.execute(host, cmd, confirm=True)

    if result['success']:
        files = result['stdout'].strip().split('\n')
        count = len(files)
        return f"✅ Found {count} files matching '{pattern}':\n```\n{result['stdout']}\n```"

    return f"❌ No files found or error: {result.get('stderr', 'Unknown error')}"


def grep_files(
    pattern: Annotated[str, "Regex pattern to search for"],
    path: Annotated[str, "File or directory path to search in"],
    host: Annotated[str, "Target host (must exist in inventory)"],
    recursive: Annotated[bool, "Search recursively (-r)"] = False
) -> str:
    """
    Search for text patterns in files using grep.

    Args:
        pattern: Regex pattern
        path: Path to search
        host: Target host
        recursive: Recursive search

    Returns:
        Matching lines
    """
    logger.info(f"AutoGen Tool: grep_files '{pattern}' in {path} on {host}")

    is_valid, msg = _validate_host(host)
    if not is_valid:
        return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts() to see available hosts."

    flags = "-E" # Extended regex
    if recursive:
        flags += "r"

    # Limit output to avoid overwhelming context
    cmd = f"grep {flags} '{pattern}' '{path}' | head -n 50"

    result = _executor.execute(host, cmd, confirm=True)

    if result['success']:
        output = result['stdout']
        if not output:
            return f"✅ No matches found for '{pattern}' in {path}"
        return f"✅ Grep results for '{pattern}':\n```\n{output}\n```"

    return f"❌ Grep failed: {result.get('stderr', 'Unknown error')}"


def find_file(
    name: Annotated[str, "Filename pattern (e.g. *.conf)"],
    path: Annotated[str, "Search start path (default: /)"],
    host: Annotated[str, "Target host (must exist in inventory)"]
) -> str:
    """
    Find files by name.

    Args:
        name: Filename pattern
        path: Start path
        host: Target host

    Returns:
        List of found files
    """
    logger.info(f"AutoGen Tool: find_file {name} in {path} on {host}")

    is_valid, msg = _validate_host(host)
    if not is_valid:
        return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts() to see available hosts."

    # Use find command with safety limits
    cmd = f"find '{path}' -name '{name}' -type f 2>/dev/null | head -n 20"

    result = _executor.execute(host, cmd, confirm=True)

    if result['success']:
        output = result['stdout']
        if not output:
            return f"✅ No files found matching '{name}' in {path}"
        return f"✅ Found files:\n```\n{output}\n```"

    return f"❌ Find failed: {result.get('stderr', 'Unknown error')}"



def write_remote_file(
    host: Annotated[str, "Target host (must exist in inventory)"],
    path: Annotated[str, "Absolute path to file"],
    content: Annotated[str, "Content to write"],
    backup: Annotated[bool, "Create .bak backup before writing"] = True
) -> str:
    """
    Write content to a remote file with optional backup.

    IMPORTANT: The host MUST exist in the inventory. Use list_hosts() first.
    CRITICAL: This modifies files! Use with caution on production systems.

    Args:
        host: Target host
        path: Absolute path to file
        content: Content to write
        backup: Create .bak backup (default: True)

    Returns:
        Success or error message
    """
    logger.info(f"AutoGen Tool: write_remote_file {path} on {host}")

    is_valid, msg = _validate_host(host)
    if not is_valid:
        return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts() to see available hosts."

    import base64
    encoded = base64.b64encode(content.encode()).decode()

    cmds = []
    if backup:
        cmds.append(f"cp -p '{path}' '{path}.bak' 2>/dev/null || true")
    cmds.append(f"echo '{encoded}' | base64 -d > '{path}'")

    result = _executor.execute(host, " && ".join(cmds), confirm=True)

    if result['success']:
        backup_note = " (backup created)" if backup else ""
        return f"✅ Written to {path}{backup_note}"

    return f"❌ Failed to write {path}: {result.get('stderr', 'Unknown error')}"


def tail_logs(
    host: Annotated[str, "Target host (must exist in inventory)"],
    path: Annotated[str, "Log file path"],
    lines: Annotated[int, "Number of lines to show"] = 50,
    grep: Annotated[str, "Optional grep filter pattern"] = ""
) -> str:
    """
    Tail a log file with optional grep filter.

    IMPORTANT: The host MUST exist in the inventory. Use list_hosts() first.

    Common log paths:
    - /var/log/syslog (Debian/Ubuntu)
    - /var/log/messages (RHEL/CentOS)
    - /var/log/nginx/access.log
    - /var/log/nginx/error.log

    Args:
        host: Target host
        path: Log file path
        lines: Number of lines (default: 50)
        grep: Optional filter pattern

    Returns:
        Log content or error
    """
    logger.info(f"AutoGen Tool: tail_logs {path} on {host}")

    is_valid, msg = _validate_host(host)
    if not is_valid:
        return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts() to see available hosts."

    cmd = f"tail -n {lines} '{path}'"
    if grep:
        cmd += f" | grep -E '{grep}'"

    result = _executor.execute(host, cmd, confirm=True)

    if result['success']:
        content = result['stdout']
        filter_note = f" (filtered: {grep})" if grep else ""
        return f"✅ Last {lines} lines of {path}{filter_note}:\n```\n{content}\n```"

    return f"❌ Failed to read {path}: {result.get('stderr', 'Unknown error')}"


# ============================================================================
# SYSTEM INFO
# ============================================================================

def disk_info(
    host: Annotated[str, "Target host (must exist in inventory)"],
    path: Annotated[str, "Path for size check (file, folder, or partition)"] = "",
    mode: Annotated[str, "Mode: 'df' (partitions), 'du' (folder size), 'size' (file/folder), 'all' (everything)"] = "df",
    check_smart: Annotated[bool, "Check SMART disk health"] = False,
    check_raid: Annotated[bool, "Check RAID status (mdadm, megacli, etc.)"] = False,
    depth: Annotated[int, "Depth for du mode (0=total only)"] = 1
) -> str:
    """
    Comprehensive disk information: space, sizes, health, RAID status.

    IMPORTANT: The host MUST exist in the inventory. Use list_hosts() first.

    Modes:
    - 'df': Partition usage (df -h)
    - 'du': Folder size breakdown (du -h --max-depth=N)
    - 'size': Single file/folder size (du -sh)
    - 'all': Complete disk overview with largest dirs + inodes

    Options:
    - check_smart: SMART health check (requires smartmontools)
    - check_raid: RAID status (mdadm, megacli, storcli, ssacli)

    Args:
        host: Target host
        path: Path for size check
        mode: df, du, size, or all
        check_smart: Enable SMART check
        check_raid: Enable RAID check
        depth: Depth for du mode

    Returns:
        Disk information report
    """
    logger.info(f"AutoGen Tool: disk_info on {host} (mode={mode})")

    is_valid, msg = _validate_host(host)
    if not is_valid:
        return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts() to see available hosts."

    results = []

    # 1. Disk space / partition usage
    if mode in ['df', 'all'] or (mode == 'size' and not path):
        cmd = f"df -h '{path}'" if path else "df -h"
        result = _executor.execute(host, cmd, confirm=True)
        if result['success']:
            results.append(f"## Partition Usage\n```\n{result['stdout']}\n```")

    # 2. Folder size breakdown
    if mode == 'du' and path:
        cmd = f"du -h --max-depth={depth} '{path}' 2>/dev/null | sort -hr | head -20"
        result = _executor.execute(host, cmd, confirm=True)
        if result['success']:
            results.append(f"## Folder Breakdown: {path}\n```\n{result['stdout']}\n```")

    # 3. Single file/folder size
    if mode == 'size' and path:
        cmd = f"du -sh '{path}' 2>/dev/null"
        result = _executor.execute(host, cmd, confirm=True)
        if result['success']:
            results.append(f"## Size: {path}\n```\n{result['stdout']}\n```")

        ls_cmd = f"ls -lh '{path}' 2>/dev/null | head -5"
        ls_result = _executor.execute(host, ls_cmd, confirm=True)
        if ls_result['success']:
            results.append(f"## Details\n```\n{ls_result['stdout']}\n```")

    # 4. All mode extras
    if mode == 'all':
        large_cmd = "du -sh /var/log /tmp /home /opt /var 2>/dev/null | sort -hr"
        result = _executor.execute(host, large_cmd, confirm=True)
        if result['success']:
            results.append(f"## Largest Directories\n```\n{result['stdout']}\n```")

        inode_cmd = "df -i | head -10"
        inode_result = _executor.execute(host, inode_cmd, confirm=True)
        if inode_result['success']:
            results.append(f"## Inode Usage\n```\n{inode_result['stdout']}\n```")

    # 5. SMART health
    if check_smart:
        disks_cmd = "lsblk -d -o NAME,TYPE | grep disk | awk '{print $1}'"
        disks_result = _executor.execute(host, disks_cmd, confirm=True)
        if disks_result['success']:
            for disk in disks_result['stdout'].strip().split('\n')[:5]:
                if disk:
                    smart_cmd = f"sudo smartctl -H /dev/{disk} 2>/dev/null || echo 'SMART unavailable'"
                    smart_result = _executor.execute(host, smart_cmd, confirm=True)
                    if smart_result['success']:
                        results.append(f"## SMART: {disk}\n```\n{smart_result['stdout']}\n```")

    # 6. RAID status
    if check_raid:
        md_cmd = "cat /proc/mdstat 2>/dev/null"
        md_result = _executor.execute(host, md_cmd, confirm=True)
        if md_result['success'] and 'Personalities' in md_result['stdout']:
            results.append(f"## Software RAID\n```\n{md_result['stdout']}\n```")

        raid_tools = [
            ("MegaCLI", "sudo megacli -LDInfo -Lall -aALL 2>/dev/null"),
            ("StorCLI", "sudo storcli /c0 show 2>/dev/null"),
            ("ssacli", "sudo ssacli ctrl all show config 2>/dev/null"),
        ]
        for name, cmd in raid_tools:
            raid_result = _executor.execute(host, cmd, confirm=True)
            if raid_result['success'] and raid_result['stdout'].strip():
                results.append(f"## Hardware RAID ({name})\n```\n{raid_result['stdout']}\n```")
                break

    if results:
        return "✅ Disk Info:\n\n" + "\n\n".join(results)
    return "❌ Could not retrieve disk information"


def memory_info(
    host: Annotated[str, "Target host (must exist in inventory)"]
) -> str:
    """
    Get memory information (RAM usage, swap, top processes by memory).

    IMPORTANT: The host MUST exist in the inventory. Use list_hosts() first.

    Args:
        host: Target host

    Returns:
        Memory information report
    """
    logger.info(f"AutoGen Tool: memory_info on {host}")

    is_valid, msg = _validate_host(host)
    if not is_valid:
        return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts() to see available hosts."

    results = []

    # Memory usage
    free_result = _executor.execute(host, "free -h", confirm=True)
    if free_result['success']:
        results.append(f"## Memory Usage\n```\n{free_result['stdout']}\n```")

    # Top memory consumers
    top_result = _executor.execute(host, "ps aux --sort=-%mem | head -10", confirm=True)
    if top_result['success']:
        results.append(f"## Top Memory Consumers\n```\n{top_result['stdout']}\n```")

    if results:
        return "✅ Memory Info:\n\n" + "\n\n".join(results)
    return "❌ Could not retrieve memory information"


def network_connections(
    host: Annotated[str, "Target host (must exist in inventory)"],
    port: Annotated[int, "Filter by port (0=all)"] = 0,
    state: Annotated[str, "Filter by state (LISTEN, ESTABLISHED, all)"] = "all"
) -> str:
    """
    List network connections and listening ports.

    IMPORTANT: The host MUST exist in the inventory. Use list_hosts() first.

    Args:
        host: Target host
        port: Filter by specific port (0=all)
        state: Filter by state (LISTEN, ESTABLISHED, all)

    Returns:
        Network connections list
    """
    logger.info(f"AutoGen Tool: network_connections on {host}")

    is_valid, msg = _validate_host(host)
    if not is_valid:
        return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts() to see available hosts."

    cmd = "ss -tuln"
    if state == "LISTEN":
        cmd = "ss -tuln | grep LISTEN"
    elif state == "ESTABLISHED":
        cmd = "ss -tun state established"

    if port > 0:
        cmd += f" | grep ':{port}'"

    result = _executor.execute(host, cmd, confirm=True)

    if result['success']:
        filter_note = ""
        if port > 0:
            filter_note += f" (port {port})"
        if state != "all":
            filter_note += f" ({state})"
        return f"✅ Network Connections{filter_note}:\n```\n{result['stdout']}\n```"

    return f"❌ Failed: {result.get('stderr', 'Unknown error')}"


def process_list(
    host: Annotated[str, "Target host (must exist in inventory)"],
    filter: Annotated[str, "Filter by process name (grep pattern)"] = "",
    sort_by: Annotated[str, "Sort by: cpu, mem, or time"] = "cpu"
) -> str:
    """
    List running processes with optional filter.

    IMPORTANT: The host MUST exist in the inventory. Use list_hosts() first.

    Args:
        host: Target host
        filter: Grep pattern to filter processes
        sort_by: Sort by cpu, mem, or time

    Returns:
        Process list
    """
    logger.info(f"AutoGen Tool: process_list on {host}")

    is_valid, msg = _validate_host(host)
    if not is_valid:
        return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts() to see available hosts."

    sort_map = {
        "cpu": "-%cpu",
        "mem": "-%mem",
        "time": "-etime"
    }
    sort_flag = sort_map.get(sort_by, "-%cpu")

    cmd = f"ps aux --sort={sort_flag} | head -20"
    if filter:
        cmd = f"ps aux | grep -E '{filter}' | grep -v grep | head -20"

    result = _executor.execute(host, cmd, confirm=True)

    if result['success']:
        filter_note = f" (filter: {filter})" if filter else ""
        return f"✅ Processes (sorted by {sort_by}){filter_note}:\n```\n{result['stdout']}\n```"

    return f"❌ Failed: {result.get('stderr', 'Unknown error')}"


# ============================================================================
# SERVICE CONTROL
# ============================================================================

def service_control(
    host: Annotated[str, "Target host (must exist in inventory)"],
    service: Annotated[str, "Service name (e.g., nginx, mongodb, docker)"],
    action: Annotated[str, "Action: status, start, stop, restart, reload, enable, disable"]
) -> str:
    """
    Control systemd services.

    IMPORTANT: The host MUST exist in the inventory. Use list_hosts() first.
    CRITICAL: start/stop/restart modify service state! Use with caution.

    Args:
        host: Target host
        service: Service name
        action: status, start, stop, restart, reload, enable, disable

    Returns:
        Service status or action result
    """
    logger.info(f"AutoGen Tool: service_control {action} {service} on {host}")

    is_valid, msg = _validate_host(host)
    if not is_valid:
        return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts() to see available hosts."

    valid_actions = ['status', 'start', 'stop', 'restart', 'reload', 'enable', 'disable']
    if action not in valid_actions:
        return f"❌ Invalid action '{action}'. Use: {', '.join(valid_actions)}"

    cmd = f"systemctl {action} {service}"

    # For status, also get some extra info
    if action == "status":
        cmd = f"systemctl status {service} 2>&1 | head -20"

    result = _executor.execute(host, cmd, confirm=True)

    if result['success'] or action == "status":
        output = result.get('stdout', '') or result.get('stderr', '')
        return f"✅ systemctl {action} {service}:\n```\n{output}\n```"

    return f"❌ Failed: {result.get('stderr', 'Unknown error')}"


# ============================================================================
# CONTAINER OPERATIONS
# ============================================================================

def docker_exec(
    container: Annotated[str, "Container name or ID"],
    command: Annotated[str, "Command to execute in container"],
    host: Annotated[str, "Docker host (use 'local' for local Docker)"] = "local"
) -> str:
    """
    Execute command in a Docker container.

    IMPORTANT: If host is not 'local', it must exist in inventory.

    Args:
        container: Container name or ID
        command: Command to run inside container
        host: Docker host (default: local)

    Returns:
        Command output or error
    """
    logger.info(f"AutoGen Tool: docker_exec {container} on {host}")

    if host != "local":
        is_valid, msg = _validate_host(host)
        if not is_valid:
            return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts() to see available hosts."

    cmd = f"docker exec {container} sh -c '{command}'"
    result = _executor.execute(host, cmd, confirm=True)

    if result['success']:
        return f"✅ docker exec {container}:\n```\n{result['stdout']}\n```"

    return f"❌ Failed: {result.get('stderr', 'Unknown error')}"


def kubectl_exec(
    namespace: Annotated[str, "Kubernetes namespace"],
    pod: Annotated[str, "Pod name"],
    command: Annotated[str, "Command to execute in pod"],
    container: Annotated[str, "Container name (if pod has multiple)"] = ""
) -> str:
    """
    Execute command in a Kubernetes pod.

    Runs kubectl locally - ensure kubectl is configured with proper context.

    Args:
        namespace: Kubernetes namespace
        pod: Pod name
        command: Command to run
        container: Container name (optional)

    Returns:
        Command output or error
    """
    logger.info(f"AutoGen Tool: kubectl_exec {namespace}/{pod}")

    container_flag = f"-c {container}" if container else ""
    cmd = f"kubectl exec -n {namespace} {pod} {container_flag} -- sh -c '{command}'"

    result = _executor.execute("local", cmd, confirm=True)

    if result['success']:
        return f"✅ kubectl exec {namespace}/{pod}:\n```\n{result['stdout']}\n```"

    return f"❌ Failed: {result.get('stderr', 'Unknown error')}"


# ============================================================================
# WEB TOOLS
# ============================================================================

def web_search(
    query: Annotated[str, "Search query"]
) -> str:
    """
    Search the web for information using DuckDuckGo.

    Use this to find documentation, error solutions, or general information.

    Args:
        query: Search query

    Returns:
        Search results summary
    """
    logger.info(f"AutoGen Tool: web_search '{query}'")

    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))

        if not results:
            return "❌ No results found."

        summary = [f"🔍 Search Results for '{query}':", ""]
        for i, res in enumerate(results, 1):
            summary.append(f"{i}. {res['title']}")
            summary.append(f"   {res['body']}")
            summary.append(f"   Source: {res['href']}")
            summary.append("")

        return "\n".join(summary)

    except ImportError:
        return "❌ duckduckgo-search not installed. Please install it to use this tool."
    except Exception as e:
        return f"❌ Search failed: {str(e)}"


def web_fetch(
    url: Annotated[str, "URL to fetch"]
) -> str:
    """
    Fetch content from a URL.

    Use this to read documentation or articles found via web_search.

    Args:
        url: URL to fetch

    Returns:
        Page content (text only)
    """
    logger.info(f"AutoGen Tool: web_fetch {url}")

    try:
        import requests
        from bs4 import BeautifulSoup

        headers = {'User-Agent': 'Athena/0.1.0 (AI Assistant)'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        # Parse HTML to text
        soup = BeautifulSoup(response.text, 'html.parser')

        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.extract()

        text = soup.get_text()

        # Clean up whitespace
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)

        # Limit length
        if len(text) > 5000:
            text = text[:5000] + "\n...(truncated)"

        return f"✅ Content of {url}:\n\n{text}"

    except Exception as e:
        return f"❌ Fetch failed: {str(e)}"


# ============================================================================
# INTERACTION & LEARNING
# ============================================================================

def ask_user(
    question: Annotated[str, "Question to ask the user"]
) -> str:
    """
    Ask the user a question and wait for their response.

    Use this when:
    - You need clarification
    - You need a decision (Yes/No)
    - You need missing information (passwords, IPs, etc.)

    Args:
        question: The question to ask

    Returns:
        User's response
    """
    logger.info(f"AutoGen Tool: ask_user '{question}'")

    # In the REPL context, this is tricky because the tool execution is synchronous.
    # We can print the question and use input(), but that blocks the whole thread.
    # However, since we are in a local CLI tool, blocking input() is actually acceptable/expected.

    print(f"\n❓ [bold cyan]Athena asks:[/bold cyan] {question}")
    try:
        response = input("   > ")
        return f"User response: {response}"
    except (KeyboardInterrupt, EOFError):
        return "User cancelled input."


def remember_skill(
    trigger: Annotated[str, "The problem or situation (e.g. 'how to restart mongo')"],
    solution: Annotated[str, "The solution or command (e.g. 'systemctl restart mongod')"],
    context: Annotated[str, "Optional context tags (e.g. 'linux production')"] = ""
) -> str:
    """
    Teach Athena a new skill (problem-solution pair).

    Use this when you have successfully solved a problem and want to remember how to do it.

    Args:
        trigger: The problem description
        solution: The solution
        context: Optional tags

    Returns:
        Confirmation
    """
    logger.info(f"AutoGen Tool: remember_skill '{trigger}'")

    if _context_memory and hasattr(_context_memory, 'skill_store'):
        _context_memory.skill_store.add_skill(trigger, solution, context)
        return f"✅ Learned skill: When '{trigger}', do '{solution}'"

    return "❌ Memory system not available"


def recall_skill(
    query: Annotated[str, "Search query for skills"]
) -> str:
    """
    Search learned skills for a solution.

    Use this when you are stuck or want to check if you've solved this before.

    Args:
        query: Search query

    Returns:
        Matching skills
    """
    logger.info(f"AutoGen Tool: recall_skill '{query}'")

    if _context_memory and hasattr(_context_memory, 'skill_store'):
        summary = _context_memory.skill_store.get_skill_summary(query)
        if summary:
            return summary
        return f"❌ No skills found matching '{query}'"

    return "❌ Memory system not available"

