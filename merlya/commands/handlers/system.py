"""
Merlya Commands - System handlers.

Implements /scan, /health, and /log commands.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, TypedDict

from merlya.commands.handlers.scan_format import (
    ScanOptions,
    ScanResult,
    format_scan_output,
    parse_scan_args,
    scan_to_dict,
)
from merlya.commands.registry import CommandResult, command
from merlya.ssh.pool import SSHConnectionOptions

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.persistence.models import Host


class _ScanHostResult(TypedDict):
    host_name: str
    success: bool
    error: str | None
    result: ScanResult | None
    host: Host | None


# Limit concurrent SSH channels to avoid MaxSessions limit (default 10 in OpenSSH)
MAX_CONCURRENT_SSH_CHANNELS = 6


async def _get_recent_errors(ctx: SharedContext, host: str) -> dict[str, Any]:
    """
    Get recent error-level log entries using journalctl (systemd) or fallback to syslog.

    Returns dict with 'lines' and 'count' keys for formatter compatibility.
    """
    from merlya.tools.security.base import execute_security_command

    # Try journalctl first (modern systemd systems)
    cmd = "journalctl -p err -n 20 --no-pager -q 2>/dev/null"
    result = await execute_security_command(ctx, host, cmd, timeout=15)

    if result.exit_code == 0 and result.stdout.strip():
        lines = [line for line in result.stdout.strip().split("\n") if line]
        return {"lines": lines, "count": len(lines), "source": "journalctl"}

    # Fallback to syslog/messages
    for log_path in ["/var/log/syslog", "/var/log/messages"]:
        cmd = f"tail -n 100 {log_path} 2>/dev/null | grep -iE '(error|fail|critical)' | tail -n 20"
        result = await execute_security_command(ctx, host, cmd, timeout=15)
        if result.exit_code == 0 and result.stdout.strip():
            lines = [line for line in result.stdout.strip().split("\n") if line]
            return {"lines": lines, "count": len(lines), "source": log_path}

    # No errors found or logs not accessible
    return {"lines": [], "count": 0, "source": "none"}


@command("scan", "Scan a host for system info and security", "/scan <host> [options]")
async def cmd_scan(ctx: SharedContext, args: list[str]) -> CommandResult:
    """
    Scan a host for system information and security issues.

    Options:
      --full        Complete scan (default)
      --quick       Fast check: CPU, memory, disk, ports only
      --security    Security checks only
      --system      System checks only
      --json        Output as JSON
      --show-all    Show all ports/users/services (no truncation)
      --no-docker   Skip Docker checks
      --no-updates  Skip pending updates check
      --no-network  Skip network diagnostics
      --no-services Skip services list
      --no-cron     Skip cron jobs list
      --parallel    Scan multiple hosts in parallel
      --tag=<tag>   Scan all hosts with a specific tag
      --all         Scan all hosts in inventory
    """
    if not args:
        return CommandResult(
            success=False,
            message="Usage: `/scan <host> [<host2> ...] [--full|--quick|--security|--system] [--json] [--parallel]`\n"
            "Examples:\n"
            "  `/scan @myserver`\n"
            "  `/scan @myserver @myserver2 --quick --parallel`\n"
            "  `/scan --tag=production --parallel`\n"
            "  `/scan --all --quick --parallel`",
            show_help=True,
        )

    # Parse special flags
    parallel_mode = "--parallel" in args
    scan_all = "--all" in args
    tag_filter = None

    for arg in args:
        if arg.startswith("--tag="):
            tag_filter = arg[6:]

    host_names, opts = parse_scan_args(args)

    # Get hosts based on flags
    if scan_all:
        hosts = await ctx.hosts.get_all()
        if not hosts:
            return CommandResult(success=False, message="No hosts in inventory.")
        host_names = [h.name for h in hosts]
    elif tag_filter:
        hosts = await ctx.hosts.get_by_tag(tag_filter)
        if not hosts:
            return CommandResult(success=False, message=f"No hosts found with tag '{tag_filter}'.")
        host_names = [h.name for h in hosts]

    if not host_names:
        return CommandResult(
            success=False,
            message="No host specified. Usage: `/scan <host> [<host2> ...] [--full|--quick|--security|--system] [--json]`",
            show_help=True,
        )

    # Parallel execution for multiple hosts
    if parallel_mode and len(host_names) > 1:
        return await _scan_hosts_parallel(ctx, host_names, opts)

    # Sequential execution (original behavior)
    return await _scan_hosts_sequential(ctx, host_names, opts)


async def _scan_hosts_parallel(
    ctx: SharedContext,
    host_names: list[str],
    opts: ScanOptions,
) -> CommandResult:
    """Scan multiple hosts in parallel."""
    ctx.ui.info(f"🔍 Scanning {len(host_names)} hosts in parallel...")

    # Limit concurrent host scans
    host_semaphore = asyncio.Semaphore(5)

    async def scan_one_host(host_name: str) -> _ScanHostResult:
        async with host_semaphore:
            host = await ctx.hosts.get_by_name(host_name)
            if not host:
                return {
                    "host_name": host_name,
                    "success": False,
                    "error": f"Host '{host_name}' not found",
                    "result": None,
                    "host": None,
                }

            try:
                # Establish connection
                ssh_pool = await ctx.get_ssh_pool()
                connect_timeout = min(ctx.config.ssh.connect_timeout, 15)
                options = SSHConnectionOptions(
                    port=host.port,
                    jump_host=host.jump_host,
                    connect_timeout=connect_timeout,
                )
                await ssh_pool.get_connection(
                    host=host.hostname,
                    username=host.username,
                    private_key=host.private_key,
                    options=options,
                    host_name=host.name,
                )

                # Run scan
                scan_result = ScanResult()
                ssh_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SSH_CHANNELS)

                if opts.scan_type == "quick":
                    await _scan_quick(ctx, host, scan_result)
                elif opts.scan_type == "system":
                    await _scan_system_parallel(ctx, host, scan_result, opts, ssh_semaphore)
                elif opts.scan_type == "security":
                    await _scan_security_parallel(ctx, host, scan_result, opts, ssh_semaphore)
                else:  # full
                    await asyncio.gather(
                        _scan_system_parallel(ctx, host, scan_result, opts, ssh_semaphore),
                        _scan_security_parallel(ctx, host, scan_result, opts, ssh_semaphore),
                    )

                await _calculate_severity_score(ctx, scan_result)

                return {
                    "host_name": host_name,
                    "success": True,
                    "error": None,
                    "result": scan_result,
                    "host": host,
                }

            except Exception as e:
                return {
                    "host_name": host_name,
                    "success": False,
                    "error": str(e),
                    "result": None,
                    "host": host,
                }

    # Run all scans in parallel
    tasks = [scan_one_host(name) for name in host_names]
    scan_results = await asyncio.gather(*tasks)

    # Format output
    outputs: list[str] = []
    results: list[ScanResult] = []
    successes = 0

    for item in scan_results:
        if item["success"] and item["result"] is not None and item["host"] is not None:
            successes += 1
            scan_result = item["result"]
            host_entry = item["host"]
            results.append(scan_result)
            if opts.output_json:
                outputs.append(
                    f"```json\n{json.dumps(scan_to_dict(scan_result, host_entry), indent=2)}\n```"
                )
            else:
                outputs.append(format_scan_output(scan_result, host_entry, opts))
        else:
            error = item["error"] or "Unknown error"
            outputs.append(f"❌ `{item['host_name']}`: {error}")

    # Summary
    summary = f"\n---\n**Summary:** {successes}/{len(host_names)} hosts scanned successfully"
    outputs.append(summary)

    return CommandResult(
        success=successes > 0,
        message="\n\n".join(outputs),
        data=results if len(results) > 1 else (results[0] if results else None),
    )


async def _scan_hosts_sequential(
    ctx: SharedContext,
    host_names: list[str],
    opts: ScanOptions,
) -> CommandResult:
    """Scan hosts sequentially (original behavior)."""
    outputs: list[str] = []
    results: list[ScanResult] = []
    successes = 0

    for host_name in host_names:
        host = await ctx.hosts.get_by_name(host_name)
        if not host:
            outputs.append(
                f"❌ Host '{host_name}' not found. Use `/hosts add {host_name}` to add it."
            )
            continue

        ctx.ui.info(f"Scanning {host.name} ({host.hostname})...")

        # Establish connection once
        try:
            with ctx.ui.spinner(f"Connecting to {host.hostname}..."):
                ssh_pool = await ctx.get_ssh_pool()
                connect_timeout = min(ctx.config.ssh.connect_timeout, 15)
                options = SSHConnectionOptions(
                    port=host.port,
                    jump_host=host.jump_host,
                    connect_timeout=connect_timeout,
                )
                await ssh_pool.get_connection(
                    host=host.hostname,
                    username=host.username,
                    private_key=host.private_key,
                    options=options,
                    host_name=host.name,  # Pass inventory name for credential lookup
                )
        except Exception as e:
            outputs.append(f"❌ Unable to connect to `{host.name}` ({host.hostname}): {e}")
            continue

        # Run scan based on type
        scan_result = ScanResult()

        # Shared semaphore to limit total concurrent SSH channels
        ssh_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SSH_CHANNELS)

        with ctx.ui.spinner(f"Scanning {host.name}..."):
            if opts.scan_type == "quick":
                await _scan_quick(ctx, host, scan_result)
            elif opts.scan_type == "system":
                await _scan_system_parallel(ctx, host, scan_result, opts, ssh_semaphore)
            elif opts.scan_type == "security":
                await _scan_security_parallel(ctx, host, scan_result, opts, ssh_semaphore)
            else:  # full
                await asyncio.gather(
                    _scan_system_parallel(ctx, host, scan_result, opts, ssh_semaphore),
                    _scan_security_parallel(ctx, host, scan_result, opts, ssh_semaphore),
                )

        # Calculate severity score using embeddings if available
        await _calculate_severity_score(ctx, scan_result)
        results.append(scan_result)
        successes += 1

        # Format output
        if opts.output_json:
            outputs.append(f"```json\n{json.dumps(scan_to_dict(scan_result, host), indent=2)}\n```")
        else:
            outputs.append(format_scan_output(scan_result, host, opts))

    return CommandResult(
        success=successes > 0,
        message="\n\n".join(outputs),
        data=results if len(results) > 1 else (results[0] if results else None),
    )


async def _scan_quick(ctx: SharedContext, host: Any, result: ScanResult) -> None:
    """Quick scan: CPU, memory, disk, ports only (parallel)."""
    from merlya.tools.security import check_open_ports
    from merlya.tools.system import check_cpu, check_disk_usage, check_memory

    # Run all checks in parallel
    mem_task = check_memory(ctx, host.name)
    cpu_task = check_cpu(ctx, host.name)
    disk_task = check_disk_usage(ctx, host.name, "/")
    ports_task = check_open_ports(ctx, host.name)

    mem_result, cpu_result, disk_result, ports_result = await asyncio.gather(
        mem_task, cpu_task, disk_task, ports_task
    )

    # Process results
    if mem_result.success and mem_result.data:
        result.sections["memory"] = mem_result.data
        if mem_result.data.get("warning"):
            result.warning_count += 1
            result.issues.append(
                {
                    "type": "memory",
                    "severity": "warning",
                    "message": f"Memory usage high: {mem_result.data.get('use_percent')}%",
                }
            )

    if cpu_result.success and cpu_result.data:
        result.sections["cpu"] = cpu_result.data
        if cpu_result.data.get("warning"):
            result.warning_count += 1
            result.issues.append(
                {
                    "type": "cpu",
                    "severity": "warning",
                    "message": f"CPU load high: {cpu_result.data.get('use_percent')}%",
                }
            )

    if disk_result.success and disk_result.data:
        result.sections["disk"] = disk_result.data
        if disk_result.data.get("warning"):
            result.warning_count += 1
            result.issues.append(
                {
                    "type": "disk",
                    "severity": "warning",
                    "message": f"Disk usage high: {disk_result.data.get('use_percent')}%",
                }
            )

    if ports_result.success and ports_result.data:
        result.sections["ports"] = ports_result.data


async def _scan_system_parallel(
    ctx: SharedContext,
    host: Any,
    result: ScanResult,
    opts: ScanOptions,
    semaphore: asyncio.Semaphore | None = None,
) -> None:
    """System scan with parallel execution."""
    from merlya.tools.system import (
        check_all_disks,
        check_cpu,
        check_docker,
        check_memory,
        check_network,
        get_system_info,
        health_summary,
        list_cron,
        list_processes,
        list_services,
    )

    sem = semaphore or asyncio.Semaphore(MAX_CONCURRENT_SSH_CHANNELS)

    async def run_with_sem(coro: Any) -> Any:
        async with sem:
            return await coro

    # Build task list based on options
    tasks = {
        "system_info": run_with_sem(get_system_info(ctx, host.name)),
        "memory": run_with_sem(check_memory(ctx, host.name)),
        "cpu": run_with_sem(check_cpu(ctx, host.name)),
        "health": run_with_sem(health_summary(ctx, [host.name])),  # list of hosts
    }

    if opts.all_disks:
        tasks["disks"] = run_with_sem(check_all_disks(ctx, host.name))
    else:
        from merlya.tools.system import check_disk_usage

        tasks["disk"] = run_with_sem(check_disk_usage(ctx, host.name, "/"))

    if opts.include_docker:
        tasks["docker"] = run_with_sem(check_docker(ctx, host.name))

    if opts.include_services:
        tasks["services"] = run_with_sem(list_services(ctx, host.name, filter_state="running"))

    if opts.include_network:
        tasks["network"] = run_with_sem(check_network(ctx, host.name))

    if opts.include_cron:
        tasks["cron"] = run_with_sem(list_cron(ctx, host.name))

    # Full scan only: top processes and recent errors
    if opts.scan_type == "full":
        tasks["processes"] = run_with_sem(list_processes(ctx, host.name, limit=10, sort_by="cpu"))
        tasks["logs"] = run_with_sem(_get_recent_errors(ctx, host.name))

    # Execute all tasks in parallel (semaphore limits concurrency)
    results_dict = {}
    task_list = list(tasks.items())
    task_results = await asyncio.gather(*[t[1] for t in task_list], return_exceptions=True)

    for (name, _), res in zip(task_list, task_results, strict=False):
        if isinstance(res, BaseException):
            continue
        if hasattr(res, "success") and res.success and hasattr(res, "data") and res.data:
            results_dict[name] = res.data
            # Check for warnings
            if isinstance(res.data, dict) and res.data.get("warning"):
                result.warning_count += 1
                result.issues.append(
                    {
                        "type": name,
                        "severity": "warning",
                        "message": f"{name.title()} threshold exceeded",
                    }
                )

    result.sections["system"] = results_dict


async def _scan_security_parallel(
    ctx: SharedContext,
    host: Any,
    result: ScanResult,
    opts: ScanOptions,
    semaphore: asyncio.Semaphore | None = None,
) -> None:
    """Security scan with parallel execution."""
    from merlya.tools.security import (
        audit_ssh_keys,
        check_critical_services,
        check_failed_logins,
        check_open_ports,
        check_pending_updates,
        check_security_config,
        check_sudo_config,
        check_users,
    )

    sem = semaphore or asyncio.Semaphore(MAX_CONCURRENT_SSH_CHANNELS)

    async def run_with_sem(coro: Any) -> Any:
        async with sem:
            return await coro

    # Build task list
    tasks = {
        "ports": run_with_sem(check_open_ports(ctx, host.name)),
        "ssh_config": run_with_sem(check_security_config(ctx, host.name)),
        "users": run_with_sem(check_users(ctx, host.name)),
        "ssh_keys": run_with_sem(audit_ssh_keys(ctx, host.name)),
        "sudo": run_with_sem(check_sudo_config(ctx, host.name)),
        "services": run_with_sem(check_critical_services(ctx, host.name)),
    }

    if opts.include_logins:
        tasks["failed_logins"] = run_with_sem(check_failed_logins(ctx, host.name))

    if opts.include_updates:
        tasks["updates"] = run_with_sem(check_pending_updates(ctx, host.name))

    # Execute all in parallel (semaphore limits concurrency)
    results_dict: dict[str, Any] = {}
    task_list = list(tasks.items())
    task_results = await asyncio.gather(*[t[1] for t in task_list], return_exceptions=True)

    for (name, _), res in zip(task_list, task_results, strict=False):
        if isinstance(res, BaseException):
            continue
        if hasattr(res, "success") and res.success:
            results_dict[name] = getattr(res, "data", None)
            # Count severity
            severity = getattr(res, "severity", "info")
            if severity == "critical":
                result.critical_count += 1
                result.issues.append({"type": name, "severity": "critical", "data": res.data})
            elif severity == "warning":
                result.warning_count += 1
                result.issues.append({"type": name, "severity": "warning", "data": res.data})

    result.sections["security"] = results_dict


async def _calculate_severity_score(_ctx: SharedContext, result: ScanResult) -> None:
    """Calculate severity score, optionally using embeddings for intelligent analysis."""
    # Base scoring
    base_score = result.critical_count * 25 + result.warning_count * 10
    result.severity_score = min(100, base_score)

    # Note: Embedding-based severity analysis removed (ONNX embeddings deprecated)
    # Severity scoring is now based solely on issue count and message patterns


@command("health", "Show system health status", "/health")
async def cmd_health(_ctx: SharedContext, _args: list[str]) -> CommandResult:
    """Show system health status."""
    from merlya.health import run_startup_checks

    health = await run_startup_checks()

    lines = ["**Health Status**\n"]
    for check in health.checks:
        icon = "✓" if check.status.value == "ok" else "✗"
        lines.append(f"  {icon} {check.message}")

    if health.capabilities:
        lines.append("\n**Capabilities:**")
        for cap, enabled in health.capabilities.items():
            status = "enabled" if enabled else "disabled"
            lines.append(f"  {cap}: `{status}`")

    return CommandResult(success=True, message="\n".join(lines), data=health)


@command("log", "Configure logging", "/log <subcommand>")
async def cmd_log(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Configure logging settings."""
    if not args:
        return _show_log_config(ctx)

    action = args[0].lower()

    if action == "level" and len(args) > 1:
        return _set_log_level(ctx, args[1])
    elif action == "show":
        return _show_recent_logs(ctx)

    return CommandResult(success=False, message="Unknown log command. Use `/log` for help.")


def _show_log_config(ctx: SharedContext) -> CommandResult:
    """Show logging configuration."""
    config = ctx.config.logging
    return CommandResult(
        success=True,
        message=f"**Logging Configuration**\n\n"
        f"  - Console level: `{config.console_level}`\n"
        f"  - File level: `{config.file_level}`\n"
        f"  - Max size: `{config.max_size_mb}MB`\n"
        f"  - Retention: `{config.retention_days} days`\n"
        f"  - Max files: `{config.max_files}`\n\n"
        "Use `/log level <debug|info|warning|error>` to change console level.",
    )


def _set_log_level(ctx: SharedContext, level_str: str) -> CommandResult:
    """Set logging level."""
    level = level_str.lower()
    if level not in ("debug", "info", "warning", "error"):
        return CommandResult(
            success=False,
            message="Valid levels: `debug`, `info`, `warning`, `error`",
        )

    ctx.config.logging.console_level = level  # type: ignore[assignment]
    ctx.config.save()

    from merlya.core.logging import configure_logging

    configure_logging(
        console_level=level,
        file_level=ctx.config.logging.file_level,
        force=True,
    )

    return CommandResult(success=True, message=f"✅ Console log level set to `{level}`")


def _show_recent_logs(ctx: SharedContext) -> CommandResult:
    """Show recent log entries."""
    log_path = ctx.config.general.data_dir / "logs" / "merlya.log"
    if log_path.exists():
        lines = log_path.read_text().split("\n")[-20:]
        return CommandResult(
            success=True,
            message=f"**Recent logs** ({log_path})\n\n```\n" + "\n".join(lines) + "\n```",
        )
    return CommandResult(success=False, message="No log file found.")
