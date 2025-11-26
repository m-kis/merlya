"""
Base connector for data sources.

Provides abstract interface for connecting to and querying various data sources
(databases, APIs, CMDBs, etc.).
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from enum import Enum


class SourceType(Enum):
    """Types of data sources."""
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    MONGODB = "mongodb"
    API = "api"
    CMDB = "cmdb"
    FILE = "file"
    UNKNOWN = "unknown"


@dataclass
class SourceMetadata:
    """Metadata about a data source."""
    name: str
    source_type: SourceType
    host: str
    port: int
    database: Optional[str] = None
    description: Optional[str] = None
    detected: bool = False  # Was this source auto-detected?
    confidence: float = 0.0  # Confidence score for detection (0-1)
    capabilities: List[str] = None  # What can this source do? ["inventory", "monitoring", etc.]

    def __post_init__(self):
        if self.capabilities is None:
            self.capabilities = []


class BaseConnector(ABC):
    """
    Abstract base class for data source connectors.

    All connectors must implement:
    - test_connection(): Verify connectivity
    - query(): Execute queries
    - get_metadata(): Return source metadata
    - close(): Clean up connection
    """

    def __init__(self, host: str, port: int, **kwargs):
        """
        Initialize connector.

        Args:
            host: Host address
            port: Port number
            **kwargs: Additional connection parameters (database, username, etc.)
        """
        self.host = host
        self.port = port
        self.connection_params = kwargs
        self._connection = None

    @abstractmethod
    def test_connection(self) -> bool:
        """
        Test connection to data source.

        Returns:
            True if connection successful
        """
        pass

    @abstractmethod
    def query(self, query_str: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Execute query against data source.

        Args:
            query_str: Query string (SQL, MongoDB query, API endpoint, etc.)
            params: Optional query parameters

        Returns:
            List of result rows/documents as dicts
        """
        pass

    @abstractmethod
    def get_metadata(self) -> SourceMetadata:
        """
        Get metadata about this data source.

        Returns:
            SourceMetadata instance
        """
        pass

    @abstractmethod
    def close(self):
        """Close connection and clean up resources."""
        pass

    def __enter__(self):
        """Context manager support."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager cleanup."""
        self.close()


class ConnectorError(Exception):
    """Exception raised by connectors."""
    pass
