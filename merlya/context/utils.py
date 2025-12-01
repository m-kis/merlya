"""
Utility functions for the context module.
"""
import logging
from typing import Dict

logger = logging.getLogger(__name__)


def parse_inventory(inventory_path: str = "/etc/hosts") -> Dict[str, str]:
    """
    Parse /etc/hosts or similar file to build simple inventory.

    Args:
        inventory_path: Path to the hosts file

    Returns:
        Dictionary mapping hostname -> IP

    Raises:
        FileNotFoundError: If the inventory file does not exist
        PermissionError: If the file cannot be read due to permissions
    """
    hosts: Dict[str, str] = {}
    try:
        with open(inventory_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split()
                    if len(parts) >= 2:
                        ip = parts[0]
                        for hostname in parts[1:]:
                            hosts[hostname] = ip
    except FileNotFoundError:
        logger.warning("Inventory file not found: %s", inventory_path)
        raise
    except PermissionError:
        logger.warning("Permission denied reading: %s", inventory_path)
        raise
    except UnicodeDecodeError as e:
        logger.error("Encoding error reading %s: %s", inventory_path, e)
        raise
    return hosts
