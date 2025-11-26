"""
PostgreSQL connector for querying infrastructure inventory.

Auto-detects PostgreSQL databases on localhost and queries them for
infrastructure data.
"""
from typing import Any, Dict, List, Optional

from athena_ai.domains.sources.connectors.base import BaseConnector, ConnectorError, SourceMetadata, SourceType
from athena_ai.utils.logger import logger


class PostgreSQLConnector(BaseConnector):
    """
    PostgreSQL database connector.

    Connects to PostgreSQL databases and executes SQL queries.
    Commonly used for infrastructure inventory, CMDBs, etc.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "postgres",
        username: Optional[str] = None,
        password: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize PostgreSQL connector.

        Args:
            host: PostgreSQL host
            port: PostgreSQL port
            database: Database name
            username: Username (optional, will use credential manager)
            password: Password (optional, will use credential manager)
        """
        super().__init__(host=host, port=port, database=database, **kwargs)
        self.database = database
        self.username = username
        self.password = password

    def test_connection(self) -> bool:
        """
        Test PostgreSQL connection.

        Returns:
            True if connection successful
        """
        try:
            import psycopg2

            # Get credentials if not provided (skip during discovery if not available)
            if not self.username or not self.password:
                from athena_ai.security.credentials import CredentialManager
                cred_mgr = CredentialManager()

                # Check if credentials are available without prompting
                if not cred_mgr.has_db_credentials(self.host, "postgresql"):
                    logger.debug(f"PostgreSQL credentials not available for {self.host}")
                    return False

                self.username, self.password = cred_mgr.get_db_credentials(
                    host=self.host,
                    service="postgresql",
                    username=self.username,
                    password=self.password
                )

            # Test connection
            conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.username,
                password=self.password,
                connect_timeout=5
            )
            conn.close()
            logger.info(f"✓ PostgreSQL connection test successful: {self.host}:{self.port}/{self.database}")
            return True

        except ImportError:
            logger.debug("psycopg2 not installed")
            return False
        except Exception as e:
            logger.debug(f"PostgreSQL connection test failed: {e}")
            return False

    def query(self, query_str: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Execute SQL query against PostgreSQL.

        Args:
            query_str: SQL query string
            params: Optional query parameters

        Returns:
            List of result rows as dicts
        """
        try:
            import psycopg2
            import psycopg2.extras

            # Get credentials if not provided (CAN prompt during actual query execution)
            if not self.username or not self.password:
                from athena_ai.security.credentials import CredentialManager
                cred_mgr = CredentialManager()
                self.username, self.password = cred_mgr.get_db_credentials(
                    host=self.host,
                    service="postgresql",
                    username=self.username,
                    password=self.password
                )

            # Connect
            conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.username,
                password=self.password,
                connect_timeout=10
            )

            try:
                # Execute query with DictCursor to get dict results
                cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

                if params:
                    cursor.execute(query_str, params)
                else:
                    cursor.execute(query_str)

                results = cursor.fetchall()

                # Convert RealDictRow to regular dict
                return [dict(row) for row in results]

            finally:
                conn.close()

        except ImportError as e:
            raise ConnectorError("psycopg2 not installed. Run: pip install psycopg2-binary") from e
        except Exception as e:
            raise ConnectorError(f"PostgreSQL query failed: {e}") from e

    def get_metadata(self) -> SourceMetadata:
        """
        Get metadata about this PostgreSQL source.

        Returns:
            SourceMetadata instance
        """
        return SourceMetadata(
            name=f"postgresql_{self.database}",
            source_type=SourceType.POSTGRESQL,
            host=self.host,
            port=self.port,
            database=self.database,
            description=f"PostgreSQL database: {self.database}",
            capabilities=["inventory", "cmdb", "sql_query"]
        )

    def close(self):
        """Close PostgreSQL connection."""
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None

    @staticmethod
    def detect_on_localhost() -> List[Dict[str, Any]]:
        """
        Detect PostgreSQL instances running on localhost.

        Returns:
            List of detected PostgreSQL instances with connection info
        """
        detected = []

        try:
            import socket

            # Common PostgreSQL ports
            ports = [5432, 5433, 5434]

            for port in ports:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex(('localhost', port))
                sock.close()

                if result == 0:
                    logger.info(f"Detected PostgreSQL on localhost:{port}")
                    detected.append({
                        "host": "localhost",
                        "port": port,
                        "database": "postgres",  # Default database
                        "confidence": 0.8
                    })

        except Exception as e:
            logger.debug(f"PostgreSQL detection failed: {e}")

        return detected

    def discover_inventory_tables(self) -> List[str]:
        """
        Discover tables that might contain infrastructure inventory.

        Returns:
            List of table names
        """
        try:
            # Query for tables with inventory-related names
            query = """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND (
                    table_name ILIKE '%host%'
                    OR table_name ILIKE '%server%'
                    OR table_name ILIKE '%inventory%'
                    OR table_name ILIKE '%asset%'
                    OR table_name ILIKE '%device%'
                    OR table_name ILIKE '%node%'
                )
                ORDER BY table_name
            """

            results = self.query(query)
            return [row['table_name'] for row in results]

        except Exception as e:
            logger.debug(f"Failed to discover inventory tables: {e}")
            return []
