"""
Merlya Commands - Scan output formatting.

Formatting utilities for scan command output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScanOptions:
    """Options for the scan command."""

    scan_type: str = "full"  # full, system, security, quick
    output_json: bool = False
    all_disks: bool = True  # Check all mounted filesystems by default
    include_docker: bool = True
    include_updates: bool = True
    include_logins: bool = True
    include_network: bool = True  # Network diagnostics (ping, dns)
    include_services: bool = True  # Running services list
    include_cron: bool = True  # Cron jobs list
    show_all: bool = False  # Show all ports/users (no truncation)


@dataclass
class ScanResult:
    """Aggregated scan result with severity scoring."""

    sections: dict[str, Any] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)
    severity_score: int = 0  # 0-100, higher = more issues
    critical_count: int = 0
    warning_count: int = 0


def parse_scan_options(args: list[str]) -> ScanOptions:
    """Parse scan options from arguments."""
    opts = ScanOptions()

    for arg in args:
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
        elif arg in ("--all-disks", "--disk"):
            opts.all_disks = True
        elif arg == "--no-docker":
            opts.include_docker = False
        elif arg == "--no-updates":
            opts.include_updates = False
        elif arg == "--no-network":
            opts.include_network = False
        elif arg == "--no-services":
            opts.include_services = False
        elif arg == "--no-cron":
            opts.include_cron = False
        elif arg == "--show-all":
            opts.show_all = True

    return opts


def parse_scan_args(args: list[str]) -> tuple[list[str], ScanOptions]:
    """Split host targets from option flags."""
    hosts: list[str] = []
    flags: list[str] = []

    for arg in args:
        if arg.startswith("--"):
            flags.append(arg)
        else:
            hosts.append(arg.lstrip("@"))

    return hosts, parse_scan_options(flags)


def scan_to_dict(result: ScanResult, host: Any) -> dict[str, Any]:
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


def progress_bar(percent: int | float, width: int = 10) -> str:
    """Create a simple progress bar."""
    filled = int(percent / 100 * width)
    empty = width - filled
    return "█" * filled + "░" * empty


def format_scan_output(result: ScanResult, host: Any, opts: ScanOptions | None = None) -> str:
    """Format scan result for display."""
    lines: list[str] = []
    show_all = opts.show_all if opts else False

    # Header with severity
    severity_icon = (
        "🔴" if result.critical_count > 0 else ("🟡" if result.warning_count > 0 else "🟢")
    )
    lines.append(f"## {severity_icon} Scan: `{host.name}` ({host.hostname})")
    lines.append("")
    lines.append(f"**Critical:** {result.critical_count} | **Warnings:** {result.warning_count}")
    lines.append("")

    # System section
    if "system" in result.sections:
        _format_system_section(lines, result.sections["system"], show_all)

    # Security section
    if "security" in result.sections:
        _format_security_section(lines, result.sections["security"], show_all)

    return "\n".join(lines)


def _format_system_section(lines: list[str], sys_data: dict[str, Any], show_all: bool) -> None:
    """Format system section of scan output."""
    lines.append("### 🖥️ System")
    lines.append("")

    if "system_info" in sys_data:
        info = sys_data["system_info"]
        lines.append(f"| Host | `{info.get('hostname', 'N/A')}` |")
        lines.append(f"| OS | {info.get('os', 'N/A')} |")
        lines.append(f"| Kernel | {info.get('kernel', 'N/A')} |")
        lines.append(f"| Uptime | {info.get('uptime', 'N/A')} |")
        lines.append(f"| Load | {info.get('load', 'N/A')} |")
        lines.append("")

    # Resources
    lines.append("**Resources:**")
    lines.append("")

    if "memory" in sys_data:
        m = sys_data["memory"]
        icon = "⚠️" if m.get("warning") else "✅"
        pct = m.get("use_percent", 0)
        bar = progress_bar(pct)
        lines.append(
            f"- {icon} **Memory:** {bar} {pct}% ({m.get('used_mb', 0)}MB / {m.get('total_mb', 0)}MB)"
        )

    if "cpu" in sys_data:
        c = sys_data["cpu"]
        icon = "⚠️" if c.get("warning") else "✅"
        pct = c.get("use_percent", 0)
        bar = progress_bar(pct)
        lines.append(
            f"- {icon} **CPU:** {bar} {pct}% (cores: {c.get('cpu_count', 0)}, load: {c.get('load_1m', 0)})"
        )

    if "disk" in sys_data:
        d = sys_data["disk"]
        icon = "⚠️" if d.get("warning") else "✅"
        pct = d.get("use_percent", 0)
        bar = progress_bar(pct)
        lines.append(
            f"- {icon} **Disk (/):** {bar} {pct}% ({d.get('used', 'N/A')} / {d.get('size', 'N/A')})"
        )

    if "disks" in sys_data:
        disks_data = sys_data["disks"]
        for disk in disks_data.get("disks", [])[:5]:
            icon = "⚠️" if disk.get("warning") else "✅"
            pct = disk.get("use_percent", 0)
            bar = progress_bar(pct)
            lines.append(f"- {icon} **Disk ({disk.get('mount', '?')}):** {bar} {pct}%")

    if "docker" in sys_data:
        docker = sys_data["docker"]
        if docker.get("status") == "running":
            lines.append(
                f"- 🐳 **Docker:** {docker.get('running_count', 0)} running, "
                f"{docker.get('stopped_count', 0)} stopped"
            )
        elif docker.get("status") == "not-installed":
            lines.append("- ◻️ **Docker:** not installed")
        else:
            lines.append("- ⚠️ **Docker:** not running")

    lines.append("")

    # Health summary
    if "health" in sys_data:
        _format_health_section(lines, sys_data["health"])

    # Network diagnostics
    if "network" in sys_data:
        _format_network_section(lines, sys_data["network"])

    # Running services
    if "services" in sys_data:
        _format_running_services(lines, sys_data["services"], show_all)

    # Cron jobs
    if "cron" in sys_data:
        _format_cron_jobs(lines, sys_data["cron"], show_all)

    # Top processes (full scan only)
    if "processes" in sys_data:
        _format_top_processes(lines, sys_data["processes"], show_all)

    # Recent errors (full scan only)
    if "logs" in sys_data:
        _format_recent_errors(lines, sys_data["logs"], show_all)


def _format_security_section(lines: list[str], sec_data: dict[str, Any], show_all: bool) -> None:
    """Format security section of scan output."""
    lines.append("### 🔒 Security")
    lines.append("")

    # Ports
    if "ports" in sec_data and isinstance(sec_data["ports"], list):
        _format_ports(lines, sec_data["ports"], show_all)

    # SSH config
    if "ssh_config" in sec_data and isinstance(sec_data["ssh_config"], dict):
        _format_ssh_config(lines, sec_data["ssh_config"], show_all)

    # Failed logins
    if "failed_logins" in sec_data:
        _format_failed_logins(lines, sec_data["failed_logins"])

    # Updates
    if "updates" in sec_data:
        _format_updates(lines, sec_data["updates"])

    # Services
    if "services" in sec_data:
        _format_services(lines, sec_data["services"])

    # Users
    if "users" in sec_data and isinstance(sec_data["users"], dict):
        _format_users(lines, sec_data["users"], show_all)


def _format_ports(lines: list[str], ports: list[Any], show_all: bool) -> None:
    """Format ports section."""
    lines.append(f"**Open Ports:** {len(ports)}")
    if ports:
        max_ports = len(ports) if show_all else 10
        port_list = []
        for p in ports[:max_ports]:
            port_val = p.get("port", "?")
            proto = p.get("protocol", "?")
            process = p.get("process") or p.get("service") or ""
            if process:
                port_list.append(f"`{port_val}/{proto}` ({process})")
            else:
                port_list.append(f"`{port_val}/{proto}`")
        lines.append("  " + " · ".join(port_list))
        if not show_all and len(ports) > 10:
            lines.append(f"  *... and {len(ports) - 10} more (use --show-all)*")
    lines.append("")


def _format_ssh_config(lines: list[str], ssh_config: dict[str, Any], show_all: bool) -> None:
    """Format SSH config section."""
    checks = ssh_config.get("checks", [])
    issues = [c for c in checks if c.get("status") != "ok"]
    if issues:
        max_items = len(issues) if show_all else 3
        lines.append(f"⚠️ **SSH Config:** {len(issues)} issue(s)")
        for item in issues[:max_items]:
            status = item.get("status", "")
            setting = item.get("setting") or "unknown"
            value = item.get("value") or "?"
            message = item.get("message") or ""
            lines.append(f"   - {setting}={value} [{status}] {message}")
        if not show_all and len(issues) > max_items:
            lines.append(f"   *... and {len(issues) - max_items} more (use --show-all)*")
    else:
        lines.append("✅ **SSH Config:** secure")
    lines.append("")


def _format_failed_logins(lines: list[str], logins: dict[str, Any]) -> None:
    """Format failed logins section."""
    total = logins.get("total_attempts", 0)
    if total > 0:
        icon = "🔴" if total > 50 else ("⚠️" if total > 20 else "ℹ️")
        lines.append(f"{icon} **Failed Logins (24h):** {total}")
        top_ips = logins.get("top_ips", [])[:3]
        if top_ips:
            ips = ", ".join(f"{ip['ip']} ({ip['count']})" for ip in top_ips)
            lines.append(f"   Top IPs: {ips}")
    else:
        lines.append("✅ **Failed Logins:** none in 24h")
    lines.append("")


def _format_updates(lines: list[str], updates: dict[str, Any]) -> None:
    """Format updates section."""
    total = updates.get("total_updates", 0)
    security = updates.get("security_updates", 0)
    if total > 0:
        icon = "🔴" if security > 5 else ("⚠️" if total > 10 else "ℹ️")
        lines.append(f"{icon} **Updates:** {total} pending ({security} security)")
    else:
        lines.append("✅ **Updates:** system up to date")
    lines.append("")


def _format_services(lines: list[str], services: dict[str, Any]) -> None:
    """Format services section."""
    inactive = services.get("inactive_count", 0)
    if inactive > 0:
        lines.append(f"⚠️ **Services:** {inactive} critical service(s) inactive")
        for svc in services.get("services", []):
            if not svc.get("active") and svc.get("status") != "not-found":
                lines.append(f"   - {svc['service']}: {svc['status']}")
    else:
        lines.append("✅ **Services:** all critical services active")
    lines.append("")


def _format_users(lines: list[str], users: dict[str, Any], show_all: bool) -> None:
    """Format users section."""
    shell_users = users.get("users", [])
    issues = users.get("issues", [])
    icon = "⚠️" if issues else "ℹ️"
    lines.append(f"{icon} **Users:** {len(shell_users)} with shell access")

    if shell_users:
        max_users = len(shell_users) if show_all else 8
        user_names = [
            u.get("username", u) if isinstance(u, dict) else str(u) for u in shell_users[:max_users]
        ]
        lines.append(f"   `{', '.join(user_names)}`")
        if not show_all and len(shell_users) > 8:
            lines.append(f"   *... and {len(shell_users) - 8} more (use --show-all)*")

    if issues:
        for issue in issues[:3]:
            lines.append(f"   ⚠️ {issue}")
    lines.append("")


def _format_health_section(lines: list[str], health: dict[str, Any]) -> None:
    """Format health summary section."""
    lines.append("**Health Summary:**")
    lines.append("")

    # Overall summary
    summary = health.get("summary", {})
    if summary:
        total = summary.get("total", 0)
        healthy = summary.get("healthy", 0)
        warning = summary.get("warning", 0)
        critical = summary.get("critical", 0)
        lines.append(f"Total: {total} | ✅ {healthy} | ⚠️ {warning} | 🔴 {critical}")
        lines.append("")

    # Per-host status (hosts is a list of dicts)
    hosts = health.get("hosts", [])
    for host_info in hosts:
        host_name = host_info.get("name", "unknown")
        score = host_info.get("score", 0)
        reachable = host_info.get("reachable", False)

        if not reachable:
            lines.append(f"- 🔴 `{host_name}`: unreachable")
        elif score >= 80:
            lines.append(f"- ✅ `{host_name}`: healthy (score: {score})")
        elif score >= 50:
            lines.append(f"- ⚠️ `{host_name}`: degraded (score: {score})")
        else:
            lines.append(f"- 🔴 `{host_name}`: critical (score: {score})")

        # Show warnings if any
        warnings = host_info.get("warnings", [])
        for warn in warnings[:3]:
            lines.append(f"    ⚠️ {warn}")

    lines.append("")


def _format_network_section(lines: list[str], network: dict[str, Any]) -> None:
    """Format network diagnostics section."""
    lines.append("**Network:**")
    lines.append("")

    # Gateway/ping
    gateway_data = network.get("gateway")
    # Handle both string and dict formats
    if isinstance(gateway_data, dict):
        gateway_ip = gateway_data.get("gateway", "")
        rtt = gateway_data.get("rtt_ms")
        reachable = gateway_data.get("reachable", False)
        if gateway_ip and reachable:
            if rtt:
                lines.append(f"- ✅ Gateway: `{gateway_ip}` ({rtt:.1f}ms)")
            else:
                lines.append(f"- ✅ Gateway: `{gateway_ip}`")
        elif gateway_ip:
            lines.append(f"- ⚠️ Gateway: `{gateway_ip}` (unreachable)")
        else:
            lines.append("- ⚠️ Gateway: not detected")
    elif gateway_data:
        latency = network.get("gateway_latency")
        if latency:
            lines.append(f"- ✅ Gateway: `{gateway_data}` (latency: {latency})")
        else:
            lines.append(f"- ✅ Gateway: `{gateway_data}`")
    else:
        lines.append("- ⚠️ Gateway: not detected")

    # DNS resolution
    dns_ok = network.get("dns_resolution", False)
    if dns_ok:
        lines.append("- ✅ DNS: resolving")
    else:
        lines.append("- ⚠️ DNS: not resolving")

    # Internet connectivity
    internet = network.get("internet", False)
    if internet:
        lines.append("- ✅ Internet: connected")
    else:
        lines.append("- ⚠️ Internet: no connectivity")

    # Interfaces summary
    interfaces = network.get("interfaces", [])
    if interfaces:
        lines.append(f"- 📶 Interfaces: {len(interfaces)} active")

    lines.append("")


def _format_running_services(lines: list[str], services: dict[str, Any], show_all: bool) -> None:
    """Format running services list."""
    svc_list = services.get("services", [])
    total = services.get("total", len(svc_list))

    lines.append(f"**Running Services:** {total}")
    lines.append("")

    if svc_list:
        max_items = len(svc_list) if show_all else 15
        for svc in svc_list[:max_items]:
            name = svc.get("name", "unknown")
            status = svc.get("status", "")
            lines.append(f"  - `{name}` [{status}]")

        if not show_all and len(svc_list) > max_items:
            lines.append(f"  *... and {len(svc_list) - max_items} more (use --show-all)*")

    lines.append("")


def _format_cron_jobs(lines: list[str], cron_data: dict[str, Any], show_all: bool) -> None:
    """Format cron jobs list."""
    jobs = cron_data.get("jobs", [])
    total = cron_data.get("total", len(jobs))

    lines.append(f"**Cron Jobs:** {total}")
    lines.append("")

    if jobs:
        max_items = len(jobs) if show_all else 10
        for job in jobs[:max_items]:
            schedule = job.get("schedule", "?")
            command = job.get("command", "?")
            human = job.get("human_schedule", "")
            user = job.get("user", "")
            # Truncate long commands
            if len(command) > 50 and not show_all:
                command = command[:47] + "..."
            user_str = f" ({user})" if user else ""
            lines.append(f"  - `{schedule}`{user_str}: {command}")
            if human:
                lines.append(f"    _{human}_")

        if not show_all and len(jobs) > max_items:
            lines.append(f"  *... and {len(jobs) - max_items} more (use --show-all)*")

    lines.append("")


def _format_top_processes(
    lines: list[str],
    proc_data: list[dict[str, Any]] | dict[str, Any] | None,
    show_all: bool,
) -> None:
    """Format top processes list."""
    processes: list[dict[str, Any]] = []
    if isinstance(proc_data, dict):
        raw = proc_data.get("processes")
        if isinstance(raw, list):
            processes = [p for p in raw if isinstance(p, dict)]
    elif isinstance(proc_data, list):
        processes = [p for p in proc_data if isinstance(p, dict)]

    if not processes:
        return

    lines.append("**Top Processes (CPU):**")
    lines.append("")

    max_items = len(processes) if show_all else 10
    for proc in processes[:max_items]:
        user = proc.get("user", "?")
        cpu = proc.get("cpu", 0)
        mem = proc.get("mem", 0)
        cmd = proc.get("command", proc.get("cmd", "?"))
        # Truncate long commands
        if len(cmd) > 40 and not show_all:
            cmd = cmd[:37] + "..."
        lines.append(f"  - `{cpu:.1f}%` CPU, `{mem:.1f}%` MEM ({user}): {cmd}")

    if not show_all and len(processes) > max_items:
        lines.append(f"  *... and {len(processes) - max_items} more (use --show-all)*")

    lines.append("")


def _format_recent_errors(lines: list[str], log_data: dict[str, Any], show_all: bool) -> None:
    """Format recent log errors."""
    log_lines = log_data.get("lines", [])
    count = log_data.get("count", len(log_lines))

    if not log_lines:
        lines.append("**Recent Errors:** none")
        lines.append("")
        return

    icon = "🔴" if count > 10 else ("⚠️" if count > 0 else "✅")
    lines.append(f"{icon} **Recent Errors:** {count}")
    lines.append("")

    max_items = len(log_lines) if show_all else 5
    for line in log_lines[:max_items]:
        # Truncate long lines
        if len(line) > 80 and not show_all:
            line = line[:77] + "..."
        lines.append(f"  `{line}`")

    if not show_all and len(log_lines) > max_items:
        lines.append(f"  *... and {len(log_lines) - max_items} more (use --show-all)*")

    lines.append("")
