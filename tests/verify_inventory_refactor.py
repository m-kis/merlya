
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from athena_ai.memory.persistence.inventory_repository import InventoryRepository

def verify_inventory_repository():
    print("🧪 Verifying InventoryRepository...")

    # Use a temporary DB
    db_path = "/tmp/athena_inventory_test.db"
    if os.path.exists(db_path):
        os.remove(db_path)

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
    
    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)

if __name__ == "__main__":
    verify_inventory_repository()
