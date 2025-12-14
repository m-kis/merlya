"""
Merlya Tools - Network diagnostics.

Network connectivity and diagnostics tools.
"""

from __future__ import annotations

import shlex
import time
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.tools.core.models import ToolResult
from merlya.tools.security.base import execute_security_command

from .network_checks import (
    check_dns as _check_dns,
)
from .network_checks import (
    check_gateway as _check_gateway,
)
from .network_checks import (
    check_internet as _check_internet,
)
from .network_checks import (
    get_interface_info as _get_interface_info,
)
from .network_helpers import (
    is_valid_domain as _is_valid_domain,
)
from .network_helpers import (
    is_valid_ping_target as _is_valid_ping_target,
)
from .network_helpers import (
    parse_ping_output as _parse_ping_output,
)
from .network_helpers import (
    parse_traceroute_output as _parse_traceroute_output,
)

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


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
        gateway_result = await _check_gateway(ctx, host, ping_fn=ping)
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
        dns_result = await _check_dns(ctx, host, dns_lookup_fn=dns_lookup)
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
        internet_result = await _check_internet(ctx, host, ping_fn=ping)
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

    # Use shlex.quote to safely escape the target and prevent command injection
    safe_target = shlex.quote(target)
    cmd = f"LANG=C ping -c {min(count, 10)} -W {min(timeout, 30)} {safe_target} 2>&1"
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

    # Use shlex.quote to safely escape the target and prevent command injection
    safe_target = shlex.quote(target)

    # Try traceroute, fall back to tracepath
    cmd = f"""
if command -v traceroute >/dev/null 2>&1; then
    LANG=C traceroute -m {min(max_hops, 30)} -w 2 {safe_target} 2>&1
elif command -v tracepath >/dev/null 2>&1; then
    LANG=C tracepath -m {min(max_hops, 30)} {safe_target} 2>&1
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

    # Use shlex.quote to safely escape the target_host and prevent command injection
    safe_target_host = shlex.quote(target_host)

    # Use timeout + nc or bash /dev/tcp
    cmd = f"""
if command -v nc >/dev/null 2>&1; then
    timeout {timeout} nc -zv {safe_target_host} {port} 2>&1
elif command -v timeout >/dev/null 2>&1; then
    timeout {timeout} bash -c 'echo > /dev/tcp/{safe_target_host}/{port}' 2>&1 && echo "Connection succeeded"
else
    echo "No nc or timeout available"
    exit 1
fi
"""

    # Measure port connection time
    start_time = time.monotonic()
    result = await execute_security_command(ctx, host, cmd, timeout=timeout + 5)
    end_time = time.monotonic()
    response_time_ms = (end_time - start_time) * 1000

    is_open = (
        result.exit_code == 0
        or "succeeded" in (result.stdout or "").lower()
        or "open" in (result.stdout or "").lower()
        or "connected" in (result.stdout or "").lower()
    )

    return ToolResult(
        success=True,
        data={
            "target": target_host,
            "port": port,
            "open": is_open,
            "response_time_ms": response_time_ms,
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

    # Use shlex.quote to safely escape the query and prevent command injection
    safe_query = shlex.quote(query)

    # Use dig if available, fall back to host, then nslookup
    cmd = f"""
if command -v dig >/dev/null 2>&1; then
    dig +short {record_type} {safe_query} 2>&1
elif command -v host >/dev/null 2>&1; then
    host -t {record_type} {safe_query} 2>&1
else
    nslookup -type={record_type} {safe_query} 2>&1
fi
"""

    # Measure DNS lookup time
    start_time = time.monotonic()
    result = await execute_security_command(ctx, host, cmd, timeout=15)
    end_time = time.monotonic()
    response_time_ms = (end_time - start_time) * 1000

    records: list[str] = []
    if result.exit_code == 0 and result.stdout:
        output = result.stdout.strip()

        # Détection du format et parsing approprié
        if "has address" in output or "has IPv6" in output:
            # Format host (ex: "example.com has address 93.184.216.34")
            for line in output.split("\n"):
                line = line.strip()
                if line and ("has address" in line or "has IPv6" in line):
                    # Extraire le dernier token (l'adresse IP)
                    tokens = line.split()
                    if tokens:
                        address = tokens[-1].strip()
                        if address:
                            records.append(address)
        elif "Answer:" in output or "question" in output.lower():
            # Format nslookup (ex: "Answer:\nName:    example.com\nAddress: 93.184.216.34")
            in_answer_section = False
            for line in output.split("\n"):
                line = line.strip()
                if "Answer:" in line:
                    in_answer_section = True
                    continue
                elif in_answer_section and line:
                    # Dans la section Answer, extraire les adresses
                    if "Address:" in line or "Addresses:" in line:
                        # Format: "Address: 93.184.216.34" ou "Addresses: 93.184.216.34,2606:2800:220:1:248:1893:25c8:1946"
                        address_part = line.split(":", 1)[1].strip()
                        # Gérer les adresses multiples séparées par des virgules
                        for addr in address_part.split(","):
                            addr = addr.strip()
                            if addr:
                                records.append(addr)
                    elif ":" in line and not line.startswith("Name:"):
                        # Autre format avec adresse après deux-points
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            addr = parts[1].strip()
                            if addr:
                                records.append(addr)
        else:
            # Format dig +short (lignes simples ou avec en-têtes dig)
            # Garder le parsing existant pour les lignes simples
            for line in output.split("\n"):
                line = line.strip()
                # Ignorer les lignes vides et les commentaires
                if line and not line.startswith(";"):
                    records.append(line)

    return ToolResult(
        success=True,
        data={
            "query": query,
            "record_type": record_type,
            "records": records,
            "resolved": len(records) > 0,
            "response_time_ms": response_time_ms,
        },
    )
