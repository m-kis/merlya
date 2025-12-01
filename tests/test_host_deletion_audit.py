"""
Tests for host deletion audit functionality.

Tests cover:
- Deletion audit record creation
- Foreign key CASCADE behavior for host_versions
- Audit record persistence after deletion
- Deletion with/without reason
- Multiple deletions tracking
"""

import json
import tempfile
from pathlib import Path

import pytest

from merlya.memory.persistence.inventory_repository import InventoryRepository


@pytest.fixture
def repo():
    """Create a temporary repository for testing.

    Since InventoryRepository is a singleton, we need to reset its state
    between tests to allow different database paths.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        # Reset singleton state to allow new instance
        InventoryRepository._instances.clear()
        InventoryRepository._initialized_classes.clear()

        instance = InventoryRepository(str(db_path))
        yield instance

        # Clean up singleton state after test
        InventoryRepository._instances.clear()
        InventoryRepository._initialized_classes.clear()


class TestHostDeletionAudit:
    """Test host deletion audit functionality."""

    def test_delete_creates_audit_record(self, repo):
        """Test that deleting a host creates an audit record."""
        # Add a host
        host_id = repo.add_host(
            hostname="test-server.example.com",
            ip_address="192.168.1.100",
            environment="production",
            role="webserver",
            groups=["web", "frontend"],
            metadata={"owner": "team-a"},
        )

        # Delete the host with audit info
        deleted = repo.delete_host(
            hostname="test-server.example.com",
            deleted_by="admin",
            reason="Server decommissioned",
        )
        assert deleted is True

        # Verify audit record was created
        with repo._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT host_id, hostname, ip_address, environment, role,
                       groups, metadata, deleted_by, deletion_reason
                FROM host_deletions
                WHERE hostname = ?
            """, ("test-server.example.com",))

            audit_row = cursor.fetchone()
            assert audit_row is not None

            audit_host_id, hostname, ip, env, role, groups_json, metadata_json, deleted_by, reason = audit_row
            assert audit_host_id == host_id
            assert hostname == "test-server.example.com"
            assert ip == "192.168.1.100"
            assert env == "production"
            assert role == "webserver"
            assert json.loads(groups_json) == ["web", "frontend"]
            assert json.loads(metadata_json) == {"owner": "team-a"}
            assert deleted_by == "admin"
            assert reason == "Server decommissioned"

    def test_delete_without_reason(self, repo):
        """Test that deletion works without providing a reason."""
        # Add a host
        repo.add_host(hostname="temp-server.example.com")

        # Delete without reason
        deleted = repo.delete_host(
            hostname="temp-server.example.com",
            deleted_by="script",
        )
        assert deleted is True

        # Verify audit record has NULL reason
        with repo._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT deletion_reason FROM host_deletions
                WHERE hostname = ?
            """, ("temp-server.example.com",))

            reason = cursor.fetchone()[0]
            assert reason is None

    def test_delete_nonexistent_host(self, repo):
        """Test that deleting a non-existent host returns False."""
        deleted = repo.delete_host(
            hostname="nonexistent.example.com",
            deleted_by="admin",
        )
        assert deleted is False

        # Verify no audit record was created
        with repo._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM host_deletions")
            count = cursor.fetchone()[0]
            assert count == 0

    def test_cascade_deletes_host_versions(self, repo):
        """Test that CASCADE deletes host_versions when host is deleted."""
        # Add a host
        host_id = repo.add_host(
            hostname="versioned-server.example.com",
            ip_address="10.0.0.1",
        )

        # Make some updates to create versions
        repo.add_host(
            hostname="versioned-server.example.com",
            ip_address="10.0.0.2",
            changed_by="user1",
        )
        repo.add_host(
            hostname="versioned-server.example.com",
            environment="staging",
            changed_by="user2",
        )

        # Verify versions exist before deletion
        with repo._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM host_versions WHERE host_id = ?",
                (host_id,)
            )
            version_count_before = cursor.fetchone()[0]
            # Should have at least: 1 for creation, and versions for the actual changes
            # The exact count depends on compute_changes logic
            assert version_count_before >= 1

        # Delete the host
        deleted = repo.delete_host(
            hostname="versioned-server.example.com",
            deleted_by="admin",
        )
        assert deleted is True

        # Verify host is gone
        assert repo.get_host_by_id(host_id) is None

        # Verify all versions were CASCADE deleted
        with repo._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM host_versions WHERE host_id = ?",
                (host_id,)
            )
            version_count_after = cursor.fetchone()[0]
            assert version_count_after == 0

        # Verify audit record still exists (not FK-constrained)
        with repo._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM host_deletions
                WHERE hostname = ?
            """, ("versioned-server.example.com",))
            audit_count = cursor.fetchone()[0]
            assert audit_count == 1

    def test_audit_persists_after_deletion(self, repo):
        """Test that audit records persist even after host is deleted."""
        # Add and delete a host
        host_id = repo.add_host(
            hostname="temp.example.com",
            ip_address="192.168.1.50",
            environment="dev",
        )
        repo.delete_host(hostname="temp.example.com", deleted_by="admin")

        # Verify host is gone
        assert repo.get_host_by_id(host_id) is None

        # Verify audit record persists
        with repo._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT hostname, ip_address, environment, deleted_by
                FROM host_deletions
                WHERE host_id = ?
            """, (host_id,))

            audit_row = cursor.fetchone()
            assert audit_row is not None
            hostname, ip, env, deleted_by = audit_row
            assert hostname == "temp.example.com"
            assert ip == "192.168.1.50"
            assert env == "dev"
            assert deleted_by == "admin"

    def test_multiple_deletions_tracked(self, repo):
        """Test that multiple deletions are all tracked in audit table."""
        hosts = [
            ("server1.example.com", "user1", "Reason 1"),
            ("server2.example.com", "user2", "Reason 2"),
            ("server3.example.com", "user3", None),
        ]

        # Add and delete multiple hosts
        for hostname, deleted_by, reason in hosts:
            repo.add_host(hostname=hostname, ip_address=f"10.0.0.{len(hostname)}")
            repo.delete_host(hostname=hostname, deleted_by=deleted_by, reason=reason)

        # Verify all deletions are tracked
        with repo._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT hostname, deleted_by, deletion_reason
                FROM host_deletions
                ORDER BY hostname
            """)

            audit_rows = cursor.fetchall()
            assert len(audit_rows) == 3

            for i, (hostname, deleted_by, reason) in enumerate(audit_rows):
                expected_hostname, expected_deleted_by, expected_reason = hosts[i]
                assert hostname == expected_hostname
                assert deleted_by == expected_deleted_by
                assert reason == expected_reason

    def test_audit_includes_all_host_fields(self, repo):
        """Test that audit record captures all host fields."""
        # Add a host with all fields populated
        repo.add_host(
            hostname="full-server.example.com",
            ip_address="192.168.1.200",
            aliases=["alias1", "alias2"],
            environment="production",
            groups=["web", "api", "backend"],
            role="application-server",
            service="web-api",
            ssh_port=2222,
            metadata={"team": "platform", "cost_center": "123"},
        )

        # Delete the host
        repo.delete_host(
            hostname="full-server.example.com",
            deleted_by="ops-team",
            reason="Migration to cloud",
        )

        # Verify all fields are in audit record
        with repo._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT hostname, ip_address, aliases, environment, groups,
                       role, service, ssh_port, metadata, deleted_by, deletion_reason
                FROM host_deletions
                WHERE hostname = ?
            """, ("full-server.example.com",))

            audit_row = cursor.fetchone()
            assert audit_row is not None

            (hostname, ip, aliases_json, env, groups_json, role, service,
             ssh_port, metadata_json, deleted_by, reason) = audit_row

            assert hostname == "full-server.example.com"
            assert ip == "192.168.1.200"
            assert json.loads(aliases_json) == ["alias1", "alias2"]
            assert env == "production"
            assert json.loads(groups_json) == ["web", "api", "backend"]
            assert role == "application-server"
            assert service == "web-api"
            assert ssh_port == 2222
            assert json.loads(metadata_json) == {"team": "platform", "cost_center": "123"}
            assert deleted_by == "ops-team"
            assert reason == "Migration to cloud"

    def test_deletion_timestamp_recorded(self, repo):
        """Test that deletion timestamp is recorded in audit."""
        from datetime import datetime

        # Add and delete a host
        repo.add_host(hostname="time-test.example.com")
        before_delete = datetime.now().isoformat()

        repo.delete_host(hostname="time-test.example.com", deleted_by="admin")

        after_delete = datetime.now().isoformat()

        # Verify timestamp is within expected range
        with repo._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT deleted_at FROM host_deletions
                WHERE hostname = ?
            """, ("time-test.example.com",))

            deleted_at = cursor.fetchone()[0]
            assert deleted_at is not None
            assert before_delete <= deleted_at <= after_delete

    def test_fk_behavior_documented_in_schema(self, repo):
        """Test that the FK CASCADE behavior is properly set up."""
        # This test verifies the schema setup through behavior
        # Add a host with versions
        host_id = repo.add_host(hostname="fk-test.example.com", ip_address="1.2.3.4")
        repo.add_host(hostname="fk-test.example.com", ip_address="1.2.3.5")

        # Verify FK exists and CASCADE is configured by attempting deletion
        # If CASCADE is not set up, this would fail with FK constraint error
        with repo._connection() as conn:
            cursor = conn.cursor()

            # Check that versions exist
            cursor.execute(
                "SELECT COUNT(*) FROM host_versions WHERE host_id = ?",
                (host_id,)
            )
            assert cursor.fetchone()[0] > 0

            # Delete should succeed with CASCADE
            cursor.execute("DELETE FROM hosts_v2 WHERE id = ?", (host_id,))
            conn.commit()

            # Versions should be gone
            cursor.execute(
                "SELECT COUNT(*) FROM host_versions WHERE host_id = ?",
                (host_id,)
            )
            assert cursor.fetchone()[0] == 0

    def test_default_deleted_by_is_system(self, repo):
        """Test that deleted_by defaults to 'system' when not provided."""
        # Add a host
        repo.add_host(hostname="default-delete.example.com")

        # Delete without specifying deleted_by (should use default)
        repo.delete_host(hostname="default-delete.example.com")

        # Verify default was used
        with repo._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT deleted_by FROM host_deletions
                WHERE hostname = ?
            """, ("default-delete.example.com",))

            deleted_by = cursor.fetchone()[0]
            assert deleted_by == "system"
