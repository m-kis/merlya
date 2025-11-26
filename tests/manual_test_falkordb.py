"""
Manual test script for Athena FalkorDB integration.
Verifies knowledge tools and graph connection.
"""
import os
import sys
from unittest.mock import MagicMock

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from athena_ai.agents import knowledge_tools
from athena_ai.knowledge.ops_knowledge_manager import get_knowledge_manager


def test_knowledge_tools():
    print("\n--- Testing Knowledge Tools ---")

    # Check if FalkorDB is available (mock if not)
    km = get_knowledge_manager()
    if not km.storage.falkordb_available:
        print("⚠️ FalkorDB not running. Mocking for test purposes.")
        km.storage._falkordb = MagicMock()
        km.storage._falkordb.is_connected = True
        km.storage._falkordb.get_stats.return_value = {
            "connected": True,
            "graph_name": "test_graph",
            "total_nodes": 10,
            "total_relationships": 5
        }

    # Test graph_stats
    print("Testing graph_stats...")
    res = knowledge_tools.graph_stats()
    if "Knowledge Graph Status" in res:
        print("✅ graph_stats passed")
    else:
        print(f"❌ graph_stats failed: {res}")

    # Test record_incident
    print("Testing record_incident...")
    res = knowledge_tools.record_incident(
        title="Test Incident",
        priority="P3",
        service="test-service",
        symptoms="slow, error 500",
        description="Test description"
    )
    if "Incident recorded" in res:
        print("✅ record_incident passed")
    else:
        print(f"❌ record_incident failed: {res}")

    # Test search_knowledge
    print("Testing search_knowledge...")
    # Mocking return values for search since we might be using mocks
    km.patterns.match_patterns = MagicMock(return_value=[])
    km.incidents.find_similar = MagicMock(return_value=[])

    res = knowledge_tools.search_knowledge("slow response")
    # Even empty result is a success for the tool wrapper
    if "No relevant knowledge found" in res or "Matching" in res:
        print("✅ search_knowledge passed")
    else:
        print(f"❌ search_knowledge failed: {res}")

    # Test Route Sync (Unified Routing)
    print("\n--- Testing Unified Routing Sync ---")
    from athena_ai.memory.persistent_store import KnowledgeStore
    ks = KnowledgeStore()
    # Mock the knowledge manager inside the store
    ks._knowledge_manager = km

    # We need to mock the query method on the falkordb client
    km.storage._falkordb.query = MagicMock()

    ks.add_route("10.99.0.0/16", "bastion-test")

    # Verify query was called
    if km.storage._falkordb.query.called:
        print("✅ Route sync to FalkorDB triggered")
        # Check args
        calls = km.storage._falkordb.query.call_args_list
        # Should have at least 3 calls (Network, Host, Rel)
        if len(calls) >= 3:
             print("✅ Route sync made expected graph queries")
        else:
             print(f"⚠️ Route sync made fewer queries than expected: {len(calls)}")
    else:
        print("❌ Route sync to FalkorDB NOT triggered")

    # Test Audit Logging
    print("\n--- Testing Audit Integration ---")
    # Mock log_action
    km.log_action = MagicMock()

    # We need to mock executor for execute_command to work
    from athena_ai.agents import autogen_tools
    mock_executor = MagicMock()
    mock_executor.execute.return_value = {"success": True, "stdout": "ok", "stderr": ""}

    # Initialize tools with mocks
    autogen_tools.initialize_autogen_tools(
        executor=mock_executor,
        context_manager=MagicMock(),
        permissions=MagicMock(),
        context_memory=MagicMock()
    )

    # Run execute_command
    autogen_tools.execute_command("local", "echo test", "testing audit")

    if km.log_action.called:
        print("✅ Audit log triggered")
        args = km.log_action.call_args[1]
        if args.get('action') == 'execute_command' and args.get('details') == 'testing audit':
            print("✅ Audit log content correct")
        else:
            print(f"❌ Audit log content incorrect: {args}")
    else:
        print("❌ Audit log NOT triggered")


if __name__ == "__main__":
    try:
        test_knowledge_tools()
        print("\n✅ All tests completed")
    except Exception as e:
        print(f"\n❌ Tests failed: {e}")
        import traceback
        traceback.print_exc()
