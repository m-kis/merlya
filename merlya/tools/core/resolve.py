"""
Merlya Tools - Reference resolution.

Resolves @hostname and @secret references in commands.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.secrets import SecretStore

# Private/internal IP ranges - warn when DNS resolves to these
# (not blocked, as internal DNS is legitimate for infrastructure tools)
PRIVATE_IP_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("127.0.0.0/8"),  # Loopback
    ipaddress.ip_network("10.0.0.0/8"),  # Private Class A
    ipaddress.ip_network("172.16.0.0/12"),  # Private Class B
    ipaddress.ip_network("192.168.0.0/16"),  # Private Class C
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),  # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
)


# Pattern to match @reference references in commands
# Only match @ preceded by whitespace, start of string, or shell operators (not emails/URLs)
# Examples matched: @api-key, --password @db-pass, echo @token, @sudo:hostname:password, @pine64
# Examples NOT matched: user@github.com, git@repo.com
# Supports colons for structured keys like @service:host:field
REFERENCE_PATTERN = re.compile(r"(?:^|(?<=[\s;|&='\"]))\@([a-zA-Z][a-zA-Z0-9_:.-]*)")


def _is_private_ip(ip_str: str) -> bool:
    """
    Check if an IP address is in a private/internal range.

    This is used to warn about potential DNS rebinding or SSRF risks.
    Private IPs are NOT blocked since internal DNS is legitimate for infrastructure tools.

    Args:
        ip_str: IP address string (IPv4 or IPv6).

    Returns:
        True if IP is in a private/internal range.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
        return any(ip in network for network in PRIVATE_IP_NETWORKS)
    except ValueError:
        return False


async def resolve_host_references(
    command: str,
    hosts: list[Any],
    ui: Any | None = None,
) -> str:
    """
    Resolve @hostname references in a command to actual hostnames/IPs.

    Resolution order (sysadmin logic):
    1. Check inventory - if host exists, use its hostname
    2. Try DNS resolution
    3. Ask user for IP if unresolved

    Args:
        command: Command string potentially containing @hostname references.
        hosts: List of Host objects from inventory.
        ui: ConsoleUI for user prompts (optional).

    Returns:
        Command with @hostname replaced by actual hostname/IP.
    """
    resolved = command

    # Build lookup dict: name -> hostname
    host_lookup: dict[str, str] = {}
    for h in hosts:
        host_lookup[h.name.lower()] = h.hostname or h.name

    # Collect matches and sort by position (reverse to replace from end)
    matches = list(REFERENCE_PATTERN.finditer(command))
    matches.sort(key=lambda m: m.start(), reverse=True)

    for match in matches:
        ref_name = match.group(1)

        # Skip structured references (secrets like @sudo:host:password)
        if ":" in ref_name:
            continue

        start, end = match.span(0)
        replacement = None

        # 1. Check inventory
        if ref_name.lower() in host_lookup:
            replacement = host_lookup[ref_name.lower()]
            logger.debug(f"🖥️ Resolved @{ref_name} from inventory → {replacement}")

        # 2. Try DNS resolution with security checks
        if replacement is None:
            try:
                resolved_ip = socket.gethostbyname(ref_name)
                replacement = ref_name  # DNS works, use the name as-is

                # Security: Warn if external hostname resolves to private IP
                # This could indicate DNS rebinding attack or misconfiguration
                if _is_private_ip(resolved_ip):
                    logger.warning(
                        f"⚠️ SECURITY: @{ref_name} resolves to private IP {resolved_ip} - "
                        "verify this is expected (potential DNS rebinding)"
                    )
                else:
                    logger.debug(f"🌐 Resolved @{ref_name} via DNS → {resolved_ip}")
            except socket.gaierror:
                pass  # DNS failed, continue to user prompt

        # 3. Ask user for IP
        if replacement is None and ui:
            logger.info(f"❓ Host @{ref_name} not found in inventory and DNS failed")
            user_ip = await ui.prompt(f"Enter IP/hostname for '{ref_name}'", default="")
            if user_ip:
                replacement = user_ip
                logger.info(f"📝 User provided: @{ref_name} → {replacement}")
            else:
                logger.warning(f"⚠️ No resolution for @{ref_name}, keeping as-is")

        # Apply replacement if found
        if replacement:
            resolved = resolved[:start] + replacement + resolved[end:]

    return resolved


def resolve_secrets(
    command: str, secrets: SecretStore, resolved_hosts: set[str] | None = None
) -> tuple[str, str]:
    """
    Resolve @secret-name references in a command.

    SECURITY: This function should only be called at execution time,
    never before sending commands to the LLM.

    Args:
        command: Command string potentially containing @secret-name references.
        secrets: SecretStore instance.
        resolved_hosts: Set of host names already resolved (to skip).

    Returns:
        Tuple of (resolved_command, safe_command_for_logging).
        The safe_command replaces secret values with '***'.
    """
    resolved = command
    safe = command
    resolved_hosts = resolved_hosts or set()

    # Collect all matches and sort by start position in reverse order
    matches = list(REFERENCE_PATTERN.finditer(command))
    matches.sort(key=lambda m: m.start(), reverse=True)

    for match in matches:
        secret_name = match.group(1)

        # Skip if this was already resolved as a host reference
        if secret_name in resolved_hosts or secret_name.lower() in resolved_hosts:
            continue

        secret_value = secrets.get(secret_name)
        start, end = match.span(0)
        if secret_value is not None:  # Allow empty strings as valid secrets
            resolved = resolved[:start] + secret_value + resolved[end:]
            safe = safe[:start] + "***" + safe[end:]
            logger.debug(f"🔐 Resolved secret @{secret_name}")
        else:
            # Only warn if it's not structured like a host:field reference
            if ":" not in secret_name:
                logger.warning(f"⚠️ Secret @{secret_name} not found in store")

    return resolved, safe


def get_resolved_host_names(hosts: list[Any]) -> set[str]:
    """
    Get a set of all host names (both original and lowercase) for exclusion.

    Args:
        hosts: List of Host objects from inventory.

    Returns:
        Set of host names to exclude from secret resolution.
    """
    return {h.name for h in hosts} | {h.name.lower() for h in hosts}


async def resolve_all_references(
    command: str,
    ctx: SharedContext,
) -> tuple[str, str]:
    """
    Resolve all @references (hosts and secrets) in a command.

    This is a convenience function that combines host and secret resolution
    in the correct order. Use this instead of calling resolve_host_references
    and resolve_secrets separately.

    Resolution order:
    1. @hostname references → inventory lookup → DNS → user prompt
    2. @secret references → keyring lookup

    Args:
        command: Command string potentially containing @references.
        ctx: Shared context with hosts, secrets, and ui.

    Returns:
        Tuple of (resolved_command, safe_command_for_logging).
        The safe_command replaces secret values with '***'.
    """
    # Get hosts for reference resolution
    all_hosts = await ctx.hosts.get_all()

    # 1. Resolve @hostname references → actual hostnames/IPs
    resolved_command = await resolve_host_references(command, all_hosts, ctx.ui)

    # Track which host names were resolved (to skip in secret resolution)
    resolved_host_names = get_resolved_host_names(all_hosts)

    # 2. Resolve @secret references → actual values
    resolved_command, safe_command = resolve_secrets(
        resolved_command, ctx.secrets, resolved_host_names
    )

    return resolved_command, safe_command
