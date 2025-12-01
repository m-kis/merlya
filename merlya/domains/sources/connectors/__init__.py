"""
Data source connectors for intelligent routing.

Provides connectors for:
- PostgreSQL
- MySQL
- MongoDB
- REST APIs (Netbox, Nautobot, etc.)
"""
from merlya.domains.sources.connectors.api import APIConnector
from merlya.domains.sources.connectors.base import BaseConnector, ConnectorError, SourceMetadata, SourceType
from merlya.domains.sources.connectors.mongodb import MongoDBConnector
from merlya.domains.sources.connectors.mysql import MySQLConnector
from merlya.domains.sources.connectors.postgres import PostgreSQLConnector

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
