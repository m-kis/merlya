"""
SQLite-based inventory source.

Loads hosts from the InventoryRepository SQLite database,
allowing hosts added via `/inventory add` to be used
in the HostRegistry for validation and resolution.
"""
from datetime import datetime
from typing import Any, Dict, List

from merlya.context.sources.base import BaseSource, Host, InventorySource
from merlya.utils.logger import logger


class SQLiteSource(BaseSource):
    """
    Inventory source that loads hosts from SQLite database.

    This bridges the InventoryRepository (SQLite) with the HostRegistry,
    ensuring that manually added hosts are available for validation.
    """

    def load(self) -> List[Host]:
        """Load hosts from SQLite InventoryRepository."""
        hosts: List[Host] = []

        try:
            from merlya.memory.persistence.inventory_repository import (
                get_inventory_repository,
            )

            repo = get_inventory_repository()
            all_hosts = repo.get_all_hosts()

            for host_data in all_hosts:
                host = self._convert_to_host(host_data)
                if host:
                    hosts.append(host)

            if hosts:
                logger.debug(f"🗄️ SQLite source loaded: {len(hosts)} hosts")

        except ImportError:
            logger.debug("SQLite inventory repository not available")
        except Exception as e:
            logger.warning(f"⚠️ Failed to load SQLite inventory: {type(e).__name__}: {e}")

        return hosts

    def _convert_to_host(self, host_data: Dict[str, Any]) -> Host | None:
        """
        Convert a host dict from SQLite to a Host object.

        Args:
            host_data: Dict from InventoryRepository.get_all_hosts()

        Returns:
            Host object or None if conversion fails
        """
        try:
            hostname = host_data.get("hostname")
            if not hostname:
                return None

            # Extract aliases
            aliases = host_data.get("aliases") or []
            if isinstance(aliases, str):
                # Handle JSON string
                import json
                try:
                    aliases = json.loads(aliases)
                except json.JSONDecodeError:
                    aliases = []

            # Extract groups
            groups = host_data.get("groups") or []
            if isinstance(groups, str):
                import json
                try:
                    groups = json.loads(groups)
                except json.JSONDecodeError:
                    groups = []

            # Extract metadata
            metadata = host_data.get("metadata") or {}
            if isinstance(metadata, str):
                import json
                try:
                    metadata = json.loads(metadata)
                except json.JSONDecodeError:
                    metadata = {}

            # Parse last_seen timestamp
            last_seen = None
            last_seen_str = host_data.get("last_seen") or host_data.get("updated_at")
            if last_seen_str:
                try:
                    last_seen = datetime.fromisoformat(last_seen_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pass

            return Host(
                hostname=hostname,
                ip_address=host_data.get("ip") or host_data.get("ip_address"),
                aliases=aliases,
                source=InventorySource.MANUAL,  # SQLite hosts are manual
                environment=host_data.get("environment"),
                groups=groups,
                metadata=metadata,
                last_seen=last_seen,
                accessible=host_data.get("accessible"),
            )

        except Exception as e:
            logger.debug(f"Failed to convert host: {e}")
            return None
