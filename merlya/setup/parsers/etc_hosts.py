"""
Merlya Setup - /etc/hosts parser.

Parses /etc/hosts file format.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from merlya.setup.parsers.utils import SKIP_HOSTNAMES, is_valid_ip

if TYPE_CHECKING:
    from pathlib import Path

    from merlya.setup.models import HostData


async def parse_etc_hosts(path: Path) -> list[HostData]:
    """
    Parse /etc/hosts file and extract hosts.

    Args:
        path: Path to /etc/hosts file.

    Returns:
        List of HostData objects.
    """
    from merlya.setup.models import HostData

    hosts: list[HostData] = []

    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split()
            if len(parts) < 2:
                continue

            ip_addr = parts[0]
            if not is_valid_ip(ip_addr):
                continue

            # First valid hostname after IP
            for hostname in parts[1:]:
                hostname_lower = hostname.lower()
                if hostname_lower in SKIP_HOSTNAMES:
                    continue

                hosts.append(
                    HostData(
                        name=hostname,
                        hostname=ip_addr,
                        port=22,
                        tags=["etc-hosts"],
                        source="/etc/hosts",
                    )
                )
                # Only take first valid hostname to avoid duplicates
                break

    except Exception as e:
        logger.error(f"❌ Failed to parse /etc/hosts: {e}")

    return hosts


def count_etc_hosts(path: Path) -> int:
    """Count hosts in /etc/hosts."""
    count = 0
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                parts = line.split()
                if len(parts) >= 2:
                    hostname = parts[1].lower()
                    if hostname not in SKIP_HOSTNAMES:
                        count += 1
    except Exception:
        pass
    return count
