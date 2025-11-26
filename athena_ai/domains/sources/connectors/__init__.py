"""
Data source connectors for intelligent routing.

Provides connectors for:
- PostgreSQL
- MySQL
- MongoDB
- REST APIs (Netbox, Nautobot, etc.)
"""
from athena_ai.domains.sources.connectors.base import (
    BaseConnector,
    SourceMetadata,
    SourceType,
    ConnectorError
)
from athena_ai.domains.sources.connectors.postgres import PostgreSQLConnector
from athena_ai.domains.sources.connectors.mysql import MySQLConnector
from athena_ai.domains.sources.connectors.mongodb import MongoDBConnector
from athena_ai.domains.sources.connectors.api import APIConnector

__all__ = [
    "BaseConnector",
    "SourceMetadata",
    "SourceType",
    "ConnectorError",
    "PostgreSQLConnector",
    "MySQLConnector",
    "MongoDBConnector",
    "APIConnector",
]
