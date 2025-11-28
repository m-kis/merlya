"""
SSH-based scanning logic.
"""
import asyncio
import os
from typing import Any, Dict, List

from athena_ai.utils.logger import logger

from .config import ScanConfig


async def ssh_scan(
    hostname: str,
    scan_type: str,
    config: ScanConfig,
) -> Dict[str, Any]:
    """
    Perform SSH-based scan.

    Args:
        hostname: Hostname to scan
        scan_type: Type of scan
        config: Scan configuration

    Returns:
        Scan data from SSH
    """
    data = {}
    client = None

    try:
        import paramiko

        # Get SSH credentials from context
        from athena_ai.security.credentials import CredentialManager
        creds = CredentialManager()
        user = creds.get_user_for_host(hostname)
        key_path = creds.get_key_for_host(hostname) or creds.get_default_key()

        # Connect
        client = paramiko.SSHClient()

        # Determine host key policy from config or environment
        # Environment variable overrides config for testing/non-production
        env_auto_add = os.environ.get("ATHENA_SSH_AUTO_ADD_HOSTS", "").lower() in ("1", "true", "yes")
        policy_name = "auto_add" if env_auto_add else config.ssh_host_key_policy

        # Load system known_hosts for security
        known_hosts_corrupted = False
        try:
            client.load_system_host_keys()
        except FileNotFoundError:
            # known_hosts file doesn't exist - common on fresh systems
            logger.warning(
                "System known_hosts file not found. "
                "Set ATHENA_SSH_AUTO_ADD_HOSTS=1 to allow connections without host verification."
            )
        except PermissionError as e:
            # Can't read known_hosts - security concern
            logger.warning(
                f"Permission denied reading known_hosts: {e}. "
                "Set ATHENA_SSH_AUTO_ADD_HOSTS=1 to allow connections without host verification."
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
                    "SSH AutoAddPolicy enabled via ATHENA_SSH_AUTO_ADD_HOSTS env var. "
                    "This should only be used in non-production environments."
                )
            else:
                logger.warning(
                    "SSH AutoAddPolicy enabled via config. "
                    "This is insecure and should only be used for testing."
                )
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        elif policy_name == "reject":
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            logger.debug("SSH host key policy: RejectPolicy (strictest)")
        else:
            # Default: RejectPolicy - safest option for production
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            logger.debug("SSH host key policy: RejectPolicy (default, strictest)")

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: client.connect(
                hostname,
                username=user,
                key_filename=key_path,
                timeout=config.connect_timeout,
                allow_agent=creds.is_agent_available(),
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
    except Exception as e:
        data["ssh_connected"] = False
        # Log full error internally but expose only safe info to prevent leaking
        # sensitive paths, hostnames, or authentication details
        logger.debug(f"SSH scan failed for {hostname}: {e}")
        data["error"] = f"SSH connection failed: {type(e).__name__}"
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    return data


async def _get_system_info(client, config: ScanConfig) -> Dict[str, Any]:
    """Get system information via SSH."""
    data = {}
    loop = asyncio.get_running_loop()

    commands = {
        "os": "cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"'",
        "kernel": "uname -r",
        "uptime": "uptime -p 2>/dev/null || uptime",
        "cpu_count": "nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null",
        "memory_mb": "free -m 2>/dev/null | awk '/^Mem:/{print $2}' || sysctl -n hw.memsize 2>/dev/null | awk '{print $0/1048576}'",
        "hostname_full": "hostname -f 2>/dev/null || hostname",
    }

    for key, cmd in commands.items():
        try:
            def run_command(c):
                _, stdout, _ = client.exec_command(c, timeout=config.command_timeout)
                return stdout.read().decode().strip()

            result = await loop.run_in_executor(None, run_command, cmd)
            if result:
                data[key] = result
        except Exception as e:
            logger.debug(f"Failed to get {key}: {e}")

    return data


async def _get_services_info(client, config: ScanConfig) -> Dict[str, Any]:
    """Get services information via SSH."""
    data = {}
    loop = asyncio.get_running_loop()

    # Try systemd first
    try:
        def run_systemctl():
            _, stdout, _ = client.exec_command(
                "systemctl list-units --type=service --state=running --no-pager --no-legend 2>/dev/null | head -20",
                timeout=config.command_timeout
            )
            return stdout.read().decode().strip()

        result = await loop.run_in_executor(None, run_systemctl)
        if result:
            services = []
            for line in result.split('\n'):
                parts = line.split()
                if parts:
                    service_name = parts[0].replace('.service', '')
                    services.append(service_name)
            data["services"] = services
    except Exception as e:
        logger.debug(f"Failed to get services: {e}")

    # Check common ports
    data["open_ports"] = await _check_common_ports(client, config)

    return data


async def _check_common_ports(client, config: ScanConfig) -> List[int]:
    """
    Check common service ports on the remote host.

    Uses multiple fallback methods for portability:
    1. ss command (modern Linux, most reliable)
    2. netstat command (older systems, BSD)
    3. /proc/net/tcp parsing (Linux fallback)

    Returns:
        List of open ports from the common ports list.
    """
    loop = asyncio.get_running_loop()
    common_ports = {22, 80, 443, 3306, 5432, 6379, 27017, 8080, 9000}
    open_ports = set()

    # Method 1: Try ss (modern Linux)
    try:
        def run_ss():
            _, stdout, _ = client.exec_command(
                "ss -tlnH 2>/dev/null | awk '{print $4}' | grep -oE '[0-9]+$'",
                timeout=config.command_timeout
            )
            return stdout.read().decode().strip()

        result = await loop.run_in_executor(None, run_ss)
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
        logger.debug(f"ss command failed: {e}")

    # Method 2: Try netstat (older Linux, BSD, macOS)
    try:
        def run_netstat():
            _, stdout, _ = client.exec_command(
                "netstat -tlnp 2>/dev/null | awk 'NR>2 {print $4}' | grep -oE '[0-9]+$' || "
                "netstat -an 2>/dev/null | grep LISTEN | awk '{print $4}' | grep -oE '[0-9]+$'",
                timeout=config.command_timeout
            )
            return stdout.read().decode().strip()

        result = await loop.run_in_executor(None, run_netstat)
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
        logger.debug(f"netstat command failed: {e}")

    # Method 3: Parse /proc/net/tcp directly (Linux fallback, doesn't require ss/netstat)
    try:
        def run_proc_tcp():
            _, stdout, _ = client.exec_command(
                "cat /proc/net/tcp /proc/net/tcp6 2>/dev/null | awk 'NR>1 && $4==\"0A\" {print $2}' | cut -d: -f2",
                timeout=config.command_timeout
            )
            return stdout.read().decode().strip()

        result = await loop.run_in_executor(None, run_proc_tcp)
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
        logger.debug(f"/proc/net/tcp parsing failed: {e}")

    return sorted(open_ports)


async def _get_full_info(client, config: ScanConfig) -> Dict[str, Any]:
    """Get full system information via SSH."""
    data = {}
    loop = asyncio.get_running_loop()

    # Disk usage
    try:
        def run_df():
            _, stdout, _ = client.exec_command(
                "df -h / 2>/dev/null | tail -1 | awk '{print $5}'",
                timeout=config.command_timeout
            )
            return stdout.read().decode().strip()

        result = await loop.run_in_executor(None, run_df)
        if result:
            data["disk_usage_root"] = result
    except Exception:
        pass

    # Load average
    try:
        def run_loadavg():
            _, stdout, _ = client.exec_command(
                "cat /proc/loadavg 2>/dev/null | cut -d' ' -f1-3",
                timeout=config.command_timeout
            )
            return stdout.read().decode().strip()

        result = await loop.run_in_executor(None, run_loadavg)
        if result:
            data["load_avg"] = result
    except Exception:
        pass

    # Process count
    try:
        def run_ps():
            _, stdout, _ = client.exec_command(
                "ps aux 2>/dev/null | wc -l",
                timeout=config.command_timeout
            )
            return stdout.read().decode().strip()

        result = await loop.run_in_executor(None, run_ps)
        if result:
            data["process_count"] = int(result)
    except Exception:
        pass

    return data
