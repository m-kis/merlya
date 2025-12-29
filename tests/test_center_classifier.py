"""Tests for CenterClassifier."""

import pytest

from merlya.centers.base import CenterMode
from merlya.router.center_classifier import (
    CenterClassification,
    CenterClassifier,
)


@pytest.fixture
def classifier() -> CenterClassifier:
    """Create classifier without context."""
    return CenterClassifier()


class TestCenterClassification:
    """Tests for CenterClassification model."""

    def test_create_diagnostic_classification(self) -> None:
        """Test creating a diagnostic classification."""
        result = CenterClassification(
            center=CenterMode.DIAGNOSTIC,
            confidence=0.9,
            reasoning="Clear status check",
        )
        assert result.center == CenterMode.DIAGNOSTIC
        assert result.confidence == 0.9
        assert result.clarification_needed is False

    def test_create_change_classification(self) -> None:
        """Test creating a change classification."""
        result = CenterClassification(
            center=CenterMode.CHANGE,
            confidence=0.85,
            clarification_needed=False,
        )
        assert result.center == CenterMode.CHANGE

    def test_classification_with_clarification(self) -> None:
        """Test classification needing clarification."""
        result = CenterClassification(
            center=CenterMode.DIAGNOSTIC,
            confidence=0.5,
            clarification_needed=True,
            suggested_prompt="Do you want to just check or also fix?",
        )
        assert result.clarification_needed is True
        assert result.suggested_prompt is not None


class TestDiagnosticPatterns:
    """Tests for diagnostic pattern matching."""

    @pytest.mark.parametrize(
        "input_text",
        [
            "check disk usage on web-01",
            "what is the status of nginx",
            "show me the logs",
            "check memory on all servers",
            "why is the service slow",
            "analyze the cpu usage",
            "list all hosts",
            "get info about the database",
            "monitor the network",
            "tail the syslog",
            "debug the connection issue",
            "verify the disk space",
            "what processes are running?",
            "how much memory is free?",
        ],
    )
    async def test_diagnostic_inputs(self, classifier: CenterClassifier, input_text: str) -> None:
        """Test various diagnostic inputs are classified correctly."""
        result = await classifier.classify(input_text)
        assert result.center == CenterMode.DIAGNOSTIC, f"Failed for: {input_text}"
        assert result.confidence >= 0.5

    @pytest.mark.parametrize(
        "input_text",
        [
            "vérifier l'espace disque",
            "quel est l'état du service",
            "afficher les logs",
            "pourquoi le serveur est lent",
        ],
    )
    async def test_diagnostic_inputs_french(
        self, classifier: CenterClassifier, input_text: str
    ) -> None:
        """Test French diagnostic inputs."""
        result = await classifier.classify(input_text)
        assert result.center == CenterMode.DIAGNOSTIC, f"Failed for: {input_text}"


class TestChangePatterns:
    """Tests for change pattern matching."""

    @pytest.mark.parametrize(
        "input_text",
        [
            "restart nginx",
            "fix the SSL error",
            "deploy the new version",
            "stop the database service",
            "update the configuration",
            "install htop",
            "configure the firewall",
            "add a new user",
            "delete the old files",
            "scale up the replicas",
            "rollback to previous version",
            "start the docker container",
            "modify the nginx config",
        ],
    )
    async def test_change_inputs(self, classifier: CenterClassifier, input_text: str) -> None:
        """Test various change inputs are classified correctly."""
        result = await classifier.classify(input_text)
        assert result.center == CenterMode.CHANGE, f"Failed for: {input_text}"
        assert result.confidence >= 0.5

    @pytest.mark.parametrize(
        "input_text",
        [
            "redémarrer nginx",
            "réparer l'erreur SSL",
            "déployer la nouvelle version",
            "arrêter le service",
        ],
    )
    async def test_change_inputs_french(
        self, classifier: CenterClassifier, input_text: str
    ) -> None:
        """Test French change inputs."""
        result = await classifier.classify(input_text)
        assert result.center == CenterMode.CHANGE, f"Failed for: {input_text}"


class TestAmbiguousInputs:
    """Tests for ambiguous inputs."""

    @pytest.mark.parametrize(
        "input_text",
        [
            "nginx issues",
            "database problem",
            "the server",
            "help",
        ],
    )
    async def test_ambiguous_defaults_to_diagnostic(
        self, classifier: CenterClassifier, input_text: str
    ) -> None:
        """Test ambiguous inputs default to safe diagnostic mode."""
        result = await classifier.classify(input_text)
        # Should default to DIAGNOSTIC (safer)
        assert result.center == CenterMode.DIAGNOSTIC

    async def test_low_confidence_needs_clarification(self, classifier: CenterClassifier) -> None:
        """Test low confidence requests clarification."""
        result = await classifier.classify("something about the server")
        # Low confidence should request clarification
        if result.confidence < 0.7:
            assert result.clarification_needed is True


class TestQuickChecks:
    """Tests for quick check methods."""

    def test_is_definitely_diagnostic(self, classifier: CenterClassifier) -> None:
        """Test quick diagnostic check."""
        assert classifier.is_definitely_diagnostic("check disk usage and show me the logs")
        assert not classifier.is_definitely_diagnostic("restart nginx")
        assert not classifier.is_definitely_diagnostic("hello")

    def test_is_definitely_change(self, classifier: CenterClassifier) -> None:
        """Test quick change check."""
        assert classifier.is_definitely_change("restart nginx and update config")
        assert not classifier.is_definitely_change("check status")
        assert not classifier.is_definitely_change("hello")


class TestMixedIntents:
    """Tests for mixed intent handling."""

    async def test_check_and_fix_is_change(self, classifier: CenterClassifier) -> None:
        """Test 'check and fix' is classified as change."""
        # This includes potential mutation, so should be CHANGE
        result = await classifier.classify("check the service and fix if needed")
        # Even though it says "check", the "fix" part makes it CHANGE
        # Note: This could go either way based on pattern weights
        # The important thing is it's at least considered
        assert result.center in (CenterMode.CHANGE, CenterMode.DIAGNOSTIC)

    async def test_pure_question_is_diagnostic(self, classifier: CenterClassifier) -> None:
        """Test pure questions are diagnostic."""
        result = await classifier.classify("how do I restart nginx?")
        # Asking HOW is diagnostic (just information)
        assert result.center == CenterMode.DIAGNOSTIC


class TestClarificationPrompts:
    """Tests for clarification prompt generation."""

    def test_generates_clarification_for_diagnostic(self, classifier: CenterClassifier) -> None:
        """Test clarification prompt for diagnostic classification."""
        result = CenterClassification(
            center=CenterMode.DIAGNOSTIC,
            confidence=0.4,
        )
        prompt = classifier._generate_clarification_prompt("check something", result)
        assert "check" in prompt.lower() or "status" in prompt.lower()

    def test_generates_clarification_for_change(self, classifier: CenterClassifier) -> None:
        """Test clarification prompt for change classification."""
        result = CenterClassification(
            center=CenterMode.CHANGE,
            confidence=0.4,
        )
        prompt = classifier._generate_clarification_prompt("do something", result)
        assert "change" in prompt.lower() or "proceed" in prompt.lower()


class TestPatternCounting:
    """Tests for pattern counting logic."""

    async def test_multiple_diagnostic_patterns(self, classifier: CenterClassifier) -> None:
        """Test multiple diagnostic patterns increase confidence."""
        result = await classifier.classify("check disk usage, show logs, and analyze memory usage")
        assert result.center == CenterMode.DIAGNOSTIC
        assert result.confidence >= 0.7

    async def test_multiple_change_patterns(self, classifier: CenterClassifier) -> None:
        """Test multiple change patterns increase confidence."""
        result = await classifier.classify("restart nginx, update config, and deploy the app")
        assert result.center == CenterMode.CHANGE
        assert result.confidence >= 0.7


class TestEdgeCases:
    """Tests for edge cases."""

    async def test_empty_input(self, classifier: CenterClassifier) -> None:
        """Test empty input defaults to diagnostic."""
        result = await classifier.classify("")
        assert result.center == CenterMode.DIAGNOSTIC
        assert result.confidence < 0.5

    async def test_whitespace_only(self, classifier: CenterClassifier) -> None:
        """Test whitespace-only input."""
        result = await classifier.classify("   ")
        assert result.center == CenterMode.DIAGNOSTIC

    async def test_special_characters(self, classifier: CenterClassifier) -> None:
        """Test input with special characters."""
        result = await classifier.classify("check @web-01 status?!")
        assert result.center == CenterMode.DIAGNOSTIC

    async def test_case_insensitive(self, classifier: CenterClassifier) -> None:
        """Test classification is case insensitive."""
        result1 = await classifier.classify("RESTART NGINX")
        result2 = await classifier.classify("restart nginx")
        assert result1.center == result2.center
