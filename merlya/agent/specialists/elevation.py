"""
Merlya Agent Specialists - Elevation helpers.

Auto-elevation for commands requiring sudo/su credentials.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


def needs_elevation_stdin(command: str) -> bool:
    """
    Check if a command requires stdin for elevation.

    Args:
        command: The command to check.

    Returns:
        True if command uses sudo -S, su -c, or similar patterns.

    Note:
        - sudo -S (uppercase S) = read password from stdin (needs stdin)
        - sudo -s (lowercase s) = run a shell (does NOT need stdin)
        - su -c = run command as another user (needs stdin for password)
    """
    # Case-sensitive check for sudo -S (uppercase S = stdin mode)
    # Pattern: start of string or after | ; && || followed by optional whitespace
    sudo_s_pattern = re.compile(r"(?:^|[|;&]|&&|\|\|)\s*sudo\s+-S\b")
    has_sudo_stdin = bool(sudo_s_pattern.search(command))

    # Case-insensitive check for su commands at command boundaries
    su_pattern = re.compile(r"(?:^|[|;&]|&&|\|\|)\s*su\b", re.IGNORECASE)
    has_su = bool(su_pattern.search(command))

    return has_sudo_stdin or has_su


async def auto_collect_elevation_credentials(
    ctx: SharedContext,
    host: str,
    command: str,
) -> str | None:
    """
    Automatically collect elevation credentials when needed.

    This function:
    1. Checks if credentials are already stored for this host
    2. If not, prompts the user for a password
    3. Returns the stdin reference to use for the command

    Args:
        ctx: Shared context.
        host: Target host.
        command: Command that needs elevation.

    Returns:
        The stdin reference (e.g., '@root:hostname:password') or None.
    """
    from merlya.tools.interaction import request_credentials

    # PRIORITY 1: Check host's configured elevation_method from database
    host_entry = await ctx.hosts.get_by_name(host)
    elevation_method = host_entry.elevation_method if host_entry else None

    # Determine service type based on host config or command analysis
    service = _determine_service_type(elevation_method, command)

    # PRIORITY 2: Check if credentials already exist
    for candidate_service in (service, "root" if service == "sudo" else "sudo"):
        secret_key = f"{candidate_service}:{host}:password"
        existing = ctx.secrets.get(secret_key)
        if existing:
            logger.debug(f"✅ Found existing credentials: @{secret_key}")
            return f"@{secret_key}"

    # PRIORITY 3: No stored credentials - prompt user
    logger.info(f"🔐 Auto-prompting for {service} credentials on {host}")
    ctx.ui.info(f"🔐 Commande nécessite élévation: {command[:50]}...")

    result = await request_credentials(
        ctx,
        service=service,
        host=host,
        fields=["password"],
    )

    if result.success and result.data:
        bundle = result.data
        password_ref = bundle.values.get("password", "")
        if password_ref and isinstance(password_ref, str):
            logger.debug("✅ Credentials collected successfully")
            return str(password_ref)

    logger.warning(f"❌ Could not collect credentials for {host}")
    return None


def _determine_service_type(elevation_method: str | None, command: str) -> str:
    """Determine the service type (sudo or root) for credentials."""
    if elevation_method in {"su", "root"}:
        return "root"
    if elevation_method in {"sudo", "sudo-S"}:
        return "sudo"

    # Fall back to command analysis
    cmd_lower = command.lower()
    su_pattern = re.compile(r"(?:^|[|;&]|&&|\|\|)\s*su\b")
    has_su_command = bool(su_pattern.search(cmd_lower))
    return "root" if has_su_command else "sudo"
