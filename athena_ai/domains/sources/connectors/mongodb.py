"""
MongoDB connector for querying infrastructure inventory.
"""
from typing import Any, Dict, List, Optional

from athena_ai.domains.sources.connectors.base import BaseConnector, ConnectorError, SourceMetadata, SourceType
from athena_ai.utils.logger import logger


class MongoDBConnector(BaseConnector):
    """MongoDB database connector."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 27017,
        database: str = "admin",
        username: Optional[str] = None,
        password: Optional[str] = None,
        **kwargs
    ):
        super().__init__(host=host, port=port, database=database, **kwargs)
        self.database = database
        self.username = username
        self.password = password

    def test_connection(self) -> bool:
        """Test MongoDB connection."""
        try:
            from pymongo import MongoClient
            from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

            if not self.username or not self.password:
                from athena_ai.security.credentials import CredentialManager
                cred_mgr = CredentialManager()
                self.username, self.password = cred_mgr.get_db_credentials(
                    host=self.host,
                    service="mongodb",
                    username=self.username,
                    password=self.password
                )

            # Build connection URI
            uri = f"mongodb://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"

            client = MongoClient(
                uri,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000
            )

            # Test connection
            client.admin.command('ping')
            client.close()

            logger.info(f"✓ MongoDB connection test successful: {self.host}:{self.port}/{self.database}")
            return True

        except ImportError:
            logger.warning("pymongo not installed. Run: pip install pymongo")
            return False
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.debug(f"MongoDB connection test failed: {e}")
            return False
        except Exception as e:
            logger.debug(f"MongoDB connection test failed: {e}")
            return False

    def query(self, query_str: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Execute query against MongoDB.

        Note: query_str should be in format "collection_name.find" or "collection_name.aggregate"
        params should contain the actual query document.

        Args:
            query_str: Collection and operation (e.g., "hosts.find")
            params: Query document/pipeline

        Returns:
            List of documents
        """
        try:
            from pymongo import MongoClient

            if not self.username or not self.password:
                from athena_ai.security.credentials import CredentialManager
                cred_mgr = CredentialManager()
                self.username, self.password = cred_mgr.get_db_credentials(
                    host=self.host,
                    service="mongodb",
                    username=self.username,
                    password=self.password
                )

            # Build connection URI
            uri = f"mongodb://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"

            client = MongoClient(
                uri,
                serverSelectionTimeoutMS=10000,
                connectTimeoutMS=10000
            )

            try:
                db = client[self.database]

                # Parse query_str to get collection and operation
                parts = query_str.split('.')
                collection_name = parts[0]
                operation = parts[1] if len(parts) > 1 else 'find'

                collection = db[collection_name]

                # Execute query
                if operation == 'find':
                    query_doc = params or {}
                    cursor = collection.find(query_doc)
                    results = list(cursor)
                elif operation == 'aggregate':
                    pipeline = params or []
                    cursor = collection.aggregate(pipeline)
                    results = list(cursor)
                else:
                    raise ConnectorError(f"Unsupported operation: {operation}")

                # Convert ObjectId to string
                for doc in results:
                    if '_id' in doc:
                        doc['_id'] = str(doc['_id'])

                return results

            finally:
                client.close()

        except ImportError as e:
            raise ConnectorError("pymongo not installed. Run: pip install pymongo") from e
        except Exception as e:
            raise ConnectorError(f"MongoDB query failed: {e}") from e

    def get_metadata(self) -> SourceMetadata:
        """Get metadata about this MongoDB source."""
        return SourceMetadata(
            name=f"mongodb_{self.database}",
            source_type=SourceType.MONGODB,
            host=self.host,
            port=self.port,
            database=self.database,
            description=f"MongoDB database: {self.database}",
            capabilities=["inventory", "cmdb", "nosql_query"]
        )

    def close(self):
        """Close MongoDB connection."""
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None

    @staticmethod
    def detect_on_localhost() -> List[Dict[str, Any]]:
        """Detect MongoDB instances on localhost."""
        detected = []
        try:
            import socket
            ports = [27017, 27018, 27019]
            for port in ports:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex(('localhost', port))
                sock.close()
                if result == 0:
                    logger.info(f"Detected MongoDB on localhost:{port}")
                    detected.append({
                        "host": "localhost",
                        "port": port,
                        "database": "admin",
                        "confidence": 0.8
                    })
        except Exception as e:
            logger.debug(f"MongoDB detection failed: {e}")
        return detected

    def discover_inventory_collections(self) -> List[str]:
        """Discover collections with infrastructure inventory."""
        try:
            from pymongo import MongoClient

            if not self.username or not self.password:
                from athena_ai.security.credentials import CredentialManager
                cred_mgr = CredentialManager()
                self.username, self.password = cred_mgr.get_db_credentials(
                    host=self.host,
                    service="mongodb",
                    username=self.username,
                    password=self.password
                )

            uri = f"mongodb://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"
            client = MongoClient(uri, serverSelectionTimeoutMS=5000)

            try:
                db = client[self.database]
                all_collections = db.list_collection_names()

                # Filter for inventory-related collections
                inventory_keywords = ['host', 'server', 'inventory', 'asset', 'device', 'node']
                inventory_collections = [
                    coll for coll in all_collections
                    if any(kw in coll.lower() for kw in inventory_keywords)
                ]

                return inventory_collections

            finally:
                client.close()

        except Exception as e:
            logger.debug(f"Failed to discover inventory collections: {e}")
            return []
