import socket
from typing import Optional, Tuple

import paramiko

from merlya.executors.connectivity import ConnectivityPlanner
from merlya.executors.ssh_connection_pool import get_connection_pool
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

    def _connect_via_jump_host(
        self, target_host: str, jump_host: str, user: str, connect_kwargs: dict
    ) -> paramiko.SSHClient:
        """
        Establish a connection to target_host via jump_host.
        """
        logger.info(f"🌐 Initiating jump connection: Local -> {jump_host} -> {target_host}")

        # 1. Connect to Jump Host
        # We reuse the execute logic recursively, but here we need the raw client
        # For simplicity, we'll create a direct client to the jump host
        jump_client = paramiko.SSHClient()
        jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # Get jump host credentials using resolve_ssh_for_host
        jump_user = self.credentials.get_user_for_host(jump_host) or user
        jump_key, jump_passphrase, _ = self.credentials.resolve_ssh_for_host(
            jump_host, prompt_passphrase=True
        )

        jump_kwargs = connect_kwargs.copy()
        if jump_key:
            jump_kwargs["key_filename"] = jump_key
        if jump_passphrase:
            jump_kwargs["passphrase"] = jump_passphrase

        jump_client.connect(jump_host, username=jump_user, **jump_kwargs)

        # 2. Create Channel
        transport = jump_client.get_transport()
        if transport is None:
            raise paramiko.SSHException("Failed to get transport from jump host")
        dest_addr = (target_host, 22)
        local_addr = ('127.0.0.1', 0)  # Source doesn't matter much
        channel = transport.open_channel("direct-tcpip", dest_addr, local_addr)

        # 3. Connect to Target through Channel
        target_client = paramiko.SSHClient()
        target_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        target_client.connect(target_host, username=user, sock=channel, **connect_kwargs)

        return target_client

    def execute(
        self,
        host: str,
        command: str,
        user: Optional[str] = None,
        key_path: Optional[str] = None,
        passphrase: Optional[str] = None,
        timeout: int = 60,
        show_spinner: bool = True
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

        # Determine connection strategy
        # Try to resolve IP for routing check
        target_ip = None
        try:
            target_ip = socket.gethostbyname(host)
        except socket.gaierror:
            pass

        strategy = self.connectivity.get_connection_strategy(host, target_ip)

        # Use spinner for connection phase if enabled
        def _establish_connection():
            nonlocal strategy
            if strategy.method == 'jump':
                return self._connect_via_jump_host(
                    host, strategy.jump_host, user, connect_kwargs
                ), True
            else:
                if self.use_pool and self.pool:
                    conn = self.pool.get_connection(host, user, **connect_kwargs)
                    return conn, False
                else:
                    client = paramiko.SSHClient()
                    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    client.connect(host, username=user, **connect_kwargs)
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

            # Execute command
            logger.debug(f"⚡ Executing: {redact_sensitive_info(command)}")
            stdin, stdout, stderr = client.exec_command(command, timeout=timeout)

            # Set timeout on channel
            stdout.channel.settimeout(timeout)

            # Wait for completion
            try:
                exit_code = stdout.channel.recv_exit_status()
                out = stdout.read().decode('utf-8', errors='replace').strip()
                err = stderr.read().decode('utf-8', errors='replace').strip()

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

        except socket.timeout:
            logger.error(f"⏱️ SSH connection timed out on {host}")
            return -1, "", "SSH connection timed out"

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
