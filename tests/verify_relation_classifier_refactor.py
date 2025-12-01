"""
Verification script for HostRelationClassifier refactoring.
"""
import unittest
from unittest.mock import MagicMock

# Import the class to be refactored (will need to update import after refactor)
try:
    from merlya.inventory.relation_classifier import HostRelationClassifier
except ImportError:
    # Fallback for after refactor if package structure changes
    from merlya.inventory.relation_classifier.classifier import HostRelationClassifier

class TestHostRelationClassifier(unittest.TestCase):
    def setUp(self):
        self.classifier = HostRelationClassifier(llm_router=MagicMock())
        # Mock LLM response for deterministic testing
        self.classifier.llm.generate.return_value = '[]'

    def test_heuristic_cluster_relations(self):
        """Test cluster detection heuristics."""
        hosts = [
            {"hostname": "web-01", "environment": "prod"},
            {"hostname": "web-02", "environment": "prod"},
            {"hostname": "db-01", "environment": "prod"},
        ]
        suggestions = self.classifier.suggest_relations(hosts, use_llm=False)

        cluster_rels = [s for s in suggestions if s.relation_type == "cluster_member"]
        self.assertTrue(len(cluster_rels) >= 1)
        self.assertEqual(cluster_rels[0].source_hostname, "web-01")
        self.assertEqual(cluster_rels[0].target_hostname, "web-02")

    def test_heuristic_replica_relations(self):
        """Test replica detection heuristics."""
        hosts = [
            {"hostname": "db-master", "environment": "prod"},
            {"hostname": "db-replica", "environment": "prod"},
        ]
        suggestions = self.classifier.suggest_relations(hosts, use_llm=False)

        replica_rels = [s for s in suggestions if s.relation_type == "database_replica"]
        self.assertTrue(len(replica_rels) >= 1)
        # Note: logic might produce bidirectional or specific direction, checking existence
        self.assertTrue(any(s.source_hostname == "db-replica" and s.target_hostname == "db-master" for s in replica_rels))

    def test_heuristic_service_relations(self):
        """Test service dependency heuristics."""
        hosts = [
            {"hostname": "web-app", "environment": "prod"},
            {"hostname": "db-main", "environment": "prod"},
        ]
        suggestions = self.classifier.suggest_relations(hosts, use_llm=False)

        # web -> db dependency
        depends_rels = [s for s in suggestions if s.relation_type == "depends_on"]
        self.assertTrue(len(depends_rels) >= 1)
        self.assertEqual(depends_rels[0].source_hostname, "web-app")
        self.assertEqual(depends_rels[0].target_hostname, "db-main")

    def test_llm_relations(self):
        """Test LLM-based relation discovery."""
        hosts = [
            {"hostname": "custom-app", "environment": "prod"},
            {"hostname": "legacy-db", "environment": "prod"},
            {"hostname": "dummy-1", "environment": "prod"},
            {"hostname": "dummy-2", "environment": "prod"},
        ]

        # Mock LLM response
        mock_response = '[{"source": "custom-app", "target": "legacy-db", "type": "depends_on", "confidence": 0.8, "reason": "Test reason"}]'
        self.classifier.llm.generate.return_value = mock_response

        suggestions = self.classifier.suggest_relations(hosts, use_llm=True)

        llm_rels = [s for s in suggestions if s.metadata.get("source") == "llm"]
        self.assertEqual(len(llm_rels), 1)
        self.assertEqual(llm_rels[0].source_hostname, "custom-app")
        self.assertEqual(llm_rels[0].target_hostname, "legacy-db")

if __name__ == "__main__":
    unittest.main()
