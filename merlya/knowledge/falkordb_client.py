"""
FalkorDB Client for Knowledge Graph.

Provides connection management, Docker auto-setup, and basic CRUD operations.
"""

from typing import Optional

from merlya.knowledge.graph.client import FalkorDBClient
from merlya.knowledge.graph.config import FalkorDBConfig

# Singleton instance
_default_client: Optional[FalkorDBClient] = None


def get_falkordb_client(
    config: Optional[FalkorDBConfig] = None,
    auto_connect: bool = False,
) -> FalkorDBClient:
    """
    Get the default FalkorDB client instance.

    Args:
        config: Optional configuration for the client.
        auto_connect: If True, attempt to connect immediately.

    Returns:
        FalkorDBClient instance (singleton).
    """
    global _default_client

    if _default_client is None:
        _default_client = FalkorDBClient(config)

    if auto_connect and not _default_client.is_connected:
        _default_client.connect()

    return _default_client


def reset_falkordb_client() -> None:
    """Reset the singleton instance (for testing)."""
    global _default_client
    if _default_client is not None:
        _default_client.disconnect()
    _default_client = None
