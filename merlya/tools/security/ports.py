"""
Merlya Tools - Security port scanning.

Check open ports on remote hosts.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.tools.security.base import (
    DEFAULT_TIMEOUT,
    SecurityResult,
    execute_security_command,
)

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


async def check_open_ports(
    ctx: SharedContext,
    host_name: str,
    include_listening: bool = True,
    include_established: bool = False,
) -> SecurityResult:
    """
    Check open ports on a remote host.

    Args:
        ctx: Shared context.
        host_name: Host name.
        include_listening: Include listening ports.
        include_established: Include established connections.

    Returns:
        SecurityResult with port information.
    """
    try:
        # Build state filter (validated values only)
        states = []
        if include_listening:
            states.append("listen")
        if include_established:
            states.append("established")

        # ss state filter uses fixed keywords only (no user input)
        state_filter = " ".join(f"state {s}" for s in states) if states else ""

        # ss command for modern Linux (all fixed strings, numeric, headerless)
        ss_cmd = f"ss -tulnHp {state_filter} 2>/dev/null".strip()
        result = await execute_security_command(ctx, host_name, ss_cmd, timeout=DEFAULT_TIMEOUT)

        if result.exit_code != 0:
            # Fallback to netstat (fixed command)
            netstat_cmd = "netstat -tuln 2>/dev/null || netstat -an"
            result = await execute_security_command(
                ctx, host_name, netstat_cmd, timeout=DEFAULT_TIMEOUT
            )

        if result.exit_code != 0:
            return SecurityResult(
                success=False,
                error="Failed to check ports: ss and netstat not available",
            )

        # Parse output
        ports = _parse_port_output(result.stdout)
        return SecurityResult(success=True, data=ports)

    except Exception as e:
        logger.error(f"❌ Failed to check ports on {host_name}: {e}")
        return SecurityResult(success=False, error=str(e))


def _parse_port_output(stdout: str) -> list[dict[str, Any]]:
    """Parse ss or netstat output into port list."""
    ports: list[dict[str, Any]] = []
    ss_pattern = re.compile(
        r"^(?P<proto>\S+)\s+(?P<state>\S+)\s+\S+\s+\S+\s+(?P<local>\S+)\s+(?P<peer>\S+)\s*(?P<proc>.*)"
    )

    for line in stdout.strip().splitlines():
        if _should_skip_line(line):
            continue

        match = ss_pattern.match(line)
        if match:
            port_entry = _parse_ss_match(match)
            if port_entry:
                ports.append(port_entry)
            continue

        # Fallback netstat parsing
        parts = line.split()
        if len(parts) >= 4:
            port_entry = _parse_netstat_parts(parts)
            if port_entry:
                ports.append(port_entry)

    return ports


def _should_skip_line(line: str) -> bool:
    """Check if line should be skipped (header/empty)."""
    return (
        not line
        or line.startswith(("Netid", "Proto", "Active", "Recv-Q"))
        or "Local Address" in line
        or ("Local" in line and "Foreign" in line)
    )


def _parse_ss_match(match: re.Match[str]) -> dict[str, Any] | None:
    """Parse ss regex match into port entry."""
    proto = match.group("proto").split("/")[0].lower()
    state = match.group("state")
    local_addr = match.group("local")
    port_value = _extract_port(local_addr)

    if port_value is None:
        return None

    pid, process = _extract_process(match.group("proc") or "")
    return _create_port_entry(port_value, proto, state, local_addr, pid, process)


def _parse_netstat_parts(parts: list[str]) -> dict[str, Any] | None:
    """Parse netstat line parts into port entry."""
    proto = parts[0].lower()
    local_addr = parts[3]
    state = parts[5] if len(parts) > 5 else (parts[1] if len(parts) > 1 else "unknown")
    port_value = _extract_port(local_addr)

    if port_value is None:
        return None

    pid, process = _extract_process(" ".join(parts[6:]) if len(parts) > 6 else "")
    return _create_port_entry(port_value, proto, state, local_addr, pid, process)


def _extract_port(address: str) -> int | str | None:
    """Extract port number from address string."""
    label = address.rsplit(":", 1)[-1] if ":" in address else address
    label = label.strip("[]")
    if not label or label == "*":
        return None
    try:
        return int(label)
    except (TypeError, ValueError):
        return label


def _extract_process(proc_str: str) -> tuple[int | None, str | None]:
    """Extract PID and process name from proc string."""
    pid = None
    process = None
    pid_match = re.search(r"pid=(\d+)", proc_str)
    if pid_match:
        pid = int(pid_match.group(1))
    quoted = re.search(r'"([^"]+)"', proc_str)
    if quoted:
        process = quoted.group(1)
    else:
        slash_match = re.search(r"(\d+)/([^\s]+)", proc_str)
        if slash_match:
            pid = pid or int(slash_match.group(1))
            process = slash_match.group(2)
    return pid, process


def _create_port_entry(
    port_value: int | str,
    protocol: str,
    state: str,
    address: str,
    pid: int | None,
    process: str | None,
) -> dict[str, Any]:
    """Create port entry dictionary."""
    service = port_value if isinstance(port_value, str) and not port_value.isdigit() else None
    return {
        "port": port_value,
        "protocol": protocol,
        "state": state.lower() if isinstance(state, str) else "unknown",
        "address": address,
        "service": service,
        "pid": pid,
        "process": process,
    }
