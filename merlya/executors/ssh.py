import socket
from typing import Optional, Tuple

import paramiko

from merlya.context.host_resolution import resolve_host
from merlya.executors.connectivity import ConnectionStrategy, ConnectivityPlanner
from merlya.executors.ssh_connection_pool import get_connection_pool
from merlya.executors.ssh_utils import read_channel_with_timeout
from merlya.security.credentials import CredentialManager
from merlya.utils.display import get_display_manager
from merlya.utils.logger import logger
from merlya.utils.security import redact_sensitive_info


class SSHManager:
    """
    SSH manager that uses the same credentials as the user's terminal.
    Supports: ssh-agent, ~/.ssh/config, and key files.
    Uses connection pooling to handle 2FA efficiently.
    """

    def __init__(self, use_connection_pool: bool = True):
        self.credentials = CredentialManager()
        self.use_pool = use_connection_pool
        self.pool = get_connection_pool() if use_connection_pool else None
        self.connectivity = ConnectivityPlanner()

    def _resolve_jump_host(self, jump_host: str) -> str:
        """
        Resolve jump host to its actual hostname/IP.

        Handles:
        - @variable references (e.g., @ansible -> actual hostname)
        - Inventory lookups
        - Direct hostnames/IPs
        """
        # Remove @ prefix if present
        if jump_host.startswith('@'):
            jump_host = jump_host[1:]

        # Try to resolve from inventory
        resolved = resolve_host(jump_host)
        if resolved.ip_address and resolved.ip_address != "unknown":
            logger.debug(f"Jump host {jump_host} resolved to {resolved.ip_address}")
            return resolved.connect_address

        return jump_host

    def _connect_via_jump_host(
        self, target_host: str, jump_host: str, user: str, connect_kwargs: dict,
        forward_agent: bool = True
    ) -> paramiko.SSHClient:
        """
        Establish a connection to target_host via jump_host with agent forwarding.

        This mimics `ssh -A jump_host` then `ssh target_host` behavior.

        Args:
            target_host: Final destination host
            jump_host: Intermediate jump/bastion host
            user: SSH user for target
            connect_kwargs: Connection parameters
            forward_agent: Enable SSH agent forwarding (default: True)

        Returns:
            SSHClient connected to target (with _jump_client reference for cleanup)

        Raises:
            paramiko.SSHException: If connection fails
        """
        # Resolve jump host (handles @variable references)
        resolved_jump = self._resolve_jump_host(jump_host)
        logger.info(f"Pivoting: Local -> {resolved_jump} -> {target_host}")

        jump_client: paramiko.SSHClient | None = None
        channel = None

        try:
            # 1. Connect to Jump Host
            jump_client = paramiko.SSHClient()
            jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Get jump host credentials
            jump_user = self.credentials.get_user_for_host(resolved_jump) or user
            jump_key, jump_passphrase, _ = self.credentials.resolve_ssh_for_host(
                resolved_jump, prompt_passphrase=True
            )

            jump_kwargs = connect_kwargs.copy()
            # Ensure agent is used for jump host
            jump_kwargs["allow_agent"] = True
            if jump_key:
                jump_kwargs["key_filename"] = jump_key
            if jump_passphrase:
                jump_kwargs["passphrase"] = jump_passphrase

            jump_client.connect(resolved_jump, username=jump_user, **jump_kwargs)
            logger.debug(f"Connected to jump host: {resolved_jump}")

            # 2. Create direct-tcpip channel to target
            transport = jump_client.get_transport()
            if transport is None:
                raise paramiko.SSHException("Failed to get transport from jump host")

            # Enable keepalive to detect broken connections
            if forward_agent:
                try:
                    transport.set_keepalive(30)
                    logger.debug("SSH keepalive enabled on jump host")
                except Exception as e:
                    logger.warning(f"Could not enable keepalive: {e}")

            dest_addr = (target_host, 22)
            local_addr = ('127.0.0.1', 0)
            channel = transport.open_channel("direct-tcpip", dest_addr, local_addr)
            logger.debug(f"Tunnel established: {resolved_jump} -> {target_host}")

            # 3. Connect to Target through the tunnel
            target_client = paramiko.SSHClient()
            target_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # For target connection, we use the channel as socket
            target_kwargs = connect_kwargs.copy()
            target_kwargs["allow_agent"] = True  # Use forwarded agent

            target_client.connect(target_host, username=user, sock=channel, **target_kwargs)
            logger.debug(f"Connected to target: {target_host} via {resolved_jump}")

            # Store jump client reference to prevent premature closure
            # and enable proper cleanup when target_client is closed
            target_client._jump_client = jump_client  # type: ignore

            return target_client

        except Exception as e:
            # Clean up jump host connection if target connection fails
            logger.error(f"Jump host connection failed: {e}")
            if channel is not None:
                try:
                    channel.close()
                except Exception:
                    pass
            if jump_client is not None:
                try:
                    jump_client.close()
                    logger.debug(f"Closed jump host connection to {resolved_jump} after failure")
                except Exception:
                    pass
            raise

    def execute(
        self,
        host: str,
        command: str,
        user: Optional[str] = None,
        key_path: Optional[str] = None,
        passphrase: Optional[str] = None,
        timeout: int = 60,
        show_spinner: bool = True,
        jump_host: Optional[str] = None
    ) -> Tuple[int, str, str]:
        """
        Execute a command on a remote host via SSH using user's credentials.

        Args:
            host: Hostname or IP
            command: Shell command to execute
            user: SSH user (auto-detected from config if not provided)
            key_path: SSH key path (auto-detected if not provided)
            passphrase: SSH key passphrase (auto-resolved if not provided)
            timeout: Command timeout in seconds (default: 60)
            show_spinner: Show spinner during SSH operations (default: True)
            jump_host: Optional jump host to connect through (e.g., bastion server)

        Returns: (exit_code, stdout, stderr)
        """
        # Auto-detect user from SSH config if not provided
        if not user:
            user = self.credentials.get_user_for_host(host)

        # Resolve SSH key and passphrase using priority system
        # Priority: explicit args > host metadata > global > ssh_config > default
        if not key_path:
            resolved_key, resolved_passphrase, source = self.credentials.resolve_ssh_for_host(
                host, prompt_passphrase=True
            )
            key_path = resolved_key
            if passphrase is None:
                passphrase = resolved_passphrase
            if source:
                logger.debug(f"🔑 SSH key resolved from: {source}")

        logger.debug(f"🔍 Connecting to {host} as {user}")
        if key_path:
            logger.debug(f"🔑 Using key: {key_path}")

        display = get_display_manager()

        # Prepare connection kwargs
        connect_kwargs: dict = {
            "timeout": 5,  # Reduced timeout for faster failure on 2FA prompts
            "auth_timeout": 5,  # Auth-specific timeout
            "banner_timeout": 5,  # Banner read timeout
            "allow_agent": True,  # Use ssh-agent if available
            "look_for_keys": True,  # Look for keys in ~/.ssh
        }

        # Add specific key if provided
        if key_path:
            connect_kwargs["key_filename"] = key_path

        # Add passphrase if provided
        if passphrase:
            connect_kwargs["passphrase"] = passphrase

        # Determine connection strategy using unified host resolution
        # Priority: inventory IP > DNS > hostname
        resolved = resolve_host(host)
        connect_host = resolved.connect_address  # IP if available, else hostname
        target_ip = resolved.ip_address

        logger.debug(f"📍 Host resolution: {resolved}")

        # If explicit jump_host provided, use it; otherwise auto-detect
        if jump_host:
            logger.info(f"🌐 Using explicit jump host: {jump_host}")
            strategy = ConnectionStrategy(method='jump', jump_host=jump_host)
        else:
            strategy = self.connectivity.get_connection_strategy(host, target_ip)

        # Use spinner for connection phase if enabled
        def _establish_connection():
            nonlocal strategy
            if strategy.method == 'jump':
                return self._connect_via_jump_host(
                    connect_host, strategy.jump_host, user, connect_kwargs
                ), True
            else:
                if self.use_pool and self.pool:
                    # Use connect_host (IP from inventory or hostname)
                    conn = self.pool.get_connection(connect_host, user, **connect_kwargs)
                    return conn, False
                else:
                    client = paramiko.SSHClient()
                    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    client.connect(connect_host, username=user, **connect_kwargs)
                    return client, True

        try:
            if show_spinner:
                with display.spinner(f"🔌 Connecting to {host}..."):
                    client, should_close = _establish_connection()
            else:
                client, should_close = _establish_connection()

            if client is None:
                return -1, "", "Failed to establish SSH connection"

        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            return -1, "", str(e)

        try:
            # Execute command using transport channel for proper timeout control
            logger.debug(f"⚡ Executing: {redact_sensitive_info(command)}")

            transport = client.get_transport()
            if not transport or not transport.is_active():
                logger.error(f"❌ SSH transport not active for {host}")
                return -1, "", "SSH transport not active"

            channel = transport.open_session()
            channel.settimeout(timeout)
            channel.exec_command(command)

            # Read with proper timeout protection (prevents blocking on Broken Pipe)
            out, err, exit_code = read_channel_with_timeout(channel, timeout)

            logger.debug(f"✅ Command completed with exit code {exit_code}")

            return exit_code, out, err

        except socket.timeout:
            logger.error(f"⏱️ Command timed out after {timeout}s on {host}")
            return -1, "", f"Command timed out after {timeout} seconds"

        except paramiko.AuthenticationException as e:
            logger.error(f"🔒 SSH authentication failed for {user}@{host}: {e}")
            return -1, "", f"Authentication failed: {e}"

        except paramiko.SSHException as e:
            logger.error(f"❌ SSH error on {host}: {e}")
            return -1, "", f"SSH error: {e}"

        except Exception as e:
            logger.error(f"❌ Unexpected error connecting to {host}: {e}")
            return -1, "", str(e)

        finally:
            # Only close connection if not using pool
            if should_close:
                client.close()

    def test_connection(self, host: str, user: Optional[str] = None) -> bool:
        """Test if SSH connection to host is possible."""
        exit_code, stdout, stderr = self.execute(host, "echo 'test'", user=user)
        return exit_code == 0
