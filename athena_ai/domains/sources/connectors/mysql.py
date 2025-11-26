"""
MySQL connector for querying infrastructure inventory.
"""
from typing import Any, Dict, List, Optional
from athena_ai.domains.sources.connectors.base import BaseConnector, SourceMetadata, SourceType, ConnectorError
from athena_ai.utils.logger import logger


class MySQLConnector(BaseConnector):
    """MySQL database connector."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 3306,
        database: str = "mysql",
        username: Optional[str] = None,
        password: Optional[str] = None,
        **kwargs
    ):
        super().__init__(host=host, port=port, database=database, **kwargs)
        self.database = database
        self.username = username
        self.password = password

    def test_connection(self) -> bool:
        """Test MySQL connection."""
        try:
            import pymysql

            if not self.username or not self.password:
                from athena_ai.security.credentials import CredentialManager
                cred_mgr = CredentialManager()
                self.username, self.password = cred_mgr.get_db_credentials(
                    host=self.host,
                    service="mysql",
                    username=self.username,
                    password=self.password
                )

            conn = pymysql.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.username,
                password=self.password,
                connect_timeout=5
            )
            conn.close()
            logger.info(f"✓ MySQL connection test successful: {self.host}:{self.port}/{self.database}")
            return True

        except ImportError:
            logger.warning("pymysql not installed. Run: pip install pymysql")
            return False
        except Exception as e:
            logger.debug(f"MySQL connection test failed: {e}")
            return False

    def query(self, query_str: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Execute SQL query against MySQL."""
        try:
            import pymysql

            if not self.username or not self.password:
                from athena_ai.security.credentials import CredentialManager
                cred_mgr = CredentialManager()
                self.username, self.password = cred_mgr.get_db_credentials(
                    host=self.host,
                    service="mysql",
                    username=self.username,
                    password=self.password
                )

            conn = pymysql.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.username,
                password=self.password,
                connect_timeout=10,
                cursorclass=pymysql.cursors.DictCursor
            )

            try:
                with conn.cursor() as cursor:
                    if params:
                        cursor.execute(query_str, params)
                    else:
                        cursor.execute(query_str)
                    return cursor.fetchall()
            finally:
                conn.close()

        except ImportError:
            raise ConnectorError("pymysql not installed. Run: pip install pymysql")
        except Exception as e:
            raise ConnectorError(f"MySQL query failed: {e}")

    def get_metadata(self) -> SourceMetadata:
        """Get metadata about this MySQL source."""
        return SourceMetadata(
            name=f"mysql_{self.database}",
            source_type=SourceType.MYSQL,
            host=self.host,
            port=self.port,
            database=self.database,
            description=f"MySQL database: {self.database}",
            capabilities=["inventory", "cmdb", "sql_query"]
        )

    def close(self):
        """Close MySQL connection."""
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None

    @staticmethod
    def detect_on_localhost() -> List[Dict[str, Any]]:
        """Detect MySQL instances on localhost."""
        detected = []
        try:
            import socket
            ports = [3306, 3307, 3308]
            for port in ports:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex(('localhost', port))
                sock.close()
                if result == 0:
                    logger.info(f"Detected MySQL on localhost:{port}")
                    detected.append({
                        "host": "localhost",
                        "port": port,
                        "database": "mysql",
                        "confidence": 0.8
                    })
        except Exception as e:
            logger.debug(f"MySQL detection failed: {e}")
        return detected

    def discover_inventory_tables(self) -> List[str]:
        """Discover tables with infrastructure inventory."""
        try:
            query = """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                AND (
                    table_name LIKE '%host%'
                    OR table_name LIKE '%server%'
                    OR table_name LIKE '%inventory%'
                    OR table_name LIKE '%asset%'
                    OR table_name LIKE '%device%'
                )
                ORDER BY table_name
            """
            results = self.query(query)
            return [row['table_name'] for row in results]
        except Exception as e:
            logger.debug(f"Failed to discover inventory tables: {e}")
            return []
