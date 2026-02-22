"""
Target resolution for the orchestrator.

Resolves target specifications to (host, username) pairs.

Supported formats:
  - "local" / "localhost" / "127.0.0.1" / "::1"  → local execution
  - "@name"               → inventory lookup by name, returns (hostname, username)
  - "user@host"           → explicit username + IP/hostname
  - "1.2.3.4"             → direct IP, no username
  - anything else         → rejected, defaults to local

Disambiguation — @name vs @secret:
  - "@name" as a *target argument* → inventory lookup (this module)
  - "@name" inside a *command string* → secret keyring reference (resolve_secrets)
  Both namespaces are separate; collisions are detected and logged.
  Convention: secret names SHOULD use ":" namespacing (e.g. "@db:password"),
  which host names cannot contain, making the distinction unambiguous.
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
    if target.startswith("@"):
        if not context:
            logger.warning(
                f"Target '{target}' requires inventory context, but none provided. "
                "Defaulting to local."
            )
            return "local", None

        name = target[1:]

        # Disambiguation: "@name:with:colons" looks like a secret reference.
        # Secret names use ":" namespacing (e.g. "@db:password", "@elevation:host:pass").
        # Host names cannot contain ":", so this is an unambiguous signal.
        if ":" in name:
            logger.error(
                f"Target '{target}' looks like a secret reference (contains ':'), "
                "not an inventory host. "
                "Use '@hostname' (no colons) for hosts. "
                "Secret references belong inside command strings, not as targets."
            )
            return "local", None

        # Collision detection: warn if the same name exists as both a host and a secret.
        # Inventory takes precedence when used as a target argument.
        if context.secrets.has(name):
            logger.warning(
                f"Name collision: '@{name}' is both an inventory host target and a "
                f"known secret. Resolving as inventory host. "
                f"To reference the secret, use '@{name}' inside a command string, "
                f"not as a target. Consider renaming the secret with a namespace "
                f"(e.g. 'service:{name}') to avoid ambiguity."
            )

        entry = await context.hosts.get_by_name(name) or await context.hosts.get_by_hostname(name)
        if entry:
            logger.debug(f"Resolved @{name} → hostname={entry.hostname}, username={entry.username}")
            return entry.hostname, entry.username
        logger.warning(f"Host '@{name}' not found in inventory, defaulting to local")
        return "local", None

    # Unknown target (plain hostname without @) — reject to prevent hallucinations
    logger.warning(
        f"Target '{target}' has no @ prefix and is not an IP or local alias. "
        "Use '@hostname' for inventory hosts. Defaulting to local."
    )
    return "local", None
