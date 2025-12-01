from typing import Any, Dict, List, Optional

from athena_ai.knowledge.falkordb_client import FalkorDBClient, FalkorDBConfig
from athena_ai.utils.logger import logger


class FalkorDBStore:
    """Handles FalkorDB storage operations."""

    def __init__(self, config: Optional[FalkorDBConfig] = None, enabled: bool = True):
        self.enabled = enabled
        self.client: Optional[FalkorDBClient] = None
        if enabled:
            self.client = FalkorDBClient(config)

    def connect(self) -> bool:
        """Connect to FalkorDB."""
        if not self.enabled or self.client is None:
            return False
        return self.client.connect()

    @property
    def available(self) -> bool:
        """Check if FalkorDB is connected and available."""
        return (
            self.client is not None and
            self.client.is_connected
        )

    def store_incident(self, incident: Dict[str, Any]) -> bool:
        """Store incident in graph."""
        if not self.available or self.client is None:
            return False

        try:
            self.client.create_node("Incident", {
                "id": incident["id"],
                "title": incident.get("title", ""),
                "description": incident.get("description", ""),
                "priority": incident.get("priority", "P3"),
                "status": incident.get("status", "open"),
                "environment": incident.get("environment", ""),
                "tags": incident.get("tags", []),
            })
            return True
        except Exception as e:
            logger.warning(f"Failed to sync incident to FalkorDB: {e}")
            return False

    def find_similar_incidents(self, limit: int = 5) -> List[Dict[Any, Any]]:
        """Find similar incidents in graph."""
        if not self.available or self.client is None:
            return []

        try:
            # Find incidents with similar symptoms
            # This is a simplified query - real implementation would use
            # embedding similarity or more sophisticated matching
            results = self.client.query("""
                MATCH (i:Incident)
                WHERE i.status = 'resolved'
                RETURN i
                ORDER BY i.created_at DESC
                LIMIT $limit
            """, {"limit": limit})

            return [r["i"] for r in results if r and r.get("i") is not None]

        except Exception as e:
            logger.debug(f"FalkorDB query failed: {e}")
            return []

    def get_node(self, label: str, properties: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get a node by properties."""
        if not self.available or self.client is None:
            return None
        try:
            return self.client.find_node(label, properties)
        except Exception:
            return None

    def get_stats(self) -> Dict[str, Any]:
        """Get FalkorDB stats."""
        stats = {
            "enabled": self.enabled,
            "available": self.available,
        }
        if self.available and self.client is not None:
            stats.update(self.client.get_stats())
        return stats
