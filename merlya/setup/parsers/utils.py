"""
Merlya Setup - Parser utilities.

Common utilities used by inventory parsers.
"""

from __future__ import annotations

import ipaddress


def is_valid_ip(s: str) -> bool:
    """Check if string is a valid IP address."""
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


def safe_parse_port(value: str | int | None, default: int = 22) -> int:
    """
    Safely parse a port value with validation.

    Args:
        value: Port value (string or int).
        default: Default port if parsing fails.

    Returns:
        Valid port number.
    """
    if value is None:
        return default
    try:
        port = int(value)
        if 1 <= port <= 65535:
            return port
        return default
    except (ValueError, TypeError):
        return default


# Hosts to skip during import (localhost variants)
SKIP_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "local",
    "broadcasthost",
    "ip6-localhost",
    "ip6-loopback",
    "ip6-localnet",
    "ip6-mcastprefix",
    "ip6-allnodes",
    "ip6-allrouters",
    "ip6-allhosts",
}
