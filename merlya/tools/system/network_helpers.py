"""
Merlya Tools - Network helpers.

Parsing and validation helpers used by network diagnostics tools.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass


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


def parse_ping_output(target: str, output: str, exit_code: int) -> PingResult:
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


def parse_traceroute_output(output: str) -> list[dict[str, object]]:
    """Parse traceroute output into hop list."""
    hops: list[dict[str, object]] = []

    for line in output.split("\n"):
        line = line.strip()
        if not line or line.startswith(("traceroute", "tracepath")):
            continue

        match = re.match(r"^\s*(\d+)\s+(.+)", line)
        if not match:
            continue

        hop_num = int(match.group(1))
        rest = match.group(2)

        if "* * *" in rest or rest.strip() == "*":
            hops.append({"hop": hop_num, "host": "*", "rtt_ms": None})
            continue

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


def is_valid_ping_target(target: str) -> bool:
    """Validate ping target to prevent injection."""
    try:
        ipaddress.ip_address(target)
        return True
    except ValueError:
        pass

    if re.match(
        r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?"
        r"(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$",
        target,
    ):
        return len(target) <= 253

    return False


def is_valid_domain(domain: str) -> bool:
    """Validate domain name."""
    return is_valid_ping_target(domain)
