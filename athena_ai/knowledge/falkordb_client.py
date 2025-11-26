"""
FalkorDB Client for Knowledge Graph.

Provides connection management, Docker auto-setup, and basic CRUD operations.
"""

import os
import time
import subprocess
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass
from datetime import datetime

from athena_ai.utils.logger import logger

try:
    from falkordb import FalkorDB
    HAS_FALKORDB = True
except ImportError:
    HAS_FALKORDB = False
    logger.warning("falkordb package not installed. Run: pip install falkordb")


DOCKER_IMAGE = "falkordb/falkordb:latest"
CONTAINER_NAME = "athena-falkordb"
DEFAULT_PORT = 6379
DEFAULT_GRAPH = "ops_knowledge"


@dataclass
class FalkorDBConfig:
    """Configuration for FalkorDB connection."""
    host: str = "localhost"
    port: int = DEFAULT_PORT
    graph_name: str = DEFAULT_GRAPH
    auto_start_docker: bool = True
    connection_timeout: int = 30


class FalkorDBClient:
    """
    Client for FalkorDB graph database.

    Features:
    - Auto-starts Docker container if not running
    - Connection pooling and retry logic
    - Convenient CRUD methods for knowledge graph
    """

    def __init__(self, config: Optional[FalkorDBConfig] = None):
        self.config = config or FalkorDBConfig()
        self._db: Optional["FalkorDB"] = None
        self._graph = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if connected to FalkorDB."""
        return self._connected and self._db is not None

    def connect(self) -> bool:
        """
        Connect to FalkorDB.

        If Docker auto-start is enabled and FalkorDB is not running,
        will attempt to start the Docker container.

        Returns:
            True if connected successfully
        """
        if not HAS_FALKORDB:
            logger.error("falkordb package not installed")
            return False

        # Check if FalkorDB is running
        if not self._is_falkordb_running():
            if self.config.auto_start_docker:
                logger.info("FalkorDB not running, starting Docker container...")
                if not self._start_docker_container():
                    logger.error("Failed to start FalkorDB Docker container")
                    return False
            else:
                logger.error("FalkorDB not running and auto_start_docker is disabled")
                return False

        # Connect to FalkorDB
        try:
            self._db = FalkorDB(
                host=self.config.host,
                port=self.config.port,
            )
            self._graph = self._db.select_graph(self.config.graph_name)
            self._connected = True
            logger.info(f"Connected to FalkorDB at {self.config.host}:{self.config.port}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to FalkorDB: {e}")
            return False

    def disconnect(self):
        """Disconnect from FalkorDB."""
        self._db = None
        self._graph = None
        self._connected = False
        logger.info("Disconnected from FalkorDB")

    def _is_falkordb_running(self) -> bool:
        """Check if FalkorDB is accepting connections."""
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((self.config.host, self.config.port))
            sock.close()
            return result == 0
        except Exception:
            return False

    def _is_docker_available(self) -> bool:
        """Check if Docker is available."""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _start_docker_container(self) -> bool:
        """Start FalkorDB Docker container."""
        if not self._is_docker_available():
            logger.error("Docker is not available. Please install Docker or start FalkorDB manually.")
            return False

        # Check if container exists but is stopped
        try:
            result = subprocess.run(
                ["docker", "ps", "-a", "--filter", f"name={CONTAINER_NAME}", "--format", "{{.Status}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.stdout.strip():
                # Container exists
                if "Exited" in result.stdout or "Created" in result.stdout:
                    logger.info(f"Starting existing container {CONTAINER_NAME}...")
                    subprocess.run(
                        ["docker", "start", CONTAINER_NAME],
                        capture_output=True,
                        timeout=30,
                    )
                # else container is already running
            else:
                # Create new container
                logger.info(f"Creating new FalkorDB container {CONTAINER_NAME}...")
                subprocess.run(
                    [
                        "docker", "run", "-d",
                        "--name", CONTAINER_NAME,
                        "-p", f"{self.config.port}:6379",
                        "--restart", "unless-stopped",
                        DOCKER_IMAGE,
                    ],
                    capture_output=True,
                    timeout=60,
                )

            # Wait for FalkorDB to be ready
            return self._wait_for_ready()

        except subprocess.TimeoutExpired:
            logger.error("Docker command timed out")
            return False
        except Exception as e:
            logger.error(f"Failed to start Docker container: {e}")
            return False

    def _wait_for_ready(self, max_wait: int = 30) -> bool:
        """Wait for FalkorDB to be ready to accept connections."""
        start = time.time()
        while time.time() - start < max_wait:
            if self._is_falkordb_running():
                logger.info("FalkorDB is ready")
                return True
            time.sleep(1)

        logger.error(f"FalkorDB not ready after {max_wait} seconds")
        return False

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    def query(self, cypher: str, params: Optional[Dict] = None) -> List[Dict]:
        """
        Execute a Cypher query and return results.

        Args:
            cypher: Cypher query string
            params: Optional parameters for the query

        Returns:
            List of result dictionaries
        """
        if not self.is_connected:
            if not self.connect():
                raise ConnectionError("Not connected to FalkorDB")

        try:
            result = self._graph.query(cypher, params or {})
            return self._parse_result(result)
        except Exception as e:
            logger.error(f"Query failed: {e}\nQuery: {cypher}")
            raise

    def _parse_result(self, result) -> List[Dict]:
        """Parse FalkorDB result into list of dictionaries."""
        if not result.result_set:
            return []

        parsed = []
        for row in result.result_set:
            row_dict = {}
            for i, col in enumerate(result.header):
                value = row[i]
                # Handle Node objects
                if hasattr(value, 'properties'):
                    row_dict[col] = dict(value.properties)
                else:
                    row_dict[col] = value
            parsed.append(row_dict)

        return parsed

    def create_node(
        self,
        label: str,
        properties: Dict[str, Any],
        return_node: bool = True
    ) -> Optional[Dict]:
        """
        Create a node in the graph.

        Args:
            label: Node label (e.g., "Host", "Incident")
            properties: Node properties
            return_node: Whether to return the created node

        Returns:
            Created node properties if return_node is True
        """
        # Add timestamp if not present
        if "created_at" not in properties:
            properties["created_at"] = datetime.now().isoformat()

        # Build property string
        props_str = ", ".join(
            f"{k}: ${k}" for k in properties.keys()
        )

        cypher = f"CREATE (n:{label} {{{props_str}}})"
        if return_node:
            cypher += " RETURN n"

        result = self.query(cypher, properties)

        if return_node and result:
            return result[0].get("n")
        return None

    def find_node(
        self,
        label: str,
        match_properties: Dict[str, Any]
    ) -> Optional[Dict]:
        """
        Find a single node by label and properties.

        Args:
            label: Node label
            match_properties: Properties to match

        Returns:
            Node properties or None if not found
        """
        where_clauses = [f"n.{k} = ${k}" for k in match_properties.keys()]
        where_str = " AND ".join(where_clauses)

        cypher = f"MATCH (n:{label}) WHERE {where_str} RETURN n LIMIT 1"
        result = self.query(cypher, match_properties)

        if result:
            return result[0].get("n")
        return None

    def find_nodes(
        self,
        label: str,
        match_properties: Optional[Dict[str, Any]] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Find multiple nodes by label and optional properties.

        Args:
            label: Node label
            match_properties: Optional properties to match
            limit: Maximum number of results

        Returns:
            List of node properties
        """
        if match_properties:
            where_clauses = [f"n.{k} = ${k}" for k in match_properties.keys()]
            where_str = " WHERE " + " AND ".join(where_clauses)
        else:
            where_str = ""
            match_properties = {}

        cypher = f"MATCH (n:{label}){where_str} RETURN n LIMIT {limit}"
        result = self.query(cypher, match_properties)

        return [r.get("n") for r in result if r.get("n")]

    def update_node(
        self,
        label: str,
        match_properties: Dict[str, Any],
        set_properties: Dict[str, Any]
    ) -> bool:
        """
        Update a node's properties.

        Args:
            label: Node label
            match_properties: Properties to match the node
            set_properties: Properties to set/update

        Returns:
            True if node was updated
        """
        # Add updated_at timestamp
        set_properties["updated_at"] = datetime.now().isoformat()

        where_clauses = [f"n.{k} = $match_{k}" for k in match_properties.keys()]
        where_str = " AND ".join(where_clauses)

        set_clauses = [f"n.{k} = $set_{k}" for k in set_properties.keys()]
        set_str = ", ".join(set_clauses)

        # Prefix params to avoid collisions
        params = {f"match_{k}": v for k, v in match_properties.items()}
        params.update({f"set_{k}": v for k, v in set_properties.items()})

        cypher = f"MATCH (n:{label}) WHERE {where_str} SET {set_str} RETURN count(n) as updated"
        result = self.query(cypher, params)

        return result[0].get("updated", 0) > 0 if result else False

    def delete_node(
        self,
        label: str,
        match_properties: Dict[str, Any],
        detach: bool = True
    ) -> int:
        """
        Delete nodes matching the criteria.

        Args:
            label: Node label
            match_properties: Properties to match
            detach: Whether to delete relationships too

        Returns:
            Number of deleted nodes
        """
        where_clauses = [f"n.{k} = ${k}" for k in match_properties.keys()]
        where_str = " AND ".join(where_clauses)

        delete_keyword = "DETACH DELETE" if detach else "DELETE"

        cypher = f"MATCH (n:{label}) WHERE {where_str} {delete_keyword} n RETURN count(n) as deleted"
        result = self.query(cypher, match_properties)

        return result[0].get("deleted", 0) if result else 0

    def create_relationship(
        self,
        from_label: str,
        from_match: Dict[str, Any],
        rel_type: str,
        to_label: str,
        to_match: Dict[str, Any],
        properties: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Create a relationship between two nodes.

        Args:
            from_label: Label of the source node
            from_match: Properties to match source node
            rel_type: Relationship type
            to_label: Label of the target node
            to_match: Properties to match target node
            properties: Optional relationship properties

        Returns:
            True if relationship was created
        """
        # Build match conditions
        from_where = [f"a.{k} = $from_{k}" for k in from_match.keys()]
        to_where = [f"b.{k} = $to_{k}" for k in to_match.keys()]

        # Combine params
        params = {f"from_{k}": v for k, v in from_match.items()}
        params.update({f"to_{k}": v for k, v in to_match.items()})

        # Build relationship properties
        if properties:
            params.update({f"rel_{k}": v for k, v in properties.items()})
            rel_props = " {" + ", ".join(f"{k}: $rel_{k}" for k in properties.keys()) + "}"
        else:
            rel_props = ""

        cypher = f"""
        MATCH (a:{from_label}), (b:{to_label})
        WHERE {' AND '.join(from_where)} AND {' AND '.join(to_where)}
        CREATE (a)-[r:{rel_type}{rel_props}]->(b)
        RETURN count(r) as created
        """

        result = self.query(cypher, params)
        return result[0].get("created", 0) > 0 if result else False

    def find_related(
        self,
        from_label: str,
        from_match: Dict[str, Any],
        rel_type: str,
        to_label: str,
        direction: str = "outgoing"  # "outgoing", "incoming", "both"
    ) -> List[Dict]:
        """
        Find nodes related to a given node.

        Args:
            from_label: Label of the source node
            from_match: Properties to match source node
            rel_type: Relationship type
            to_label: Label of related nodes
            direction: Relationship direction

        Returns:
            List of related node properties
        """
        from_where = [f"a.{k} = ${k}" for k in from_match.keys()]

        if direction == "outgoing":
            rel_pattern = f"-[:{rel_type}]->"
        elif direction == "incoming":
            rel_pattern = f"<-[:{rel_type}]-"
        else:
            rel_pattern = f"-[:{rel_type}]-"

        cypher = f"""
        MATCH (a:{from_label}){rel_pattern}(b:{to_label})
        WHERE {' AND '.join(from_where)}
        RETURN b
        """

        result = self.query(cypher, from_match)
        return [r.get("b") for r in result if r.get("b")]

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """Get graph statistics."""
        if not self.is_connected:
            return {"connected": False}

        try:
            # Count nodes by label
            node_counts = {}
            labels_result = self.query("CALL db.labels()")
            for row in labels_result:
                label = list(row.values())[0] if row else None
                if label:
                    count_result = self.query(f"MATCH (n:{label}) RETURN count(n) as count")
                    node_counts[label] = count_result[0].get("count", 0) if count_result else 0

            # Count relationships
            rel_result = self.query("MATCH ()-[r]->() RETURN count(r) as count")
            rel_count = rel_result[0].get("count", 0) if rel_result else 0

            return {
                "connected": True,
                "graph_name": self.config.graph_name,
                "node_counts": node_counts,
                "total_nodes": sum(node_counts.values()),
                "total_relationships": rel_count,
            }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {"connected": True, "error": str(e)}

    def clear_graph(self) -> bool:
        """Clear all nodes and relationships from the graph. Use with caution!"""
        if not self.is_connected:
            return False

        try:
            self.query("MATCH (n) DETACH DELETE n")
            logger.warning(f"Cleared all data from graph {self.config.graph_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to clear graph: {e}")
            return False

    def create_indexes(self) -> int:
        """Create indexes defined in the schema."""
        from .schema import get_create_index_queries

        if not self.is_connected:
            if not self.connect():
                return 0

        created = 0
        for query in get_create_index_queries(self.config.graph_name):
            try:
                self.query(query)
                created += 1
            except Exception as e:
                # Index might already exist
                logger.debug(f"Index creation skipped: {e}")

        logger.info(f"Created {created} indexes")
        return created


# Singleton instance
_default_client: Optional[FalkorDBClient] = None


def get_falkordb_client(config: Optional[FalkorDBConfig] = None) -> FalkorDBClient:
    """Get the default FalkorDB client instance."""
    global _default_client

    if _default_client is None:
        _default_client = FalkorDBClient(config)

    return _default_client
