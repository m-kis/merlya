"""
Merlya Setup - known_hosts parser.

Parses ~/.ssh/known_hosts file format.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger

from merlya.setup.parsers.utils import SKIP_HOSTNAMES, is_valid_ip, safe_parse_port

if TYPE_CHECKING:
    from pathlib import Path

    from merlya.setup.models import HostData


async def parse_known_hosts(path: Path) -> list[HostData]:
    """
    Parse known_hosts and extract unique hostnames.

    Note: known_hosts only contains hostnames, no connection details.
    These hosts will need SSH config or manual configuration.

    Args:
        path: Path to known_hosts file.

    Returns:
        List of HostData objects.
    """
    from merlya.setup.models import HostData

    hosts: list[HostData] = []
    hosts_seen: set[str] = set()

    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split()
            if len(parts) < 3:
                continue

            host_part = parts[0]

            # Skip hashed entries - we can't resolve them
            if host_part.startswith("|1|"):
                continue

            # Parse comma-separated hosts (e.g., "hostname,ip")
            for h in host_part.split(","):
                # Remove [port] suffix and brackets
                port = 22
                port_match = re.search(r":(\d+)$", h)
                if port_match:
                    port = safe_parse_port(port_match.group(1), 22)
                    h = re.sub(r":\d+$", "", h)
                h = h.strip("[]")

                if not h or h in SKIP_HOSTNAMES or h in hosts_seen:
                    continue

                is_ip = is_valid_ip(h)

                hosts_seen.add(h)
                hosts.append(
                    HostData(
                        name=h,
                        hostname=h if is_ip else None,
                        port=port,
                        tags=["known-hosts"],
                        source="~/.ssh/known_hosts",
                    )
                )

    except Exception as e:
        logger.error(f"❌ Failed to parse known_hosts: {e}")

    return hosts


def count_known_hosts(path: Path) -> int:
    """Count unique hosts in known_hosts."""
    hosts_seen: set[str] = set()
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 3:
                host_part = parts[0]
                if host_part.startswith("|1|"):
                    continue
                for h in host_part.split(","):
                    h = re.sub(r":\d+$", "", h)
                    h = h.strip("[]")
                    if h and h not in SKIP_HOSTNAMES:
                        hosts_seen.add(h)
    except Exception:
        pass
    return len(hosts_seen)
