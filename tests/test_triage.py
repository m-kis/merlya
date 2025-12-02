"""
Tests for the Triage System.

Tests priority classification, signal detection, and behavior profiles.
"""

import pytest

from merlya.triage import (
    BEHAVIOR_PROFILES,
    BehaviorProfile,
    Intent,
    Priority,
    PriorityClassifier,
    PriorityResult,
    TriageResult,
    classify_priority,
    describe_behavior,
    get_behavior,
    get_classifier,
    get_smart_classifier,
    reset_smart_classifier,
)
from merlya.triage.signals import SignalDetector


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


class TestIntent:
    """Tests for Intent enum."""

    def test_intent_values(self):
        """Intent should have expected values."""
        assert Intent.QUERY.value == "query"
        assert Intent.ACTION.value == "action"
        assert Intent.ANALYSIS.value == "analysis"

    def test_query_intent_has_restricted_tools(self):
        """QUERY intent should restrict tools to read-only operations."""
        allowed = Intent.QUERY.allowed_tools
        assert allowed is not None
        # Host info tools
        assert "list_hosts" in allowed
        assert "get_infrastructure_context" in allowed
        assert "scan_host" in allowed
        # File reading tools
        assert "read_remote_file" in allowed
        assert "tail_logs" in allowed
        assert "grep_files" in allowed
        # System info tools
        assert "disk_info" in allowed
        assert "memory_info" in allowed
        # Interaction tools
        assert "request_elevation" in allowed
        assert "ask_user" in allowed
        # Write/dangerous tools should NOT be in QUERY
        assert "write_remote_file" not in allowed
        assert "execute_command" not in allowed
        assert "service_control" not in allowed

    def test_action_intent_allows_all_tools(self):
        """ACTION intent should allow all tools."""
        assert Intent.ACTION.allowed_tools is None

    def test_analysis_intent_allows_all_tools(self):
        """ANALYSIS intent should allow all tools."""
        assert Intent.ANALYSIS.allowed_tools is None


class TestTriageResult:
    """Tests for TriageResult dataclass."""

    def test_triage_result_creation(self):
        """TriageResult should be creatable."""
        result = TriageResult(
            priority=Priority.P1,
            intent=Intent.ACTION,
            confidence=0.85,
            signals=["P1:degraded"],
            reasoning="Service degraded",
        )
        assert result.priority == Priority.P1
        assert result.intent == Intent.ACTION
        assert result.confidence == 0.85

    def test_triage_result_response_time(self):
        """TriageResult should provide response time."""
        result = TriageResult(
            priority=Priority.P0,
            intent=Intent.ACTION,
            confidence=0.9,
        )
        assert result.suggested_response_time == 60  # P0 = 1 minute

    def test_triage_result_allowed_tools(self):
        """TriageResult should delegate allowed_tools to intent."""
        result_query = TriageResult(
            priority=Priority.P3,
            intent=Intent.QUERY,
            confidence=0.8,
        )
        assert result_query.allowed_tools is not None
        assert "list_hosts" in result_query.allowed_tools

        result_action = TriageResult(
            priority=Priority.P3,
            intent=Intent.ACTION,
            confidence=0.8,
        )
        assert result_action.allowed_tools is None

    def test_triage_result_to_dict(self):
        """TriageResult should serialize to dict."""
        result = TriageResult(
            priority=Priority.P2,
            intent=Intent.ANALYSIS,
            confidence=0.75,
            signals=["analysis:diagnose"],
            reasoning="Deep investigation needed",
        )
        d = result.to_dict()
        assert d["priority"] == "P2"
        assert d["priority_label"] == "IMPORTANT"
        assert d["intent"] == "analysis"
        assert d["confidence"] == 0.75
        assert "analysis:diagnose" in d["signals"]

    def test_triage_result_str(self):
        """TriageResult should have string representation."""
        result = TriageResult(
            priority=Priority.P1,
            intent=Intent.ACTION,
            confidence=0.9,
            signals=["P1:degraded", "action:restart"],
        )
        s = str(result)
        assert "P1" in s
        assert "URGENT" in s
        assert "action" in s
        assert "90%" in s


class TestIntentDetection:
    """Tests for intent detection in SignalDetector."""

    def setup_method(self):
        self.detector = SignalDetector()

    def test_query_intent_detection_english(self):
        """QUERY intent should be detected for information requests (English)."""
        test_cases = [
            "what are my servers",
            "list hosts",
            "show me the services",
            "how many containers are running?",
            "where is the database?",
        ]
        for query in test_cases:
            intent, confidence, signals = self.detector.detect_intent(query)
            assert intent == Intent.QUERY, f"Failed for: {query}"
            assert confidence >= 0.6

    def test_query_intent_detection_french(self):
        """QUERY intent should be detected for information requests (French)."""
        test_cases = [
            "quels sont mes serveurs",
            "liste les hosts",
            "montre moi les services",
            "combien de conteneurs",
        ]
        for query in test_cases:
            intent, confidence, signals = self.detector.detect_intent(query)
            assert intent == Intent.QUERY, f"Failed for: {query}"

    def test_action_intent_detection(self):
        """ACTION intent should be detected for commands."""
        test_cases = [
            "restart nginx",
            "check the disk space",
            "deploy the application",
            "stop the container",
            "install package",
        ]
        for query in test_cases:
            intent, confidence, signals = self.detector.detect_intent(query)
            assert intent == Intent.ACTION, f"Failed for: {query}"

    def test_analysis_intent_detection(self):
        """ANALYSIS intent should be detected for investigations."""
        test_cases = [
            "analyze the performance",
            "why is the service slow",
            "diagnose the problem",
            "troubleshoot the error",
            "investigate the logs",
        ]
        for query in test_cases:
            intent, confidence, signals = self.detector.detect_intent(query)
            assert intent == Intent.ANALYSIS, f"Failed for: {query}"

    def test_question_mark_detection(self):
        """Question mark at end should boost QUERY intent."""
        query = "is nginx running?"
        intent, confidence, signals = self.detector.detect_intent(query)
        assert intent == Intent.QUERY
        assert "?" in signals or any("?" in s for s in signals)

    def test_question_mark_in_middle_not_detected(self):
        """Question mark in middle should not trigger query detection."""
        # This tests that we use endswith("?") not "?" in text
        query = "fix the error? restart the service"
        intent, confidence, signals = self.detector.detect_intent(query)
        # Should be ACTION because "restart" and "fix" are action keywords
        assert intent == Intent.ACTION

    def test_default_to_action(self):
        """Ambiguous queries should default to ACTION."""
        query = "hello world"  # No keywords
        intent, confidence, signals = self.detector.detect_intent(query)
        assert intent == Intent.ACTION
        assert confidence == 0.5


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

    def test_p3_standard_mode(self):
        """P3 should have standard mode settings with autonomous reads."""
        p3 = BEHAVIOR_PROFILES[Priority.P3]
        assert p3.max_analysis_time_seconds == 300
        assert p3.use_chain_of_thought is True
        assert p3.auto_confirm_reads is True  # Autonomous for reads
        assert p3.confirmation_mode == "writes_only"  # Only confirm writes
        assert p3.response_format == "detailed"

    def test_should_confirm(self):
        """should_confirm should respect confirmation_mode."""
        p0 = BEHAVIOR_PROFILES[Priority.P0]
        p3 = BEHAVIOR_PROFILES[Priority.P3]

        # P0: critical_only
        assert p0.should_confirm(is_write=False, is_critical=False) is False
        assert p0.should_confirm(is_write=True, is_critical=True) is True

        # P3: writes_only - autonomous for reads, confirm writes
        assert p3.should_confirm(is_write=False, is_critical=False) is False  # Reads don't need confirmation
        assert p3.should_confirm(is_write=True, is_critical=False) is True  # Writes need confirmation
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
        assert behavior.auto_confirm_reads is True  # P3 now auto-confirms reads
        assert behavior.confirmation_mode == "writes_only"  # Only writes need confirmation

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


class TestSmartTriageClassifier:
    """Tests for SmartTriageClassifier."""

    def setup_method(self):
        # Reset classifier to get fresh instance
        reset_smart_classifier()
        # Get classifier without DB (uses in-memory only)
        self.classifier = get_smart_classifier(db_client=None, user_id="test")

    def teardown_method(self):
        reset_smart_classifier()

    def test_classifier_creation(self):
        """SmartTriageClassifier should be creatable without DB."""
        assert self.classifier is not None

    def test_classify_returns_intent_and_priority(self):
        """classify() should return (Intent, PriorityResult)."""
        intent, priority_result = self.classifier.classify("list my servers")
        assert isinstance(intent, Intent)
        assert isinstance(priority_result, PriorityResult)

    def test_classify_query_intent(self):
        """classify() should detect QUERY intent."""
        intent, _ = self.classifier.classify("what servers do I have?")
        assert intent == Intent.QUERY

    def test_classify_action_intent(self):
        """classify() should detect ACTION intent."""
        intent, _ = self.classifier.classify("restart the nginx service")
        assert intent == Intent.ACTION

    def test_classify_analysis_intent(self):
        """classify() should detect ANALYSIS intent."""
        intent, _ = self.classifier.classify("why is the database slow")
        assert intent == Intent.ANALYSIS

    def test_provide_feedback_without_db(self):
        """provide_feedback() should return False without DB."""
        # Without FalkorDB, feedback cannot be stored
        success = self.classifier.provide_feedback(
            "test query",
            Intent.QUERY,
            Priority.P3,
        )
        assert success is False  # No DB available

    def test_get_stats(self):
        """get_stats() should return statistics dict."""
        stats = self.classifier.get_stats()
        assert "embeddings_available" in stats
        assert "pattern_store" in stats

    def test_singleton_pattern(self):
        """get_smart_classifier should return same instance for same params."""
        c1 = get_smart_classifier(db_client=None, user_id="test")
        c2 = get_smart_classifier(db_client=None, user_id="test")
        assert c1 is c2

    def test_different_users_different_classifiers(self):
        """Different user_ids should get different classifiers."""
        c1 = get_smart_classifier(db_client=None, user_id="user1")
        c2 = get_smart_classifier(db_client=None, user_id="user2")
        assert c1 is not c2

    def test_force_new_creates_new_instance(self):
        """force_new=True should create new instance."""
        c1 = get_smart_classifier(db_client=None, user_id="test")
        c2 = get_smart_classifier(db_client=None, user_id="test", force_new=True)
        assert c1 is not c2

    def test_reset_clears_all(self):
        """reset_smart_classifier() should clear all instances."""
        get_smart_classifier(db_client=None, user_id="user1")
        get_smart_classifier(db_client=None, user_id="user2")
        reset_smart_classifier()
        # After reset, new calls should create new instances
        c1 = get_smart_classifier(db_client=None, user_id="user1")
        assert c1 is not None

    def test_reset_specific_user(self):
        """reset_smart_classifier(user_id) should clear only that user."""
        _ = get_smart_classifier(db_client=None, user_id="user1")
        c2 = get_smart_classifier(db_client=None, user_id="user2")
        reset_smart_classifier(user_id="user1")
        # user2 should still be cached
        c2_new = get_smart_classifier(db_client=None, user_id="user2")
        assert c2 is c2_new


class TestIntegrationWithIntent:
    """Integration tests for intent + priority classification."""

    def test_full_triage_with_intent(self):
        """Test complete triage with intent detection."""
        detector = SignalDetector()

        # Query intent with low priority
        intent, _, _ = detector.detect_intent("list my hosts")
        priority, _, _ = detector.detect_keywords("list my hosts")
        assert intent == Intent.QUERY
        assert priority == Priority.P3

        # Action intent with production escalation
        intent, _, _ = detector.detect_intent("restart nginx on prod")
        priority, _, _ = detector.detect_keywords("restart nginx on prod")
        assert intent == Intent.ACTION
        # prod environment should have been detected
        env, mult, min_p = detector.detect_environment("restart nginx on prod")
        assert env == "prod"
        assert min_p == Priority.P1

        # Analysis intent with critical issue
        intent, _, _ = detector.detect_intent("why is production down")
        priority, _, _ = detector.detect_keywords("why is production down")
        assert intent == Intent.ANALYSIS
        assert priority == Priority.P0  # "down" is P0 keyword


class TestErrorAnalyzer:
    """Tests for ErrorAnalyzer semantic error classification."""

    def setup_method(self):
        from merlya.triage import ErrorType, get_error_analyzer
        self.analyzer = get_error_analyzer(force_new=True)
        self.ErrorType = ErrorType

    def test_analyzer_creation(self):
        """ErrorAnalyzer should be creatable."""
        assert self.analyzer is not None

    def test_credential_error_detection(self):
        """Should detect credential/authentication errors."""
        credential_errors = [
            "Permission denied (publickey,password)",
            "Authentication failed",
            "password authentication failed for user",
            "Access denied for user 'admin'",
            "Invalid API key",
        ]
        for error in credential_errors:
            analysis = self.analyzer.analyze(error)
            assert analysis.error_type == self.ErrorType.CREDENTIAL, f"Failed for: {error}"
            assert analysis.needs_credentials is True
            assert analysis.confidence >= 0.6

    def test_connection_error_detection(self):
        """Should detect connection/network errors."""
        connection_errors = [
            "Connection refused",
            "Connection timed out",
            "No route to host",
            "Network is unreachable",
            "Could not resolve hostname",
        ]
        for error in connection_errors:
            analysis = self.analyzer.analyze(error)
            assert analysis.error_type == self.ErrorType.CONNECTION, f"Failed for: {error}"
            assert analysis.needs_credentials is False
            assert analysis.confidence >= 0.6

    def test_permission_error_detection(self):
        """Should detect permission errors."""
        permission_errors = [
            "Permission denied",
            "Operation not permitted",
            "Insufficient privileges",
            "403 Forbidden",
        ]
        for error in permission_errors:
            analysis = self.analyzer.analyze(error)
            assert analysis.error_type == self.ErrorType.PERMISSION, f"Failed for: {error}"
            assert analysis.needs_credentials is False

    def test_not_found_error_detection(self):
        """Should detect not found errors."""
        not_found_errors = [
            "No such file or directory",
            "File not found",
            "Command not found",
            "404 Not Found",
        ]
        for error in not_found_errors:
            analysis = self.analyzer.analyze(error)
            assert analysis.error_type == self.ErrorType.NOT_FOUND, f"Failed for: {error}"

    def test_timeout_error_detection(self):
        """Should detect timeout errors."""
        timeout_errors = [
            "Timed out",
            "Operation timed out",
            "Request timeout",
            "504 Gateway Timeout",
        ]
        for error in timeout_errors:
            analysis = self.analyzer.analyze(error)
            assert analysis.error_type == self.ErrorType.TIMEOUT, f"Failed for: {error}"

    def test_resource_error_detection(self):
        """Should detect resource exhaustion errors."""
        resource_errors = [
            "No space left on device",
            "Out of memory",
            "Cannot allocate memory",
            "Too many open files",
        ]
        for error in resource_errors:
            analysis = self.analyzer.analyze(error)
            assert analysis.error_type == self.ErrorType.RESOURCE, f"Failed for: {error}"

    def test_empty_error_returns_unknown(self):
        """Empty error should return UNKNOWN."""
        analysis = self.analyzer.analyze("")
        assert analysis.error_type == self.ErrorType.UNKNOWN
        assert analysis.confidence == 0.0

    def test_analysis_returns_suggested_action(self):
        """Analysis should include suggested action."""
        analysis = self.analyzer.analyze("Authentication failed")
        assert analysis.suggested_action is not None
        assert len(analysis.suggested_action) > 0

    def test_needs_credentials_helper(self):
        """needs_credentials() helper should work."""
        assert self.analyzer.needs_credentials("Authentication failed") is True
        assert self.analyzer.needs_credentials("Connection refused") is False

    def test_get_error_type_helper(self):
        """get_error_type() helper should work."""
        error_type = self.analyzer.get_error_type("Permission denied (publickey)")
        assert error_type == self.ErrorType.CREDENTIAL


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
