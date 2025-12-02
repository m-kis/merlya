"""
Tests for continuation detection logic.
"""
import pytest

from merlya.agents.orchestrator_service.continuation import (
    ContinuationContext,
    ContinuationDecision,
    ContinuationDetector,
    get_continuation_detector,
    should_continue,
)


@pytest.fixture
def detector():
    """Get a fresh detector instance."""
    return ContinuationDetector()


class TestContinuationDetector:
    """Tests for ContinuationDetector class."""

    def test_explicit_yes_continue(self, detector):
        """Test explicit 'yes' responses trigger continuation."""
        for response in ['yes', 'oui', 'y', 'o', 'continue', 'ok', 'go ahead', 'vas-y', 'proceed']:
            result = detector.analyze_user_response(response)
            assert result.decision == ContinuationDecision.CONTINUE, f"Failed for: {response}"

    def test_explicit_no_pause(self, detector):
        """Test explicit 'no' responses trigger pause."""
        for response in ['no', 'non', 'n', 'stop', 'cancel', 'abort', 'annuler']:
            result = detector.analyze_user_response(response)
            assert result.decision == ContinuationDecision.PAUSE, f"Failed for: {response}"

    def test_french_correction_patterns(self, detector):
        """Test French correction patterns are detected."""
        corrections = [
            "c'est pas la bonne machine",
            "non c'est pas le bon serveur",
            "la bonne machine c'est ANSIBLE",
            "le bon host est preprodlb",
        ]

        for correction in corrections:
            result = detector.analyze_user_response(correction)
            assert result.decision == ContinuationDecision.CONTINUE, f"Failed for: {correction}"

    def test_english_correction_patterns(self, detector):
        """Test English correction patterns are detected."""
        corrections = [
            "no, it's ANSIBLE",
            "use preprodlb instead",
            "wrong host",
            "should be production-server",
        ]

        for correction in corrections:
            result = detector.analyze_user_response(correction)
            assert result.decision == ContinuationDecision.CONTINUE, f"Failed for: {correction}"

    def test_hostname_after_disambiguation(self, detector):
        """Test single hostname response after disambiguation question."""
        question = "Which host do you want to use? Please specify."
        response = "ANSIBLE"

        result = detector.analyze_user_response(
            response,
            agent_question=question
        )

        assert result.decision == ContinuationDecision.CONTINUE
        assert "ANSIBLE" in (result.next_action or "")

    def test_short_response_not_hostname(self, detector):
        """Test that short non-hostname responses don't trigger hostname detection."""
        question = "What is the error?"
        response = "ok"  # This is a confirmation, not a hostname

        result = detector.analyze_user_response(response, agent_question=question)

        # 'ok' should be treated as continuation confirmation
        assert result.decision == ContinuationDecision.CONTINUE

    def test_new_input_pauses(self, detector):
        """Test that unrelated new input causes pause."""
        result = detector.analyze_user_response(
            "I have a completely different question now"
        )

        assert result.decision == ContinuationDecision.PAUSE


class TestAgentOutputAnalysis:
    """Tests for agent output analysis."""

    def test_completion_detected(self, detector):
        """Test that completion signals are detected."""
        outputs = [
            "✅ Task completed successfully",
            "Here's the summary of findings",
            "In conclusion, the issue was...",
        ]

        for output in outputs:
            result = detector.analyze_agent_output(output)
            assert result.decision == ContinuationDecision.COMPLETE, f"Failed for: {output}"

    def test_continuation_detected(self, detector):
        """Test that continuation signals are detected."""
        outputs = [
            "Now I'll check the logs",
            "Let me verify the configuration",  # Changed from "Next, let me..."
            "Continuing with the analysis...",
            "Retrying with the correct hostname",
        ]

        for output in outputs:
            result = detector.analyze_agent_output(output)
            assert result.decision == ContinuationDecision.CONTINUE, f"Failed for: {output}"

    def test_error_with_question_pauses(self, detector):
        """Test that errors with questions pause for user input."""
        output = "❌ Error: Permission denied. Should I retry with sudo?"

        result = detector.analyze_agent_output(output)

        assert result.decision == ContinuationDecision.PAUSE

    def test_error_without_question_continues(self, detector):
        """Test that errors without questions allow continuation."""
        output = "❌ Error: Connection refused. Retrying..."

        result = detector.analyze_agent_output(output)

        # Should allow continuation for retry
        assert result.decision in [ContinuationDecision.CONTINUE, ContinuationDecision.COMPLETE]


class TestToolResponseAnalysis:
    """Tests for tool response analysis."""

    def test_user_correction_in_tool_response(self, detector):
        """Test detection of user correction in tool response."""
        # Use a clear correction pattern that matches our regex
        tool_response = (
            "User response: c'est pas la bonne machine la bonne machine c'est ANSIBLE\n\n"
            "**IMPORTANT**: Continue with original task."
        )

        should_cont, reason = detector.should_continue_after_tool_response(
            tool_response, "check the ansible server"
        )

        assert should_cont is True, f"Failed with reason: {reason}"

    def test_normal_tool_response(self, detector):
        """Test normal tool response doesn't trigger special continuation."""
        tool_response = "✅ SUCCESS\n\nOutput:\nNginx is running"

        should_cont, reason = detector.should_continue_after_tool_response(
            tool_response, "check nginx status"
        )

        # Normal success - doesn't need special continuation handling
        assert should_cont is False


class TestHostDisambiguationDetection:
    """Tests for host disambiguation question detection."""

    def test_detects_host_question(self, detector):
        """Test detection of host disambiguation questions."""
        questions = [
            "Which host do you want to use?",
            "Please specify the hostname",
            "Quel serveur voulez-vous utiliser?",
            "Choose the target machine:",
        ]

        for question in questions:
            result = detector._is_host_disambiguation_question(question)
            assert result is True, f"Failed for: {question}"

    def test_non_host_question(self, detector):
        """Test that non-host questions are not detected as such."""
        questions = [
            "What is the error message?",
            "Do you want to proceed?",
            "How many retries?",
        ]

        for question in questions:
            result = detector._is_host_disambiguation_question(question)
            assert result is False, f"Should not match: {question}"


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_get_continuation_detector_singleton(self):
        """Test singleton behavior."""
        d1 = get_continuation_detector()
        d2 = get_continuation_detector()
        assert d1 is d2

    def test_should_continue_convenience(self):
        """Test should_continue convenience function."""
        result = should_continue("yes")
        assert isinstance(result, ContinuationContext)
        assert result.decision == ContinuationDecision.CONTINUE


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_response(self, detector):
        """Test handling of empty response."""
        result = detector.analyze_user_response("")
        # Empty should be treated as new input / pause
        assert result.decision == ContinuationDecision.PAUSE

    def test_whitespace_only_response(self, detector):
        """Test handling of whitespace-only response."""
        result = detector.analyze_user_response("   ")
        assert result.decision == ContinuationDecision.PAUSE

    def test_special_characters(self, detector):
        """Test handling of special characters."""
        result = detector.analyze_user_response("!@#$%^&*()")
        # Should not crash
        assert result.decision is not None

    def test_very_long_response(self, detector):
        """Test handling of very long responses."""
        long_response = "word " * 1000
        result = detector.analyze_user_response(long_response)
        # Should not crash
        assert result.decision is not None
