import platform
import subprocess
import os
from typing import Dict, Any
from athena_ai.utils.logger import logger


class Discovery:
    def scan_local(self) -> Dict[str, Any]:
        """Scan the local system for basic information."""
        info = {
            "hostname": platform.node(),
            "os": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "services": self._get_active_services(),
            "processes": self._get_processes()
        }
        return info

    def _get_processes(self) -> list:
        """Get top running processes."""
        processes = []
        try:
            # Cross-platform way to get top processes (Linux/macOS)
            cmd = ["ps", "-eo", "pid,comm,%cpu,%mem", "--sort=-%cpu"]
            if platform.system() == "Darwin":
                 cmd = ["ps", "-eo", "pid,comm,%cpu,%mem"] # macOS ps doesn't support --sort like GNU ps
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                lines = result.stdout.splitlines()
                # Take top 10
                for line in lines[1:11]:
                    parts = line.split(maxsplit=3)
                    if len(parts) >= 4:
                        processes.append({
                            "pid": parts[0],
                            "name": parts[1],
                            "cpu": parts[2],
                            "mem": parts[3]
                        })
        except Exception:
            pass
        return processes

    def parse_inventory(self, inventory_path: str = "/etc/hosts") -> Dict[str, str]:
        """Parse /etc/hosts or similar file to build simple inventory."""
        hosts = {}
        try:
            with open(inventory_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        parts = line.split()
                        if len(parts) >= 2:
                            ip = parts[0]
                            for hostname in parts[1:]:
                                hosts[hostname] = ip
        except Exception as e:
            pass
        return hosts

    def _get_active_services(self) -> list:
        """Get a list of active systemd services (Linux only for now)."""
        services = []
        if platform.system() == "Linux":
            try:
                # Run systemctl to list active units
                cmd = ["systemctl", "list-units", "--type=service", "--state=active", "--no-pager", "--plain"]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        parts = line.split()
                        if parts:
                            services.append(parts[0])
            except Exception as e:
                # Log error in real implementation
                pass
        return services

    def scan_remote_hosts(self, inventory: Dict[str, str]) -> Dict[str, Any]:
        """
        Scan remote hosts via SSH to gather their system information.
        Returns a dict of {hostname: host_info}
        """
        # Import here to avoid circular dependency
        from athena_ai.executors.ssh import SSHManager

        hosts_info = {}
        ssh = SSHManager()

        logger.info(f"Scanning {len(inventory)} hosts from inventory...")

        for hostname, ip in inventory.items():
            # Skip localhost, broadcast, and special IPs
            skip_ips = ['127.0.0.1', '::1', 'localhost', '255.255.255.255', '0.0.0.0', 'ff02::1', 'ff02::2']
            skip_hostnames = ['localhost', 'broadcasthost', 'ip6-localhost', 'ip6-loopback',
                            'ip6-localnet', 'ip6-mcastprefix', 'ip6-allnodes', 'ip6-allrouters']

            if ip in skip_ips or hostname in skip_hostnames:
                logger.debug(f"Skipping {hostname} ({ip}) - local/broadcast IP")
                continue

            logger.debug(f"Attempting to connect to {hostname} ({ip})")

            # Test SSH connectivity
            exit_code, stdout, stderr = ssh.execute(ip, "echo 'test'")

            if exit_code == 0:
                logger.info(f"✓ {hostname} is accessible via SSH")

                # Gather system info
                host_info = {
                    'hostname': hostname,
                    'ip': ip,
                    'accessible': True,
                    'os': 'unknown',
                    'services': [],
                }

                # Get OS info
                exit_code, os_info, _ = ssh.execute(ip, "uname -s")
                if exit_code == 0:
                    host_info['os'] = os_info

                # Get kernel version
                exit_code, kernel, _ = ssh.execute(ip, "uname -r")
                if exit_code == 0:
                    host_info['kernel'] = kernel

                # Get hostname (actual)
                exit_code, actual_hostname, _ = ssh.execute(ip, "hostname")
                if exit_code == 0:
                    host_info['actual_hostname'] = actual_hostname

                # Get systemd services (if Linux)
                if 'Linux' in host_info['os']:
                    exit_code, services_output, _ = ssh.execute(
                        ip,
                        "systemctl list-units --type=service --state=running --no-pager --no-legend | awk '{print $1}' | head -20"
                    )
                    if exit_code == 0 and services_output:
                        host_info['services'] = [s.strip() for s in services_output.split('\n') if s.strip()]

                hosts_info[hostname] = host_info

            else:
                logger.warning(f"✗ {hostname} ({ip}) not accessible: {stderr}")
                hosts_info[hostname] = {
                    'hostname': hostname,
                    'ip': ip,
                    'accessible': False,
                    'error': stderr or 'Connection failed'
                }

        logger.info(f"Scan complete: {sum(1 for h in hosts_info.values() if h.get('accessible'))} hosts accessible")

        return hosts_info
