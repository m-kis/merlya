import paramiko
import socket
from typing import Optional, Tuple
from athena_ai.security.credentials import CredentialManager
from athena_ai.executors.ssh_connection_pool import get_connection_pool
from athena_ai.executors.connectivity import ConnectivityPlanner
from athena_ai.utils.logger import logger


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

    def _connect_via_jump_host(self, target_host: str, jump_host: str, user: str, connect_kwargs: dict) -> paramiko.SSHClient:
        """
        Establish a connection to target_host via jump_host.
        """
        logger.info(f"Initiating jump connection: Local -> {jump_host} -> {target_host}")
        
        # 1. Connect to Jump Host
        # We reuse the execute logic recursively, but here we need the raw client
        # For simplicity, we'll create a direct client to the jump host
        jump_client = paramiko.SSHClient()
        jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Get jump host credentials
        jump_user = self.credentials.get_user_for_host(jump_host) or user
        jump_key = self.credentials.get_key_for_host(jump_host) or self.credentials.get_default_key()
        
        jump_kwargs = connect_kwargs.copy()
        if jump_key:
            jump_kwargs["key_filename"] = jump_key
            
        jump_client.connect(jump_host, username=jump_user, **jump_kwargs)
        
        # 2. Create Channel
        transport = jump_client.get_transport()
        dest_addr = (target_host, 22)
        local_addr = ('127.0.0.1', 0) # Source doesn't matter much
        channel = transport.open_channel("direct-tcpip", dest_addr, local_addr)
        
        # 3. Connect to Target through Channel
        target_client = paramiko.SSHClient()
        target_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        target_client.connect(target_host, username=user, sock=channel, **connect_kwargs)
        
        return target_client

    def execute(self, host: str, command: str, user: Optional[str] = None, key_path: Optional[str] = None, timeout: int = 60) -> Tuple[int, str, str]:
        """
        Execute a command on a remote host via SSH using user's credentials.

        Args:
            host: Hostname or IP
            command: Shell command to execute
            user: SSH user (auto-detected from config if not provided)
            key_path: SSH key path (auto-detected if not provided)
            timeout: Command timeout in seconds (default: 60)

        Returns: (exit_code, stdout, stderr)
        """
        # Auto-detect user from SSH config if not provided
        if not user:
            user = self.credentials.get_user_for_host(host)

        # Auto-detect key from SSH config if not provided
        if not key_path:
            key_path = self.credentials.get_key_for_host(host)
            if not key_path:
                key_path = self.credentials.get_default_key()

        logger.debug(f"Connecting to {host} as {user}")
        if key_path:
            logger.debug(f"Using key: {key_path}")

        # Prepare connection kwargs
        connect_kwargs = {
            "timeout": 5,  # Reduced timeout for faster failure on 2FA prompts
            "auth_timeout": 5,  # Auth-specific timeout
            "banner_timeout": 5,  # Banner read timeout
            "allow_agent": True,  # Use ssh-agent if available
            "look_for_keys": True,  # Look for keys in ~/.ssh
        }

        # Add specific key if provided
        if key_path:
            connect_kwargs["key_filename"] = key_path

        # Determine connection strategy
        # Try to resolve IP for routing check
        target_ip = None
        try:
            target_ip = socket.gethostbyname(host)
        except:
            pass
            
        strategy = self.connectivity.get_connection_strategy(host, target_ip)
        
        if strategy.method == 'jump':
            # JUMP HOST CONNECTION
            try:
                client = self._connect_via_jump_host(host, strategy.jump_host, user, connect_kwargs)
                should_close = True
            except Exception as e:
                logger.error(f"Jump host connection failed: {e}")
                return -1, "", f"Failed to connect via {strategy.jump_host}: {e}"
        else:
            # DIRECT CONNECTION
            # Get connection from pool or create new one
            if self.use_pool and self.pool:
                client = self.pool.get_connection(host, user, **connect_kwargs)
                if client is None:
                    return -1, "", "Failed to establish SSH connection"
                should_close = False  # Don't close pooled connections
            else:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                try:
                    client.connect(host, username=user, **connect_kwargs)
                except Exception as e:
                    logger.error(f"Connection failed: {e}")
                    return -1, "", str(e)
                should_close = True  # Close non-pooled connections

        try:

            # Execute command
            logger.debug(f"Executing: {command}")
            stdin, stdout, stderr = client.exec_command(command, timeout=timeout)

            # Set timeout on channel
            stdout.channel.settimeout(timeout)

            # Wait for completion
            try:
                exit_code = stdout.channel.recv_exit_status()
                out = stdout.read().decode('utf-8', errors='replace').strip()
                err = stderr.read().decode('utf-8', errors='replace').strip()

                logger.debug(f"Command completed with exit code {exit_code}")

                return exit_code, out, err

            except socket.timeout:
                logger.error(f"Command timed out after {timeout}s on {host}")
                return -1, "", f"Command timed out after {timeout} seconds"

        except paramiko.AuthenticationException as e:
            logger.error(f"SSH authentication failed for {user}@{host}: {e}")
            return -1, "", f"Authentication failed: {e}"

        except paramiko.SSHException as e:
            logger.error(f"SSH error on {host}: {e}")
            return -1, "", f"SSH error: {e}"

        except socket.timeout:
            logger.error(f"SSH connection timed out on {host}")
            return -1, "", f"SSH connection timed out"

        except Exception as e:
            logger.error(f"Unexpected error connecting to {host}: {e}")
            return -1, "", str(e)

        finally:
            # Only close connection if not using pool
            if should_close:
                client.close()

    def test_connection(self, host: str, user: Optional[str] = None) -> bool:
        """Test if SSH connection to host is possible."""
        exit_code, stdout, stderr = self.execute(host, "echo 'test'", user=user)
        return exit_code == 0
