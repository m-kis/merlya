"""
Test script for SmartOrchestrator list filtering logic.
"""
from unittest.mock import MagicMock

import pytest

# Mark as manual test
pytestmark = pytest.mark.manual


def test_list_filtering():
    """Test smart list filtering (manual test)."""
    # Import here to avoid import errors at collection time
    from merlya.agents.smart_orchestrator import SmartOrchestrator

    from merlya.agents.request_classifier import ClassificationResult, ExecutionStrategy, RequestComplexity

    print("🧪 Testing Smart List Filtering...")

    # Mock dependencies
    mock_router = MagicMock()
    mock_context = MagicMock()
    mock_executor = MagicMock()

    # Mock inventory
    mock_context.get_context.return_value = {
        "inventory": {
            "mongo-prod-1": "10.0.0.1",
            "mongo-preprod-1": "10.0.0.2",
            "web-prod-1": "10.0.0.3",
            "redis-preprod-1": "10.0.0.4"
        }
    }

    orchestrator = SmartOrchestrator(mock_router, mock_context, mock_executor)

    # Test query
    query = "donne moi la list des serveurs de preprod mongo"
    print(f"Query: {query}")

    # Force classification to DIRECT to test _execute_direct
    classification = ClassificationResult(
        complexity=RequestComplexity.SIMPLE,
        strategy=ExecutionStrategy.DIRECT,
        estimated_steps=1,
        estimated_duration=1,
        needs_reformulation=False,
        show_thinking=False,
        reasoning="Test reasoning"
    )

    # Execute direct logic
    result = orchestrator._execute_direct(query, classification)

    print("\n--- Result ---")
    print(result)
    print("--------------\n")

    # Verify filtering
    assert "mongo-preprod-1" in result, "Should find mongo-preprod-1"
    assert "mongo-prod-1" not in result, "Should exclude mongo-prod-1"


if __name__ == "__main__":
    test_list_filtering()
