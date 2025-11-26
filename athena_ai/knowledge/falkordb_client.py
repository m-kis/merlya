"""
FalkorDB Client for Knowledge Graph.

Provides connection management, Docker auto-setup, and basic CRUD operations.
"""

from typing import Optional

from athena_ai.knowledge.graph.client import FalkorDBClient
from athena_ai.knowledge.graph.config import FalkorDBConfig

# Singleton instance
_default_client: Optional[FalkorDBClient] = None


def get_falkordb_client(config: Optional[FalkorDBConfig] = None) -> FalkorDBClient:
    """Get the default FalkorDB client instance."""
    global _default_client

    if _default_client is None:
        _default_client = FalkorDBClient(config)

    return _default_client
