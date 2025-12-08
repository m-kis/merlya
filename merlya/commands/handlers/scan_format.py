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
    all_disks: bool = False
    include_docker: bool = True
    include_updates: bool = True
    include_logins: bool = True
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
    lines.append(
        f"**Critical:** {result.critical_count} | **Warnings:** {result.warning_count}"
    )
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


def _format_security_section(
    lines: list[str], sec_data: dict[str, Any], show_all: bool
) -> None:
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
        icon = "🔴" if total > 50 else ("⚠️" if total > 20 else "ℹ️")  # noqa: RUF001
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
        icon = "🔴" if security > 5 else ("⚠️" if total > 10 else "ℹ️")  # noqa: RUF001
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
    icon = "⚠️" if issues else "ℹ️"  # noqa: RUF001
    lines.append(f"{icon} **Users:** {len(shell_users)} with shell access")

    if shell_users:
        max_users = len(shell_users) if show_all else 8
        user_names = [
            u.get("username", u) if isinstance(u, dict) else str(u)
            for u in shell_users[:max_users]
        ]
        lines.append(f"   `{', '.join(user_names)}`")
        if not show_all and len(shell_users) > 8:
            lines.append(f"   *... and {len(shell_users) - 8} more (use --show-all)*")

    if issues:
        for issue in issues[:3]:
            lines.append(f"   ⚠️ {issue}")
    lines.append("")
