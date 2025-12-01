"""
Tests for Storage Manager (Hybrid SQLite + FalkorDB).
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock

from merlya.knowledge.storage.models import AuditEntry, SessionRecord
from merlya.knowledge.storage_manager import StorageManager


class TestAuditEntry(unittest.TestCase):
    """Test AuditEntry dataclass."""

    def test_default_values(self):
        """Test default values for AuditEntry."""
        entry = AuditEntry()
        self.assertIsNone(entry.id)
        self.assertEqual(entry.timestamp, "")
        self.assertEqual(entry.action, "")
        self.assertEqual(entry.result, "")

    def test_custom_values(self):
        """Test custom values for AuditEntry."""
        entry = AuditEntry(
            action="execute_command",
            target="server-01",
            command="systemctl status nginx",
            result="success",
        )
        self.assertEqual(entry.action, "execute_command")
        self.assertEqual(entry.target, "server-01")
        self.assertEqual(entry.result, "success")


class TestSessionRecord(unittest.TestCase):
    """Test SessionRecord dataclass."""

    def test_default_values(self):
        """Test default values for SessionRecord."""
        record = SessionRecord()
        self.assertEqual(record.id, "")
        self.assertEqual(record.queries, 0)
        self.assertEqual(record.commands, 0)

    def test_custom_values(self):
        """Test custom values for SessionRecord."""
        record = SessionRecord(
            id="session-123",
            env="prod",
            queries=5,
            commands=3,
        )
        self.assertEqual(record.id, "session-123")
        self.assertEqual(record.env, "prod")
        self.assertEqual(record.queries, 5)


class TestStorageManager(unittest.TestCase):
    """Test StorageManager class."""

    def setUp(self):
        """Set up test fixtures with temp database."""
        self.temp_db = tempfile.mktemp(suffix='.db')
        self.manager = StorageManager(
            sqlite_path=self.temp_db,
            enable_falkordb=False,
        )

    def tearDown(self):
        """Clean up temp database."""
        if os.path.exists(self.temp_db):
            os.unlink(self.temp_db)

    def test_init_creates_database(self):
        """Test initialization creates database file."""
        self.assertTrue(os.path.exists(self.temp_db))

    def test_falkordb_disabled(self):
        """Test FalkorDB is disabled when configured."""
        self.assertFalse(self.manager.falkordb_available)

    # =========================================================================
    # Session Tests
    # =========================================================================

    def test_create_session(self):
        """Test creating a session."""
        result = self.manager.create_session("test-session-1", env="dev")
        self.assertTrue(result)

    def test_get_session(self):
        """Test retrieving a session."""
        self.manager.create_session("test-session-2", env="staging")

        session = self.manager.get_session("test-session-2")

        self.assertIsNotNone(session)
        self.assertEqual(session.id, "test-session-2")
        self.assertEqual(session.env, "staging")

    def test_get_session_not_found(self):
        """Test get_session returns None for nonexistent session."""
        session = self.manager.get_session("nonexistent")
        self.assertIsNone(session)

    def test_end_session(self):
        """Test ending a session."""
        self.manager.create_session("test-session-3", env="dev")

        result = self.manager.end_session("test-session-3")

        self.assertTrue(result)
        session = self.manager.get_session("test-session-3")
        self.assertIsNotNone(session.ended_at)

    def test_update_session_stats(self):
        """Test updating session statistics."""
        self.manager.create_session("test-session-4", env="dev")

        self.manager.update_session_stats(
            "test-session-4",
            queries=5,
            commands=3,
            incidents=1,
        )

        session = self.manager.get_session("test-session-4")
        self.assertEqual(session.queries, 5)
        self.assertEqual(session.commands, 3)
        self.assertEqual(session.incidents, 1)

    def test_list_sessions(self):
        """Test listing sessions."""
        self.manager.create_session("session-a", env="dev")
        self.manager.create_session("session-b", env="prod")

        sessions = self.manager.list_sessions(limit=10)

        self.assertEqual(len(sessions), 2)

    # =========================================================================
    # Audit Log Tests
    # =========================================================================

    def test_log_audit(self):
        """Test logging an audit entry."""
        entry = AuditEntry(
            action="execute_command",
            target="server-01",
            command="systemctl status nginx",
            result="success",
        )

        log_id = self.manager.log_audit(entry)

        self.assertIsNotNone(log_id)
        self.assertGreater(log_id, 0)

    def test_log_audit_auto_timestamp(self):
        """Test audit log auto-sets timestamp."""
        entry = AuditEntry(action="test_action")

        self.manager.log_audit(entry)

        logs = self.manager.get_audit_log(limit=1)
        self.assertEqual(len(logs), 1)
        self.assertNotEqual(logs[0].timestamp, "")

    def test_get_audit_log(self):
        """Test retrieving audit logs."""
        self.manager.create_session("audit-session", env="dev")

        entry1 = AuditEntry(action="action1", session_id="audit-session")
        entry2 = AuditEntry(action="action2", session_id="audit-session")
        self.manager.log_audit(entry1)
        self.manager.log_audit(entry2)

        logs = self.manager.get_audit_log(session_id="audit-session")

        self.assertEqual(len(logs), 2)

    def test_get_audit_log_filter_action(self):
        """Test filtering audit logs by action."""
        entry1 = AuditEntry(action="execute_command")
        entry2 = AuditEntry(action="scan_host")
        self.manager.log_audit(entry1)
        self.manager.log_audit(entry2)

        logs = self.manager.get_audit_log(action="execute_command")

        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].action, "execute_command")

    # =========================================================================
    # Incident Storage Tests
    # =========================================================================

    def test_store_incident(self):
        """Test storing an incident."""
        incident = {
            "title": "Test incident",
            "priority": "P1",
            "service": "nginx",
            "symptoms": ["high latency", "errors"],
        }

        incident_id = self.manager.store_incident(incident)

        self.assertIsNotNone(incident_id)
        self.assertTrue(incident_id.startswith("INC-"))

    def test_store_incident_custom_id(self):
        """Test storing an incident with custom ID."""
        incident = {
            "id": "CUSTOM-123",
            "title": "Custom ID incident",
            "priority": "P2",
        }

        incident_id = self.manager.store_incident(incident)

        self.assertEqual(incident_id, "CUSTOM-123")

    def test_get_incident(self):
        """Test retrieving an incident."""
        incident = {
            "title": "Get test incident",
            "priority": "P0",
            "service": "mongodb",
            "symptoms": ["connection refused"],
        }
        incident_id = self.manager.store_incident(incident)

        retrieved = self.manager.get_incident(incident_id)

        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["title"], "Get test incident")
        self.assertEqual(retrieved["priority"], "P0")

    def test_get_incident_not_found(self):
        """Test get_incident returns None for nonexistent incident."""
        retrieved = self.manager.get_incident("NONEXISTENT-123")
        self.assertIsNone(retrieved)

    def test_find_similar_incidents(self):
        """Test finding similar incidents."""
        # Store some incidents with status='resolved'
        incident1 = {
            "id": "INC-TEST-001",
            "title": "Nginx error",
            "priority": "P1",
            "service": "nginx",
            "status": "resolved",
        }
        incident2 = {
            "id": "INC-TEST-002",
            "title": "MongoDB timeout",
            "priority": "P2",
            "service": "mongodb",
            "status": "resolved",
        }
        self.manager.store_incident(incident1)
        self.manager.store_incident(incident2)

        # Find similar incidents by service (default looks for resolved incidents)
        similar = self.manager.find_similar_incidents(service="nginx", limit=5)

        self.assertEqual(len(similar), 1)
        self.assertEqual(similar[0]["service"], "nginx")

    # =========================================================================
    # Configuration Tests
    # =========================================================================

    def test_set_config(self):
        """Test setting a configuration value."""
        result = self.manager.set_config("test_key", {"value": 42})
        self.assertTrue(result)

    def test_get_config(self):
        """Test getting a configuration value."""
        self.manager.set_config("my_setting", "test_value")

        value = self.manager.get_config("my_setting")

        self.assertEqual(value, "test_value")

    def test_get_config_default(self):
        """Test get_config returns default for nonexistent key."""
        value = self.manager.get_config("nonexistent_key", default="default_value")
        self.assertEqual(value, "default_value")

    def test_get_config_complex_value(self):
        """Test storing and retrieving complex values."""
        complex_value = {
            "hosts": ["server-01", "server-02"],
            "settings": {"timeout": 30, "retries": 3},
        }
        self.manager.set_config("complex", complex_value)

        retrieved = self.manager.get_config("complex")

        self.assertEqual(retrieved, complex_value)

    # =========================================================================
    # Statistics Tests
    # =========================================================================

    def test_get_stats(self):
        """Test getting storage statistics."""
        self.manager.create_session("stats-session", env="dev")
        self.manager.log_audit(AuditEntry(action="test"))
        self.manager.store_incident({"title": "Test", "priority": "P3"})

        stats = self.manager.get_stats()

        self.assertIn("sqlite", stats)
        self.assertIn("falkordb", stats)


class TestStorageManagerWithFalkorDB(unittest.TestCase):
    """Test StorageManager with mocked FalkorDB."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_db = tempfile.mktemp(suffix='.db')
        self.manager = StorageManager(
            sqlite_path=self.temp_db,
            enable_falkordb=True,
        )
        # Mock the FalkorDB store
        self.manager.falkordb = MagicMock()
        self.manager.falkordb.available = True
        self.manager.falkordb.store_incident.return_value = True

    def tearDown(self):
        """Clean up."""
        if os.path.exists(self.temp_db):
            os.unlink(self.temp_db)

    def test_falkordb_available(self):
        """Test FalkorDB availability check."""
        self.assertTrue(self.manager.falkordb_available)

    def test_store_incident_syncs_to_falkordb(self):
        """Test incident storage syncs to FalkorDB."""
        incident = {
            "title": "Sync test",
            "priority": "P1",
        }

        self.manager.store_incident(incident)

        self.manager.falkordb.store_incident.assert_called_once()

    def test_sync_to_falkordb(self):
        """Test syncing unsynced data to FalkorDB."""
        # Store incident
        self.manager.falkordb.available = False
        self.manager.falkordb.store_incident.return_value = False
        incident = {"title": "Unsync test", "priority": "P2"}
        self.manager.store_incident(incident)

        # Re-enable FalkorDB
        self.manager.falkordb.available = True
        self.manager.falkordb.connect.return_value = True
        self.manager.falkordb.store_incident.return_value = True

        # Mock the sqlite method to return unsynced incidents
        self.manager.sqlite.get_unsynced_incidents = MagicMock(return_value=[incident])
        self.manager.sqlite.mark_incident_synced = MagicMock()

        result = self.manager.sync_to_falkordb()

        self.assertIn("incidents", result)


if __name__ == "__main__":
    unittest.main()
