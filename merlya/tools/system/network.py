"""
Merlya Tools - Network diagnostics.

Network connectivity and diagnostics tools.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.tools.core.models import ToolResult
from merlya.tools.security.base import execute_security_command

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


@dataclass
class PingResult:
    """Result of a ping test."""

    target: str
    reachable: bool
    packets_sent: int = 0
    packets_received: int = 0
    packet_loss_percent: float = 0.0
    rtt_min: float = 0.0
    rtt_avg: float = 0.0
    rtt_max: float = 0.0


@dataclass
class DNSResult:
    """Result of a DNS lookup."""

    query: str
    resolved: bool
    addresses: list[str] = field(default_factory=list)
    nameserver: str = ""
    response_time_ms: float = 0.0


@dataclass
class PortCheckResult:
    """Result of a port connectivity check."""

    host: str
    port: int
    open: bool
    response_time_ms: float = 0.0


async def check_network(
    ctx: SharedContext,
    host: str,
    target: str | None = None,
    check_dns: bool = True,
    check_gateway: bool = True,
    check_internet: bool = True,
) -> ToolResult:
    """
    Perform network diagnostics from a remote host.

    Args:
        ctx: Shared context.
        host: Host name from inventory.
        target: Optional specific target to check.
        check_dns: Check DNS resolution.
        check_gateway: Check default gateway.
        check_internet: Check internet connectivity.

    Returns:
        ToolResult with network diagnostics.
    """
    logger.info(f"🌐 Running network diagnostics on {host}...")

    results: dict[str, Any] = {
        "host": host,
        "checks": [],
        "issues": [],
    }

    # Get network interfaces info
    iface_info = await _get_interface_info(ctx, host)
    results["interfaces"] = iface_info

    # Check gateway connectivity
    if check_gateway:
        gateway_result = await _check_gateway(ctx, host)
        results["gateway"] = gateway_result
        results["checks"].append(
            {
                "name": "gateway",
                "status": "ok" if gateway_result.get("reachable") else "failed",
                "details": gateway_result,
            }
        )
        if not gateway_result.get("reachable"):
            results["issues"].append("Default gateway unreachable")

    # Check DNS
    if check_dns:
        dns_result = await _check_dns(ctx, host)
        results["dns"] = dns_result
        results["checks"].append(
            {
                "name": "dns",
                "status": "ok" if dns_result.get("working") else "failed",
                "details": dns_result,
            }
        )
        if not dns_result.get("working"):
            results["issues"].append("DNS resolution failed")

    # Check internet connectivity
    if check_internet:
        internet_result = await _check_internet(ctx, host)
        results["internet"] = internet_result
        results["checks"].append(
            {
                "name": "internet",
                "status": "ok" if internet_result.get("reachable") else "failed",
                "details": internet_result,
            }
        )
        if not internet_result.get("reachable"):
            results["issues"].append("Internet unreachable")

    # Check specific target if provided
    if target:
        target_result = await ping(ctx, host, target)
        if target_result.success:
            results["target"] = target_result.data
            results["checks"].append(
                {
                    "name": f"target:{target}",
                    "status": "ok" if target_result.data.get("reachable") else "failed",
                    "details": target_result.data,
                }
            )

    # Determine overall status
    failed_checks = [c for c in results["checks"] if c["status"] == "failed"]
    if failed_checks:
        results["status"] = "degraded" if len(failed_checks) < len(results["checks"]) else "failed"
    else:
        results["status"] = "healthy"

    return ToolResult(
        success=True,
        data=results,
    )


async def ping(
    ctx: SharedContext,
    host: str,
    target: str,
    count: int = 4,
    timeout: int = 5,
) -> ToolResult:
    """
    Ping a target from a remote host.

    Args:
        ctx: Shared context.
        host: Host name from inventory.
        target: Target to ping (IP or hostname).
        count: Number of ping packets.
        timeout: Ping timeout in seconds.

    Returns:
        ToolResult with ping statistics.
    """
    # Validate target
    if not _is_valid_ping_target(target):
        return ToolResult(
            success=False,
            data=None,
            error=f"❌ Invalid ping target: {target}",
        )

    cmd = f"LANG=C ping -c {min(count, 10)} -W {min(timeout, 30)} {target} 2>&1"
    result = await execute_security_command(ctx, host, cmd, timeout=timeout * count + 10)

    ping_result = _parse_ping_output(target, result.stdout, result.exit_code)

    return ToolResult(
        success=True,
        data={
            "target": ping_result.target,
            "reachable": ping_result.reachable,
            "packets_sent": ping_result.packets_sent,
            "packets_received": ping_result.packets_received,
            "packet_loss_percent": ping_result.packet_loss_percent,
            "rtt_min_ms": ping_result.rtt_min,
            "rtt_avg_ms": ping_result.rtt_avg,
            "rtt_max_ms": ping_result.rtt_max,
        },
    )


async def traceroute(
    ctx: SharedContext,
    host: str,
    target: str,
    max_hops: int = 20,
) -> ToolResult:
    """
    Run traceroute from a remote host.

    Args:
        ctx: Shared context.
        host: Host name from inventory.
        target: Target to trace.
        max_hops: Maximum number of hops.

    Returns:
        ToolResult with traceroute output.
    """
    if not _is_valid_ping_target(target):
        return ToolResult(
            success=False,
            data=None,
            error=f"❌ Invalid target: {target}",
        )

    # Try traceroute, fall back to tracepath
    cmd = f"""
if command -v traceroute >/dev/null 2>&1; then
    LANG=C traceroute -m {min(max_hops, 30)} -w 2 {target} 2>&1
elif command -v tracepath >/dev/null 2>&1; then
    LANG=C tracepath -m {min(max_hops, 30)} {target} 2>&1
else
    echo "No traceroute or tracepath available"
    exit 1
fi
"""

    result = await execute_security_command(ctx, host, cmd, timeout=max_hops * 3)

    if result.exit_code != 0 and "No traceroute" in result.stdout:
        return ToolResult(
            success=False,
            data=None,
            error="❌ Neither traceroute nor tracepath available on host",
        )

    hops = _parse_traceroute_output(result.stdout)

    return ToolResult(
        success=True,
        data={
            "target": target,
            "hops": hops,
            "total_hops": len(hops),
            "raw_output": result.stdout[:2000],
        },
    )


async def check_port(
    ctx: SharedContext,
    host: str,
    target_host: str,
    port: int,
    timeout: int = 5,
) -> ToolResult:
    """
    Check if a port is reachable from a remote host.

    Args:
        ctx: Shared context.
        host: Host name from inventory.
        target_host: Target to check.
        port: Port number.
        timeout: Connection timeout.

    Returns:
        ToolResult with port status.
    """
    if not 1 <= port <= 65535:
        return ToolResult(
            success=False,
            data=None,
            error=f"❌ Invalid port: {port}",
        )

    if not _is_valid_ping_target(target_host):
        return ToolResult(
            success=False,
            data=None,
            error=f"❌ Invalid target: {target_host}",
        )

    # Use timeout + nc or bash /dev/tcp
    cmd = f"""
if command -v nc >/dev/null 2>&1; then
    timeout {timeout} nc -zv {target_host} {port} 2>&1
elif command -v timeout >/dev/null 2>&1; then
    timeout {timeout} bash -c 'echo > /dev/tcp/{target_host}/{port}' 2>&1 && echo "Connection succeeded"
else
    echo "No nc or timeout available"
    exit 1
fi
"""

    result = await execute_security_command(ctx, host, cmd, timeout=timeout + 5)

    is_open = (
        result.exit_code == 0
        or "succeeded" in result.stdout.lower()
        or "open" in result.stdout.lower()
        or "connected" in result.stdout.lower()
    )

    return ToolResult(
        success=True,
        data={
            "target": target_host,
            "port": port,
            "open": is_open,
            "details": result.stdout[:200] if result.stdout else result.stderr[:200],
        },
    )


async def dns_lookup(
    ctx: SharedContext,
    host: str,
    query: str,
    record_type: str = "A",
) -> ToolResult:
    """
    Perform DNS lookup from a remote host.

    Args:
        ctx: Shared context.
        host: Host name from inventory.
        query: Domain to lookup.
        record_type: DNS record type (A, AAAA, MX, NS, TXT, etc.).

    Returns:
        ToolResult with DNS records.
    """
    if not _is_valid_domain(query):
        return ToolResult(
            success=False,
            data=None,
            error=f"❌ Invalid domain: {query}",
        )

    record_type = record_type.upper()
    if record_type not in {"A", "AAAA", "MX", "NS", "TXT", "CNAME", "SOA", "PTR"}:
        return ToolResult(
            success=False,
            data=None,
            error=f"❌ Invalid record type: {record_type}",
        )

    # Use dig if available, fall back to host, then nslookup
    cmd = f"""
if command -v dig >/dev/null 2>&1; then
    dig +short {record_type} {query} 2>&1
elif command -v host >/dev/null 2>&1; then
    host -t {record_type} {query} 2>&1
else
    nslookup -type={record_type} {query} 2>&1
fi
"""

    result = await execute_security_command(ctx, host, cmd, timeout=15)

    records = []
    if result.exit_code == 0 and result.stdout:
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line and not line.startswith(";"):
                records.append(line)

    return ToolResult(
        success=True,
        data={
            "query": query,
            "record_type": record_type,
            "records": records,
            "resolved": len(records) > 0,
        },
    )


# =============================================================================
# Helper Functions
# =============================================================================


async def _get_interface_info(ctx: SharedContext, host: str) -> dict:
    """Get network interface information."""
    cmd = "ip -4 addr show 2>/dev/null || ifconfig 2>/dev/null"
    result = await execute_security_command(ctx, host, cmd, timeout=10)

    interfaces = []
    if result.exit_code == 0:
        # Simple parsing - get interface names and IPs
        current_iface = None
        for line in result.stdout.split("\n"):
            if not line.startswith(" ") and ":" in line:
                parts = line.split(":")
                current_iface = parts[1].strip().split("@")[0] if len(parts) > 1 else parts[0]
            elif "inet " in line and current_iface:
                match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", line)
                if match:
                    interfaces.append(
                        {
                            "name": current_iface,
                            "ip": match.group(1),
                        }
                    )

    return {"interfaces": interfaces}


async def _check_gateway(ctx: SharedContext, host: str) -> dict:
    """Check default gateway connectivity."""
    # Get default gateway
    cmd = "ip route | grep default | awk '{print $3}' | head -1"
    result = await execute_security_command(ctx, host, cmd, timeout=5)

    gateway = result.stdout.strip() if result.exit_code == 0 else None
    if not gateway:
        return {"gateway": None, "reachable": False}

    # Ping gateway
    ping_result = await ping(ctx, host, gateway, count=2, timeout=2)

    return {
        "gateway": gateway,
        "reachable": ping_result.data.get("reachable", False) if ping_result.success else False,
        "rtt_ms": ping_result.data.get("rtt_avg_ms", 0) if ping_result.success else 0,
    }


async def _check_dns(ctx: SharedContext, host: str) -> dict:
    """Check DNS resolution."""
    # Get nameserver
    cmd = "grep '^nameserver' /etc/resolv.conf 2>/dev/null | head -1 | awk '{print $2}'"
    ns_result = await execute_security_command(ctx, host, cmd, timeout=5)
    nameserver = ns_result.stdout.strip() if ns_result.exit_code == 0 else "unknown"

    # Try to resolve a known domain
    dns_result = await dns_lookup(ctx, host, "google.com", "A")

    return {
        "nameserver": nameserver,
        "working": dns_result.data.get("resolved", False) if dns_result.success else False,
        "test_domain": "google.com",
    }


async def _check_internet(ctx: SharedContext, host: str) -> dict:
    """Check internet connectivity."""
    # Try multiple targets
    targets = ["8.8.8.8", "1.1.1.1"]

    for target in targets:
        ping_result = await ping(ctx, host, target, count=2, timeout=3)
        if ping_result.success and ping_result.data.get("reachable"):
            return {
                "reachable": True,
                "tested_target": target,
                "rtt_ms": ping_result.data.get("rtt_avg_ms", 0),
            }

    return {"reachable": False, "tested_targets": targets}


def _parse_ping_output(target: str, output: str, exit_code: int) -> PingResult:
    """Parse ping command output."""
    result = PingResult(target=target, reachable=exit_code == 0)

    # Parse packet statistics
    # Format: "X packets transmitted, Y received, Z% packet loss"
    pkt_match = re.search(
        r"(\d+) packets transmitted, (\d+) (?:packets )?received, (\d+(?:\.\d+)?)% packet loss",
        output,
    )
    if pkt_match:
        result.packets_sent = int(pkt_match.group(1))
        result.packets_received = int(pkt_match.group(2))
        result.packet_loss_percent = float(pkt_match.group(3))
        result.reachable = result.packets_received > 0

    # Parse RTT statistics
    # Format: "rtt min/avg/max/mdev = X/Y/Z/W ms"
    rtt_match = re.search(
        r"(?:rtt|round-trip) min/avg/max(?:/mdev)? = ([\d.]+)/([\d.]+)/([\d.]+)",
        output,
    )
    if rtt_match:
        result.rtt_min = float(rtt_match.group(1))
        result.rtt_avg = float(rtt_match.group(2))
        result.rtt_max = float(rtt_match.group(3))

    return result


def _parse_traceroute_output(output: str) -> list[dict]:
    """Parse traceroute output into hop list."""
    hops = []

    for line in output.split("\n"):
        line = line.strip()
        if not line or line.startswith("traceroute") or line.startswith("tracepath"):
            continue

        # Match hop number at start
        match = re.match(r"^\s*(\d+)\s+(.+)", line)
        if match:
            hop_num = int(match.group(1))
            rest = match.group(2)

            # Check for timeout
            if "* * *" in rest or rest.strip() == "*":
                hops.append({"hop": hop_num, "host": "*", "rtt_ms": None})
            else:
                # Try to extract host and RTT
                host_match = re.search(r"([\w\-.]+(?:\s+\([\d.]+\))?)", rest)
                rtt_match = re.search(r"([\d.]+)\s*ms", rest)

                hops.append(
                    {
                        "hop": hop_num,
                        "host": host_match.group(1) if host_match else "unknown",
                        "rtt_ms": float(rtt_match.group(1)) if rtt_match else None,
                    }
                )

    return hops


def _is_valid_ping_target(target: str) -> bool:
    """Validate ping target to prevent injection."""
    # Allow IP addresses
    if re.match(r"^(\d{1,3}\.){3}\d{1,3}$", target):
        return True

    # Allow valid hostnames
    if re.match(
        r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$",
        target,
    ):
        return len(target) <= 253

    return False


def _is_valid_domain(domain: str) -> bool:
    """Validate domain name."""
    return _is_valid_ping_target(domain)
