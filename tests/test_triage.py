"""
Tests for the Triage System.

Tests priority classification, signal detection, and behavior profiles.
"""

import pytest

from athena_ai.triage import (
    BEHAVIOR_PROFILES,
    BehaviorProfile,
    Priority,
    PriorityClassifier,
    PriorityResult,
    classify_priority,
    describe_behavior,
    get_behavior,
    get_classifier,
)
from athena_ai.triage.signals import SignalDetector


class TestPriority:
    """Tests for Priority enum."""

    def test_priority_values(self):
        """P0 is highest priority (lowest value)."""
        assert Priority.P0 < Priority.P1 < Priority.P2 < Priority.P3
        assert Priority.P0.value == 0
        assert Priority.P3.value == 3

    def test_priority_labels(self):
        """Each priority has a label."""
        assert Priority.P0.label == "CRITICAL"
        assert Priority.P1.label == "URGENT"
        assert Priority.P2.label == "IMPORTANT"
        assert Priority.P3.label == "NORMAL"

    def test_priority_colors(self):
        """Each priority has a color for UI."""
        # Each priority has a rich color string
        assert "red" in Priority.P0.color
        assert "yellow" in Priority.P1.color
        assert Priority.P2.color  # Has some color
        assert Priority.P3.color  # Has some color


class TestSignalDetector:
    """Tests for SignalDetector."""

    def setup_method(self):
        self.detector = SignalDetector()

    def test_p0_keyword_detection(self):
        """P0 keywords should be detected."""
        test_cases = [
            "MongoDB is down",
            "Production outage in progress",
            "Data loss detected on disk",
            "Security breach detected",
            "Ransomware attack in progress",
        ]
        for query in test_cases:
            priority, signals, confidence = self.detector.detect_keywords(query)
            assert priority == Priority.P0, f"Failed for: {query}"
            assert len(signals) > 0
            assert confidence >= 0.7

    def test_p1_keyword_detection(self):
        """P1 keywords should be detected."""
        test_cases = [
            "High latency on API",
            "Service degraded",
            "CVE-2024-1234 vulnerability found",
            "OOM killer triggered",
            "Certificate expiring soon",
        ]
        for query in test_cases:
            priority, signals, confidence = self.detector.detect_keywords(query)
            assert priority == Priority.P1, f"Failed for: {query}"

    def test_p2_keyword_detection(self):
        """P2 keywords should be detected."""
        test_cases = [
            "Need to optimize performance",
            "High CPU usage on server",
            "Replica lag increasing",
            "Cache miss rate high",
        ]
        for query in test_cases:
            priority, signals, confidence = self.detector.detect_keywords(query)
            assert priority == Priority.P2, f"Failed for: {query}"

    def test_p3_default(self):
        """Unknown queries should default to P3."""
        test_cases = [
            "Check nginx config",
            "List users on server",
            "Show disk usage",
            "What version is installed",
        ]
        for query in test_cases:
            priority, signals, confidence = self.detector.detect_keywords(query)
            assert priority == Priority.P3, f"Failed for: {query}"

    def test_environment_detection_prod(self):
        """Production environment should be detected."""
        test_cases = [
            "Issue on prod server",
            "production database slow",
            "prd-db-01 not responding",
            "live server down",
        ]
        for query in test_cases:
            env, mult, min_priority = self.detector.detect_environment(query)
            assert env == "prod", f"Failed for: {query}"
            assert mult == 1.5
            assert min_priority == Priority.P1

    def test_environment_detection_staging(self):
        """Staging environment should be detected."""
        test_cases = [
            "Issue on staging server",
            "stg-api-01 failing",
            "UAT environment broken",
            "preprod database issue",
        ]
        for query in test_cases:
            env, mult, min_priority = self.detector.detect_environment(query)
            assert env in ("staging", "preprod"), f"Failed for: {query}"

    def test_environment_detection_dev(self):
        """Dev environment should be detected."""
        test_cases = [
            "Issue on dev server",
            "local machine failing",
            "test environment issue",
        ]
        for query in test_cases:
            env, mult, min_priority = self.detector.detect_environment(query)
            assert env in ("dev", "test"), f"Failed for: {query}"

    def test_impact_detection(self):
        """Impact amplifiers should be detected."""
        high_impact = [
            "All users affected",
            "Revenue impacting issue",
            "Business critical system down",
            "Emergency situation",
        ]
        for query in high_impact:
            multiplier = self.detector.detect_impact(query)
            assert multiplier >= 1.5, f"Failed for: {query}"

        low_impact = [
            "Internal tool issue",
            "Simple question",
        ]
        for query in low_impact:
            multiplier = self.detector.detect_impact(query)
            assert multiplier <= 1.0, f"Failed for: {query}"

    def test_service_detection(self):
        """Services should be detected from query."""
        test_cases = [
            ("nginx not responding", "nginx"),
            ("MySQL query slow", "mysql"),
            ("MongoDB connection issues", "mongodb"),
            ("Redis cache timeout", "redis"),
            ("Docker container failing", "docker"),
            ("Kubernetes pod crashloop", "kubernetes"),
        ]
        for query, expected_service in test_cases:
            host, service = self.detector.detect_host_or_service(query)
            assert service == expected_service, f"Failed for: {query}"


class TestPriorityClassifier:
    """Tests for PriorityClassifier."""

    def setup_method(self):
        self.classifier = PriorityClassifier()

    def test_critical_production_down(self):
        """Production down should be P0."""
        result = self.classifier.classify("MongoDB is down on prod-db-01")
        assert result.priority == Priority.P0
        assert result.confidence >= 0.79  # Allow floating point tolerance
        assert result.escalation_required is True
        assert result.environment_detected == "prod"
        assert result.service_detected == "mongodb"

    def test_urgent_with_staging(self):
        """Staging issues should be at least P1."""
        result = self.classifier.classify("High latency on staging API server")
        assert result.priority in (Priority.P0, Priority.P1)
        assert result.environment_detected == "staging"

    def test_normal_maintenance(self):
        """Normal maintenance should be P3."""
        result = self.classifier.classify("Check nginx configuration on web-server")
        assert result.priority == Priority.P3
        assert result.escalation_required is False

    def test_production_escalation(self):
        """Production issues should escalate priority."""
        # Normal query becomes P1 in production
        result = self.classifier.classify("Check logs on production server")
        assert result.priority <= Priority.P1
        assert result.environment_detected == "prod"

    def test_system_state_override(self):
        """System state should override keyword detection."""
        # Host unreachable should always be P0
        result = self.classifier.classify(
            "Check disk usage",
            system_state={"host_accessible": False}
        )
        assert result.priority == Priority.P0

        # High disk should be P1
        result = self.classifier.classify(
            "Check server status",
            system_state={"disk_usage_percent": 96}
        )
        assert result.priority == Priority.P1

    def test_classification_count(self):
        """Classification count should increment."""
        initial_count = self.classifier.classification_count
        self.classifier.classify("Test query 1")
        self.classifier.classify("Test query 2")
        assert self.classifier.classification_count == initial_count + 2


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_classify_priority(self):
        """classify_priority should work as convenience function."""
        result = classify_priority("MongoDB down on production")
        assert isinstance(result, PriorityResult)
        assert result.priority == Priority.P0

    def test_get_classifier_singleton(self):
        """get_classifier should return singleton."""
        c1 = get_classifier()
        c2 = get_classifier()
        assert c1 is c2


class TestBehaviorProfiles:
    """Tests for BehaviorProfile."""

    def test_all_priorities_have_profiles(self):
        """Each priority should have a behavior profile."""
        for priority in Priority:
            assert priority in BEHAVIOR_PROFILES
            profile = BEHAVIOR_PROFILES[priority]
            assert isinstance(profile, BehaviorProfile)

    def test_p0_fast_mode(self):
        """P0 should have fast mode settings."""
        p0 = BEHAVIOR_PROFILES[Priority.P0]
        assert p0.max_analysis_time_seconds == 5
        assert p0.use_chain_of_thought is False
        assert p0.parallel_execution is True
        assert p0.auto_confirm_reads is True
        assert p0.response_format == "terse"

    def test_p3_careful_mode(self):
        """P3 should have careful mode settings."""
        p3 = BEHAVIOR_PROFILES[Priority.P3]
        assert p3.max_analysis_time_seconds == 300
        assert p3.use_chain_of_thought is True
        assert p3.auto_confirm_reads is False
        assert p3.confirmation_mode == "all"
        assert p3.response_format == "detailed"

    def test_should_confirm(self):
        """should_confirm should respect confirmation_mode."""
        p0 = BEHAVIOR_PROFILES[Priority.P0]
        p3 = BEHAVIOR_PROFILES[Priority.P3]

        # P0: critical_only
        assert p0.should_confirm(is_write=False, is_critical=False) is False
        assert p0.should_confirm(is_write=True, is_critical=True) is True

        # P3: all
        assert p3.should_confirm(is_write=False, is_critical=False) is True
        assert p3.should_confirm(is_write=True, is_critical=True) is True

    def test_get_behavior(self):
        """get_behavior should return correct profile."""
        for priority in Priority:
            profile = get_behavior(priority)
            assert profile == BEHAVIOR_PROFILES[priority]

    def test_describe_behavior(self):
        """describe_behavior should return string description."""
        for priority in Priority:
            desc = describe_behavior(priority)
            assert isinstance(desc, str)
            assert len(desc) > 0


class TestIntegration:
    """Integration tests for complete triage flow."""

    def test_full_triage_flow(self):
        """Test complete triage flow from query to behavior."""
        # Critical incident
        result = classify_priority("Production database down, all users affected")
        behavior = get_behavior(result.priority)

        assert result.priority == Priority.P0
        assert behavior.auto_confirm_reads is True
        assert behavior.response_format == "terse"

        # Normal request
        result = classify_priority("Show system status")
        behavior = get_behavior(result.priority)

        assert result.priority == Priority.P3
        assert behavior.auto_confirm_reads is False
        assert behavior.confirmation_mode == "all"

    def test_priority_result_fields(self):
        """PriorityResult should have all expected fields."""
        result = classify_priority("MongoDB down on prod-web-01")

        assert hasattr(result, 'priority')
        assert hasattr(result, 'confidence')
        assert hasattr(result, 'signals')
        assert hasattr(result, 'reasoning')
        assert hasattr(result, 'escalation_required')
        assert hasattr(result, 'detected_at')
        assert hasattr(result, 'environment_detected')
        assert hasattr(result, 'service_detected')
        assert hasattr(result, 'host_detected')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
