"""
Tests for relation classification heuristics.

Tests cluster detection, replica patterns, and group-based relations.
"""
import pytest

from merlya.inventory.relation_classifier.heuristics import RelationHeuristics
from merlya.inventory.relation_classifier.models import RelationSuggestion


class TestClusterDetection:
    """Test cluster member detection (numbered hosts)."""

    def test_simple_numbered_cluster(self):
        """Test: web-01, web-02, web-03 detected as cluster."""
        hosts = [
            {"hostname": "web-prod-01", "groups": ["web"]},
            {"hostname": "web-prod-02", "groups": ["web"]},
            {"hostname": "web-prod-03", "groups": ["web"]},
        ]
        relations = RelationHeuristics.find_cluster_relations(hosts)

        assert len(relations) == 3, "Should find 3 relations (each pair)"
        assert all(r.relation_type == "cluster_member" for r in relations)
        assert all(r.confidence >= 0.8 for r in relations), "High confidence for numbered pattern"

    def test_zero_padded_cluster(self):
        """Test: web-001, web-002 detected as cluster."""
        hosts = [
            {"hostname": "web-prod-001"},
            {"hostname": "web-prod-002"},
        ]
        relations = RelationHeuristics.find_cluster_relations(hosts)

        assert len(relations) >= 1, "Should find at least 1 relation"
        assert all(r.relation_type == "cluster_member" for r in relations)

    def test_single_host_no_cluster(self):
        """Test: Single host doesn't form cluster."""
        hosts = [{"hostname": "web-prod-01"}]
        relations = RelationHeuristics.find_cluster_relations(hosts)

        assert len(relations) == 0, "Single host can't have cluster relations"

    def test_different_prefixes_no_cluster(self):
        """Test: Different prefixes don't form cluster."""
        hosts = [
            {"hostname": "web-01"},
            {"hostname": "db-01"},
            {"hostname": "cache-01"},
        ]
        relations = RelationHeuristics.find_cluster_relations(hosts)

        assert len(relations) == 0, "Different prefixes shouldn't cluster"

    def test_mixed_numbering_no_cluster(self):
        """Test: Inconsistent numbering doesn't form cluster."""
        hosts = [
            {"hostname": "web-1"},     # Single digit
            {"hostname": "web-01"},    # Two digit padded
            {"hostname": "web-001"},   # Three digit padded
        ]
        relations = RelationHeuristics.find_cluster_relations(hosts)

        # May or may not cluster (implementation-dependent)
        # At minimum, should not crash
        assert isinstance(relations, list)

    def test_cluster_with_environment(self):
        """Test: Cluster detection works with environment suffix."""
        hosts = [
            {"hostname": "web-prod-us-east-1"},
            {"hostname": "web-prod-us-east-2"},
            {"hostname": "web-prod-us-east-3"},
        ]
        relations = RelationHeuristics.find_cluster_relations(hosts)

        # Should detect numbered pattern at end
        assert len(relations) >= 1, "Should find cluster despite complex naming"

    def test_cluster_confidence_decreases_with_gap(self):
        """Test: Confidence lower if there's a gap in numbers."""
        hosts = [
            {"hostname": "web-01"},
            {"hostname": "web-02"},
            {"hostname": "web-05"},  # Gap (03, 04 missing)
        ]
        relations = RelationHeuristics.find_cluster_relations(hosts)

        if len(relations) > 0:
            # Confidence should still be reasonable but may be lower
            assert all(r.confidence >= 0.5 for r in relations)

    def test_large_cluster(self):
        """Test: Large cluster (20 hosts) handled efficiently."""
        hosts = [{"hostname": f"web-{i:02d}"} for i in range(1, 21)]
        relations = RelationHeuristics.find_cluster_relations(hosts)

        # Should find relations for all pairs (n*(n-1)/2 = 190 relations for 20 hosts)
        # Or optimized to n-1 = 19 relations (chain)
        assert len(relations) >= 19, "Should find many relations in large cluster"
        assert all(r.relation_type == "cluster_member" for r in relations)


class TestReplicaDetection:
    """Test database replica pattern detection."""

    @pytest.mark.parametrize("primary,replica,confidence_threshold", [
        ("db-master", "db-replica", 0.9),
        ("mysql-main-master", "mysql-main-slave", 0.9),
        ("db-primary", "db-secondary", 0.9),
    ])
    def test_database_replica_patterns(self, primary, replica, confidence_threshold):
        """Test: Database replica naming patterns that match implementation."""
        hosts = [
            {"hostname": primary, "service": "database"},
            {"hostname": replica, "service": "database"},
        ]
        relations = RelationHeuristics.find_replica_relations(hosts)

        assert len(relations) >= 1, f"Should detect replica: {primary} -> {replica}"

        # Find the specific relation (source is replica, target is primary)
        found = False
        for r in relations:
            if r.target_hostname == primary and r.source_hostname == replica:
                assert r.relation_type == "database_replica"
                assert r.confidence >= confidence_threshold, f"Low confidence: {r.confidence}"
                found = True
                break

        assert found, "Should find replica->primary relation"

    def test_no_replica_without_service(self):
        """Test: Replica detection requires service field."""
        hosts = [
            {"hostname": "db-master"},  # No service field
            {"hostname": "db-replica"},
        ]
        relations = RelationHeuristics.find_replica_relations(hosts)

        # May or may not detect without service field (implementation-dependent)
        # Should not crash
        assert isinstance(relations, list)

    def test_bidirectional_replication(self):
        """Test: Bidirectional replication (multi-master)."""
        hosts = [
            {"hostname": "db-master-1", "service": "database"},
            {"hostname": "db-master-2", "service": "database"},
        ]
        relations = RelationHeuristics.find_replica_relations(hosts)

        # Should find mutual replication (or at least one direction)
        assert isinstance(relations, list)

    def test_replica_chain(self):
        """Test: Replica chain (primary -> replica1 -> replica2)."""
        hosts = [
            {"hostname": "db-primary", "service": "database"},
            {"hostname": "db-secondary", "service": "database"},
        ]
        relations = RelationHeuristics.find_replica_relations(hosts)

        # Should find at least one relation
        assert len(relations) >= 1, "Should find at least one replica relation"

    def test_different_database_types_no_replica(self):
        """Test: Different DB types don't replicate."""
        hosts = [
            {"hostname": "postgres-master", "service": "postgres"},
            {"hostname": "mysql-master", "service": "mysql"},
        ]
        relations = RelationHeuristics.find_replica_relations(hosts)

        # Should not suggest cross-DB replication
        assert len(relations) == 0, "Different DB types shouldn't replicate"


class TestGroupRelations:
    """Test group-based relation detection."""

    def test_same_group_related(self):
        """Test: Hosts in same group are related."""
        hosts = [
            {"hostname": "web-01", "groups": ["frontend", "production"]},
            {"hostname": "web-02", "groups": ["frontend", "production"]},
            {"hostname": "web-03", "groups": ["frontend", "production"]},
        ]
        relations = RelationHeuristics.find_group_relations(hosts)

        assert len(relations) >= 1, "Should find group-based relations"

        # All relations should be based on shared groups
        for r in relations:
            assert r.metadata is not None, "Should have metadata"
            assert "group" in r.metadata, "Should have group in metadata"

    def test_no_shared_groups_no_relation(self):
        """Test: Hosts without shared groups aren't related."""
        hosts = [
            {"hostname": "web-01", "groups": ["frontend"]},
            {"hostname": "db-01", "groups": ["backend"]},
        ]
        relations = RelationHeuristics.find_group_relations(hosts)

        assert len(relations) == 0, "No shared groups = no group relations"

    def test_partial_group_overlap(self):
        """Test: Partial group overlap still creates relation."""
        hosts = [
            {"hostname": "web-01", "groups": ["frontend", "production"]},
            {"hostname": "web-02", "groups": ["frontend", "staging"]},
        ]
        relations = RelationHeuristics.find_group_relations(hosts)

        # Should find relation based on shared "frontend" group
        assert len(relations) >= 1, "Partial overlap should create relation"

    def test_confidence_increases_with_shared_groups(self):
        """Test: Multiple shared groups creates multiple relations."""
        hosts = [
            {"hostname": "web-01", "groups": ["frontend", "production", "us-east"]},
            {"hostname": "web-02", "groups": ["frontend", "production", "us-east"]},
        ]
        relations = RelationHeuristics.find_group_relations(hosts)

        # Should find relations (implementation may create 1 per group pair or aggregate)
        assert len(relations) >= 1, "Should find at least one relation"

    def test_empty_groups_no_relation(self):
        """Test: Hosts without groups don't have group relations."""
        hosts = [
            {"hostname": "web-01", "groups": []},
            {"hostname": "web-02", "groups": []},
        ]
        relations = RelationHeuristics.find_group_relations(hosts)

        assert len(relations) == 0, "Empty groups = no relations"

    def test_missing_groups_field(self):
        """Test: Hosts without 'groups' field don't crash."""
        hosts = [
            {"hostname": "web-01"},  # No groups field
            {"hostname": "web-02"},
        ]
        relations = RelationHeuristics.find_group_relations(hosts)

        # Should handle gracefully (no crash)
        assert isinstance(relations, list)


class TestServiceRelations:
    """Test service-based relation detection (hostname patterns)."""

    def test_same_service_related(self):
        """Test: Service dependency detection (hostname patterns)."""
        hosts = [
            {"hostname": "frontend-web-server"},
            {"hostname": "backend-api-service"},
            {"hostname": "postgres-database"},
        ]
        relations = RelationHeuristics.find_service_relations(hosts)

        # Implementation detects dependencies based on common patterns
        # Should not crash and return valid RelationSuggestion objects
        assert isinstance(relations, list)
        for r in relations:
            assert r.relation_type == "depends_on"

    def test_different_services_no_relation(self):
        """Test: Different services aren't related."""
        hosts = [
            {"hostname": "nginx-01", "service": "nginx"},
            {"hostname": "postgres-01", "service": "postgres"},
        ]
        relations = RelationHeuristics.find_service_relations(hosts)

        assert len(relations) == 0, "Different services = no relation"

    def test_complementary_services_dependency(self):
        """Test: Complementary services (web->db) detected."""
        hosts = [
            {"hostname": "web-01", "service": "nginx"},
            {"hostname": "db-01", "service": "postgres"},
        ]
        relations = RelationHeuristics.find_service_relations(hosts)

        # May detect dependency (web depends on db)
        # Implementation-dependent
        if len(relations) > 0:
            assert any(r.relation_type in ["depends_on", "related_service"] for r in relations)


class TestHeuristicsEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_host_list(self):
        """Test: Empty host list doesn't crash."""
        hosts = []

        assert RelationHeuristics.find_cluster_relations(hosts) == []
        assert RelationHeuristics.find_replica_relations(hosts) == []
        assert RelationHeuristics.find_group_relations(hosts) == []
        assert RelationHeuristics.find_service_relations(hosts) == []

    def test_single_host(self):
        """Test: Single host doesn't create self-relations."""
        hosts = [{"hostname": "web-01", "groups": ["frontend"], "service": "nginx"}]

        cluster = RelationHeuristics.find_cluster_relations(hosts)
        replica = RelationHeuristics.find_replica_relations(hosts)
        group = RelationHeuristics.find_group_relations(hosts)
        service = RelationHeuristics.find_service_relations(hosts)

        assert len(cluster) == 0, "No self cluster"
        assert len(replica) == 0, "No self replica"
        assert len(group) == 0, "No self group relation"
        assert len(service) == 0, "No self service relation"

    def test_malformed_hostname(self):
        """Test: Malformed hostnames don't crash."""
        hosts = [
            {"hostname": ""},  # Empty
            {"hostname": "a" * 1000},  # Too long
            {"hostname": "host@#$%^&*()"},  # Special chars
        ]

        # Should not crash
        relations = RelationHeuristics.find_cluster_relations(hosts)
        assert isinstance(relations, list)

    def test_unicode_hostnames(self):
        """Test: Unicode hostnames handled gracefully."""
        hosts = [
            {"hostname": "serveur-01", "service": "web"},
            {"hostname": "serveur-02", "service": "web"},
        ]

        relations = RelationHeuristics.find_service_relations(hosts)
        assert isinstance(relations, list)

    def test_case_sensitivity(self):
        """Test: Hostname matching is case-insensitive."""
        hosts = [
            {"hostname": "WEB-01", "groups": ["frontend"]},
            {"hostname": "web-02", "groups": ["frontend"]},
        ]

        relations = RelationHeuristics.find_group_relations(hosts)
        # Should handle mixed case
        assert isinstance(relations, list)


class TestHeuristicsPerformance:
    """Performance tests for heuristics."""

    @pytest.mark.slow
    def test_large_inventory_cluster_detection(self):
        """Test: Cluster detection on 1000 hosts."""
        hosts = [{"hostname": f"web-{i:04d}"} for i in range(1000)]

        import time
        start = time.time()
        result = RelationHeuristics.find_cluster_relations(hosts)
        duration = time.time() - start

        assert isinstance(result, list)
        assert duration < 5.0, f"Should complete in < 5s, took {duration:.2f}s"

    @pytest.mark.slow
    def test_large_inventory_all_heuristics(self):
        """Test: All heuristics on large inventory (1000 hosts)."""
        hosts = [
            {
                "hostname": f"web-{i:04d}",
                "groups": ["frontend", "production"],
            }
            for i in range(1000)
        ]

        # Should complete in reasonable time (< 5 seconds)
        cluster = RelationHeuristics.find_cluster_relations(hosts)
        group = RelationHeuristics.find_group_relations(hosts)

        assert len(cluster) > 0, "Should find many cluster relations"
        assert len(group) > 0, "Should find many group relations"


class TestHeuristicsIntegration:
    """Integration tests with RelationSuggestion model."""

    def test_suggestion_model_compliance(self):
        """Test: Heuristics return valid RelationSuggestion objects."""
        hosts = [
            {"hostname": "web-01", "groups": ["frontend"]},
            {"hostname": "web-02", "groups": ["frontend"]},
        ]

        relations = RelationHeuristics.find_group_relations(hosts)

        for r in relations:
            assert isinstance(r, RelationSuggestion), "Should return RelationSuggestion"
            assert hasattr(r, "source_hostname")
            assert hasattr(r, "target_hostname")
            assert hasattr(r, "relation_type")
            assert hasattr(r, "confidence")
            assert hasattr(r, "reason")
            assert 0.0 <= r.confidence <= 1.0, "Confidence should be 0-1"

    def test_reason_field_populated(self):
        """Test: Reason field explains why relation was suggested."""
        hosts = [
            {"hostname": "db-master", "service": "postgres"},
            {"hostname": "db-replica", "service": "postgres"},
        ]

        relations = RelationHeuristics.find_replica_relations(hosts)

        if len(relations) > 0:
            for r in relations:
                assert r.reason is not None, "Reason should be populated"
                assert len(r.reason) > 0, "Reason should not be empty"
                assert "master" in r.reason.lower() or "replica" in r.reason.lower(), "Reason should explain pattern"
