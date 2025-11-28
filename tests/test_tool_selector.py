"""
Tests for ToolSelector service.

Tests AI-powered and heuristic tool selection.
"""
import pytest

from athena_ai.domains.tools.selector import (
    ToolAction,
    ToolRecommendation,
    ToolSelector,
    get_tool_selector,
    reset_tool_selector,
)
from athena_ai.triage import ErrorType, Intent


@pytest.fixture(autouse=True)
def reset_selector():
    """Reset singleton between tests."""
    reset_tool_selector()
    yield
    reset_tool_selector()


class TestToolSelector:
    """Tests for ToolSelector class."""

    def test_selector_creation(self):
        """ToolSelector can be created."""
        selector = ToolSelector()
        assert selector is not None

    def test_selector_singleton(self):
        """get_tool_selector returns same instance."""
        s1 = get_tool_selector()
        s2 = get_tool_selector()
        assert s1 is s2

    def test_selector_force_new(self):
        """force_new creates new instance."""
        s1 = get_tool_selector()
        s2 = get_tool_selector(force_new=True)
        assert s1 is not s2


class TestHeuristicSelection:
    """Tests for heuristic-based selection (fallback mode)."""

    def test_permission_error_recommends_elevation(self):
        """Permission error should recommend request_elevation."""
        selector = ToolSelector(use_embeddings=False)
        rec = selector.select(
            error_type=ErrorType.PERMISSION,
            error_message="Permission denied",
            context={
                "target": "testhost",
                "command": "cat /etc/shadow",
                "elevation_method": "sudo",
            },
        )
        assert rec.action == ToolAction.REQUEST_ELEVATION
        assert rec.confidence >= 0.8
        assert rec.tool_name == "request_elevation"
        assert rec.tool_params.get("target") == "testhost"

    def test_permission_error_without_elevation_suggests_sudo(self):
        """Permission error without elevation method suggests sudo prefix."""
        selector = ToolSelector(use_embeddings=False)
        rec = selector.select(
            error_type=ErrorType.PERMISSION,
            error_message="Permission denied",
            context={
                "target": "testhost",
                "command": "cat /etc/shadow",
                "elevation_method": None,
            },
        )
        assert rec.action == ToolAction.RETRY_WITH_SUDO
        assert rec.tool_params.get("prefix") == "sudo"

    def test_credential_error_recommends_credentials(self):
        """Credential error should recommend providing credentials."""
        selector = ToolSelector(use_embeddings=False)
        rec = selector.select(
            error_type=ErrorType.CREDENTIAL,
            error_message="Authentication failed: invalid password",
            context={"target": "dbhost"},
        )
        assert rec.action == ToolAction.PROVIDE_CREDENTIALS
        assert rec.tool_name == "ask_user"

    def test_not_found_recommends_alternate_path(self):
        """File not found should recommend alternate path."""
        selector = ToolSelector(use_embeddings=False)
        rec = selector.select(
            error_type=ErrorType.NOT_FOUND,
            error_message="No such file: /var/log/syslog",
            context={"target": "testhost"},
        )
        assert rec.action == ToolAction.RETRY_ALTERNATE_PATH
        assert rec.tool_params.get("new_path") == "/var/log/messages"

    def test_command_not_found_recommends_alternate_command(self):
        """Command not found should recommend alternate command."""
        selector = ToolSelector(use_embeddings=False)
        rec = selector.select(
            error_type=ErrorType.NOT_FOUND,
            error_message="command not found: service",
            context={"target": "testhost", "exit_code": 127},
        )
        assert rec.action == ToolAction.RETRY_ALTERNATE_COMMAND

    def test_unknown_error_returns_no_action(self):
        """Unknown error should return NO_ACTION."""
        selector = ToolSelector(use_embeddings=False)
        rec = selector.select(
            error_type=None,
            error_message="Some random error occurred",
            context={},
        )
        assert rec.action == ToolAction.NO_ACTION
        assert rec.confidence <= 0.6


class TestToolRecommendation:
    """Tests for ToolRecommendation dataclass."""

    def test_recommendation_fields(self):
        """ToolRecommendation has all expected fields."""
        rec = ToolRecommendation(
            action=ToolAction.REQUEST_ELEVATION,
            confidence=0.9,
            tool_name="request_elevation",
            tool_params={"target": "host1"},
            reason="Test reason",
        )
        assert rec.action == ToolAction.REQUEST_ELEVATION
        assert rec.confidence == 0.9
        assert rec.tool_name == "request_elevation"
        assert rec.tool_params == {"target": "host1"}
        assert rec.reason == "Test reason"


class TestToolAction:
    """Tests for ToolAction enum."""

    def test_all_actions_defined(self):
        """All expected actions are defined."""
        assert ToolAction.REQUEST_ELEVATION
        assert ToolAction.ASK_USER
        assert ToolAction.RETRY_WITH_SUDO
        assert ToolAction.RETRY_ALTERNATE_PATH
        assert ToolAction.RETRY_ALTERNATE_COMMAND
        assert ToolAction.PROVIDE_CREDENTIALS
        assert ToolAction.NO_ACTION

    def test_action_values(self):
        """Action values are strings."""
        for action in ToolAction:
            assert isinstance(action.value, str)


class TestIntegrationWithTriage:
    """Tests for integration with triage system."""

    def test_selector_uses_error_type(self):
        """Selector properly uses ErrorType from triage."""
        selector = ToolSelector(use_embeddings=False)

        # Test with each error type
        error_type_expectations = {
            ErrorType.PERMISSION: ToolAction.REQUEST_ELEVATION,
            ErrorType.CREDENTIAL: ToolAction.PROVIDE_CREDENTIALS,
        }

        for error_type, expected_action in error_type_expectations.items():
            rec = selector.select(
                error_type=error_type,
                error_message="Error message",
                context={"elevation_method": "sudo"},
            )
            assert rec.action == expected_action, f"Failed for {error_type}"

    def test_selector_handles_missing_intent(self):
        """Selector handles None intent gracefully."""
        selector = ToolSelector(use_embeddings=False)
        rec = selector.select(
            error_type=ErrorType.PERMISSION,
            error_message="Permission denied",
            intent=None,
            context={"elevation_method": "sudo"},
        )
        # Should still work
        assert rec is not None
        assert rec.action == ToolAction.REQUEST_ELEVATION
