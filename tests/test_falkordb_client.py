"""
Tests for FalkorDB client functionality.
"""

import unittest
from unittest.mock import MagicMock, patch

from athena_ai.knowledge.falkordb_client import get_falkordb_client
from athena_ai.knowledge.graph.client import FalkorDBClient
from athena_ai.knowledge.graph.config import FalkorDBConfig


class TestFalkorDBConfig(unittest.TestCase):
    """Test cases for FalkorDBConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = FalkorDBConfig()
        self.assertEqual(config.host, "localhost")
        self.assertEqual(config.port, 6379)
        self.assertEqual(config.graph_name, "ops_knowledge")
        self.assertTrue(config.auto_start_docker)
        self.assertEqual(config.connection_timeout, 30)

    def test_custom_config(self):
        """Test custom configuration values."""
        config = FalkorDBConfig(
            host="redis.example.com",
            port=6380,
            graph_name="custom_graph",
            auto_start_docker=False,
        )
        self.assertEqual(config.host, "redis.example.com")
        self.assertEqual(config.port, 6380)
        self.assertEqual(config.graph_name, "custom_graph")
        self.assertFalse(config.auto_start_docker)


class TestFalkorDBClient(unittest.TestCase):
    """Test cases for FalkorDBClient."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = FalkorDBConfig(auto_start_docker=False)
        self.client = FalkorDBClient(self.config)

    def test_init_default_config(self):
        """Test client initializes with default config."""
        client = FalkorDBClient()
        self.assertEqual(client.config.host, "localhost")
        self.assertEqual(client.config.port, 6379)

    def test_init_custom_config(self):
        """Test client initializes with custom config."""
        config = FalkorDBConfig(host="custom", port=9999)
        client = FalkorDBClient(config)
        self.assertEqual(client.config.host, "custom")
        self.assertEqual(client.config.port, 9999)

    def test_is_connected_false_by_default(self):
        """Test is_connected returns False when not connected."""
        self.assertFalse(self.client.is_connected)

    @patch("athena_ai.knowledge.graph.client.FalkorDBClient._is_falkordb_running")
    def test_connect_success(self, mock_is_running):
        """Test successful connection when FalkorDB is available."""
        import athena_ai.knowledge.graph.client as module

        mock_is_running.return_value = True
        mock_db = MagicMock()
        mock_graph = MagicMock()
        mock_db.select_graph.return_value = mock_graph

        # Save original state
        original_has = module.HAS_FALKORDB
        original_class = getattr(module, 'FalkorDB', None)

        # Mock FalkorDB
        module.HAS_FALKORDB = True
        module.FalkorDB = MagicMock(return_value=mock_db)

        try:
            result = self.client.connect()

            self.assertTrue(result)
            self.assertTrue(self.client.is_connected)
        finally:
            # Restore original state
            module.HAS_FALKORDB = original_has
            if original_class is not None:
                module.FalkorDB = original_class
            elif hasattr(module, 'FalkorDB'):
                delattr(module, 'FalkorDB')

    @patch("athena_ai.knowledge.graph.client.FalkorDBClient._is_falkordb_running")
    def test_connect_falkordb_not_running_no_auto_start(self, mock_is_running):
        """Test connection fails when FalkorDB not running and auto-start disabled."""
        mock_is_running.return_value = False

        result = self.client.connect()

        self.assertFalse(result)
        self.assertFalse(self.client.is_connected)

    @patch("athena_ai.knowledge.graph.client.FalkorDBClient._is_falkordb_running")
    def test_connect_failure_exception(self, mock_is_running):
        """Test connection handles exceptions."""
        import athena_ai.knowledge.graph.client as module

        mock_is_running.return_value = True

        # Save original state
        original_has = module.HAS_FALKORDB
        original_class = getattr(module, 'FalkorDB', None)

        # Mock FalkorDB to raise exception
        module.HAS_FALKORDB = True
        module.FalkorDB = MagicMock(side_effect=Exception("Connection refused"))

        try:
            result = self.client.connect()

            self.assertFalse(result)
            self.assertFalse(self.client.is_connected)
        finally:
            # Restore original state
            module.HAS_FALKORDB = original_has
            if original_class is not None:
                module.FalkorDB = original_class
            elif hasattr(module, 'FalkorDB'):
                delattr(module, 'FalkorDB')

    def test_disconnect(self):
        """Test disconnect clears state."""
        self.client._db = MagicMock()
        self.client._graph = MagicMock()
        self.client._connected = True

        self.client.disconnect()

        self.assertIsNone(self.client._db)
        self.assertIsNone(self.client._graph)
        self.assertFalse(self.client.is_connected)

    @patch("socket.socket")
    def test_is_falkordb_running_true(self, mock_socket_class):
        """Test _is_falkordb_running returns True when connection succeeds."""
        mock_socket = MagicMock()
        mock_socket.connect_ex.return_value = 0
        mock_socket_class.return_value = mock_socket

        result = self.client._is_falkordb_running()

        self.assertTrue(result)
        mock_socket.close.assert_called_once()

    @patch("socket.socket")
    def test_is_falkordb_running_false(self, mock_socket_class):
        """Test _is_falkordb_running returns False when connection fails."""
        mock_socket = MagicMock()
        mock_socket.connect_ex.return_value = 111  # Connection refused
        mock_socket_class.return_value = mock_socket

        result = self.client._is_falkordb_running()

        self.assertFalse(result)

    @patch("subprocess.run")
    def test_is_docker_available_true(self, mock_run):
        """Test _is_docker_available returns True when docker is available."""
        mock_run.return_value = MagicMock(returncode=0)

        result = self.client._is_docker_available()

        self.assertTrue(result)

    @patch("subprocess.run")
    def test_is_docker_available_false(self, mock_run):
        """Test _is_docker_available returns False when docker is unavailable."""
        mock_run.return_value = MagicMock(returncode=1)

        result = self.client._is_docker_available()

        self.assertFalse(result)


class TestFalkorDBClientCRUD(unittest.TestCase):
    """Test CRUD operations on FalkorDB client."""

    def setUp(self):
        """Set up mock client."""
        self.config = FalkorDBConfig(auto_start_docker=False)
        self.client = FalkorDBClient(self.config)
        self.client._db = MagicMock()
        self.client._graph = MagicMock()
        self.client._connected = True

    def test_query_not_connected(self):
        """Test query raises error when not connected."""
        self.client._connected = False
        self.client._db = None

        with self.assertRaises(ConnectionError):
            self.client.query("MATCH (n) RETURN n")

    def test_query_success(self):
        """Test successful query execution."""
        mock_result = MagicMock()
        mock_result.result_set = [[{"name": "test"}]]
        mock_result.header = ["n"]
        self.client._graph.query.return_value = mock_result

        self.client.query("MATCH (n) RETURN n")

        self.client._graph.query.assert_called_once()

    def test_create_node(self):
        """Test node creation."""
        mock_result = MagicMock()
        mock_result.result_set = [[MagicMock(properties={"id": "test-123"})]]
        mock_result.header = ["n"]
        self.client._graph.query.return_value = mock_result

        self.client.create_node(
            label="Host",
            properties={"hostname": "server-01", "ip": "192.168.1.1"}
        )

        # Verify query was called
        self.client._graph.query.assert_called_once()
        call_args = self.client._graph.query.call_args
        cypher = call_args[0][0]
        self.assertIn("CREATE", cypher)
        self.assertIn("Host", cypher)

    def test_find_node(self):
        """Test finding a single node."""
        mock_result = MagicMock()
        mock_node = MagicMock()
        mock_node.properties = {"id": "host-1", "hostname": "server-01"}
        mock_result.result_set = [[mock_node]]
        mock_result.header = ["n"]
        self.client._graph.query.return_value = mock_result

        result = self.client.find_node("Host", {"hostname": "server-01"})

        self.assertIsNotNone(result)
        self.assertEqual(result["hostname"], "server-01")

    def test_find_node_not_found(self):
        """Test find_node returns None when not found."""
        mock_result = MagicMock()
        mock_result.result_set = []
        mock_result.header = ["n"]
        self.client._graph.query.return_value = mock_result

        result = self.client.find_node("Host", {"hostname": "nonexistent"})

        self.assertIsNone(result)

    def test_find_nodes(self):
        """Test finding multiple nodes."""
        mock_result = MagicMock()
        mock_node1 = MagicMock()
        mock_node1.properties = {"id": "1", "hostname": "server-01"}
        mock_node2 = MagicMock()
        mock_node2.properties = {"id": "2", "hostname": "server-02"}
        mock_result.result_set = [[mock_node1], [mock_node2]]
        mock_result.header = ["n"]
        self.client._graph.query.return_value = mock_result

        result = self.client.find_nodes("Host", limit=10)

        self.assertEqual(len(result), 2)

    def test_update_node(self):
        """Test node update."""
        mock_result = MagicMock()
        mock_result.result_set = [[1]]
        mock_result.header = ["updated"]
        self.client._graph.query.return_value = mock_result

        result = self.client.update_node(
            label="Host",
            match_properties={"id": "host-1"},
            set_properties={"status": "active"}
        )

        self.assertTrue(result)

    def test_delete_node(self):
        """Test node deletion."""
        mock_result = MagicMock()
        mock_result.result_set = [[1]]
        mock_result.header = ["deleted"]
        self.client._graph.query.return_value = mock_result

        result = self.client.delete_node(
            label="Host",
            match_properties={"id": "host-1"}
        )

        self.assertEqual(result, 1)

    def test_create_relationship(self):
        """Test relationship creation."""
        mock_result = MagicMock()
        mock_result.result_set = [[1]]
        mock_result.header = ["created"]
        self.client._graph.query.return_value = mock_result

        result = self.client.create_relationship(
            from_label="Service",
            from_match={"name": "nginx"},
            rel_type="RUNS_ON",
            to_label="Host",
            to_match={"hostname": "server-01"}
        )

        self.assertTrue(result)

    def test_find_related(self):
        """Test finding related nodes."""
        mock_result = MagicMock()
        mock_node = MagicMock()
        mock_node.properties = {"hostname": "server-01"}
        mock_result.result_set = [[mock_node]]
        mock_result.header = ["b"]
        self.client._graph.query.return_value = mock_result

        result = self.client.find_related(
            from_label="Service",
            from_match={"name": "nginx"},
            rel_type="RUNS_ON",
            to_label="Host"
        )

        self.assertEqual(len(result), 1)


class TestFalkorDBClientUtility(unittest.TestCase):
    """Test utility methods."""

    def setUp(self):
        """Set up mock client."""
        self.config = FalkorDBConfig()
        self.client = FalkorDBClient(self.config)
        self.client._db = MagicMock()
        self.client._graph = MagicMock()
        self.client._connected = True

    def test_get_stats_not_connected(self):
        """Test get_stats when not connected."""
        self.client._connected = False

        stats = self.client.get_stats()

        self.assertFalse(stats["connected"])

    def test_get_stats_connected(self):
        """Test get_stats when connected."""
        # Mock labels query
        labels_result = MagicMock()
        labels_result.result_set = [["Host"], ["Service"]]
        labels_result.header = ["label"]

        # Mock count queries
        count_result = MagicMock()
        count_result.result_set = [[5]]
        count_result.header = ["count"]

        rel_count_result = MagicMock()
        rel_count_result.result_set = [[10]]
        rel_count_result.header = ["count"]

        self.client._graph.query.side_effect = [
            labels_result,
            count_result,
            count_result,
            rel_count_result,
        ]

        stats = self.client.get_stats()

        self.assertTrue(stats["connected"])
        self.assertEqual(stats["graph_name"], "ops_knowledge")

    def test_clear_graph_not_connected(self):
        """Test clear_graph when not connected."""
        self.client._connected = False

        result = self.client.clear_graph()

        self.assertFalse(result)

    def test_clear_graph_success(self):
        """Test successful graph clearing."""
        mock_result = MagicMock()
        mock_result.result_set = []
        self.client._graph.query.return_value = mock_result

        result = self.client.clear_graph()

        self.assertTrue(result)


class TestGetFalkorDBClient(unittest.TestCase):
    """Test get_falkordb_client factory."""

    def test_singleton_instance(self):
        """Test factory returns singleton."""
        import athena_ai.knowledge.falkordb_client as module
        module._default_client = None

        client1 = get_falkordb_client()
        client2 = get_falkordb_client()

        self.assertIs(client1, client2)

    def test_custom_config(self):
        """Test factory accepts custom config."""
        import athena_ai.knowledge.falkordb_client as module
        module._default_client = None

        config = FalkorDBConfig(host="custom-host", port=9999)
        client = get_falkordb_client(config)

        self.assertEqual(client.config.host, "custom-host")
        self.assertEqual(client.config.port, 9999)

        # Reset singleton
        module._default_client = None


if __name__ == "__main__":
    unittest.main()
