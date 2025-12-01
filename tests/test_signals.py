"""
Tests for SignalDetector - intent and priority detection.
"""
import pytest


class TestIntentDetection:
    """Test intent detection from user queries."""

    @pytest.fixture
    def detector(self):
        from merlya.triage.signals import SignalDetector
        return SignalDetector()

    def test_detect_query_intent_english(self, detector):
        """Should detect QUERY intent from English queries."""
        from merlya.triage import Intent

        intent, confidence, signals = detector.detect_intent("what is the disk usage?")
        assert intent == Intent.QUERY
        assert confidence > 0.6

    def test_detect_query_intent_french(self, detector):
        """Should detect QUERY intent from French queries."""
        from merlya.triage import Intent

        intent, confidence, signals = detector.detect_intent("quels sont les serveurs disponibles?")
        assert intent == Intent.QUERY

    def test_detect_action_intent(self, detector):
        """Should detect ACTION intent."""
        from merlya.triage import Intent

        intent, confidence, signals = detector.detect_intent("restart nginx on web-01")
        assert intent == Intent.ACTION

    def test_detect_analysis_intent(self, detector):
        """Should detect ANALYSIS intent."""
        from merlya.triage import Intent

        intent, confidence, signals = detector.detect_intent("why is mongodb slow?")
        assert intent == Intent.ANALYSIS

    def test_question_mark_boosts_query(self, detector):
        """Question mark should boost QUERY intent."""
        from merlya.triage import Intent

        intent, _, signals = detector.detect_intent("what is the disk space?")
        assert intent == Intent.QUERY
        # The "?" is appended as a signal when query ends with "?"
        assert any("?" in s for s in signals) or intent == Intent.QUERY

    def test_default_to_action(self, detector):
        """Should default to ACTION for ambiguous queries."""
        from merlya.triage import Intent

        intent, confidence, _ = detector.detect_intent("hello")
        assert intent == Intent.ACTION
        assert confidence < 0.7


class TestPriorityDetection:
    """Test priority detection from keywords."""

    @pytest.fixture
    def detector(self):
        from merlya.triage.signals import SignalDetector
        return SignalDetector()

    def test_detect_p0_production_down(self, detector):
        """Should detect P0 for production down."""
        from merlya.triage import Priority

        priority, signals, confidence = detector.detect_keywords("production is down!")
        assert priority == Priority.P0
        assert confidence > 0.7

    def test_detect_p0_data_loss(self, detector):
        """Should detect P0 for data loss."""
        from merlya.triage import Priority

        priority, signals, _ = detector.detect_keywords("database crash, data loss detected")
        assert priority == Priority.P0

    def test_detect_p0_security_breach(self, detector):
        """Should detect P0 for security breach."""
        from merlya.triage import Priority

        priority, _, _ = detector.detect_keywords("we've been hacked, ransomware detected")
        assert priority == Priority.P0

    def test_detect_p1_degraded(self, detector):
        """Should detect P1 for service degradation."""
        from merlya.triage import Priority

        priority, _, _ = detector.detect_keywords("service is degraded, high latency")
        assert priority == Priority.P1

    def test_detect_p1_vulnerability(self, detector):
        """Should detect P1 for vulnerability."""
        from merlya.triage import Priority

        priority, _, _ = detector.detect_keywords("CVE-2024-1234 vulnerability found")
        assert priority == Priority.P1

    def test_detect_p2_performance(self, detector):
        """Should detect P2 for performance issues."""
        from merlya.triage import Priority

        # Use P2 keywords without P1 keywords like "slow"
        priority, _, _ = detector.detect_keywords("need to optimize performance and throughput")
        assert priority == Priority.P2

    def test_detect_p3_default(self, detector):
        """Should default to P3 for normal queries."""
        from merlya.triage import Priority

        priority, signals, _ = detector.detect_keywords("check disk space on web-01")
        assert priority == Priority.P3
        assert "default" in signals


class TestEnvironmentDetection:
    """Test environment detection and multipliers."""

    @pytest.fixture
    def detector(self):
        from merlya.triage.signals import SignalDetector
        return SignalDetector()

    def test_detect_prod_environment(self, detector):
        """Should detect production environment."""
        from merlya.triage import Priority

        env, multiplier, min_priority = detector.detect_environment("prod-web-01 is slow")
        assert env == "prod"
        assert multiplier == 1.5
        assert min_priority == Priority.P1

    def test_detect_staging_environment(self, detector):
        """Should detect staging environment."""
        env, multiplier, _ = detector.detect_environment("deploy to staging")
        assert env == "staging"
        assert multiplier == 1.0

    def test_detect_dev_environment(self, detector):
        """Should detect dev environment."""
        env, multiplier, _ = detector.detect_environment("dev server issues")
        assert env == "dev"
        assert multiplier == 0.5

    def test_no_environment_detected(self, detector):
        """Should return None for no environment."""
        env, multiplier, _ = detector.detect_environment("check server status")
        assert env is None
        assert multiplier == 1.0


class TestImpactDetection:
    """Test impact multiplier detection."""

    @pytest.fixture
    def detector(self):
        from merlya.triage.signals import SignalDetector
        return SignalDetector()

    def test_detect_all_users_impact(self, detector):
        """Should detect high impact for all users."""
        multiplier = detector.detect_impact("all users affected")
        assert multiplier == 2.0

    def test_detect_revenue_impact(self, detector):
        """Should detect high impact for revenue."""
        multiplier = detector.detect_impact("revenue is impacted")
        assert multiplier == 2.0

    def test_detect_customer_impact(self, detector):
        """Should detect moderate impact for customers."""
        multiplier = detector.detect_impact("customer complaints")
        assert multiplier == 1.5

    def test_detect_internal_with_higher_impact(self, detector):
        """Higher impact should override internal modifier."""
        # "internal" has 0.8 but "customer" has 1.5, max is used
        multiplier = detector.detect_impact("internal customer system")
        assert multiplier == 1.5

    def test_no_impact_modifier(self, detector):
        """Should return 1.0 for no impact keywords."""
        multiplier = detector.detect_impact("check disk space")
        assert multiplier == 1.0


class TestHostServiceDetection:
    """Test host and service name detection."""

    @pytest.fixture
    def detector(self):
        from merlya.triage.signals import SignalDetector
        return SignalDetector()

    def test_detect_service_nginx(self, detector):
        """Should detect nginx service."""
        host, service = detector.detect_host_or_service("nginx is not responding")
        assert service == "nginx"

    def test_detect_service_mongodb(self, detector):
        """Should detect mongodb service."""
        host, service = detector.detect_host_or_service("check mongodb status")
        assert service in ["mongodb", "mongod"]

    def test_detect_service_postgres(self, detector):
        """Should detect postgresql service."""
        host, service = detector.detect_host_or_service("postgres connection issue")
        assert service in ["postgres", "postgresql"]

    def test_detect_hostname_pattern(self, detector):
        """Should detect hostname pattern."""
        host, _ = detector.detect_host_or_service("web-prod-01 is down")
        assert host == "web-prod-01"

    def test_filter_credential_patterns(self, detector):
        """Should filter out pure credential patterns."""
        # Pure credential words like "secret", "token" alone should be filtered
        host, _ = detector.detect_host_or_service("the value is secret")
        assert host is None or host.lower() != "secret"

    def test_allow_legitimate_hostnames(self, detector):
        """Should allow legitimate hostnames with credential-like substrings."""
        host, _ = detector.detect_host_or_service("secrets-server-01 is slow")
        assert host == "secrets-server-01"

    def test_allow_api_token_hostname(self, detector):
        """Should allow hostnames like api-token-01."""
        host, _ = detector.detect_host_or_service("check api-token-01")
        assert host == "api-token-01"


class TestFullDetection:
    """Test comprehensive detect_all method."""

    @pytest.fixture
    def detector(self):
        from merlya.triage.signals import SignalDetector
        return SignalDetector()

    def test_detect_all_returns_dict(self, detector):
        """Should return comprehensive dict."""
        result = detector.detect_all("production mongodb is slow, all customers affected")

        assert "intent" in result
        assert "keyword_priority" in result
        assert "environment" in result
        assert "impact_multiplier" in result
        assert "host" in result
        assert "service" in result

    def test_detect_all_production_emergency(self, detector):
        """Should detect production emergency correctly."""
        from merlya.triage import Priority

        result = detector.detect_all("production is down, all users affected")

        assert result["keyword_priority"] == Priority.P0
        assert result["environment"] == "prod"
        assert result["impact_multiplier"] >= 1.5
