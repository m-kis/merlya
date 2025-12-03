"""
SSH-based scanning logic.

Provides async SSH scanning with:
- Intelligent credential resolution (host-specific > global > default)
- Comprehensive error handling with actionable messages
- Multiple fallback methods for port detection
- Timeout-protected command execution to prevent blocking
"""
import asyncio
import os
from typing import Any, Dict, List, Optional, Tuple

import paramiko

from merlya.executors.ssh_utils import exec_command_with_timeout
from merlya.security.ssh_credentials import check_key_needs_passphrase
from merlya.utils.logger import logger

from .config import ScanConfig

# Alias for backward compatibility - provides timeout-protected command execution
_exec_command_safe = exec_command_with_timeout


def _get_ssh_credentials(hostname: str) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    """
    Get SSH credentials for a hostname.

    Resolution priority:
    1. Host-specific key from inventory metadata
    2. Global key (ssh_key_global variable)
    3. SSH config IdentityFile
    4. Default keys (id_ed25519, id_rsa, etc.)

    Args:
        hostname: Target hostname

    Returns:
        Tuple of (username, key_path, passphrase, source_description)
    """
    from merlya.security.credentials import CredentialManager
    creds = CredentialManager()

    user = creds.get_user_for_host(hostname)
    key_path, passphrase, source = creds.resolve_ssh_for_host(hostname, prompt_passphrase=False)

    return user, key_path, passphrase, source


async def ssh_scan(
    hostname: str,
    scan_type: str,
    config: ScanConfig,
    connect_host: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Perform SSH-based scan.

    Args:
        hostname: Hostname for credential lookup (canonical name)
        scan_type: Type of scan (system, services, full)
        config: Scan configuration
        connect_host: Actual host/IP to connect to (defaults to hostname if not provided)

    Returns:
        Scan data from SSH, including:
        - ssh_connected: bool
        - ssh_user: str (if connected)
        - error: str (if failed, with actionable message)
        - Various system info depending on scan_type
    """
    # Use resolved IP for connection, hostname for credentials
    connect_target = connect_host or hostname
    data: Dict[str, Any] = {}
    client = None

    try:
        import paramiko

        # Get SSH credentials using unified resolution
        user, key_path, passphrase, source = _get_ssh_credentials(hostname)

        # Log credential resolution (sanitized)
        if key_path:
            key_name = os.path.basename(key_path)
            logger.debug(f"🔑 SSH credentials for {hostname}: user={user}, key={key_name}, source={source}")
        else:
            logger.debug(f"🔑 SSH credentials for {hostname}: user={user}, no key configured")

        # Check if key needs passphrase but we don't have one
        if key_path and not passphrase:
            if check_key_needs_passphrase(key_path, skip_validation=True):
                data["ssh_connected"] = False
                data["error"] = (
                    f"SSH key requires passphrase. Configure it with:\n"
                    f"  /inventory ssh-key set {key_path}\n"
                    f"Or set a global passphrase at startup."
                )
                return data

        # Connect
        client = paramiko.SSHClient()

        # Determine host key policy from config or environment
        # Environment variable overrides config for testing/non-production
        env_auto_add = os.environ.get("MERLYA_SSH_AUTO_ADD_HOSTS", "").lower() in ("1", "true", "yes")
        policy_name = "auto_add" if env_auto_add else config.ssh_host_key_policy

        # Load system known_hosts for security
        known_hosts_corrupted = False
        try:
            client.load_system_host_keys()
        except FileNotFoundError:
            # known_hosts file doesn't exist - common on fresh systems
            logger.warning(
                "System known_hosts file not found. "
                "Set MERLYA_SSH_AUTO_ADD_HOSTS=1 to allow connections without host verification."
            )
        except PermissionError as e:
            # Can't read known_hosts - security concern
            logger.warning(
                f"Permission denied reading known_hosts: {e}. "
                "Set MERLYA_SSH_AUTO_ADD_HOSTS=1 to allow connections without host verification."
            )
        except paramiko.ssh_exception.SSHException as e:
            # Parsing error in known_hosts file - this is a real problem
            # Force RejectPolicy and skip further policy configuration
            logger.error(
                f"Failed to parse known_hosts file: {e}. "
                "The file may be corrupted. Using RejectPolicy for safety."
            )
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            known_hosts_corrupted = True

        # Set host key policy based on configuration
        # Skip if known_hosts was corrupted - RejectPolicy already enforced above
        if known_hosts_corrupted:
            logger.debug("SSH host key policy: RejectPolicy (known_hosts corrupted)")
        elif policy_name == "auto_add":
            if env_auto_add:
                logger.warning(
                    "SSH AutoAddPolicy enabled via MERLYA_SSH_AUTO_ADD_HOSTS env var. "
                    "This should only be used in non-production environments."
                )
            else:
                logger.warning(
                    "SSH AutoAddPolicy enabled via config. "
                    "This is insecure and should only be used for testing."
                )
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        elif policy_name == "warning":
            # WarningPolicy: Log warning but accept unknown hosts
            # Suitable for internal networks where hosts may not be pre-registered
            client.set_missing_host_key_policy(paramiko.WarningPolicy())
            logger.debug("SSH host key policy: WarningPolicy (allows unknown hosts with warning)")
        elif policy_name == "reject":
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            logger.debug("SSH host key policy: RejectPolicy (strictest)")
        else:
            # Default: WarningPolicy - balanced for most use cases
            client.set_missing_host_key_policy(paramiko.WarningPolicy())
            logger.debug("SSH host key policy: WarningPolicy (default)")

        # Check if ssh-agent is available
        from merlya.security.credentials import CredentialManager
        creds = CredentialManager()
        agent_available = creds.is_agent_available()

        loop = asyncio.get_running_loop()
        logger.debug(f"🔌 SSH connecting to {connect_target} (credentials from {hostname})")
        await loop.run_in_executor(
            None,
            lambda: client.connect(
                connect_target,  # Use resolved IP, not hostname
                username=user,
                key_filename=key_path,
                passphrase=passphrase,
                timeout=config.connect_timeout,
                allow_agent=agent_available,
            )
        )

        data["ssh_connected"] = True
        data["ssh_user"] = user

        # Run commands based on scan type
        if scan_type in ["system", "full"]:
            data.update(await _get_system_info(client, config))

        if scan_type in ["services", "full"]:
            data.update(await _get_services_info(client, config))

        if scan_type == "full":
            data.update(await _get_full_info(client, config))

    except ImportError:
        data["ssh_connected"] = False
        data["error"] = "paramiko not installed"
    except paramiko.ssh_exception.PasswordRequiredException:
        data["ssh_connected"] = False
        logger.warning(f"SSH scan failed for {hostname}: Password/Passphrase required")
        data["error"] = "SSH key is encrypted. Please set passphrase: /inventory ssh-key <host> set"
    except Exception as e:
        data["ssh_connected"] = False
        error_str = str(e)
        error_type = type(e).__name__

        # Log full error internally but expose only safe info to prevent leaking
        # sensitive paths, hostnames, or authentication details
        logger.debug(f"SSH scan failed for {hostname}: {e}")

        # Provide more helpful error messages for common issues
        if "Incorrect padding" in error_str:
            data["error"] = "SSH key encoding error (check key format or passphrase)"
        elif "Broken pipe" in error_str:
            data["error"] = "SSH connection closed by server (check firewall/network)"
        elif "Authentication failed" in error_str or "AuthenticationException" in error_type:
            data["error"] = "SSH authentication failed (check credentials)"
        elif "No route to host" in error_str or "Network is unreachable" in error_str:
            data["error"] = "Host unreachable (check network connectivity)"
        elif "Connection refused" in error_str:
            data["error"] = "SSH connection refused (check if SSH is running)"
        elif "timed out" in error_str.lower():
            data["error"] = "SSH connection timed out"
        else:
            data["error"] = f"SSH connection failed: {error_type}"
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    return data


async def _get_system_info(
    client: paramiko.SSHClient, config: ScanConfig
) -> Dict[str, Any]:
    """Get system information via SSH with timeout protection."""
    data: Dict[str, Any] = {}
    loop = asyncio.get_running_loop()
    timeout = config.command_timeout

    # Shell commands for system info (Linux with macOS fallbacks)
    memory_cmd = (
        "free -m 2>/dev/null | awk '/^Mem:/{print $2}' || "
        "sysctl -n hw.memsize 2>/dev/null | awk '{print $0/1048576}'"
    )
    commands = {
        "os": "cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"'",
        "kernel": "uname -r",
        "uptime": "uptime -p 2>/dev/null || uptime",
        "cpu_count": "nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null",
        "memory_mb": memory_cmd,
        "hostname_full": "hostname -f 2>/dev/null || hostname",
    }

    for key, cmd in commands.items():
        try:
            result = await loop.run_in_executor(
                None, _exec_command_safe, client, cmd, timeout
            )
            if result:
                data[key] = result
        except Exception as e:
            logger.debug(f"⚠️ Failed to get {key}: {e}")

    return data


async def _get_services_info(
    client: paramiko.SSHClient, config: ScanConfig
) -> Dict[str, Any]:
    """Get services information via SSH with timeout protection."""
    data: Dict[str, Any] = {}
    loop = asyncio.get_running_loop()
    timeout = config.command_timeout

    # Try systemd first
    try:
        cmd = "systemctl list-units --type=service --state=running --no-pager --no-legend 2>/dev/null | head -20"
        result = await loop.run_in_executor(
            None, _exec_command_safe, client, cmd, timeout
        )
        if result:
            services = []
            for line in result.split('\n'):
                parts = line.split()
                if parts:
                    service_name = parts[0].replace('.service', '')
                    services.append(service_name)
            data["services"] = services
    except Exception as e:
        logger.debug(f"⚠️ Failed to get services: {e}")

    # Check common ports
    data["open_ports"] = await _check_common_ports(client, config)

    return data


async def _check_common_ports(
    client: paramiko.SSHClient, config: ScanConfig
) -> List[int]:
    """
    Check common service ports on the remote host with timeout protection.

    Uses multiple fallback methods for portability:
    1. ss command (modern Linux, most reliable)
    2. netstat command (older systems, BSD)
    3. /proc/net/tcp parsing (Linux fallback)

    Returns:
        List of open ports from the common ports list.
    """
    loop = asyncio.get_running_loop()
    timeout = config.command_timeout
    common_ports = {22, 80, 443, 3306, 5432, 6379, 27017, 8080, 9000}
    open_ports = set()

    # Method 1: Try ss (modern Linux)
    try:
        cmd = "ss -tlnH 2>/dev/null | awk '{print $4}' | grep -oE '[0-9]+$'"
        result = await loop.run_in_executor(
            None, _exec_command_safe, client, cmd, timeout
        )
        if result:
            for line in result.split('\n'):
                line = line.strip()
                if line.isdigit():
                    port = int(line)
                    if port in common_ports:
                        open_ports.add(port)
            if open_ports:
                return sorted(open_ports)
    except Exception as e:
        logger.debug(f"⚠️ ss command failed: {e}")

    # Method 2: Try netstat (older Linux, BSD, macOS)
    try:
        cmd = (
            "netstat -tlnp 2>/dev/null | awk 'NR>2 {print $4}' | grep -oE '[0-9]+$' || "
            "netstat -an 2>/dev/null | grep LISTEN | awk '{print $4}' | grep -oE '[0-9]+$'"
        )
        result = await loop.run_in_executor(
            None, _exec_command_safe, client, cmd, timeout
        )
        if result:
            for line in result.split('\n'):
                line = line.strip()
                if line.isdigit():
                    port = int(line)
                    if port in common_ports:
                        open_ports.add(port)
            if open_ports:
                return sorted(open_ports)
    except Exception as e:
        logger.debug(f"⚠️ netstat command failed: {e}")

    # Method 3: Parse /proc/net/tcp directly (Linux fallback, doesn't require ss/netstat)
    try:
        cmd = "cat /proc/net/tcp /proc/net/tcp6 2>/dev/null | awk 'NR>1 && $4==\"0A\" {print $2}' | cut -d: -f2"
        result = await loop.run_in_executor(
            None, _exec_command_safe, client, cmd, timeout
        )
        if result:
            for line in result.split('\n'):
                line = line.strip()
                if line:
                    try:
                        # /proc/net/tcp ports are in hex
                        port = int(line, 16)
                        if port in common_ports:
                            open_ports.add(port)
                    except ValueError:
                        continue
    except Exception as e:
        logger.debug(f"⚠️ /proc/net/tcp parsing failed: {e}")

    return sorted(open_ports)


async def _get_full_info(
    client: paramiko.SSHClient, config: ScanConfig
) -> Dict[str, Any]:
    """Get full system information via SSH with timeout protection."""
    data: Dict[str, Any] = {}
    loop = asyncio.get_running_loop()
    timeout = config.command_timeout

    # Disk usage
    try:
        cmd = "df -h / 2>/dev/null | tail -1 | awk '{print $5}'"
        result = await loop.run_in_executor(
            None, _exec_command_safe, client, cmd, timeout
        )
        if result:
            data["disk_usage_root"] = result
    except Exception:
        pass

    # Load average
    try:
        cmd = "cat /proc/loadavg 2>/dev/null | cut -d' ' -f1-3"
        result = await loop.run_in_executor(
            None, _exec_command_safe, client, cmd, timeout
        )
        if result:
            data["load_avg"] = result
    except Exception:
        pass

    # Process count
    try:
        cmd = "ps aux 2>/dev/null | wc -l"
        result = await loop.run_in_executor(
            None, _exec_command_safe, client, cmd, timeout
        )
        if result:
            data["process_count"] = int(result)
    except Exception:
        pass

    return data
