"""
Merlya Commands - System handlers.

Implements /scan, /health, and /log commands.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from merlya.commands.registry import CommandResult, command
from merlya.ssh.pool import SSHConnectionOptions

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


@dataclass
class ScanOptions:
    """Options for the scan command."""

    scan_type: str = "full"  # full, system, security, quick
    output_json: bool = False
    all_disks: bool = False
    include_docker: bool = True
    include_updates: bool = True
    include_logins: bool = True


# Limit concurrent SSH channels to avoid MaxSessions limit (default 10 in OpenSSH)
MAX_CONCURRENT_SSH_CHANNELS = 6


@dataclass
class ScanResult:
    """Aggregated scan result with severity scoring."""

    sections: dict[str, Any] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)
    severity_score: int = 0  # 0-100, higher = more issues
    critical_count: int = 0
    warning_count: int = 0


def _parse_scan_options(args: list[str]) -> ScanOptions:
    """Parse scan options from arguments."""
    opts = ScanOptions()

    for arg in args[1:]:
        if arg == "--security":
            opts.scan_type = "security"
        elif arg == "--system":
            opts.scan_type = "system"
        elif arg == "--full":
            opts.scan_type = "full"
        elif arg == "--quick":
            opts.scan_type = "quick"
        elif arg == "--json":
            opts.output_json = True
        elif arg == "--all-disks":
            opts.all_disks = True
        elif arg == "--no-docker":
            opts.include_docker = False
        elif arg == "--no-updates":
            opts.include_updates = False

    return opts


@command("scan", "Scan a host for system info and security", "/scan <host> [options]")
async def cmd_scan(ctx: SharedContext, args: list[str]) -> CommandResult:
    """
    Scan a host for system information and security issues.

    Options:
      --full       Complete scan (default)
      --quick      Fast check: CPU, memory, disk, ports only
      --security   Security checks only
      --system     System checks only
      --json       Output as JSON
      --all-disks  Check all mounted filesystems
      --no-docker  Skip Docker checks
      --no-updates Skip pending updates check
    """
    if not args:
        return CommandResult(
            success=False,
            message="Usage: `/scan <host> [--full|--quick|--security|--system] [--json]`\n"
            "Example: `/scan @myserver` or `/scan @myserver --quick --json`",
            show_help=True,
        )

    host_name = args[0].lstrip("@")
    opts = _parse_scan_options(args)

    host = await ctx.hosts.get_by_name(host_name)
    if not host:
        return CommandResult(
            success=False,
            message=f"Host '{host_name}' not found. Use `/hosts add {host_name}` to add it.",
        )

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
        return CommandResult(
            success=False,
            message=f"❌ Unable to connect to `{host.name}` ({host.hostname}): {e}",
        )

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

    # Format output
    if opts.output_json:
        return CommandResult(
            success=True,
            message=f"```json\n{json.dumps(_scan_to_dict(scan_result, host), indent=2)}\n```",
            data=scan_result,
        )

    return CommandResult(
        success=True,
        message=_format_scan_output(scan_result, host),
        data=scan_result,
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
        get_system_info,
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
    }

    if opts.all_disks:
        tasks["disks"] = run_with_sem(check_all_disks(ctx, host.name))
    else:
        from merlya.tools.system import check_disk_usage

        tasks["disk"] = run_with_sem(check_disk_usage(ctx, host.name, "/"))

    if opts.include_docker:
        tasks["docker"] = run_with_sem(check_docker(ctx, host.name))

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


async def _calculate_severity_score(ctx: SharedContext, result: ScanResult) -> None:
    """Calculate severity score, optionally using embeddings for intelligent analysis."""
    # Base scoring
    base_score = result.critical_count * 25 + result.warning_count * 10
    result.severity_score = min(100, base_score)

    # Try embedding-based severity analysis
    try:
        if hasattr(ctx, "_router") and ctx._router and ctx._router.model_loaded:
            # Use embeddings to analyze issue severity
            issue_texts = [
                issue.get("message", str(issue.get("data", "")))[:200] for issue in result.issues
            ]
            if issue_texts:
                # Get embeddings for issues and compare to critical patterns
                classifier = ctx._router.classifier
                critical_patterns = [
                    "critical security vulnerability",
                    "root access compromised",
                    "unauthorized access detected",
                    "system completely down",
                ]
                # This is a simplified version - could be extended
                for issue_text in issue_texts:
                    issue_emb = await classifier._get_embedding(issue_text)
                    if issue_emb is not None:
                        for pattern in critical_patterns:
                            pattern_emb = await classifier._get_embedding(pattern)
                            if pattern_emb is not None:
                                sim = classifier._cosine_similarity(issue_emb, pattern_emb)
                                if sim > 0.7:
                                    result.severity_score = min(100, result.severity_score + 15)
                                    break
    except Exception:
        pass  # Fallback to base scoring if embeddings fail


def _scan_to_dict(result: ScanResult, host: Any) -> dict[str, Any]:
    """Convert scan result to dictionary for JSON output."""
    return {
        "host": host.name,
        "hostname": host.hostname,
        "severity_score": result.severity_score,
        "critical_count": result.critical_count,
        "warning_count": result.warning_count,
        "sections": result.sections,
        "issues": result.issues,
    }


def _format_scan_output(result: ScanResult, host: Any) -> str:
    """Format scan result for display."""
    lines: list[str] = []

    # Header with severity
    severity_icon = (
        "🔴" if result.critical_count > 0 else ("🟡" if result.warning_count > 0 else "🟢")
    )
    lines.append(f"## {severity_icon} Scan: `{host.name}` ({host.hostname})")
    lines.append("")
    lines.append(
        f"**Score:** {result.severity_score}/100 | **Critical:** {result.critical_count} | **Warnings:** {result.warning_count}"
    )
    lines.append("")

    # System section
    if "system" in result.sections:
        sys_data = result.sections["system"]
        lines.append("### 🖥️ System")
        lines.append("")

        if "system_info" in sys_data:
            info = sys_data["system_info"]
            lines.append(f"| Host | `{info.get('hostname', host.hostname)}` |")
            lines.append(f"| OS | {info.get('os', 'N/A')} |")
            lines.append(f"| Kernel | {info.get('kernel', 'N/A')} |")
            lines.append(f"| Uptime | {info.get('uptime', 'N/A')} |")
            lines.append(f"| Load | {info.get('load', 'N/A')} |")
            lines.append("")

        # Resources table
        lines.append("**Resources:**")
        lines.append("")

        if "memory" in sys_data:
            m = sys_data["memory"]
            icon = "⚠️" if m.get("warning") else "✅"
            pct = m.get("use_percent", 0)
            bar = _progress_bar(pct)
            lines.append(
                f"- {icon} **Memory:** {bar} {pct}% ({m.get('used_mb', 0)}MB / {m.get('total_mb', 0)}MB)"
            )

        if "cpu" in sys_data:
            c = sys_data["cpu"]
            icon = "⚠️" if c.get("warning") else "✅"
            pct = c.get("use_percent", 0)
            bar = _progress_bar(pct)
            lines.append(
                f"- {icon} **CPU:** {bar} {pct}% (cores: {c.get('cpu_count', 0)}, load: {c.get('load_1m', 0)})"
            )

        if "disk" in sys_data:
            d = sys_data["disk"]
            icon = "⚠️" if d.get("warning") else "✅"
            pct = d.get("use_percent", 0)
            bar = _progress_bar(pct)
            lines.append(
                f"- {icon} **Disk (/):** {bar} {pct}% ({d.get('used', 'N/A')} / {d.get('size', 'N/A')})"
            )

        if "disks" in sys_data:
            disks_data = sys_data["disks"]
            for disk in disks_data.get("disks", [])[:5]:
                icon = "⚠️" if disk.get("warning") else "✅"
                pct = disk.get("use_percent", 0)
                bar = _progress_bar(pct)
                lines.append(f"- {icon} **Disk ({disk.get('mount', '?')}):** {bar} {pct}%")

        if "docker" in sys_data:
            docker = sys_data["docker"]
            if docker.get("status") == "running":
                lines.append(
                    f"- 🐳 **Docker:** {docker.get('running_count', 0)} running, {docker.get('stopped_count', 0)} stopped"
                )
            elif docker.get("status") == "not-installed":
                lines.append("- ◻️ **Docker:** not installed")
            else:
                lines.append("- ⚠️ **Docker:** not running")

        lines.append("")

    # Security section
    if "security" in result.sections:
        sec_data = result.sections["security"]
        lines.append("### 🔒 Security")
        lines.append("")

        # Ports
        if "ports" in sec_data and isinstance(sec_data["ports"], list):
            ports = sec_data["ports"]
            lines.append(f"**Open Ports:** {len(ports)}")
            if ports:
                port_list = []
                for p in ports[:8]:
                    port_val = p.get("port", "?")
                    proto = p.get("protocol", "?")
                    process = p.get("process") or p.get("service") or ""
                    if process:
                        port_list.append(f"`{port_val}/{proto}` ({process})")
                    else:
                        port_list.append(f"`{port_val}/{proto}`")
                lines.append("  " + " · ".join(port_list))
                if len(ports) > 8:
                    lines.append(f"  *... and {len(ports) - 8} more*")
            lines.append("")

        # SSH config
        if "ssh_config" in sec_data and isinstance(sec_data["ssh_config"], dict):
            checks = sec_data["ssh_config"].get("checks", [])
            issues = [c for c in checks if c.get("status") != "ok"]
            if issues:
                lines.append(f"⚠️ **SSH Config:** {len(issues)} issue(s)")
                for item in issues[:3]:
                    lines.append(f"   - {item.get('setting')}: {item.get('message', '')}")
            else:
                lines.append("✅ **SSH Config:** secure")
            lines.append("")

        # Failed logins
        if "failed_logins" in sec_data:
            logins = sec_data["failed_logins"]
            total = logins.get("total_attempts", 0)
            if total > 0:
                icon = "🔴" if total > 50 else ("⚠️" if total > 20 else "ℹ️")  # noqa: RUF001
                lines.append(f"{icon} **Failed Logins (24h):** {total}")
                top_ips = logins.get("top_ips", [])[:3]
                if top_ips:
                    ips = ", ".join(f"{ip['ip']} ({ip['count']})" for ip in top_ips)
                    lines.append(f"   Top IPs: {ips}")
            else:
                lines.append("✅ **Failed Logins:** none in 24h")
            lines.append("")

        # Updates
        if "updates" in sec_data:
            updates = sec_data["updates"]
            total = updates.get("total_updates", 0)
            security = updates.get("security_updates", 0)
            if total > 0:
                icon = "🔴" if security > 5 else ("⚠️" if total > 10 else "ℹ️")  # noqa: RUF001
                lines.append(f"{icon} **Updates:** {total} pending ({security} security)")
            else:
                lines.append("✅ **Updates:** system up to date")
            lines.append("")

        # Services
        if "services" in sec_data:
            services = sec_data["services"]
            inactive = services.get("inactive_count", 0)
            if inactive > 0:
                lines.append(f"⚠️ **Services:** {inactive} critical service(s) inactive")
                for svc in services.get("services", []):
                    if not svc.get("active") and svc.get("status") != "not-found":
                        lines.append(f"   - {svc['service']}: {svc['status']}")
            else:
                lines.append("✅ **Services:** all critical services active")
            lines.append("")

        # Users
        if "users" in sec_data and isinstance(sec_data["users"], dict):
            users = sec_data["users"]
            shell_users = users.get("users", [])
            issues = users.get("issues", [])
            icon = "⚠️" if issues else "ℹ️"  # noqa: RUF001
            lines.append(f"{icon} **Users:** {len(shell_users)} with shell access")
            if issues:
                for issue in issues[:3]:
                    lines.append(f"   ⚠️ {issue}")
            lines.append("")

    return "\n".join(lines)


def _progress_bar(percent: int | float, width: int = 10) -> str:
    """Create a simple progress bar."""
    filled = int(percent / 100 * width)
    empty = width - filled
    if percent >= 90 or percent >= 70:
        return "█" * filled + "░" * empty
    else:
        return "█" * filled + "░" * empty


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
        f"  - Level: `{config.file_level}`\n"
        f"  - Max size: `{config.max_size_mb}MB`\n"
        f"  - Retention: `{config.retention_days} days`\n"
        f"  - Max files: `{config.max_files}`\n\n"
        "Use `/log level <debug|info|warning|error>` to change.",
    )


def _set_log_level(ctx: SharedContext, level_str: str) -> CommandResult:
    """Set logging level."""
    level = level_str.lower()
    if level not in ("debug", "info", "warning", "error"):
        return CommandResult(
            success=False,
            message="Valid levels: `debug`, `info`, `warning`, `error`",
        )

    ctx.config.logging.file_level = level  # type: ignore[assignment]
    ctx.config.save()

    from merlya.core.logging import configure_logging

    configure_logging(console_level=level, file_level=level, force=True)

    return CommandResult(success=True, message=f"✅ Log level set to `{level}`")


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
