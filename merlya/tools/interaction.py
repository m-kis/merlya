"""
Interaction tools for credentials and elevation (brain-driven).
"""

from __future__ import annotations

import getpass
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from loguru import logger

from merlya.commands.registry import CommandResult

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.persistence.models import ElevationMethod, Host


# Maximum retries for password verification
MAX_PASSWORD_RETRIES = 3


@dataclass
class CredentialBundle:
    """Structured credentials returned to the agent."""

    service: str
    host: str | None
    values: dict[str, str]
    stored: bool


async def _verify_elevation_password(
    ctx: SharedContext, host: str, password: str, method: str = "sudo"
) -> tuple[bool, str]:
    """
    Verify an elevation password works by testing with 'sudo -S true' or 'su -c true'.

    Tries sudo first, then falls back to su if sudo fails.
    Uses expect-based approach for su testing since su reads passwords from /dev/tty.

    Args:
        ctx: Shared context.
        host: Target host.
        password: Password to verify.
        method: "sudo" or "su" (which method to test).

    Returns:
        Tuple of (success, working_method).
        working_method is "sudo", "su", or "" if none worked.
    """
    try:
        ssh_pool = await ctx.get_ssh_pool()
        host_entry = await ctx.hosts.get_by_name(host)

        from merlya.ssh import SSHConnectionOptions

        opts = SSHConnectionOptions()
        if host_entry:
            opts.port = host_entry.port

        async def _test_sudo() -> bool:
            """Test sudo method with stdin."""
            try:
                if host_entry:
                    result = await ssh_pool.execute(
                        host=host_entry.hostname,
                        command="sudo -S true",
                        timeout=10,
                        input_data=password,
                        username=host_entry.username,
                        private_key=host_entry.private_key,
                        options=opts,
                        host_name=host,
                    )
                else:
                    result = await ssh_pool.execute(
                        host=host,
                        command="sudo -S true",
                        timeout=10,
                        input_data=password,
                        options=opts,
                        host_name=host,
                    )
                return result.exit_code == 0
            except Exception as e:
                logger.debug(f"Sudo test failed: {e}")
                return False

        def _escape_tcl_string(s: str) -> str:
            """Escape special TCL characters in a string for use in double-quoted TCL contexts.

            Escapes: backslash, dollar sign, left/right square brackets, and double quotes.

            Args:
                s: String to escape

            Returns:
                String with TCL special characters escaped
            """
            return (
                s.replace("\\", "\\\\")  # Escape backslashes first
                .replace("$", "\\$")  # Escape dollar signs
                .replace("[", "\\[")  # Escape left brackets
                .replace("]", "\\]")  # Escape right brackets
                .replace('"', '\\"')  # Escape double quotes
            )

        async def _test_su_with_expect() -> bool:
            """Test su method using expect script since su reads from /dev/tty."""
            # Check if expect is available on the remote system
            try:
                check_result = await ssh_pool.execute(
                    host=host_entry.hostname if host_entry else host,
                    command="which expect",
                    timeout=5,
                    options=opts,
                    host_name=host,
                )
                if check_result.exit_code != 0:
                    logger.debug(
                        f"expect not available on {host}, cannot test su (fallback method not supported)"
                    )
                    return False
            except Exception as e:
                logger.debug(f"Could not check for expect on {host}: {e}")
                return False

            # Use expect -c with inline script (executed on remote)
            # Escape TCL special characters for the send command
            tcl_escaped_password = _escape_tcl_string(password)
            # Apply shell escaping to the TCL-escaped password to prevent shell injection
            shell_escaped_password = tcl_escaped_password.replace("'", "'\\''")
            expect_cmd = (
                f"expect -c '"
                f"set timeout 10; "
                f'spawn su -c "true"; '
                f"expect {{"
                f'  "assword:" {{ send "{shell_escaped_password}\\r"; expect eof; exit 0 }} '
                f"  timeout {{ exit 1 }} "
                f"  eof {{ exit 1 }} "
                f"}}"
                f"'"
            )

            try:
                if host_entry:
                    result = await ssh_pool.execute(
                        host=host_entry.hostname,
                        command=expect_cmd,
                        timeout=15,
                        username=host_entry.username,
                        private_key=host_entry.private_key,
                        options=opts,
                        host_name=host,
                    )
                else:
                    result = await ssh_pool.execute(
                        host=host,
                        command=expect_cmd,
                        timeout=15,
                        options=opts,
                        host_name=host,
                    )

                return result.exit_code == 0

            except Exception as e:
                logger.debug(f"Expect-based su test failed: {e}")
                return False

        # Try sudo first
        if method == "sudo":
            if await _test_sudo():
                logger.debug(f"✅ Password verified for sudo on {host} (stdin method)")
                return True, "sudo"

            # Sudo failed - try su as fallback using expect
            logger.info(f"sudo failed on {host}, trying su with expect script...")
            if await _test_su_with_expect():
                logger.info(f"✅ Password verified for su (root) on {host} (expect method)")
                return True, "su"

        # Try su directly if requested
        elif method == "su":
            if await _test_su_with_expect():
                logger.info(f"✅ Password verified for su on {host} (expect method)")
                return True, "su"

        logger.warning(
            f"❌ Password verification failed on {host} (tried sudo and su with expect fallback)"
        )
        return False, ""

    except Exception as e:
        logger.warning(f"⚠️ Could not verify password for {host}: {e}")
        # Connection error - don't assume success, let the user retry
        return False, ""


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
            if service_lower in {"sudo", "root", "su", "doas"}:
                # Elevation services only need password, not username
                # (uses the current SSH user's password)
                fields = ["password"]
            elif service_lower in {"ssh", "ssh_login", "ssh_auth"}:
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

        # NON-INTERACTIVE MODE CHECK: Fail early if we can't prompt
        # This prevents the agent from looping on credential requests
        if ctx.auto_confirm or getattr(ctx.ui, "auto_confirm", False):
            host_display = host or "unknown"
            missing_str = ", ".join(missing_fields)
            return CommandResult(
                success=False,
                message=(
                    f"❌ Cannot obtain credentials in non-interactive mode.\n\n"
                    f"Missing: {missing_str} for {service}@{host_display}\n\n"
                    f"To fix this, before running in --yes mode:\n"
                    f"1. Store credentials in keyring:\n"
                    f"   merlya secret set {service}:{host_display}:password\n"
                    f"2. Or configure NOPASSWD sudo on the target host\n"
                    f"3. Or run in interactive mode (without --yes)\n\n"
                    f"⚠️ DO NOT retry this command - credentials cannot be obtained."
                ),
                data={
                    "non_interactive": True,
                    "service": service,
                    "host": host,
                    "missing_fields": missing_fields,
                },
            )

        ctx.ui.info(f"🔐 Credentials needed for {service}{' @' + host if host else ''}")
        if format_hint:
            ctx.ui.muted(f"Format hint: {format_hint}")

        # For elevation services (sudo/root/su/doas), verify password before storing
        is_elevation_service = service_lower in {"sudo", "root", "su", "doas"}
        final_key_prefix = key_prefix  # Default fallback

        if is_elevation_service and "password" in missing_fields and host:
            # Special handling: verify password works before storing
            password_verified = False
            working_method = ""
            retries = 0

            while not password_verified and retries < MAX_PASSWORD_RETRIES:
                if retries > 0:
                    ctx.ui.warning(
                        f"❌ Password incorrect. Attempt {retries + 1}/{MAX_PASSWORD_RETRIES}"
                    )

                password = await ctx.ui.prompt_secret("Password")
                ctx.ui.muted("🔍 Verifying password (trying sudo, then su)...")

                # Try sudo first, fallback to su
                password_verified, working_method = await _verify_elevation_password(
                    ctx, host, password, method="sudo"
                )

                if password_verified:
                    values["password"] = password
                    # Remember which method worked for elevation commands
                    working_method_for_storage = working_method
                    if working_method == "su":
                        ctx.ui.success(
                            "✅ Password verified using su (expect method - commands will use 'su -c')"
                        )
                        # Store under root: prefix for su (for backward compatibility)
                        root_key_prefix = f"root:{host}"
                        # Also store under the original service prefix for compatibility
                        # This ensures future lookups under sudo:{host} will still work
                        original_key_prefix = f"{service_lower}:{host}"
                        if original_key_prefix != root_key_prefix:
                            secret_store.set(f"{original_key_prefix}:password", password)
                            logger.debug(
                                f"🔑 Also stored password under original prefix: {original_key_prefix}:password"
                            )
                        # Use root prefix for main storage (backward compatibility)
                        final_key_prefix = root_key_prefix
                    else:
                        ctx.ui.success("✅ Password verified using sudo (stdin method)")
                        final_key_prefix = key_prefix

                    # IMPORTANT: Cache the elevation method for this host
                    # This allows ssh.py to auto-transform commands
                    from merlya.tools.core.ssh_patterns import set_cached_elevation_method

                    set_cached_elevation_method(host, working_method)

                    # PERSIST to Host model for future sessions
                    try:
                        host_entry = await ctx.hosts.get_by_name(host)
                        if (
                            host_entry
                            and getattr(host_entry, "elevation_method", None) != working_method
                        ):
                            host_entry.elevation_method = cast("ElevationMethod", working_method)
                            await ctx.hosts.update(host_entry)
                            logger.info(f"💾 Elevation method '{working_method}' saved for {host}")
                    except Exception as e:
                        logger.debug(f"Could not persist elevation method: {e}")
                else:
                    retries += 1

            if not password_verified:
                return CommandResult(
                    success=False,
                    message=f"❌ Password verification failed after {MAX_PASSWORD_RETRIES} attempts. "
                    f"Neither sudo nor su worked with this password.",
                )

            # Remove password from missing_fields since we handled it
            missing_fields = [f for f in missing_fields if f != "password"]

            # Store info about which method works
            values["_elevation_method"] = working_method

        # Prompt for any remaining missing fields (non-password or non-elevation)
        for field in missing_fields:
            prompt = f"{field.capitalize()}"
            secret = await ctx.ui.prompt_secret(prompt)
            values[field] = secret

        # For elevation services, password was already verified - always store
        # For other services, ask user
        if is_elevation_service and host:
            # Password verified - store it automatically
            # Don't store internal metadata like _elevation_method
            # Use the appropriate key prefix (final_key_prefix set above)
            storage_key_prefix = final_key_prefix if "final_key_prefix" in locals() else key_prefix
            for name, val in values.items():
                if not name.startswith("_"):
                    secret_store.set(f"{storage_key_prefix}:{name}", val)
            stored = True
            ctx.ui.success("✅ Verified credentials stored securely")
        elif allow_store:
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
        # Use the appropriate key prefix for safe references
        reference_key_prefix = final_key_prefix if "final_key_prefix" in locals() else key_prefix
        for name, val in values.items():
            if name.lower() in {"password", "token", "secret", "key", "passphrase", "api_key"}:
                # Store the value and return a reference
                secret_key = f"{reference_key_prefix}:{name}"
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
    Request privilege elevation via ElevationManager (brain-driven).

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

        # Look up host model from database
        host_entry = await ctx.hosts.get_by_name(host)
        if not host_entry:
            return CommandResult(
                success=False,
                message=f"❌ Host '{host}' not found in inventory.",
            )

        from merlya.security import CenterMode, ElevationDeniedError

        elevation_mgr = await ctx.get_elevation()
        try:
            elevation = await elevation_mgr.prepare_command(
                host_entry, command, center=CenterMode.DIAGNOSTIC
            )
        except ElevationDeniedError as e:
            return CommandResult(
                success=False,
                message=f"❌ Elevation declined: {e}",
            )

        # SECURITY: Store input_data (password) in a secure cache, don't expose to LLM
        elevation_ref = None
        if elevation.input_data:
            import uuid

            elevation_ref = f"elev_{uuid.uuid4().hex[:8]}"
            if not hasattr(ctx, "_elevation_cache"):
                ctx._elevation_cache = {}  # type: ignore[attr-defined]
            ctx._elevation_cache[elevation_ref] = {  # type: ignore[attr-defined]
                "input_data": elevation.input_data,
                "host": host,
                "command": command,
            }
            logger.debug(f"🔐 Stored elevation cache entry: {elevation_ref} for host {host}")

        return CommandResult(
            success=True,
            message="✅ Elevation prepared",
            data={
                "command": elevation.command,
                "input_ref": elevation_ref,
                "has_password": elevation.input_data is not None,
                "method": elevation.method,
                "elevated": elevation.elevated,
                "base_command": command,
            },
        )
    except Exception as e:
        logger.error(f"Failed to request elevation: {e}")
        return CommandResult(success=False, message=f"❌ Failed to request elevation: {e}")
