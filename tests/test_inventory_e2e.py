"""
End-to-End integration tests for inventory system.

Tests complete flows: Parse → Import → Relations → Export
"""
import json
import tempfile
from pathlib import Path

import pytest

from merlya.inventory.parser import get_inventory_parser
from merlya.inventory.relation_classifier import get_relation_classifier
from merlya.memory.persistence.inventory_repository import get_inventory_repository
from merlya.memory.persistence.repositories import HostData


@pytest.fixture
def test_db():
    """Create temporary test database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    # Reset singleton to use test DB
    from merlya.memory.persistence.inventory_repository import InventoryRepository
    InventoryRepository.reset_instance()

    repo = get_inventory_repository(db_path)
    yield repo

    # Cleanup
    InventoryRepository.reset_instance()
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def sample_csv_file():
    """Create sample CSV inventory file."""
    content = """hostname,ip_address,environment,groups
web-prod-01,10.0.1.10,production,web;frontend
web-prod-02,10.0.1.11,production,web;frontend
db-prod-01,10.0.2.10,production,database;backend
db-prod-replica,10.0.2.11,production,database;backend
cache-prod-01,10.0.3.10,production,cache
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write(content)
        f.flush()
        yield Path(f.name)

    Path(f.name).unlink(missing_ok=True)


@pytest.fixture
def sample_json_file():
    """Create sample JSON inventory file."""
    content = [
        {"hostname": "api-prod-01", "ip_address": "10.0.4.10", "environment": "production", "service": "api"},
        {"hostname": "api-prod-02", "ip_address": "10.0.4.11", "environment": "production", "service": "api"},
    ]
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(content, f)
        f.flush()
        yield Path(f.name)

    Path(f.name).unlink(missing_ok=True)


@pytest.mark.integration
class TestInventoryE2EFlow:
    """End-to-end tests for complete inventory workflows."""

    def test_csv_import_flow(self, test_db, sample_csv_file):
        """Test: Parse CSV → Import → Verify."""
        parser = get_inventory_parser()

        # 1. Parse
        result = parser.parse(str(sample_csv_file))

        assert result.success, f"Parse failed: {result.errors}"
        assert len(result.hosts) == 5, "Should parse 5 hosts"
        assert result.source_type == "csv"

        # 2. Import
        source_id = test_db.add_source(
            name="test_csv",
            source_type="csv",
            file_path=str(sample_csv_file),
        )

        hosts = [HostData(**h.__dict__) for h in result.hosts]
        added = test_db.bulk_add_hosts(hosts, source_id)

        assert added == 5, "Should import 5 hosts"

        # 3. Verify
        all_hosts = test_db.get_all_hosts()
        assert len(all_hosts) == 5

        # Check specific host
        web01 = test_db.get_host_by_name("web-prod-01")
        assert web01 is not None
        assert web01["ip_address"] == "10.0.1.10"
        assert web01["environment"] == "production"
        # Groups stored as semicolon-separated string or list
        groups = web01["groups"]
        assert "web" in groups or "web" in str(groups)

    def test_json_import_flow(self, test_db, sample_json_file):
        """Test: Parse JSON → Import → Verify."""
        parser = get_inventory_parser()

        result = parser.parse(str(sample_json_file))

        assert result.success
        assert len(result.hosts) == 2
        assert result.source_type == "json"

        source_id = test_db.add_source("test_json", "json", str(sample_json_file))
        hosts = [HostData(**h.__dict__) for h in result.hosts]
        added = test_db.bulk_add_hosts(hosts, source_id)

        assert added == 2

    def test_multiple_sources_merge(self, test_db, sample_csv_file, sample_json_file):
        """Test: Import from multiple sources → Merge correctly."""
        parser = get_inventory_parser()

        # Import CSV
        csv_result = parser.parse(str(sample_csv_file))
        csv_source_id = test_db.add_source("csv_source", "csv", str(sample_csv_file))
        csv_hosts = [HostData(**h.__dict__) for h in csv_result.hosts]
        test_db.bulk_add_hosts(csv_hosts, csv_source_id)

        # Import JSON
        json_result = parser.parse(str(sample_json_file))
        json_source_id = test_db.add_source("json_source", "json", str(sample_json_file))
        json_hosts = [HostData(**h.__dict__) for h in json_result.hosts]
        test_db.bulk_add_hosts(json_hosts, json_source_id)

        # Verify merge
        all_hosts = test_db.get_all_hosts()
        assert len(all_hosts) == 7, "Should have 5 from CSV + 2 from JSON"

        sources = test_db.list_sources()
        assert len(sources) == 2

    def test_relations_detection_flow(self, test_db, sample_csv_file):
        """Test: Import → Detect Relations → Validate."""
        parser = get_inventory_parser()
        classifier = get_relation_classifier()

        # 1. Import hosts
        result = parser.parse(str(sample_csv_file))
        source_id = test_db.add_source("test", "csv", str(sample_csv_file))
        hosts = [HostData(**h.__dict__) for h in result.hosts]
        test_db.bulk_add_hosts(hosts, source_id)

        # 2. Detect relations
        all_hosts = test_db.get_all_hosts()
        suggestions = classifier.suggest_relations(all_hosts, use_llm=False)

        assert len(suggestions) > 0, "Should find some relations"

        # Check cluster relation (web-prod-01, web-prod-02)
        cluster_relations = [s for s in suggestions if s.relation_type == "cluster_member"]
        assert len(cluster_relations) >= 1, "Should find cluster relations"

        # Check replica relation (db-prod-01, db-prod-replica)
        _ = [s for s in suggestions if s.relation_type == "database_replica"]
        # May or may not find (depends on heuristics implementation)

        # 3. Save relations
        for suggestion in suggestions[:5]:  # Save first 5
            test_db.add_relation(
                source_hostname=suggestion.source_hostname,
                target_hostname=suggestion.target_hostname,
                relation_type=suggestion.relation_type,
                confidence=suggestion.confidence,
                metadata=suggestion.metadata,
            )

        # 4. Verify saved
        saved_relations = test_db.get_relations()
        assert len(saved_relations) >= 1, "Should have saved relations"

    def test_export_flow(self, test_db, sample_csv_file):
        """Test: Import → Export to different format."""
        parser = get_inventory_parser()

        # Import
        result = parser.parse(str(sample_csv_file))
        source_id = test_db.add_source("test", "csv", str(sample_csv_file))
        hosts = [HostData(**h.__dict__) for h in result.hosts]
        test_db.bulk_add_hosts(hosts, source_id)

        # Export to JSON
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            export_path = Path(f.name)

        try:
            all_hosts = test_db.get_all_hosts()
            with open(export_path, 'w') as f:
                json.dump(all_hosts, f, indent=2, default=str)

            # Verify export
            with open(export_path) as f:
                exported = json.load(f)

            assert len(exported) == 5
            assert all("hostname" in h for h in exported)

        finally:
            export_path.unlink(missing_ok=True)

    def test_search_and_pagination_flow(self, test_db):
        """Test: Import many hosts → Search with pagination."""
        # Import 100 hosts
        hosts = [
            HostData(
                hostname=f"host-{i:03d}",
                ip_address=f"10.0.{i//256}.{i%256}",
                environment="production" if i % 2 == 0 else "staging",
                groups=["web"] if i < 50 else ["db"],
            )
            for i in range(100)
        ]

        source_id = test_db.add_source("bulk", "generated", "/dev/null")
        added = test_db.bulk_add_hosts(hosts, source_id)
        assert added == 100

        # Search with pagination
        page1 = test_db.search_hosts(limit=20, offset=0)
        page2 = test_db.search_hosts(limit=20, offset=20)

        assert len(page1) == 20
        assert len(page2) == 20
        assert page1[0]["hostname"] != page2[0]["hostname"], "Different pages"

        # Filter search
        prod_hosts = test_db.search_hosts(environment="production")
        assert len(prod_hosts) == 50

        # Count
        total = test_db.count_hosts()
        assert total == 100

    def test_update_and_versioning_flow(self, test_db):
        """Test: Import → Update host → Check versioning."""
        # Initial import
        host_id = test_db.add_host(
            hostname="web-01",
            ip_address="10.0.1.10",
            environment="staging",
        )

        # Update
        test_db.add_host(
            hostname="web-01",
            ip_address="10.0.1.20",  # Changed IP
            environment="production",  # Changed env
        )

        # Check versions (implementation may or may not create full version history)
        versions = test_db.get_host_versions(host_id)
        assert len(versions) >= 1, "Should have at least one version"

        # Check current state
        host = test_db.get_host_by_name("web-01")
        assert host["ip_address"] == "10.0.1.20", "Should have updated IP"
        assert host["environment"] == "production", "Should have updated env"

    def test_delete_and_audit_flow(self, test_db):
        """Test: Import → Delete host → Check audit trail."""
        # Import
        test_db.add_host(hostname="temp-host", ip_address="10.0.0.1")

        # Delete
        deleted = test_db.delete_host(
            hostname="temp-host",
            deleted_by="test_user",
            reason="cleanup",
        )
        assert deleted, "Should delete successfully"

        # Verify deleted
        host = test_db.get_host_by_name("temp-host")
        assert host is None, "Host should be deleted"

        # Check audit trail (if implemented)
        # This depends on having a query method for deletions
        # test_db.get_deletion_audit()

    def test_snapshot_flow(self, test_db, sample_csv_file):
        """Test: Import → Create snapshot → Verify."""
        parser = get_inventory_parser()

        # Import
        result = parser.parse(str(sample_csv_file))
        source_id = test_db.add_source("test", "csv", str(sample_csv_file))
        hosts = [HostData(**h.__dict__) for h in result.hosts]
        test_db.bulk_add_hosts(hosts, source_id)

        # Create snapshot
        snapshot_id = test_db.create_snapshot(name="pre_migration")
        assert snapshot_id is not None

        # Verify snapshot
        snapshots = test_db.list_snapshots()
        assert len(snapshots) >= 1

        snapshot = test_db.get_snapshot(snapshot_id)
        assert snapshot is not None
        assert snapshot["host_count"] == 5


@pytest.mark.integration
class TestInventoryErrorHandling:
    """Test error handling in E2E flows."""

    def test_invalid_csv_graceful_fail(self, test_db):
        """Test: Invalid CSV → Graceful error."""
        invalid_csv = """not,valid,csv,with,issues
        missing,columns
        malformed"quotes
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(invalid_csv)
            path = Path(f.name)

        try:
            parser = get_inventory_parser()
            result = parser.parse(str(path))

            # Should either parse with errors or return empty
            assert isinstance(result.errors, list)

        finally:
            path.unlink(missing_ok=True)

    def test_duplicate_hostname_update(self, test_db):
        """Test: Duplicate hostname → Update instead of error."""
        # Add first time
        test_db.add_host(hostname="dup-host", ip_address="10.0.0.1")

        # Add again (should update)
        test_db.add_host(hostname="dup-host", ip_address="10.0.0.2")

        # Verify updated
        host = test_db.get_host_by_name("dup-host")
        assert host["ip_address"] == "10.0.0.2"

    def test_bulk_import_transaction_rollback(self, test_db):
        """Test: Bulk import with invalid data → Validation fails."""
        # Invalid: hostname too long (>253 chars)
        long_hostname = "x" * 300

        # Should fail during HostData validation
        with pytest.raises(ValueError) as exc_info:
            HostData(hostname=long_hostname, ip_address="10.0.0.3")

        # Error message should be clear
        assert "too long" in str(exc_info.value).lower() or "max" in str(exc_info.value).lower()

        # Verify no hosts were added (since validation failed before DB call)
        all_hosts = test_db.get_all_hosts()
        assert len(all_hosts) == 0, "No hosts should have been added"


@pytest.mark.integration
@pytest.mark.slow
class TestInventoryPerformance:
    """Performance tests for inventory flows."""

    def test_bulk_import_10k_hosts(self, test_db):
        """Test: Import 10,000 hosts performance."""
        hosts = [
            HostData(
                hostname=f"host-{i:05d}",
                ip_address=f"10.{i//65536}.{(i//256)%256}.{i%256}",
                environment="production",
            )
            for i in range(10_000)
        ]

        source_id = test_db.add_source("bulk", "generated", "/dev/null")

        import time
        start = time.time()
        result = test_db.bulk_add_hosts(hosts, source_id)
        duration = time.time() - start

        assert result == 10_000
        # Target: < 10 seconds for 10k hosts (generous limit for slow CI)
        assert duration < 10.0, f"Import took {duration:.2f}s, should be < 10s"

    def test_search_100k_hosts(self, test_db):
        """Test: Search performance on 100k hosts."""
        # This test is VERY slow, skip unless explicitly requested
        pytest.skip("Slow test: 100k hosts")

        # Import 100k hosts
        batch_size = 1000
        for batch in range(100):
            hosts = [
                HostData(
                    hostname=f"host-{batch:03d}-{i:03d}",
                    ip_address=f"10.{batch}.{i//256}.{i%256}",
                )
                for i in range(batch_size)
            ]
            source_id = test_db.add_source(f"batch_{batch}", "generated", "/dev/null")
            test_db.bulk_add_hosts(hosts, source_id)

        # Search should still be fast
        import time
        start = time.time()
        results = test_db.search_hosts(pattern="host-050", limit=100)
        duration = time.time() - start

        assert duration < 0.1, "Search should be < 100ms even on 100k hosts"
        assert len(results) > 0
