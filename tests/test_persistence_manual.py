"""
Test script for Persistent Memory.
"""
import os
import sys

from athena_ai.memory.persistent_store import KnowledgeStore


def test_persistence():
    print("🧪 Testing Persistent Memory...")

    # Use a temporary file for testing
    test_path = "/tmp/athena_test_knowledge.json"
    if os.path.exists(test_path):
        os.remove(test_path)

    # 1. Create store and save a fact
    print("1. Creating store and saving fact...")
    store1 = KnowledgeStore(storage_path=test_path)
    store1.update_host_fact("test-host-01", "os", "Linux 5.4")
    store1.update_host_fact("test-host-01", "ip", "192.168.1.100")

    # 2. Reload from disk
    print("2. Reloading from disk...")
    store2 = KnowledgeStore(storage_path=test_path)

    # 3. Verify data
    info = store2.get_host_info("test-host-01")
    print(f"   Retrieved info: {info}")

    if info and info.get("os") == "Linux 5.4":
        print("✅ Persistence verified!")
    else:
        print("❌ Persistence failed!")
        sys.exit(1)

    # 4. Test Search
    print("3. Testing search...")
    matches = store2.search_hosts("linux")
    if "test-host-01" in matches:
        print("✅ Search verified!")
    else:
        print(f"❌ Search failed! Found: {matches}")

    # Cleanup
    if os.path.exists(test_path):
        os.remove(test_path)

if __name__ == "__main__":
    try:
        # Also verify ag2 import
        import ag2
        print(f"✅ ag2 imported successfully (version: {ag2.__version__})")
    except ImportError:
        print("⚠️ ag2 not installed yet (expected if poetry install not run)")

    test_persistence()
