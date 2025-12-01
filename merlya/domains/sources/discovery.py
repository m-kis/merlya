"""
Source Discovery - Auto-detect data sources on localhost.

Discovers:
- PostgreSQL databases
- MySQL databases
- MongoDB databases
- REST APIs (Netbox, Nautobot, etc.)

This provides the "intelligence" to understand the environment and route
queries to appropriate sources instead of manual filtering or SSH scanning.
"""
from typing import Any, Dict, List, Optional

from merlya.domains.sources.connectors import (
    APIConnector,
    MongoDBConnector,
    MySQLConnector,
    PostgreSQLConnector,
    SourceMetadata,
    SourceType,
)
from merlya.utils.logger import logger


class SourceDiscovery:
    """
    Auto-discover data sources on localhost.

    Detects databases, APIs, and other infrastructure data sources
    that can be queried for inventory and configuration data.
    """

    def __init__(self):
        """Initialize source discovery."""
        self.discovered_sources: List[SourceMetadata] = []

    def discover_all(self) -> List[SourceMetadata]:
        """
        Discover all available data sources on localhost.

        Returns:
            List of discovered source metadata
        """
        logger.info("🔍 Starting data source discovery on localhost...")

        self.discovered_sources = []

        # Discover PostgreSQL
        postgres_instances = PostgreSQLConnector.detect_on_localhost()
        for instance in postgres_instances:
            pg_connector = PostgreSQLConnector(**instance)
            if pg_connector.test_connection():
                metadata = pg_connector.get_metadata()
                metadata.detected = True
                metadata.confidence = instance.get('confidence', 0.8)

                # Try to discover inventory tables
                try:
                    tables = pg_connector.discover_inventory_tables()
                    if tables and metadata.capabilities is not None:
                        logger.info(f"  Found {len(tables)} inventory tables in PostgreSQL")
                        metadata.capabilities.append("has_inventory_tables")
                        metadata.confidence = min(metadata.confidence + 0.1, 1.0)
                except Exception as e:
                    logger.debug(f"Failed to discover PostgreSQL tables: {e}")

                self.discovered_sources.append(metadata)
                pg_connector.close()

        # Discover MySQL
        mysql_instances = MySQLConnector.detect_on_localhost()
        for instance in mysql_instances:
            mysql_connector = MySQLConnector(**instance)
            if mysql_connector.test_connection():
                metadata = mysql_connector.get_metadata()
                metadata.detected = True
                metadata.confidence = instance.get('confidence', 0.8)

                # Try to discover inventory tables
                try:
                    tables = mysql_connector.discover_inventory_tables()
                    if tables and metadata.capabilities is not None:
                        logger.info(f"  Found {len(tables)} inventory tables in MySQL")
                        metadata.capabilities.append("has_inventory_tables")
                        metadata.confidence = min(metadata.confidence + 0.1, 1.0)
                except Exception as e:
                    logger.debug(f"Failed to discover MySQL tables: {e}")

                self.discovered_sources.append(metadata)
                mysql_connector.close()

        # Discover MongoDB
        mongodb_instances = MongoDBConnector.detect_on_localhost()
        for instance in mongodb_instances:
            mongo_connector = MongoDBConnector(**instance)
            if mongo_connector.test_connection():
                metadata = mongo_connector.get_metadata()
                metadata.detected = True
                metadata.confidence = instance.get('confidence', 0.8)

                # Try to discover inventory collections
                try:
                    collections = mongo_connector.discover_inventory_collections()
                    if collections and metadata.capabilities is not None:
                        logger.info(f"  Found {len(collections)} inventory collections in MongoDB")
                        metadata.capabilities.append("has_inventory_collections")
                        metadata.confidence = min(metadata.confidence + 0.1, 1.0)
                except Exception as e:
                    logger.debug(f"Failed to discover MongoDB collections: {e}")

                self.discovered_sources.append(metadata)
                mongo_connector.close()

        # Discover REST APIs
        api_instances = APIConnector.detect_on_localhost()
        for instance in api_instances:
            api_connector = APIConnector(**instance)
            if api_connector.test_connection():
                metadata = api_connector.get_metadata()
                metadata.detected = True
                metadata.confidence = instance.get('confidence', 0.6)

                # Try to discover endpoints
                try:
                    endpoints = api_connector.discover_endpoints()
                    if endpoints and metadata.capabilities is not None:
                        logger.info(f"  Found {len(endpoints)} API endpoints")
                        metadata.capabilities.append("has_endpoints")
                        metadata.confidence = min(metadata.confidence + 0.2, 1.0)
                except Exception as e:
                    logger.debug(f"Failed to discover API endpoints: {e}")

                self.discovered_sources.append(metadata)
                api_connector.close()

        logger.info(f"✅ Discovery complete: Found {len(self.discovered_sources)} data sources")

        return self.discovered_sources

    def get_sources_by_type(self, source_type: SourceType) -> List[SourceMetadata]:
        """
        Get discovered sources by type.

        Args:
            source_type: Type of source to filter

        Returns:
            List of sources matching type
        """
        return [s for s in self.discovered_sources if s.source_type == source_type]

    def get_sources_by_capability(self, capability: str) -> List[SourceMetadata]:
        """
        Get discovered sources by capability.

        Args:
            capability: Capability to filter (e.g., "inventory", "cmdb")

        Returns:
            List of sources with capability
        """
        return [s for s in self.discovered_sources if s.capabilities and capability in s.capabilities]

    def get_best_source_for_inventory(self) -> Optional[SourceMetadata]:
        """
        Get the best source for inventory queries.

        Prioritizes sources with:
        1. Has inventory tables/collections
        2. Highest confidence score
        3. Database over API (faster, more reliable)

        Returns:
            Best source metadata or None
        """
        inventory_sources = self.get_sources_by_capability("inventory")

        if not inventory_sources:
            return None

        # Sort by:
        # 1. Has inventory tables/collections (higher priority)
        # 2. Confidence score (higher is better)
        # 3. Source type (database > API)
        def score_source(source: SourceMetadata) -> tuple[int, float, int]:
            has_inventory = 1 if source.capabilities and any(cap in source.capabilities for cap in ["has_inventory_tables", "has_inventory_collections"]) else 0
            is_database = 1 if source.source_type in [SourceType.POSTGRESQL, SourceType.MYSQL, SourceType.MONGODB] else 0
            return (has_inventory, source.confidence, is_database)

        sorted_sources = sorted(inventory_sources, key=score_source, reverse=True)
        return sorted_sources[0] if sorted_sources else None

    def to_dict(self) -> Dict[str, Any]:
        """
        Export discovered sources as dict.

        Returns:
            Dict representation
        """
        return {
            "total_sources": len(self.discovered_sources),
            "sources": [
                {
                    "name": s.name,
                    "type": s.source_type.value,
                    "host": s.host,
                    "port": s.port,
                    "database": s.database,
                    "confidence": s.confidence,
                    "capabilities": s.capabilities
                }
                for s in self.discovered_sources
            ]
        }
