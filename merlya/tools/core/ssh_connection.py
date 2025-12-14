"""
Merlya Tools - SSH connection handling.

Jump host resolution, callbacks, and SSH execution.
"""

from __future__ import annotations

import asyncio as _asyncio
import concurrent.futures
import ipaddress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.persistence.models import Host
    from merlya.ssh import SSHConnectionOptions, SSHPool


@dataclass(frozen=True)
class JumpHostConfig:
    """Jump host configuration for SSH tunneling."""

    host: str
    port: int | None = None
    username: str | None = None
    private_key: str | None = None


def is_ip_address(value: str) -> bool:
    """Return True if value is a valid IPv4/IPv6 address."""
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def ensure_callbacks(ctx: SharedContext, ssh_pool: SSHPool) -> None:
    """
    Ensure MFA and passphrase callbacks are set for SSH operations.

    Uses blocking prompts in background threads to avoid event-loop conflicts.
    """
    if hasattr(ssh_pool, "has_passphrase_callback") and not ssh_pool.has_passphrase_callback():

        def passphrase_cb(key_path: str) -> str:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    lambda: _asyncio.run(ctx.ui.prompt_secret(f"🔐 Passphrase for {key_path}"))
                )
                return future.result(timeout=60)

        ssh_pool.set_passphrase_callback(passphrase_cb)

    if hasattr(ssh_pool, "has_mfa_callback") and not ssh_pool.has_mfa_callback():

        def mfa_cb(prompt: str) -> str:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(lambda: _asyncio.run(ctx.ui.prompt_secret(f"🔐 {prompt}")))
                return future.result(timeout=120)

        ssh_pool.set_mfa_callback(mfa_cb)


async def resolve_jump_host(
    ctx: SharedContext,
    jump_host_name: str,
) -> JumpHostConfig:
    """
    Resolve jump host configuration from inventory or use directly.

    Args:
        ctx: Shared context.
        jump_host_name: Jump host name (inventory entry or hostname/IP).

    Returns:
        JumpHostConfig with resolved configuration.
    """
    try:
        jump_entry = await ctx.hosts.get_by_name(jump_host_name)
    except Exception:
        jump_entry = None

    if jump_entry:
        logger.debug(f"🔗 Using jump host '{jump_host_name}' ({jump_entry.hostname})")
        return JumpHostConfig(
            host=jump_entry.hostname,
            port=jump_entry.port,
            username=jump_entry.username,
            private_key=jump_entry.private_key,
        )

    logger.debug(f"🔗 Using jump host '{jump_host_name}' (direct)")
    return JumpHostConfig(host=jump_host_name)


async def execute_ssh_command(
    ssh_pool: SSHPool,
    host: str,
    host_entry: Host | None,
    command: str,
    timeout: int,
    input_data: str | None,
    ssh_opts: SSHConnectionOptions,
) -> Any:
    """
    Execute SSH command with proper options.

    Args:
        ssh_pool: SSH connection pool.
        host: Target host name or IP.
        host_entry: Host configuration from inventory, if available.
        command: Command to execute.
        timeout: Command timeout in seconds.
        input_data: Optional stdin data.
        ssh_opts: SSH connection options.

    Returns:
        SSH execution result.
    """
    if host_entry:
        from merlya.ssh import SSHConnectionOptions

        opts = SSHConnectionOptions(
            port=host_entry.port,
            connect_timeout=ssh_opts.connect_timeout,
        )
        if ssh_opts.jump_host:
            opts.jump_host = ssh_opts.jump_host
            opts.jump_port = ssh_opts.jump_port
            opts.jump_username = ssh_opts.jump_username
            opts.jump_private_key = ssh_opts.jump_private_key

        return await ssh_pool.execute(
            host=host_entry.hostname,
            command=command,
            timeout=timeout,
            input_data=input_data,
            username=host_entry.username,
            private_key=host_entry.private_key,
            options=opts,
            host_name=host,
        )

    return await ssh_pool.execute(
        host=host,
        command=command,
        timeout=timeout,
        input_data=input_data,
        options=ssh_opts,
        host_name=host,
    )
