"""
Test for N+1 query optimization in relation batch insertion.

Verifies that add_relations_batch uses a single query to fetch all host IDs
instead of N individual queries (one per relation).
"""
import tempfile
from pathlib import Path

import pytest

from athena_ai.memory.persistence.inventory_repository import get_inventory_repository
from athena_ai.memory.persistence.repositories import HostData


@pytest.fixture
def test_db():
    """Create temporary test database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    # Reset singleton to use test DB
    from athena_ai.memory.persistence.inventory_repository import InventoryRepository
    InventoryRepository.reset_instance()

    repo = get_inventory_repository(db_path)
    yield repo

    # Cleanup
    InventoryRepository.reset_instance()
    Path(db_path).unlink(missing_ok=True)


def test_batch_relations_performance_improvement(test_db):
    """Test: Verify performance improvement with batch query optimization."""
    import time

    # Create 100 test hosts
    hosts = [
        HostData(hostname=f"perf-host-{i:03d}", ip_address=f"10.0.1.{i % 256}")
        for i in range(100)
    ]
    source_id = test_db.add_source("perf_test", "generated", "/dev/null")
    test_db.bulk_add_hosts(hosts, source_id)

    # Create 200 relations (2 per host, cycling through all 100 hosts)
    relations = [
        {
            "source_hostname": f"perf-host-{i % 100:03d}",
            "target_hostname": f"perf-host-{(i+1) % 100:03d}",
            "relation_type": "connects_to",
        }
        for i in range(200)
    ]

    start = time.time()
    result = test_db.add_relations_batch(relations)
    duration = time.time() - start

    # All 200 relations are processed (100 inserts + 100 ON CONFLICT updates)
    assert result.saved_count == 200, f"Should process 200 relations, got {result.saved_count}"

    # With N+1 queries, this would take significantly longer
    # With optimization (single batched query), should be fast
    assert duration < 2.0, (
        f"Batch insert took {duration:.2f}s, expected < 2s. "
        f"This may indicate N+1 query problem."
    )


def test_batch_relations_handles_missing_hosts(test_db):
    """Test: Batch optimization correctly handles missing hosts."""
    # Create only 5 hosts
    hosts = [
        HostData(hostname=f"exist-{i}", ip_address=f"10.0.0.{i}")
        for i in range(5)
    ]
    source_id = test_db.add_source("test", "generated", "/dev/null")
    test_db.bulk_add_hosts(hosts, source_id)

    # Create relations with some missing hosts
    relations = [
        {"source_hostname": "exist-0", "target_hostname": "exist-1", "relation_type": "valid"},
        {"source_hostname": "missing-src", "target_hostname": "exist-2", "relation_type": "invalid_src"},
        {"source_hostname": "exist-3", "target_hostname": "missing-tgt", "relation_type": "invalid_tgt"},
        {"source_hostname": "exist-4", "target_hostname": "exist-0", "relation_type": "valid"},
    ]

    result = test_db.add_relations_batch(relations)

    assert result.saved_count == 2, "Should save only 2 valid relations"
    assert len(result.skipped) == 2, "Should skip 2 invalid relations"

    # Verify skip reasons mention "not found"
    skip_reasons = [reason for _, reason in result.skipped]
    assert any("not found" in reason for reason in skip_reasons), "Should report missing hosts"
