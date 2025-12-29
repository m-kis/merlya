"""
Merlya Commands - SSH handlers.

Implements /ssh command with subcommands: connect, exec, disconnect, config, test.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import asyncssh
from loguru import logger

from merlya.commands.registry import CommandResult, command, subcommand
from merlya.ssh.pool import SSHConnectionOptions

if TYPE_CHECKING:
    from collections.abc import Callable

    from merlya.core.context import SharedContext


@command("ssh", "Manage SSH connections", "/ssh <subcommand>")
async def cmd_ssh(_ctx: SharedContext, args: list[str]) -> CommandResult:
    """Manage SSH connections with MFA, jump hosts, and passphrase support."""
    if not args:
        return CommandResult(
            success=False,
            message="**SSH Commands:**\n"
            "  `/ssh connect <host>` - Connect to a host\n"
            "  `/ssh exec <host> <cmd>` - Execute command\n"
            "  `/ssh config <host>` - Configure SSH (user, key, port, jump)\n"
            "  `/ssh test <host>` - Test connection with diagnostics\n"
            "  `/ssh disconnect [host]` - Disconnect\n\n"
            "**Elevation Commands:**\n"
            "  `/ssh elevation detect <host>` - Detect sudo/doas/su capabilities\n"
            "  `/ssh elevation status <host>` - Show elevation status and failed methods\n"
            "  `/ssh elevation reset [host]` - Clear failed methods (retry with new password)\n\n"
            "**Features:**\n"
            "  - Key discovery (inventory + ~/.ssh/config), jump hosts, ssh-agent\n"
            "  - Encrypted keys/passphrases (keyring-backed), MFA/2FA\n"
            "  - Auto-healing elevation (tries sudo → doas → su until success)\n"
            "  - Passwords stored in keyring, verified before caching",
            show_help=True,
        )

    return CommandResult(
        success=False,
        message="Unknown subcommand. Use `/ssh` for available commands.",
        show_help=True,
    )


@subcommand("ssh", "connect", "Connect to a host", "/ssh connect <host>")
async def cmd_ssh_connect(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Connect to a host with passphrase and MFA support."""
    if not args:
        return CommandResult(success=False, message="Usage: `/ssh connect <host>`")

    host_name = args[0].lstrip("@")
    host = await ctx.hosts.get_by_name(host_name)

    if not host:
        return CommandResult(success=False, message=f"❌ Host '{host_name}' not found.")

    ctx.ui.info(f"🌐 Connecting to `{host_name}` ({host.hostname}:{host.port})...")

    try:
        ssh_pool = await ctx.get_ssh_pool()
        _install_ssh_callbacks(ctx, ssh_pool, host.name, host.private_key, force=True)

        options = SSHConnectionOptions(
            port=host.port,
            jump_host=host.jump_host,
        )
        await ssh_pool.get_connection(
            host=host.hostname,
            username=host.username,
            private_key=host.private_key,
            options=options,
        )

        jump_info = f" via `{host.jump_host}`" if host.jump_host else ""
        return CommandResult(
            success=True,
            message=f"✅ Connected to `{host_name}` ({host.hostname}){jump_info}",
        )

    except Exception as e:
        return _handle_ssh_error(e, host.private_key, host.hostname)


def _create_mfa_callback(ctx: SharedContext) -> Callable[[str], str]:
    """Create MFA callback for keyboard-interactive prompts."""

    def mfa_callback(prompt: str) -> str:
        try:
            asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(lambda: asyncio.run(ctx.ui.prompt_secret(f"🔐 {prompt}")))
                return future.result(timeout=120)
        except RuntimeError:
            return asyncio.run(ctx.ui.prompt_secret(f"🔐 {prompt}"))

    return mfa_callback


def _install_ssh_callbacks(
    ctx: SharedContext,
    ssh_pool: Any,
    host_name: str,
    _key_path: str | None,  # Reserved for future use
    *,
    force: bool = False,
) -> None:
    """
    Install passphrase/MFA callbacks that reuse stored secrets when available.
    """
    import asyncio as _asyncio
    import concurrent.futures
    from pathlib import Path

    should_set_passphrase = force
    if hasattr(ssh_pool, "has_passphrase_callback"):
        should_set_passphrase = force or not ssh_pool.has_passphrase_callback()

    if should_set_passphrase:

        def passphrase_cb(path: str) -> str:
            resolved = str(Path(path).expanduser())
            secrets_keys = _candidate_passphrase_keys(host_name, resolved, path)
            logger.debug(f"🔐 Looking up passphrase for keys: {secrets_keys}")
            secret = _lookup_passphrase(ctx, secrets_keys)
            if secret:
                logger.debug(f"🔐 Found cached passphrase for {path}")
                return secret
            logger.debug(f"🔐 No cached passphrase found, prompting user for {path}")
            try:
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        lambda: _asyncio.run(ctx.ui.prompt_secret(f"🔐 Passphrase for {path}"))
                    )
                    pw = future.result(timeout=60)
                if pw:
                    try:
                        for key in secrets_keys:
                            ctx.secrets.set(key, pw)
                        logger.debug("🔐 Passphrase cached successfully")
                    except Exception as exc:
                        logger.debug(f"Failed to cache passphrase: {exc}")
                return pw or ""
            except Exception as exc:
                logger.error(f"❌ Passphrase callback error: {exc}")
                return ""

        ssh_pool.set_passphrase_callback(passphrase_cb)

    if hasattr(ssh_pool, "has_mfa_callback") and (force or not ssh_pool.has_mfa_callback()):

        def mfa_cb(prompt: str) -> str:
            logger.debug(f"🔐 MFA callback invoked with prompt: {prompt}")
            try:
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        lambda: _asyncio.run(ctx.ui.prompt_secret(f"🔐 {prompt}"))
                    )
                    response = future.result(timeout=120)
                    logger.debug("🔐 MFA response received")
                    return response or ""
            except concurrent.futures.TimeoutError:
                logger.error("❌ MFA prompt timed out")
                return ""
            except Exception as exc:
                logger.error(f"❌ MFA callback error: {exc}")
                return ""

        ssh_pool.set_mfa_callback(mfa_cb)


def _handle_ssh_error(e: Exception, private_key: str | None, hostname: str) -> CommandResult:
    """Handle SSH connection errors with helpful messages."""
    error_msg = str(e)
    logger.error(f"❌ SSH connection failed: {e}")

    if "Passphrase" in error_msg or "encrypted" in error_msg.lower():
        return CommandResult(
            success=False,
            message=f"❌ Key requires passphrase.\n"
            f"Add key to ssh-agent: `ssh-add {private_key or '~/.ssh/id_rsa'}`",
        )
    if "Permission denied" in error_msg:
        return CommandResult(
            success=False,
            message=(
                "❌ Permission denied. Verify username and authorized key on the target.\n"
                "Try: `ssh -i {key} {user}@{host}` to confirm, or update with `/ssh config <host>`."
            ).format(
                key=private_key or "~/.ssh/id_rsa",
                user="{user}",
                host=hostname,
            ),
        )
    elif "Host key" in error_msg or "trusted" in error_msg.lower():
        return CommandResult(
            success=False,
            message=f"❌ Host key not trusted.\n"
            f"Run: `ssh-keyscan {hostname} >> ~/.ssh/known_hosts`",
        )
    else:
        return CommandResult(success=False, message=f"❌ Connection failed: {e}")


@subcommand("ssh", "exec", "Execute command on host", "/ssh exec <host> <command>")
async def cmd_ssh_exec(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Execute command on a host (inventory name or direct IP/hostname)."""
    if len(args) < 2:
        return CommandResult(success=False, message="Usage: `/ssh exec <host> <command>`")

    host_name = args[0].lstrip("@")
    command_str = " ".join(args[1:])

    # First try inventory lookup
    host = await ctx.hosts.get_by_name(host_name)

    if host:
        # Use inventory host settings
        hostname = host.hostname
        port = host.port
        username = host.username
        private_key = host.private_key
        jump_host = host.jump_host
    else:
        # Direct IP/hostname mode - try to resolve
        if not _is_valid_target(host_name):
            return CommandResult(
                success=False,
                message=f"❌ '{host_name}' is not in inventory and couldn't be resolved.\n"
                f"Add to inventory: `/hosts add {host_name}`",
            )
        # Use direct connection with defaults
        hostname = host_name
        port = 22
        username = None  # Will use SSH defaults
        private_key = None  # Will use ssh-agent or default keys
        jump_host = None

    try:
        ssh_pool = await ctx.get_ssh_pool()
        if host:
            _install_ssh_callbacks(ctx, ssh_pool, host.name, private_key)

        options = SSHConnectionOptions(
            port=port,
            jump_host=jump_host,
        )
        result = await ssh_pool.execute(
            host=hostname,
            command=command_str,
            username=username,
            private_key=private_key,
            options=options,
        )

        output = result.stdout or result.stderr
        status = "✓" if result.exit_code == 0 else "✗"

        return CommandResult(
            success=result.exit_code == 0,
            message=f"{status} Exit code: {result.exit_code}\n```\n{output}\n```",
            data={"stdout": result.stdout, "stderr": result.stderr, "exit_code": result.exit_code},
        )

    except Exception as e:
        logger.error(f"❌ SSH execution failed: {e}")
        return CommandResult(success=False, message=f"Execution failed: {e}")


def _is_valid_target(target: str) -> bool:
    """Check if target is a valid IP address or resolvable hostname."""
    import ipaddress
    import socket

    # Check if it's an IPv4/IPv6 address
    try:
        ipaddress.ip_address(target)
        return True
    except ValueError:
        pass

    # Check if it's resolvable as a hostname
    try:
        socket.getaddrinfo(target, 22, socket.AF_UNSPEC, socket.SOCK_STREAM)
        return True
    except socket.gaierror:
        return False


@subcommand("ssh", "disconnect", "Disconnect from a host", "/ssh disconnect <host>")
async def cmd_ssh_disconnect(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Disconnect from a host."""
    ssh_pool = await ctx.get_ssh_pool()

    if args:
        host_name = args[0].lstrip("@")
        await ssh_pool.disconnect(host_name)
        return CommandResult(success=True, message=f"🔌 Disconnected from `{host_name}`.")

    await ssh_pool.disconnect_all()
    return CommandResult(success=True, message="🔌 Disconnected from all hosts.")


@subcommand("ssh", "config", "Configure SSH for a host", "/ssh config <host>")
async def cmd_ssh_config(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Configure SSH settings for a host (user, key, port, jump host)."""
    if not args:
        return CommandResult(success=False, message="Usage: `/ssh config <host>`")

    host_name = args[0].lstrip("@")
    host = await ctx.hosts.get_by_name(host_name)

    if not host:
        return CommandResult(success=False, message=f"❌ Host '{host_name}' not found.")

    ctx.ui.info(f"⚙️ Configuring SSH for `{host_name}`...")
    ctx.ui.muted(
        f"Current: user={host.username or 'default'}, port={host.port}, key={host.private_key or 'none'}"
    )

    host = await _prompt_ssh_config(ctx, host)
    await ctx.hosts.update(host)

    return CommandResult(
        success=True,
        message=f"✅ SSH config updated for `{host_name}`:\n"
        f"  - User: `{host.username or 'default'}`\n"
        f"  - Port: `{host.port}`\n"
        f"  - Key: `{host.private_key or 'none'}`\n"
        f"  - Jump: `{host.jump_host or 'none'}`",
    )


async def _prompt_ssh_config(ctx: SharedContext, host: Any) -> Any:
    """Prompt user for SSH configuration values."""
    host.username = await _prompt_username(ctx, host)
    host.port = await _prompt_port(ctx, host)

    passphrase = await _prompt_private_key(ctx, host)
    host.jump_host = await _prompt_jump_host(ctx, host)

    _store_passphrase(ctx, host, passphrase)

    return host


async def _prompt_username(ctx: SharedContext, host: Any) -> str | None:
    """Prompt for SSH username while keeping existing by default."""
    username = await ctx.ui.prompt(
        "SSH username (Enter to keep current)", default=host.username or ""
    )
    return username or host.username


async def _prompt_port(ctx: SharedContext, host: Any) -> int:
    """Prompt for SSH port with validation."""
    port_str = await ctx.ui.prompt("SSH port", default=str(host.port))
    try:
        port = int(port_str)
        if 1 <= port <= 65535:
            return port
        ctx.ui.warning("⚠️ Invalid port, keeping current")
    except ValueError:
        ctx.ui.warning("⚠️ Invalid port, keeping current")
    return int(host.port)


async def _prompt_private_key(ctx: SharedContext, host: Any) -> str | None:
    """
    Prompt for private key path and request passphrase when needed.

    Returns validated passphrase (if any) for secure storage.
    """
    private_key = await ctx.ui.prompt(
        "Private key path (Enter to skip)", default=host.private_key or ""
    )
    if not private_key:
        return None

    key_path = Path(private_key).expanduser()
    if not key_path.exists():
        ctx.ui.warning(f"⚠️ Key not found: {key_path}")
        return None

    passphrase = _get_cached_passphrase(ctx, host.name, key_path)

    while True:
        try:
            if passphrase:
                asyncssh.read_private_key(str(key_path), passphrase)
            else:
                asyncssh.read_private_key(str(key_path))
            host.private_key = str(key_path)
            if passphrase:
                ctx.ui.success(f"✅ Key set: {key_path} (passphrase validated)")
            else:
                ctx.ui.success(f"✅ Key set: {key_path}")
            return passphrase
        except asyncssh.KeyEncryptionError:
            passphrase = await _prompt_passphrase(ctx, key_path)
            if not passphrase:
                ctx.ui.warning("⚠️ Passphrase required for encrypted key.")
                return None
        except asyncssh.KeyImportError as exc:
            if "passphrase" in str(exc).lower():
                passphrase = await _prompt_passphrase(ctx, key_path)
                if not passphrase:
                    ctx.ui.warning("⚠️ Passphrase required for encrypted key.")
                    return None
                continue
            ctx.ui.error(f"❌ Invalid key: {exc}")
            return None
        except Exception as exc:
            ctx.ui.error(f"❌ Invalid key: {exc}")
            return None


async def _prompt_jump_host(ctx: SharedContext, host: Any) -> str | None:
    """Prompt for jump host/bastion details."""
    jump_host = await ctx.ui.prompt(
        "Jump host / bastion (Enter to skip)", default=host.jump_host or ""
    )
    return jump_host or host.jump_host


async def _prompt_passphrase(ctx: SharedContext, key_path: Path) -> str | None:
    """Prompt user for key passphrase."""
    secret = await ctx.ui.prompt_secret(f"🔐 Passphrase for {key_path}")
    return secret or None


def _get_cached_passphrase(ctx: SharedContext, host_name: str, key_path: Path | str) -> str | None:
    """Fetch stored passphrase for host or key filename if available."""
    resolved = str(Path(key_path).expanduser())
    keys = _candidate_passphrase_keys(host_name, resolved, key_path)
    return _lookup_passphrase(ctx, keys)


def _store_passphrase(ctx: SharedContext, host: Any, passphrase: str | None) -> None:
    """Persist validated passphrase securely."""
    if passphrase and host.private_key:
        try:
            for key in _candidate_passphrase_keys(
                host.name,
                str(Path(host.private_key).expanduser()),
                host.private_key,
            ):
                ctx.secrets.set(key, passphrase)
            ctx.ui.success("✅ Passphrase stored securely")
        except Exception as exc:
            logger.debug(f"Failed to store passphrase: {exc}")


def _candidate_passphrase_keys(
    host_name: str, resolved_path: str, original_path: str | Path
) -> list[str]:
    """Build candidate key names for passphrase lookup."""
    name = Path(original_path).name
    return [
        f"ssh:passphrase:{host_name}",
        f"ssh:passphrase:{name}",
        f"ssh:passphrase:{resolved_path}",
    ]


def _lookup_passphrase(ctx: SharedContext, keys: list[str]) -> str | None:
    """
    Try to retrieve a passphrase from secret store or keyring for the given keys.

    Keyring lookup is attempted even if SecretStore marked keyring unavailable,
    to support pre-existing secrets added manually.
    """
    for key in keys:
        secret = ctx.secrets.get(key)
        if secret:
            return secret

    # Fallback: direct keyring lookup (service name matches SecretStore)
    try:
        import keyring

        for key in keys:
            value = keyring.get_password("merlya", key)
            if value:
                return value
    except Exception as exc:
        logger.debug(f"Keyring lookup failed: {exc}")

    return None


@subcommand("ssh", "test", "Test SSH connection to a host", "/ssh test <host>")
async def cmd_ssh_test(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Test SSH connection with diagnostic output."""
    if not args:
        return CommandResult(success=False, message="Usage: `/ssh test <host>`")

    host_name = args[0].lstrip("@")
    host = await ctx.hosts.get_by_name(host_name)

    if not host:
        return CommandResult(success=False, message=f"❌ Host '{host_name}' not found.")

    ctx.ui.info(f"🔍 Testing SSH to `{host_name}` ({host.hostname}:{host.port})...")

    lines = _build_test_header(host_name, host)

    try:
        start = time.time()
        ssh_pool = await ctx.get_ssh_pool()
        _install_ssh_callbacks(ctx, ssh_pool, host.name, host.private_key)

        options = SSHConnectionOptions(
            port=host.port,
            jump_host=host.jump_host,
        )
        await ssh_pool.get_connection(
            host=host.hostname,
            username=host.username,
            private_key=host.private_key,
            options=options,
        )

        connect_time = time.time() - start

        result = await ssh_pool.execute(
            host=host.hostname,
            command="echo 'SSH OK' && uname -a",
            username=host.username,
            options=options,
        )

        total_time = time.time() - start

        if result.exit_code == 0:
            lines.extend(
                [
                    "**Result:** ✅ Success",
                    f"  - Connect time: `{connect_time:.2f}s`",
                    f"  - Total time: `{total_time:.2f}s`",
                    f"  - Remote OS: `{result.stdout.strip().split(chr(10))[-1]}`",
                ]
            )
            return CommandResult(success=True, message="\n".join(lines))
        else:
            lines.extend(
                [
                    "**Result:** ⚠️ Connected but command failed",
                    f"  - Exit code: `{result.exit_code}`",
                    f"  - Error: `{result.stderr}`",
                ]
            )
            return CommandResult(success=False, message="\n".join(lines))

    except Exception as e:
        lines.extend(_build_error_troubleshooting(str(e), host.hostname))
        return CommandResult(success=False, message="\n".join(lines))


def _build_test_header(host_name: str, host: Any) -> list[str]:
    """Build SSH test header lines."""
    return [
        f"**SSH Test for `{host_name}`**",
        "",
        "**Config:**",
        f"  - Hostname: `{host.hostname}`",
        f"  - Port: `{host.port}`",
        f"  - User: `{host.username or 'default'}`",
        f"  - Key: `{host.private_key or 'ssh-agent'}`",
        f"  - Jump: `{host.jump_host or 'direct'}`",
        "",
    ]


def _build_error_troubleshooting(error_msg: str, hostname: str) -> list[str]:
    """Build error troubleshooting lines."""
    lines = [
        "**Result:** ❌ Failed",
        f"  - Error: `{error_msg}`",
        "",
        "**Troubleshooting:**",
    ]

    if "Passphrase" in error_msg or "encrypted" in error_msg.lower():
        lines.append("  - Your key is encrypted. Add it to ssh-agent: `ssh-add ~/.ssh/id_rsa`")
    elif "Host key" in error_msg or "trusted" in error_msg.lower():
        lines.append(
            f"  - Host key not trusted. Run: `ssh-keyscan {hostname} >> ~/.ssh/known_hosts`"
        )
    elif "Connection refused" in error_msg:
        lines.append("  - SSH port may be blocked or service not running")
    elif "timeout" in error_msg.lower():
        lines.append("  - Check network connectivity and firewall rules")
    elif "Authentication" in error_msg or "permission" in error_msg.lower():
        lines.append("  - Check username and key permissions (should be 600)")
    else:
        lines.append("  - Check host connectivity and SSH configuration")

    return lines
