"""
Merlya Agent Specialists - Elevation helpers.

Transparent host-config-based elevation: the LLM sends plain commands,
the system applies the correct elevation prefix based on the host's configured
elevation_method.  No regex heuristics on command content.
"""

from __future__ import annotations

import re
import shlex
from typing import TYPE_CHECKING

from loguru import logger

from merlya.persistence.models import ElevationMethod

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


# Matches elevation prefixes at the very START of a command only.
# Anchored at ^ so it never fires on mid-command occurrences like
# "apt install sudo" or "echo 'use sudo'".
_ELEVATION_PREFIX_RE = re.compile(
    r"^(?:sudo\s+(?:-[Ss]\s+)?|doas\s+|su\s+-c\s+)",
    re.IGNORECASE,
)


def _strip_elevation_prefix(command: str) -> str:
    """
    Strip a sudo/doas/su prefix the LLM may have added to the start of a command.

    Only strips from the beginning of the string — avoids false-positives on
    subcommands such as 'apt install sudo' or 'echo "run sudo"'.

    After stripping 'su -c <quoted>', surrounding quotes are also removed so the
    caller gets a plain command string.
    """
    stripped = _ELEVATION_PREFIX_RE.sub("", command.strip(), count=1).strip()
    # Remove surrounding quotes left by 'su -c "CMD"' stripping.
    if len(stripped) >= 2 and stripped[0] in ("'", '"') and stripped[-1] == stripped[0]:
        stripped = stripped[1:-1]
    return stripped


async def prepare_host_elevation(
    command: str,
    host: str,
    ctx: SharedContext,
    stdin: str | None = None,
) -> tuple[str | None, str | None]:
    """
    Apply transparent host-based elevation.

    Reads the host's ``elevation_method`` from inventory and:

    1. Strips any sudo/doas prefix the LLM may have added (avoids double-prefix).
    2. Applies the correct wrapper for the configured method.
    3. Fetches or prompts for the password credential if needed.

    Args:
        command: Command from the LLM (may already have a sudo/doas prefix).
        host:    Target hostname.
        ctx:     Shared context.
        stdin:   Existing stdin override — skips elevation when provided.

    Returns:
        ``(elevated_command, stdin_ref)`` on success, or ``(None, None)`` if the
        user cancelled the credential prompt (caller should abort execution).
    """
    # If the caller already set stdin, pass through unchanged.
    if stdin:
        return command, stdin

    # Look up by inventory name first, then by hostname/IP (hosts are often
    # addressed by their IP in the tool call even though stored by name).
    host_entry = await ctx.hosts.get_by_name(host)
    if host_entry is None:
        host_entry = await ctx.hosts.get_by_hostname(host)
    elevation_method = host_entry.elevation_method if host_entry else ElevationMethod.NONE

    if elevation_method == ElevationMethod.NONE:
        logger.debug(f"⬆️  No elevation configured for {host} — executing as-is")
        return command, None

    # Strip any prefix the LLM already added to avoid double-prefixing.
    base_cmd = _strip_elevation_prefix(command)

    if elevation_method == ElevationMethod.SUDO:
        logger.debug(f"🔓 Elevation: sudo (NOPASSWD) for {host}")
        return f"sudo {base_cmd}", None

    if elevation_method == ElevationMethod.SUDO_PASSWORD:
        logger.debug(f"🔐 Elevation: sudo -S (password) for {host}")
        stdin_ref = await _get_credential(ctx, "sudo", host, command)
        if stdin_ref is None:
            return None, None  # User cancelled — caller must abort.
        return f"sudo -S {base_cmd}", stdin_ref

    if elevation_method == ElevationMethod.DOAS:
        logger.debug(f"🔓 Elevation: doas (NOPASSWD) for {host}")
        return f"doas {base_cmd}", None

    if elevation_method == ElevationMethod.DOAS_PASSWORD:
        logger.debug(f"🔐 Elevation: doas (password) for {host}")
        stdin_ref = await _get_credential(ctx, "doas", host, command)
        if stdin_ref is None:
            return None, None
        return f"doas {base_cmd}", stdin_ref

    if elevation_method == ElevationMethod.SU:
        logger.debug(f"🔐 Elevation: su -c (root password) for {host}")
        stdin_ref = await _get_credential(ctx, "root", host, command)
        if stdin_ref is None:
            return None, None
        quoted = shlex.quote(base_cmd)
        return f"su -c {quoted}", stdin_ref

    # Unknown elevation_method — pass through unchanged.
    logger.warning(f"⚠️  Unknown elevation_method '{elevation_method}' for {host} — skipping")
    return command, None


async def _get_credential(
    ctx: SharedContext,
    service: str,
    host: str,
    command: str,
) -> str | None:
    """
    Return a ``@service:host:password`` reference, prompting the user if needed.

    Args:
        ctx:     Shared context.
        service: Credential service type (``sudo``, ``root``, ``doas``).
        host:    Target host.
        command: Command requiring elevation (shown in the prompt).

    Returns:
        ``@reference`` string, or ``None`` if the user cancelled.
    """
    from merlya.tools.interaction import request_credentials

    # Check if credential already exists (primary service, then common fallback).
    fallback = "root" if service in ("sudo", "doas") else "sudo"
    for svc in (service, fallback):
        secret_key = f"{svc}:{host}:password"
        if ctx.secrets.get(secret_key):
            logger.debug(f"✅ Found stored credential: @{secret_key}")
            return f"@{secret_key}"

    # Prompt user for the missing credential.
    logger.info(f"🔐 Prompting for {service} credential on {host}")
    ctx.ui.info(f"🔐 Elevation required: {command[:50]}...")

    result = await request_credentials(ctx, service=service, host=host, fields=["password"])
    if result.success and result.data:
        ref = result.data.values.get("password", "")
        if ref and isinstance(ref, str):
            logger.debug("✅ Credential collected successfully")
            return str(ref)

    logger.warning(f"❌ Could not obtain credential for {service}@{host}")
    return None


# ---------------------------------------------------------------------------
# Legacy helpers kept for merlya/agent/tools/core/ssh.py compatibility.
# Do not use in new code — prefer prepare_host_elevation().
# ---------------------------------------------------------------------------


async def auto_collect_elevation_credentials(
    ctx: SharedContext,
    host: str,
    command: str,
) -> str | None:
    """
    Automatically collect elevation credentials when needed.

    .. deprecated::
        Prefer :func:`prepare_host_elevation` for new code.
        This function is kept for backward-compat with
        ``merlya/agent/tools/core/ssh.py``.
    """
    from merlya.tools.interaction import request_credentials

    host_entry = await ctx.hosts.get_by_name(host)
    if host_entry is None:
        host_entry = await ctx.hosts.get_by_hostname(host)
    elevation_method = host_entry.elevation_method if host_entry else None

    service = _determine_service_type(elevation_method, command)

    for candidate_service in (service, "root" if service == "sudo" else "sudo"):
        secret_key = f"{candidate_service}:{host}:password"
        existing = ctx.secrets.get(secret_key)
        if existing:
            logger.debug(f"✅ Found existing credentials: @{secret_key}")
            return f"@{secret_key}"

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

    cmd_lower = command.lower()
    has_su_command = bool(re.compile(r"(?:^|[|;&]|&&|\|\|)\s*su\b").search(cmd_lower))
    return "root" if has_su_command else "sudo"
