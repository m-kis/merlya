from pathlib import Path
from typing import List, Optional

from athena_ai.context.sources.base import BaseSource, Host, InventorySource
from athena_ai.utils.logger import logger


class AnsibleSource(BaseSource):
    """Source for Ansible inventory."""

    def load(self) -> List[Host]:
        # Try common Ansible inventory locations
        inventory_paths = [
            Path.home() / "inventory",
            Path.home() / "ansible" / "inventory",
            Path.home() / "ansible" / "hosts",
            Path("/etc/ansible/hosts"),
            Path("./inventory"),
            Path("./hosts"),
        ]

        # Add configured paths
        if self.config.get("ansible_inventory_paths"):
            for p in self.config["ansible_inventory_paths"]:
                inventory_paths.append(Path(p))

        hosts = []
        for inv_path in inventory_paths:
            if inv_path.exists():
                hosts.extend(self._parse_ansible_inventory(inv_path))

        return hosts

    def _parse_ansible_inventory(self, path: Path) -> List[Host]:
        """Parse an Ansible inventory file (INI format)."""
        hosts = []
        try:
            current_group: Optional[str] = "ungrouped"

            with open(path, "r") as f:
                for line in f:
                    line = line.strip()

                    if not line or line.startswith("#") or line.startswith(";"):
                        continue

                    # Group header
                    if line.startswith("[") and line.endswith("]"):
                        group_name = line[1:-1]
                        # Skip special groups
                        if ":vars" in group_name or ":children" in group_name:
                            current_group = None
                        else:
                            current_group = group_name
                        continue

                    if current_group is None:
                        continue

                    # Parse host line
                    # Format: hostname ansible_host=IP other_vars...
                    parts = line.split()
                    if not parts:
                        continue

                    hostname = parts[0]
                    ip_address = None
                    metadata = {}

                    for part in parts[1:]:
                        if "=" in part:
                            key, value = part.split("=", 1)
                            if key == "ansible_host":
                                ip_address = value
                            else:
                                metadata[key] = value

                    # Detect environment from group name
                    env = None
                    group_lower = current_group.lower()
                    if "prod" in group_lower:
                        env = "production"
                    elif "stag" in group_lower:
                        env = "staging"
                    elif "dev" in group_lower:
                        env = "development"

                    hosts.append(Host(
                        hostname=hostname,
                        ip_address=ip_address,
                        source=InventorySource.ANSIBLE_INVENTORY,
                        environment=env,
                        groups=[current_group],
                        metadata=metadata,
                    ))

            logger.debug(f"Loaded {len(hosts)} hosts from Ansible inventory {path}")
            return hosts

        except Exception as e:
            logger.warning(f"Failed to parse Ansible inventory {path}: {e}")
            return []
