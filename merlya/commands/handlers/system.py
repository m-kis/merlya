"""
Merlya Commands - System handlers.

Implements /scan, /health, and /log commands.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from merlya.commands.registry import CommandResult, command, subcommand

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


@command("scan", "Scan a host for system info and security", "/scan <host> [--full|--security|--system]")
async def cmd_scan(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Scan a host for system information and security issues."""
    if not args:
        return CommandResult(
            success=False,
            message="Usage: `/scan <host> [--full|--security|--system]`\n"
            "Example: `/scan @myserver` or `/scan @myserver --security`",
            show_help=True,
        )

    host_name = args[0].lstrip("@")
    scan_type = _parse_scan_type(args)

    host = await ctx.hosts.get_by_name(host_name)
    if not host:
        return CommandResult(
            success=False,
            message=f"Host '{host_name}' not found. Use `/hosts add {host_name}` to add it.",
        )

    ctx.ui.info(f"Scanning {host.name} ({host.hostname})...")

    # Establish connection once with a short timeout to avoid repeated failures
    try:
        with ctx.ui.spinner(f"Connecting to {host.hostname}..."):
            ssh_pool = await ctx.get_ssh_pool()
            connect_timeout = min(ctx.config.ssh.connect_timeout, 15)
            await ssh_pool.get_connection(
                host=host.hostname,
                port=host.port,
                username=host.username,
                private_key=host.private_key,
                jump_host=host.jump_host,
                connect_timeout=connect_timeout,
            )
    except Exception as e:
        return CommandResult(
            success=False,
            message=f"❌ Unable to connect to `{host.name}` ({host.hostname}): {e}",
        )

    results: list[str] = [f"**Scan Results for `{host.name}`**\n"]

    total_steps = 0
    if scan_type in ("full", "system"):
        total_steps += 1
    if scan_type in ("full", "security"):
        total_steps += 1

    with ctx.ui.progress() as progress:
        task = progress.add_task(f"Scanning {host.name}", total=max(total_steps, 1))

        if scan_type in ("full", "system"):
            results.extend(await _scan_system(ctx, host))
            progress.advance(task)

        if scan_type in ("full", "security"):
            results.extend(await _scan_security(ctx, host))
            progress.advance(task)

    return CommandResult(success=True, message="\n".join(results))


def _parse_scan_type(args: list[str]) -> str:
    """Parse scan type from arguments."""
    for arg in args[1:]:
        if arg == "--security":
            return "security"
        elif arg == "--system":
            return "system"
        elif arg == "--full":
            return "full"
    return "full"


async def _scan_system(ctx: SharedContext, host) -> list[str]:
    """Run system scan and return result lines."""
    from merlya.tools.system import (
        check_cpu,
        check_disk_usage,
        check_memory,
        get_system_info,
    )

    results: list[str] = []
    ctx.ui.muted("  Gathering system info...")

    sys_result = await get_system_info(ctx, host.name)
    if sys_result.success and sys_result.data:
        info = sys_result.data
        results.append("### 🖥️ System")
        results.append(
            f"- hostname: `{info.get('hostname', host.hostname)}`"
            f" | os: `{info.get('os', 'N/A')}`"
        )
        results.append(
            f"- kernel: `{info.get('kernel', 'N/A')}` | arch: `{info.get('arch', 'N/A')}`"
        )
        results.append(f"- uptime: `{info.get('uptime', 'N/A')}`")
        results.append(f"- load: `{info.get('load', 'N/A')}`")
        results.append("")

    mem_result = await check_memory(ctx, host.name)
    if mem_result.success and mem_result.data:
        data = mem_result.data
        icon = "⚠️" if data.get("warning") else "✓"
        results.append(
            f"{icon} Memory: {data.get('use_percent', 0)}% used "
            f"({data.get('used_mb', 0)}MB / {data.get('total_mb', 0)}MB)"
        )

    cpu_result = await check_cpu(ctx, host.name)
    if cpu_result.success and cpu_result.data:
        data = cpu_result.data
        icon = "⚠️" if data.get("warning") else "✓"
        results.append(
            f"{icon} CPU: {data.get('use_percent', 0)}% "
            f"(load 1m: {data.get('load_1m', 0)}, cores: {data.get('cpu_count', 0)})"
        )

    disk_result = await check_disk_usage(ctx, host.name, "/")
    if disk_result.success and disk_result.data:
        data = disk_result.data
        icon = "⚠️" if data.get("warning") else "✓"
        results.append(
            f"{icon} Disk (/): {data.get('use_percent', 0)}% used "
            f"({data.get('used', 'N/A')} / {data.get('size', 'N/A')})"
        )

    results.append("")
    return results


async def _scan_security(ctx: SharedContext, host) -> list[str]:
    """Run security scan and return result lines."""
    from merlya.tools.security import (
        check_open_ports,
        check_security_config,
        check_users,
    )

    results: list[str] = []
    ctx.ui.muted("  Running security checks...")

    ports_result = await check_open_ports(ctx, host.name)
    if ports_result.success and ports_result.data and isinstance(ports_result.data, list):
        ports = ports_result.data
        results.append("### 🔒 Security")
        results.append(f"- Open ports: `{len(ports)}`")

        def _format_port(p: dict) -> str:
            port_value = p.get("port", "?")
            proto = p.get("protocol", "?")
            process = p.get("process") or p.get("service") or "unknown"
            state = p.get("state", "").lower()
            addr = p.get("address") or "*"
            pid = p.get("pid")
            pid_str = f" pid={pid}" if pid else ""
            state_str = f"[{state}] " if state else ""
            return f"  • `{port_value}/{proto}` {state_str}({process}) @{addr}{pid_str}"

        for port in ports[:10]:
            if isinstance(port, dict):
                results.append(_format_port(port))

        if len(ports) > 10:
            results.append(f"  • ... and {len(ports) - 10} more")
        results.append("")

    sec_result = await check_security_config(ctx, host.name)
    if sec_result.success and sec_result.data and isinstance(sec_result.data, dict):
        checks = sec_result.data.get("checks", [])
        misconfigs = [c for c in checks if c.get("status") != "ok"]
        if misconfigs:
            results.append(f"⚠️ Security config: {len(misconfigs)} warning(s)")
            for item in misconfigs[:5]:
                setting = item.get("setting", "?")
                value = item.get("value", "")
                message = item.get("message", "")
                results.append(f"  - {setting}: {value} {message}".strip())
            if len(misconfigs) > 5:
                results.append(f"  ... and {len(misconfigs) - 5} more")
        else:
            results.append("✓ Security config: no obvious issues")
        results.append("")

    users_result = await check_users(ctx, host.name)
    if users_result.success and users_result.data and isinstance(users_result.data, dict):
        users = users_result.data.get("users", [])
        sudo_users = users_result.data.get("sudo_users", [])
        shell_users = users_result.data.get("shell_users", []) or [u for u in users if u.get("shell")]
        results.append(
            f"**Users:** {len(shell_users)} with shell, {len(sudo_users)} with sudo"
        )
        if shell_users:
            names = [u.get("username", "?") if isinstance(u, dict) else str(u) for u in shell_users[:5]]
            results.append(f"  Shell users: {', '.join(names)}")
        if sudo_users:
            sudo_names = [u.get("username", "?") if isinstance(u, dict) else str(u) for u in sudo_users[:5]]
            results.append(f"  Sudo: {', '.join(sudo_names)}")
        if users_result.data.get("issues"):
            for issue in users_result.data["issues"][:5]:
                results.append(f"  ⚠️ {issue}")

    return results


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
    level = level_str.upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        return CommandResult(
            success=False,
            message="Valid levels: `debug`, `info`, `warning`, `error`",
        )

    ctx.config.logging.file_level = level
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
