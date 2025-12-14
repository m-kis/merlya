"""
Interaction tools for credentials and elevation (brain-driven).
"""

from __future__ import annotations

import getpass
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from merlya.commands.registry import CommandResult

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.persistence.models import Host


@dataclass
class CredentialBundle:
    """Structured credentials returned to the agent."""

    service: str
    host: str | None
    values: dict[str, str]
    stored: bool


async def request_credentials(
    ctx: SharedContext,
    service: str,
    host: str | None = None,
    fields: list[str] | None = None,
    format_hint: str | None = None,
    allow_store: bool = True,
) -> CommandResult:
    """
    Prompt the user for credentials (token/password/passphrase/JSON/username).

    Args:
        ctx: Shared context.
        service: Service name (e.g., mysql, mongo, api).
        host: Optional host context.
        fields: Optional list of fields to collect (default: ["username", "password"]).
        format_hint: Optional hint ("token", "json", "passphrase", "key", etc.).
        allow_store: Whether to offer storage in keyring.
    """
    try:
        # Validate service name to prevent path traversal or malicious names
        import re

        if not re.match(r"^[a-zA-Z0-9_-]+$", service):
            return CommandResult(
                success=False,
                message=f"Invalid service name: {service}. Only alphanumeric, underscore, and hyphen allowed.",
            )

        service_lower = service.lower()
        key_based_ssh = False
        prompt_password_for_ssh = format_hint in {"password", "password_required"}

        # Resolve host if provided (inventory may contain username/key)
        host_entry: Host | None = None
        if host:
            try:
                # Case-insensitive lookup fallback
                host_entry = await ctx.hosts.get_by_name(host)
                if not host_entry:
                    alt = await ctx.hosts.get_by_name(host.lower())
                    host_entry = host_entry or alt
            except Exception as exc:
                logger.debug(f"Could not resolve host '{host}' for credentials prefill: {exc}")

        if fields is None:
            if service_lower in {"ssh", "ssh_login", "ssh_auth"}:
                key_based_ssh = bool(
                    (host_entry and host_entry.private_key)
                    or getattr(ctx.config.ssh, "default_key", None)
                )
                # With a key, only ask for username; otherwise prompt for password too
                fields = ["username"] if key_based_ssh else ["username", "password"]
            else:
                fields = ["username", "password"]
        values: dict[str, str] = {}
        stored = False

        # Prefill from host inventory for SSH-style requests
        if service_lower in {"ssh", "ssh_login", "ssh_auth"}:
            if host_entry and host_entry.username:
                values["username"] = host_entry.username
            elif ctx.config.ssh.default_user:
                values["username"] = ctx.config.ssh.default_user
            else:
                values["username"] = getpass.getuser()

        # Prefill from secret store when available
        secret_store = ctx.secrets
        key_prefix = f"{service}:{host}" if host else service
        for field in fields:
            try:
                secret_val = secret_store.get(f"{key_prefix}:{field}")
                if secret_val is not None:
                    values[field] = secret_val
                    stored = True
            except Exception as keyring_err:
                # Keyring backend might fail - log but continue with manual prompt
                logger.debug(f"Keyring retrieval failed for {field}: {keyring_err}")
                continue

        # Only prompt for missing fields
        missing_fields = [f for f in fields if f not in values]

        # If everything is already known or connection is live, short-circuit without prompting
        if service_lower in {"ssh", "ssh_login", "ssh_auth"}:
            try:
                ssh_pool = await ctx.get_ssh_pool()
                if host_entry:
                    if ssh_pool.has_connection(
                        host_entry.hostname, port=host_entry.port, username=values.get("username")
                    ):
                        bundle = CredentialBundle(
                            service=service, host=host, values=values, stored=stored
                        )
                        return CommandResult(
                            success=True,
                            message="✅ Credentials resolved (active connection)",
                            data=bundle,
                        )
                elif host and ssh_pool.has_connection(host):
                    bundle = CredentialBundle(
                        service=service, host=host, values=values, stored=stored
                    )
                    return CommandResult(
                        success=True,
                        message="✅ Credentials resolved (active connection)",
                        data=bundle,
                    )
            except Exception as exc:
                logger.debug(f"Could not check SSH connection cache: {exc}")

        if not missing_fields:
            bundle = CredentialBundle(service=service, host=host, values=values, stored=stored)
            return CommandResult(success=True, message="✅ Credentials resolved", data=bundle)

        # For SSH, avoid prompting for password unless explicitly requested by format_hint
        if service_lower in {"ssh", "ssh_login", "ssh_auth"}:
            if key_based_ssh and not prompt_password_for_ssh:
                # Return what we have (username, maybe key) without prompting
                bundle = CredentialBundle(service=service, host=host, values=values, stored=stored)
                return CommandResult(
                    success=True,
                    message="✅ Credentials resolved (no password prompt for key-based SSH)",
                    data=bundle,
                )

            # If password is missing but not explicitly requested, skip prompting
            missing_fields = [
                f for f in missing_fields if f != "password" or prompt_password_for_ssh
            ]
            if not missing_fields:
                bundle = CredentialBundle(service=service, host=host, values=values, stored=stored)
                return CommandResult(success=True, message="✅ Credentials resolved", data=bundle)

        ctx.ui.info(f"🔐 Credentials needed for {service}{' @' + host if host else ''}")
        if format_hint:
            ctx.ui.muted(f"Format hint: {format_hint}")

        for field in missing_fields:
            prompt = f"{field.capitalize()}"
            secret = await ctx.ui.prompt_secret(prompt)
            values[field] = secret

        if allow_store:
            save = await ctx.ui.prompt_confirm(
                "Store these credentials securely for reuse?", default=False
            )
            if save:
                for name, val in values.items():
                    secret_store.set(f"{key_prefix}:{name}", val)
                stored = True
                ctx.ui.success("✅ Credentials stored securely")

        # SECURITY: Return secret references instead of raw values
        # This prevents the LLM from seeing or logging actual passwords
        # The references will be resolved at execution time by resolve_secrets()
        safe_values = {}
        for name, val in values.items():
            if name.lower() in {"password", "token", "secret", "key", "passphrase", "api_key"}:
                # Store the value and return a reference
                secret_key = f"{key_prefix}:{name}"
                if not stored:
                    # Always store sensitive values so references work
                    secret_store.set(secret_key, val)
                # Return reference like @sudo:hostname:password
                safe_values[name] = f"@{secret_key}"
            else:
                # Non-sensitive fields (like username) can be returned as-is
                safe_values[name] = val

        bundle = CredentialBundle(service=service, host=host, values=safe_values, stored=True)
        return CommandResult(success=True, message="✅ Credentials captured", data=bundle)

    except Exception as e:
        logger.error(f"Failed to request credentials: {e}")
        return CommandResult(success=False, message=f"❌ Failed to request credentials: {e}")


async def request_elevation(
    ctx: SharedContext, command: str, host: str | None = None
) -> CommandResult:
    """
    Request privilege elevation via PermissionManager (brain-driven).

    SECURITY NOTE: This tool does NOT return the actual password to the LLM.
    The password (if needed) is stored internally and applied automatically
    when ssh_execute is called with the returned elevation data.
    """
    try:
        if not host:
            return CommandResult(
                success=False,
                message="❌ Host is required to prepare elevation. Provide the target host.",
            )

        permissions = await ctx.get_permissions()
        elevation = await permissions.prepare_command(host, command)

        # SECURITY: Store input_data (password) in a secure cache, don't expose to LLM
        # Generate a unique reference ID if there's sensitive input data
        elevation_ref = None
        if elevation.input_data:
            import uuid

            elevation_ref = f"elev_{uuid.uuid4().hex[:8]}"
            # Store in session cache (accessible by ssh_execute)
            if not hasattr(ctx, "_elevation_cache"):
                ctx._elevation_cache = {}  # type: ignore[attr-defined]
            ctx._elevation_cache[elevation_ref] = {  # type: ignore[attr-defined]
                "input_data": elevation.input_data,
                "host": host,
                "command": command,
            }

        return CommandResult(
            success=True,
            message="✅ Elevation prepared",
            data={
                "command": elevation.command,
                # SECURITY: Never expose password to LLM - use reference instead
                "input_ref": elevation_ref,  # Reference ID, not actual password
                "has_password": elevation.input_data is not None,
                "method": elevation.method,
                "note": elevation.note,
                "needs_password": elevation.needs_password,
                "base_command": elevation.base_command or command,
            },
        )
    except Exception as e:
        logger.error(f"Failed to request elevation: {e}")
        return CommandResult(success=False, message=f"❌ Failed to request elevation: {e}")
