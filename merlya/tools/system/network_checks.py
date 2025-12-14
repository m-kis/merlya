"""
Merlya Tools - Network check helpers.

Sub-checks used by check_network() to keep network.py focused and under size limits.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from merlya.tools.core.models import ToolResult
from merlya.tools.security.base import execute_security_command

if TYPE_CHECKING:
    from merlya.core.context import SharedContext

_PingFn = Callable[..., Awaitable[ToolResult]]
_DNSLookupFn = Callable[..., Awaitable[ToolResult]]


async def get_interface_info(ctx: SharedContext, host: str) -> dict[str, Any]:
    """Get network interface information."""
    cmd = "ip -4 addr show 2>/dev/null || ifconfig 2>/dev/null"
    result = await execute_security_command(ctx, host, cmd, timeout=10)

    interfaces: list[dict[str, str]] = []
    if result.exit_code == 0:
        current_iface: str | None = None
        for line in result.stdout.split("\n"):
            if not line.startswith(" ") and ":" in line:
                parts = line.split(":")
                current_iface = parts[1].strip().split("@")[0] if len(parts) > 1 else parts[0]
            elif "inet " in line and current_iface:
                match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", line)
                if match:
                    interfaces.append({"name": current_iface, "ip": match.group(1)})

    return {"interfaces": interfaces}


async def check_gateway(ctx: SharedContext, host: str, *, ping_fn: _PingFn) -> dict[str, Any]:
    """Check default gateway connectivity."""
    cmd = "ip route | grep default | awk '{print $3}' | head -1"
    result = await execute_security_command(ctx, host, cmd, timeout=5)

    gateway = result.stdout.strip() if result.exit_code == 0 else None
    if not gateway:
        return {"gateway": None, "reachable": False}

    ping_result = await ping_fn(ctx, host, gateway, count=2, timeout=2)
    return {
        "gateway": gateway,
        "reachable": ping_result.data.get("reachable", False) if ping_result.success else False,
        "rtt_ms": ping_result.data.get("rtt_avg_ms", 0) if ping_result.success else 0,
    }


async def check_dns(
    ctx: SharedContext, host: str, *, dns_lookup_fn: _DNSLookupFn
) -> dict[str, Any]:
    """Check DNS resolution."""
    cmd = "grep '^nameserver' /etc/resolv.conf 2>/dev/null | head -1 | awk '{print $2}'"
    ns_result = await execute_security_command(ctx, host, cmd, timeout=5)
    nameserver = ns_result.stdout.strip() if ns_result.exit_code == 0 else "unknown"

    dns_result = await dns_lookup_fn(ctx, host, "google.com", "A")
    return {
        "nameserver": nameserver,
        "working": dns_result.data.get("resolved", False) if dns_result.success else False,
        "test_domain": "google.com",
    }


async def check_internet(ctx: SharedContext, host: str, *, ping_fn: _PingFn) -> dict[str, Any]:
    """Check internet connectivity."""
    targets = ["8.8.8.8", "1.1.1.1"]
    for target in targets:
        ping_result = await ping_fn(ctx, host, target, count=2, timeout=3)
        if ping_result.success and ping_result.data.get("reachable"):
            return {
                "reachable": True,
                "tested_target": target,
                "rtt_ms": ping_result.data.get("rtt_avg_ms", 0),
            }

    return {"reachable": False, "tested_targets": targets}
