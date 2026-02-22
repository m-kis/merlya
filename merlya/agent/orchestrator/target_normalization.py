"""
Target resolution for the orchestrator.

Resolves target specifications to (host, username) pairs.

Supported formats:
  - "local" / "localhost" / "127.0.0.1" / "::1"  → local execution
  - "@name"               → inventory lookup by name, returns (hostname, username)
  - "user@host"           → explicit username + IP/hostname
  - "1.2.3.4"             → direct IP, no username
  - anything else         → rejected, defaults to local
"""

from __future__ import annotations

import re as _re
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from merlya.core.context import SharedContext

_LOCAL_NAMES = frozenset(("local", "localhost", "127.0.0.1", "::1"))
_IP_RE = _re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}")


async def resolve_target(
    target: str,
    context: SharedContext | None = None,
) -> tuple[str, str | None]:
    """
    Resolve a target specification to (host, username).

    Args:
        target: Target string in one of the supported formats.
        context: Optional SharedContext for inventory lookups.

    Returns:
        (host, username) where host is "local", an IP, or a hostname,
        and username is None if not specified.
    """
    # Local aliases
    if target.lower() in _LOCAL_NAMES:
        return "local", None

    # "user@host" syntax — explicit username + host (not starting with @)
    if "@" in target and not target.startswith("@"):
        username, host = target.split("@", 1)
        if username and host:
            logger.debug(f"Resolved user@host: username={username}, host={host}")
            return host, username

    # Direct IP — trust it, username must come from elsewhere
    if _IP_RE.fullmatch(target):
        return target, None

    # "@name" — inventory lookup
    if target.startswith("@") and context:
        name = target[1:]
        entry = (
            await context.hosts.get_by_name(name)
            or await context.hosts.get_by_hostname(name)
        )
        if entry:
            logger.debug(
                f"Resolved @{name} → hostname={entry.hostname}, username={entry.username}"
            )
            return entry.hostname, entry.username
        logger.warning(f"Host '@{name}' not found in inventory, defaulting to local")
        return "local", None

    # Unknown target (plain hostname without @) — reject to prevent hallucinations
    logger.warning(
        f"Target '{target}' has no @ prefix and is not an IP or local alias. "
        "Use '@hostname' for inventory hosts. Defaulting to local."
    )
    return "local", None
