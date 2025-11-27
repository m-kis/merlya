"""
Source Registry - Stores and manages discovered data sources.

Singleton registry that caches discovered sources to avoid repeated detection.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from athena_ai.domains.sources.connectors import (
    APIConnector,
    BaseConnector,
    MongoDBConnector,
    MySQLConnector,
    PostgreSQLConnector,
    SourceMetadata,
    SourceType,
)
from athena_ai.utils.logger import logger


class SourceRegistry:
    """
    Registry for discovered data sources.

    Features:
    - Singleton pattern (one registry per process)
    - Persistent cache (saved to disk)
    - TTL-based refresh (re-discover after expiry)
    - Get connector instances by source name
    """

    _instance = None

    def __new__(cls, env: str = "dev"):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, env: str = "dev"):
        """
        Initialize source registry.

        Args:
            env: Environment name (for separate cache files)
        """
        if self._initialized:
            return

        self.env = env
        self._sources: Dict[str, SourceMetadata] = {}

        # Cache configuration
        self.cache_dir = Path.home() / ".athena" / env / "sources"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "registry.json"
        self.cache_ttl = timedelta(hours=24)  # Re-discover every 24 hours

        # Load cached sources
        self._load_cache()

        self._initialized = True
        logger.debug(f"SourceRegistry initialized for {env}")

    def register(self, source: SourceMetadata):
        """
        Register a data source.

        Args:
            source: Source metadata to register
        """
        self._sources[source.name] = source
        self._save_cache()
        logger.debug(f"Registered source: {source.name}")

    def get(self, name: str) -> Optional[SourceMetadata]:
        """
        Get source metadata by name.

        Args:
            name: Source name

        Returns:
            SourceMetadata or None
        """
        return self._sources.get(name)

    def list_sources(self) -> List[SourceMetadata]:
        """
        List all registered sources.

        Returns:
            List of source metadata
        """
        return list(self._sources.values())

    def get_sources_by_type(self, source_type: SourceType) -> List[SourceMetadata]:
        """
        Get sources by type.

        Args:
            source_type: Type of source

        Returns:
            List of matching sources
        """
        return [s for s in self._sources.values() if s.source_type == source_type]

    def get_connector(self, name: str) -> Optional[BaseConnector]:
        """
        Get connector instance for a source.

        Args:
            name: Source name

        Returns:
            Connector instance or None
        """
        source = self.get(name)
        if not source:
            return None

        # Create connector based on type
        connector_map = {
            SourceType.POSTGRESQL: PostgreSQLConnector,
            SourceType.MYSQL: MySQLConnector,
            SourceType.MONGODB: MongoDBConnector,
            SourceType.API: APIConnector
        }

        connector_class = connector_map.get(source.source_type)
        if not connector_class:
            logger.warning(f"No connector class for type: {source.source_type}")
            return None

        # Build connector kwargs from metadata
        kwargs = {
            "host": source.host,
            "port": source.port
        }

        if source.database:
            kwargs["database"] = source.database

        return connector_class(**kwargs)

    def is_cache_expired(self) -> bool:
        """
        Check if cache has expired.

        Returns:
            True if cache should be refreshed
        """
        if not self.cache_file.exists():
            return True

        cache_age = datetime.now() - datetime.fromtimestamp(self.cache_file.stat().st_mtime)
        return cache_age > self.cache_ttl

    def clear(self):
        """Clear all registered sources."""
        self._sources.clear()
        if self.cache_file.exists():
            self.cache_file.unlink()
        logger.info("Source registry cleared")

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing)."""
        cls._instance = None

    def _save_cache(self):
        """Save registry to cache file."""
        try:
            cache_data = {
                "timestamp": datetime.now().isoformat(),
                "sources": [
                    {
                        "name": s.name,
                        "source_type": s.source_type.value,
                        "host": s.host,
                        "port": s.port,
                        "database": s.database,
                        "description": s.description,
                        "detected": s.detected,
                        "confidence": s.confidence,
                        "capabilities": s.capabilities
                    }
                    for s in self._sources.values()
                ]
            }

            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)

            logger.debug(f"Saved {len(self._sources)} sources to cache")

        except Exception as e:
            logger.error(f"Failed to save source cache: {e}")

    def _load_cache(self):
        """Load registry from cache file."""
        if not self.cache_file.exists():
            logger.debug("No cached sources found")
            return

        try:
            with open(self.cache_file, 'r') as f:
                cache_data = json.load(f)

            # Check cache age
            cache_time = datetime.fromisoformat(cache_data.get("timestamp", "2000-01-01"))
            cache_age = datetime.now() - cache_time

            if cache_age > self.cache_ttl:
                logger.info(f"Source cache expired ({cache_age.total_seconds() / 3600:.1f}h old)")
                return

            # Load sources
            for source_data in cache_data.get("sources", []):
                source = SourceMetadata(
                    name=source_data["name"],
                    source_type=SourceType(source_data["source_type"]),
                    host=source_data["host"],
                    port=source_data["port"],
                    database=source_data.get("database"),
                    description=source_data.get("description"),
                    detected=source_data.get("detected", False),
                    confidence=source_data.get("confidence", 0.0),
                    capabilities=source_data.get("capabilities", [])
                )
                self._sources[source.name] = source

            logger.info(f"Loaded {len(self._sources)} sources from cache")

        except Exception as e:
            logger.error(f"Failed to load source cache: {e}")
