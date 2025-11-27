"""
Verification script for inventory repository refactoring.
Tests the mixin-based architecture and new features.
"""
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from athena_ai.memory.persistence.inventory_repository import InventoryRepository

def verify_inventory_repository():
    print("🧪 Verifying InventoryRepository...")

    # Use a cross-platform temporary DB with guaranteed cleanup
    tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tmp_file.name
    tmp_file.close()

    try:
        # Reset singleton to allow fresh initialization with test db_path
        InventoryRepository.reset_instance()
        repo = InventoryRepository(db_path=db_path)

        # 1. Test Sources
        print("1. Testing Sources...")
        source_id = repo.add_source("test_source", "manual", metadata={"foo": "bar"})
        assert source_id is not None
        source = repo.get_source("test_source")
        assert source["name"] == "test_source"
        assert source["source_type"] == "manual"

        # 2. Test Hosts
        print("2. Testing Hosts...")
        host_id = repo.add_host(
            hostname="test-host",
            ip_address="192.168.1.1",
            environment="prod",
            role="web",
            source_id=source_id,
            metadata={"os": "linux"}
        )
        assert host_id is not None

        host = repo.get_host_by_name("test-host")
        assert host["hostname"] == "test-host"
        assert host["ip_address"] == "192.168.1.1"

        # Test Search
        results = repo.search_hosts(pattern="test", environment="prod")
        assert len(results) == 1
        assert results[0]["hostname"] == "test-host"

        # 3. Test Relations
        print("3. Testing Relations...")
        host2_id = repo.add_host("db-host", "192.168.1.2", role="db")
        rel_id = repo.add_relation("test-host", "db-host", "connects_to")
        assert rel_id is not None

        rels = repo.get_relations(hostname="test-host")
        assert len(rels) == 1
        assert rels[0]["relation_type"] == "connects_to"

        # 4. Test Scan Cache
        print("4. Testing Scan Cache...")
        repo.save_scan_cache(host_id, "nmap", {"ports": [80, 443]}, 3600)
        cache = repo.get_scan_cache(host_id, "nmap")
        assert cache is not None
        assert cache["data"]["ports"] == [80, 443]

        # 5. Test Local Context
        print("5. Testing Local Context...")
        repo.save_local_context({"user": {"name": "cedric"}})
        ctx = repo.get_local_context()
        assert ctx["user"]["name"] == "cedric"

        # 6. Test Snapshots
        print("6. Testing Snapshots...")
        snap_id = repo.create_snapshot("snap1", "initial state")
        snap = repo.get_snapshot(snap_id)
        assert snap["name"] == "snap1"
        assert snap["host_count"] == 2

        print("✅ All verification steps passed!")
    finally:
        # Cleanup: reset singleton and remove temp DB
        InventoryRepository.reset_instance()
        if os.path.exists(db_path):
            os.remove(db_path)


def verify_bulk_add_hosts():
    """Test bulk host import with successful import."""
    print("\n🧪 Verifying bulk_add_hosts...")

    from athena_ai.memory.persistence.repositories import HostData

    # Use a cross-platform temporary DB with guaranteed cleanup
    tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tmp_file.name
    tmp_file.close()

    try:
        InventoryRepository.reset_instance()
        repo = InventoryRepository(db_path=db_path)

        # Create a source
        source_id = repo.add_source("bulk_source", "file")

        # Test successful bulk import
        print("1. Testing successful bulk import...")
        hosts = [
            HostData(hostname="host1", ip_address="10.0.0.1", environment="prod"),
            HostData(hostname="host2", ip_address="10.0.0.2", environment="prod"),
            HostData(hostname="host3", ip_address="10.0.0.3", environment="staging"),
        ]

        added = repo.bulk_add_hosts(hosts, source_id=source_id, changed_by="test")
        assert added == 3, f"Expected 3 hosts added, got {added}"

        # Verify all hosts exist
        all_hosts = repo.search_hosts()
        assert len(all_hosts) == 3, f"Expected 3 hosts in DB, got {len(all_hosts)}"

        print("✅ Bulk import verification passed!")
    finally:
        # Cleanup: reset singleton and remove temp DB
        InventoryRepository.reset_instance()
        if os.path.exists(db_path):
            os.remove(db_path)


def verify_bulk_add_hosts_rollback():
    """Test bulk host import transaction rollback on failure.

    Verifies that when bulk_add_hosts fails partway through, no partial
    inserts remain in the database (atomic transaction semantics).
    """
    print("\n🧪 Verifying bulk_add_hosts rollback...")

    from unittest.mock import patch
    import sqlite3
    from athena_ai.memory.persistence.repositories import HostData
    from athena_ai.core.exceptions import PersistenceError

    # Use a cross-platform temporary DB with guaranteed cleanup
    tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tmp_file.name
    tmp_file.close()

    try:
        InventoryRepository.reset_instance()
        repo = InventoryRepository(db_path=db_path)

        # Create a source
        source_id = repo.add_source("bulk_source", "file")

        # Verify DB is empty before test
        initial_hosts = repo.search_hosts()
        assert len(initial_hosts) == 0, "DB should be empty before rollback test"

        # Test rollback on failure by patching _add_host_internal to fail after 2 hosts
        print("1. Testing transaction rollback on failure...")
        hosts = [
            HostData(hostname="host1", ip_address="10.0.0.1", environment="prod"),
            HostData(hostname="host2", ip_address="10.0.0.2", environment="prod"),
            HostData(hostname="host3", ip_address="10.0.0.3", environment="staging"),
        ]

        call_count = 0
        original_add_host_internal = repo._add_host_internal

        def failing_add_host_internal(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                # Simulate a database error on the 3rd host
                raise sqlite3.IntegrityError("Simulated failure on third host")
            return original_add_host_internal(*args, **kwargs)

        # Patch the method and verify rollback behavior
        with patch.object(repo, '_add_host_internal', side_effect=failing_add_host_internal):
            exception_raised = False
            try:
                repo.bulk_add_hosts(hosts, source_id=source_id, changed_by="test")
            except PersistenceError as e:
                exception_raised = True
                assert "hosts_before_failure" in e.details
                assert e.details["hosts_before_failure"] == 2
                print(f"   ✅ PersistenceError raised as expected: {e.reason}")

            assert exception_raised, "Expected PersistenceError to be raised"

        # Verify no partial inserts - DB should still be empty
        print("2. Verifying no partial inserts remain...")
        hosts_after_failure = repo.search_hosts()
        assert len(hosts_after_failure) == 0, (
            f"Expected 0 hosts after rollback, found {len(hosts_after_failure)}. "
            "Transaction rollback failed - partial inserts remain!"
        )
        print("   ✅ No partial inserts - rollback successful")

        print("✅ Bulk import rollback verification passed!")
    finally:
        # Cleanup: reset singleton and remove temp DB
        InventoryRepository.reset_instance()
        if os.path.exists(db_path):
            os.remove(db_path)


def verify_local_context():
    """Test LocalContext.from_dict edge cases."""
    print("\n🧪 Verifying LocalContext.from_dict...")

    from athena_ai.context.local_scanner import LocalContext
    from athena_ai.context.local_scanner.models import UNKNOWN_SCAN_TIME

    # Test with valid ISO timestamp
    print("1. Testing valid timestamp...")
    data = {"scanned_at": "2024-01-15T10:30:00", "os_info": {"system": "Linux"}}
    ctx = LocalContext.from_dict(data)
    assert ctx.scanned_at.year == 2024
    assert ctx.os_info["system"] == "Linux"
    print("   ✅ Valid timestamp handled")

    # Test with None timestamp (should use UNKNOWN_SCAN_TIME sentinel)
    print("2. Testing None timestamp...")
    data = {"scanned_at": None, "os_info": {}}
    ctx = LocalContext.from_dict(data)
    assert ctx.scanned_at == UNKNOWN_SCAN_TIME
    print("   ✅ None timestamp handled")

    # Test with invalid timestamp string (should use UNKNOWN_SCAN_TIME)
    print("3. Testing invalid timestamp...")
    data = {"scanned_at": "not-a-date", "os_info": {}}
    ctx = LocalContext.from_dict(data)
    assert ctx.scanned_at == UNKNOWN_SCAN_TIME
    print("   ✅ Invalid timestamp handled")

    # Test with missing scanned_at key
    print("4. Testing missing timestamp key...")
    data = {"os_info": {"system": "Darwin"}}
    ctx = LocalContext.from_dict(data)
    assert ctx.scanned_at == UNKNOWN_SCAN_TIME
    print("   ✅ Missing timestamp handled")

    # Test with already datetime object
    print("5. Testing datetime object passthrough...")
    now = datetime.now()
    data = {"scanned_at": now, "os_info": {}}
    ctx = LocalContext.from_dict(data)
    assert ctx.scanned_at == now
    print("   ✅ Datetime passthrough handled")

    # Test needs_rescan method
    print("6. Testing needs_rescan method...")
    ctx = LocalContext.from_dict({"scanned_at": None})
    assert ctx.needs_rescan(), "Unknown scan time should need rescan"
    ctx = LocalContext.from_dict({"scanned_at": datetime.now().isoformat()})
    assert not ctx.needs_rescan(max_age_seconds=3600), "Fresh scan should not need rescan"
    print("   ✅ needs_rescan method works")

    print("✅ LocalContext.from_dict verification passed!")


def verify_search_with_limit():
    """Test search_hosts with limit parameter."""
    print("\n🧪 Verifying search_hosts with limit...")

    # Use a cross-platform temporary DB with guaranteed cleanup
    tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tmp_file.name
    tmp_file.close()

    try:
        InventoryRepository.reset_instance()
        repo = InventoryRepository(db_path=db_path)

        # Add many hosts
        source_id = repo.add_source("limit_source", "manual")
        for i in range(10):
            repo.add_host(f"server-{i:02d}", f"10.0.0.{i}", source_id=source_id)

        # Test without limit (should return all)
        print("1. Testing without limit...")
        all_hosts = repo.search_hosts()
        assert len(all_hosts) == 10

        # Test with limit
        print("2. Testing with limit=5...")
        limited = repo.search_hosts(limit=5)
        assert len(limited) == 5

        # Test with limit+1 pattern (for truncation detection)
        print("3. Testing limit+1 pattern...")
        limit = 5
        results = repo.search_hosts(limit=limit + 1)
        truncated = len(results) > limit
        assert truncated, "Should detect truncation with limit+1 pattern"

        print("✅ Search with limit verification passed!")
    finally:
        # Cleanup: reset singleton and remove temp DB
        InventoryRepository.reset_instance()
        if os.path.exists(db_path):
            os.remove(db_path)


if __name__ == "__main__":
    verify_inventory_repository()
    verify_bulk_add_hosts()
    verify_bulk_add_hosts_rollback()
    verify_local_context()
    verify_search_with_limit()
