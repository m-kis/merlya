"""
Persistent knowledge store for Merlya.
Saves infrastructure facts to a local JSON file to accumulate knowledge over time.
"""
import ipaddress
import json
import os
from typing import Any, Dict, List, Optional

from merlya.utils.logger import logger


class KnowledgeStore:
    """
    Persistent storage for infrastructure knowledge.

    Structure:
    {
        "hosts": {
            "hostname": {
                "ip": "...",
                "os": "...",
                "services": [...],
                "last_seen": "timestamp",
                "facts": {
                    "key": "value"
                }
            }
        },
        "topology": {
            "routes": [
                {"network": "10.0.0.0/8", "gateway": "bastion-prod"}
            ]
        }
    }
    """

    def __init__(self, storage_path: str = "~/.merlya/knowledge.json"):
        self.storage_path = os.path.expanduser(storage_path)
        self.data = self._load_data()

        # Lazy load knowledge manager to avoid circular imports
        self._knowledge_manager = None

    @property
    def knowledge_manager(self):
        if not self._knowledge_manager:
            from merlya.knowledge.ops_knowledge_manager import get_knowledge_manager
            self._knowledge_manager = get_knowledge_manager()
        return self._knowledge_manager

    def _load_data(self) -> Dict[str, Any]:
        """Load knowledge from disk."""
        if not os.path.exists(self.storage_path):
            return {"hosts": {}, "topology": {}}

        try:
            with open(self.storage_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load knowledge store: {e}")
            return {"hosts": {}, "topology": {}}

    def _save_data(self):
        """Save knowledge to disk."""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)

            with open(self.storage_path, 'w') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save knowledge store: {e}")

    def update_host_fact(self, hostname: str, category: str, data: Any):
        """
        Update a specific fact about a host.

        Args:
            hostname: The host identifier
            category: Fact category (e.g., 'os', 'services', 'ip')
            data: The data to store
        """
        if "hosts" not in self.data:
            self.data["hosts"] = {}

        if hostname not in self.data["hosts"]:
            self.data["hosts"][hostname] = {}

        self.data["hosts"][hostname][category] = data
        self._save_data()
        logger.debug(f"Updated knowledge for {hostname}: {category}")

    def add_route(self, network_cidr: str, gateway_host: str):
        """
        Add a routing rule.

        Args:
            network_cidr: Network in CIDR format (e.g. '10.0.0.0/8')
            gateway_host: Hostname of the jump host/bastion
        """
        if "topology" not in self.data:
            self.data["topology"] = {}

        if "routes" not in self.data["topology"]:
            self.data["topology"]["routes"] = []

        # Check if exists
        routes = self.data["topology"]["routes"]
        for route in routes:
            if route["network"] == network_cidr:
                route["gateway"] = gateway_host
                self._save_data()
                logger.info(f"Updated route: {network_cidr} via {gateway_host}")
                return

        # Add new
        # Add new
        routes.append({"network": network_cidr, "gateway": gateway_host})
        self._save_data()
        logger.info(f"Added route: {network_cidr} via {gateway_host}")

        # Sync to FalkorDB for visualization
        try:
            # We use the storage manager directly to add nodes/rels if possible,
            # or we can rely on a sync method.
            # Since OpsKnowledgeManager doesn't expose a direct "add_route" for graph yet,
            # we'll use the storage manager's falkordb client if available.
            km = self.knowledge_manager
            if km.storage.falkordb_available:
                # Create Network node
                km.storage._falkordb.query(
                    "MERGE (n:Network {cidr: $cidr})",
                    {"cidr": network_cidr}
                )
                # Create Gateway node (Host)
                km.storage._falkordb.query(
                    "MERGE (h:Host {hostname: $host})",
                    {"host": gateway_host}
                )
                # Create Relationship
                km.storage._falkordb.query(
                    """
                    MATCH (n:Network {cidr: $cidr}), (h:Host {hostname: $host})
                    MERGE (h)-[:ROUTES_TO]->(n)
                    """,
                    {"cidr": network_cidr, "host": gateway_host}
                )
                logger.debug(f"Synced route {network_cidr} -> {gateway_host} to FalkorDB")
        except Exception as e:
            logger.warning(f"Failed to sync route to FalkorDB: {e}")

    def get_route_for_host(self, host_ip: str) -> Optional[str]:
        """
        Find a gateway for a given host IP.
        Returns the hostname of the gateway/bastion, or None if direct.
        """
        if not host_ip or host_ip == "unknown":
            return None

        routes = self.data.get("topology", {}).get("routes", [])

        try:
            ip = ipaddress.ip_address(host_ip)

            # Find most specific match (longest prefix)
            best_gateway = None
            best_prefix_len = -1

            for route in routes:
                try:
                    network = ipaddress.ip_network(route["network"])
                    if ip in network:
                        if network.prefixlen > best_prefix_len:
                            best_prefix_len = network.prefixlen
                            best_gateway = route["gateway"]
                except ValueError:
                    continue

            return best_gateway

        except ValueError:
            return None


    def get_host_info(self, hostname: str) -> Optional[Dict[str, Any]]:
        """Get all known info about a host."""
        return self.data.get("hosts", {}).get(hostname)

    def search_hosts(self, query: str) -> List[str]:
        """Find hosts matching a query string (simple substring match)."""
        query = query.lower()
        matches = []

        for hostname, info in self.data.get("hosts", {}).items():
            if query in hostname.lower():
                matches.append(hostname)
                continue

            # Search in facts
            str_info = str(info).lower()
            if query in str_info:
                matches.append(hostname)

        return matches
