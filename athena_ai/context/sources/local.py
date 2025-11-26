from pathlib import Path
from typing import List

from athena_ai.context.sources.base import BaseSource, Host, InventorySource
from athena_ai.utils.logger import logger


class EtcHostsSource(BaseSource):
    """Source for /etc/hosts file."""

    def load(self) -> List[Host]:
        hosts_file = self.config.get("etc_hosts_path", "/etc/hosts")
        hosts = []

        if not Path(hosts_file).exists():
            logger.debug(f"Hosts file not found: {hosts_file}")
            return []

        try:
            with open(hosts_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    parts = line.split()
                    if len(parts) < 2:
                        continue

                    ip = parts[0]

                    # Skip special IPs
                    if ip in ["127.0.0.1", "::1", "255.255.255.255", "0.0.0.0"]:
                        continue
                    if ip.startswith("fe80::") or ip.startswith("ff02::"):
                        continue

                    # First name is canonical, rest are aliases
                    canonical = parts[1]
                    aliases = parts[2:] if len(parts) > 2 else []

                    # Skip special hostnames
                    if canonical in ["localhost", "broadcasthost", "ip6-localhost"]:
                        continue

                    hosts.append(Host(
                        hostname=canonical,
                        ip_address=ip,
                        aliases=aliases,
                        source=InventorySource.ETC_HOSTS,
                    ))

            logger.debug(f"Loaded {len(hosts)} hosts from {hosts_file}")
            return hosts

        except Exception as e:
            logger.warning(f"Failed to load {hosts_file}: {e}")
            return []


class SSHConfigSource(BaseSource):
    """Source for SSH config file."""

    def load(self) -> List[Host]:
        ssh_config = Path.home() / ".ssh" / "config"
        hosts = []

        if not ssh_config.exists():
            logger.debug("SSH config not found")
            return []

        try:
            current_host = None
            current_hostname = None

            with open(ssh_config, "r") as f:
                for line in f:
                    line = line.strip()

                    if line.lower().startswith("host "):
                        # Save previous host
                        if current_host and current_host != "*":
                            hosts.append(Host(
                                hostname=current_host,
                                ip_address=current_hostname,
                                source=InventorySource.SSH_CONFIG,
                            ))

                        # Start new host
                        current_host = line.split()[1]
                        current_hostname = None

                    elif line.lower().startswith("hostname "):
                        current_hostname = line.split()[1]

            # Save last host
            if current_host and current_host != "*":
                hosts.append(Host(
                    hostname=current_host,
                    ip_address=current_hostname,
                    source=InventorySource.SSH_CONFIG,
                ))

            logger.debug(f"Loaded {len(hosts)} hosts from SSH config")
            return hosts

        except Exception as e:
            logger.warning(f"Failed to load SSH config: {e}")
            return []
