"""
Merlya Tools - Health summary.

Consolidated health view across one or multiple hosts.
"""

from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger

from merlya.tools.core.models import ToolResult
from merlya.tools.security.base import execute_security_command

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.persistence.models import Host


@dataclass
class HostHealth:
    """Health status for a single host."""

    host_name: str
    reachable: bool = False
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_percent: float = 0.0
    load_1m: float = 0.0
    uptime: str = ""
    critical_services_down: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    score: int = 100  # 0-100, lower is worse


@dataclass
class HealthSummary:
    """Aggregated health summary across hosts."""

    hosts: list[HostHealth] = field(default_factory=list)
    total_hosts: int = 0
    healthy_hosts: int = 0
    warning_hosts: int = 0
    critical_hosts: int = 0
    unreachable_hosts: int = 0


# Thresholds for health scoring
THRESHOLDS = {
    "cpu_warning": 80,
    "cpu_critical": 95,
    "memory_warning": 85,
    "memory_critical": 95,
    "disk_warning": 85,
    "disk_critical": 95,
    "load_warning_factor": 2.0,  # load > 2x CPU cores
}

# Critical services to check
CRITICAL_SERVICES = [
    "sshd",
    "ssh",
    "cron",
    "rsyslog",
    "systemd-journald",
]


async def health_summary(
    ctx: SharedContext,
    hosts: list[str] | None = None,
    include_services: bool = True,
    timeout_per_host: int = 15,
) -> ToolResult:
    """
    Get consolidated health summary for one or multiple hosts.

    Args:
        ctx: Shared context.
        hosts: List of host names (None = all hosts).
        include_services: Check critical services status.
        timeout_per_host: Timeout per host in seconds.

    Returns:
        ToolResult with aggregated health data.
    """
    # Get hosts to check
    if hosts:
        host_entries = []
        for name in hosts:
            entry = await ctx.hosts.get_by_name(name)
            if entry:
                host_entries.append(entry)
            else:
                logger.warning(f"⚠️ Host '{name}' not found in inventory")
    else:
        host_entries = await ctx.hosts.get_all()

    if not host_entries:
        return ToolResult(
            success=False,
            data=None,
            error="❌ No hosts found to check",
        )

    logger.info(f"🏥 Checking health of {len(host_entries)} host(s)...")

    # Check all hosts in parallel with semaphore
    semaphore = asyncio.Semaphore(10)  # Max 10 concurrent checks

    async def check_one(host: Host) -> HostHealth:
        async with semaphore:
            return await _check_host_health(ctx, host, include_services, timeout_per_host)

    results = await asyncio.gather(
        *[check_one(h) for h in host_entries],
        return_exceptions=True,
    )

    # Build summary
    summary = HealthSummary(total_hosts=len(host_entries))

    for result in results:
        if isinstance(result, BaseException):
            logger.warning(f"⚠️ Health check exception: {result}")
            continue

        health = result
        summary.hosts.append(health)

        if not health.reachable:
            summary.unreachable_hosts += 1
        elif health.score < 50:
            summary.critical_hosts += 1
        elif health.score < 80:
            summary.warning_hosts += 1
        else:
            summary.healthy_hosts += 1

    # Sort by score (worst first)
    summary.hosts.sort(key=lambda h: h.score)

    logger.info(
        f"🏥 Health summary: {summary.healthy_hosts} healthy, "
        f"{summary.warning_hosts} warning, {summary.critical_hosts} critical, "
        f"{summary.unreachable_hosts} unreachable"
    )

    return ToolResult(
        success=True,
        data={
            "hosts": [
                {
                    "name": h.host_name,
                    "reachable": h.reachable,
                    "score": h.score,
                    "cpu_percent": h.cpu_percent,
                    "memory_percent": h.memory_percent,
                    "disk_percent": h.disk_percent,
                    "load_1m": h.load_1m,
                    "uptime": h.uptime,
                    "services_down": h.critical_services_down,
                    "warnings": h.warnings,
                    "errors": h.errors,
                }
                for h in summary.hosts
            ],
            "summary": {
                "total": summary.total_hosts,
                "healthy": summary.healthy_hosts,
                "warning": summary.warning_hosts,
                "critical": summary.critical_hosts,
                "unreachable": summary.unreachable_hosts,
            },
        },
    )


async def _check_host_health(
    ctx: SharedContext,
    host: Host,
    include_services: bool,
    timeout: int,
) -> HostHealth:
    """Check health of a single host."""

    health = HostHealth(host_name=host.name)

    try:
        # Single command that gets all metrics at once (efficient)
        cmd = """
LANG=C
echo "---CPU---"
grep -c ^processor /proc/cpuinfo 2>/dev/null || echo 1
cat /proc/loadavg 2>/dev/null | awk '{print $1}'
echo "---MEM---"
cat /proc/meminfo 2>/dev/null | grep -E '^(MemTotal|MemAvailable):' | awk '{print $2}'
echo "---DISK---"
df -P / 2>/dev/null | tail -1 | awk '{print $5}' | tr -d '%'
echo "---UPTIME---"
uptime -p 2>/dev/null || uptime | sed 's/.*up/up/'
"""

        result = await execute_security_command(ctx, host.name, cmd, timeout=timeout)

        if result.exit_code != 0 or not result.stdout:
            health.reachable = False
            health.errors.append("Unable to connect or execute commands")
            health.score = 0
            return health

        health.reachable = True

        # Parse output
        _parse_health_output(health, result.stdout)

        # Check services if requested
        if include_services:
            await _check_critical_services(ctx, host.name, health, timeout)

        # Calculate health score
        _calculate_health_score(health)

    except TimeoutError:
        health.reachable = False
        health.errors.append("Connection timeout")
        health.score = 0
    except Exception as e:
        health.reachable = False
        health.errors.append(str(e)[:100])
        health.score = 0

    return health


def _parse_health_output(health: HostHealth, output: str) -> None:
    """Parse the combined health check output."""
    sections = output.split("---")

    for section in sections:
        lines = section.strip().split("\n")
        if not lines:
            continue

        header = lines[0].strip()

        if header == "CPU":
            if len(lines) >= 3:
                try:
                    cpu_count = int(lines[1].strip())
                    load_1m = float(lines[2].strip())
                    health.load_1m = load_1m

                    # Estimate CPU usage from load average
                    cpu_percent = min(100, (load_1m / cpu_count) * 100)
                    health.cpu_percent = round(cpu_percent, 1)

                    if cpu_percent > THRESHOLDS["cpu_critical"]:
                        health.warnings.append(f"CPU critical: {cpu_percent:.0f}%")
                    elif cpu_percent > THRESHOLDS["cpu_warning"]:
                        health.warnings.append(f"CPU high: {cpu_percent:.0f}%")
                except (ValueError, IndexError):
                    pass

        elif header == "MEM":
            if len(lines) >= 3:
                try:
                    total_kb = int(lines[1].strip())
                    available_kb = int(lines[2].strip())
                    used_kb = total_kb - available_kb
                    memory_percent = (used_kb / total_kb) * 100
                    health.memory_percent = round(memory_percent, 1)

                    if memory_percent > THRESHOLDS["memory_critical"]:
                        health.warnings.append(f"Memory critical: {memory_percent:.0f}%")
                    elif memory_percent > THRESHOLDS["memory_warning"]:
                        health.warnings.append(f"Memory high: {memory_percent:.0f}%")
                except (ValueError, IndexError, ZeroDivisionError):
                    pass

        elif header == "DISK":
            if len(lines) >= 2:
                try:
                    disk_percent = int(lines[1].strip())
                    health.disk_percent = disk_percent

                    if disk_percent > THRESHOLDS["disk_critical"]:
                        health.warnings.append(f"Disk critical: {disk_percent}%")
                    elif disk_percent > THRESHOLDS["disk_warning"]:
                        health.warnings.append(f"Disk high: {disk_percent}%")
                except (ValueError, IndexError):
                    pass

        elif header == "UPTIME" and len(lines) >= 2:
            health.uptime = lines[1].strip()[:50]


async def _check_critical_services(
    ctx: SharedContext,
    host_name: str,
    health: HostHealth,
    timeout: int,
) -> None:
    """Check status of critical services."""
    # Use shlex.quote to safely escape each service name and prevent command injection
    quoted_services = " ".join(shlex.quote(svc) for svc in CRITICAL_SERVICES)
    cmd = f"""
for svc in {quoted_services}; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        echo "$svc:active"
    elif systemctl list-unit-files "$svc.service" 2>/dev/null | grep -q enabled; then
        echo "$svc:inactive"
    fi
done
"""

    try:
        result = await execute_security_command(ctx, host_name, cmd, timeout=timeout)

        if result.exit_code == 0 and result.stdout:
            for line in result.stdout.strip().split("\n"):
                if ":" in line:
                    svc, status = line.split(":", 1)
                    if status.strip() == "inactive":
                        health.critical_services_down.append(svc.strip())
                        health.warnings.append(f"Service '{svc}' is down")
    except Exception:
        pass  # Non-critical, don't fail the health check


def _calculate_health_score(health: HostHealth) -> None:
    """Calculate overall health score (0-100)."""
    if not health.reachable:
        health.score = 0
        return

    score = 100

    # CPU penalties
    if health.cpu_percent > THRESHOLDS["cpu_critical"]:
        score -= 30
    elif health.cpu_percent > THRESHOLDS["cpu_warning"]:
        score -= 15

    # Memory penalties
    if health.memory_percent > THRESHOLDS["memory_critical"]:
        score -= 30
    elif health.memory_percent > THRESHOLDS["memory_warning"]:
        score -= 15

    # Disk penalties
    if health.disk_percent > THRESHOLDS["disk_critical"]:
        score -= 25
    elif health.disk_percent > THRESHOLDS["disk_warning"]:
        score -= 10

    # Service penalties
    score -= len(health.critical_services_down) * 10

    # Error penalties
    score -= len(health.errors) * 20

    health.score = max(0, min(100, score))
