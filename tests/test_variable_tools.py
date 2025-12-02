"""
Tests for variable tools and detection.

Ensures that:
1. Variable tools work correctly
2. Variable query detection works for French/English (semantic + keyword)
3. Integration with credentials system works
"""
from unittest.mock import MagicMock

import pytest


class TestVariableQueryDetector:
    """Test VariableQueryDetector directly."""

    @pytest.fixture
    def detector(self):
        """Create a detector for testing."""
        from merlya.triage.variable_detector import VariableQueryDetector

        return VariableQueryDetector()

    def test_detect_at_variable_reference(self, detector):
        """Should detect @variable references."""
        is_var, conf = detector.detect("affiche moi @Test")
        assert is_var is True
        assert conf >= 0.7

    def test_detect_variable_keyword_french(self, detector):
        """Should detect French variable queries."""
        queries = [
            "affiche moi la variable Test",
            "quelle est la valeur de @config",
        ]
        for query in queries:
            is_var, conf = detector.detect(query)
            assert is_var is True, f"Failed to detect: {query} (conf={conf})"

    def test_detect_variable_keyword_english(self, detector):
        """Should detect English variable queries."""
        queries = [
            "show me my variables",
            "list all defined variables",
            "what is the value of @config",
        ]
        for query in queries:
            is_var, conf = detector.detect(query)
            assert is_var is True, f"Failed to detect: {query} (conf={conf})"

    def test_no_false_positive_infrastructure_queries(self, detector):
        """Should not detect non-variable queries."""
        queries = [
            "check disk space on server1",
            "restart nginx",
            "list hosts",
            "what is running on port 80",
            "analyse les logs",
        ]
        for query in queries:
            is_var, conf = detector.detect(query)
            assert is_var is False, f"False positive for: {query} (conf={conf})"

    def test_get_context_hint(self, detector):
        """Should return proper context hint."""
        hint = detector.get_context_hint()
        assert "VARIABLE QUERY DETECTED" in hint
        assert "get_user_variables()" in hint
        assert "get_variable_value" in hint

    def test_is_semantic_enabled(self, detector):
        """Should report semantic status."""
        # This should be True if sentence-transformers is installed
        assert isinstance(detector.is_semantic_enabled, bool)


class TestVariableQueryDetection:
    """Test _detect_variable_query in ExecutionPlanner."""

    @pytest.fixture
    def planner(self):
        """Create a minimal planner for testing detection."""
        from merlya.agents.orchestrator_service.planner import ExecutionPlanner

        # Create planner with mocked dependencies
        mock_client = MagicMock()
        return ExecutionPlanner(
            model_client=mock_client,
            tools=[],
            env="test"
        )

    def test_detect_at_variable(self, planner):
        """Should detect @variable references."""
        result = planner._detect_variable_query("affiche moi @Test")
        assert result is not None
        assert "VARIABLE QUERY DETECTED" in result

    def test_detect_variable_keyword_french(self, planner):
        """Should detect French variable queries."""
        queries = [
            "affiche moi la variable Test",
            "quelle est la valeur de @config",
        ]
        for query in queries:
            result = planner._detect_variable_query(query)
            assert result is not None, f"Failed to detect: {query}"

    def test_detect_variable_keyword_english(self, planner):
        """Should detect English variable queries."""
        queries = [
            "show me my variables",
            "list all defined variables",
            "what is the value of @config",
        ]
        for query in queries:
            result = planner._detect_variable_query(query)
            assert result is not None, f"Failed to detect: {query}"

    def test_no_false_positive_host_query(self, planner):
        """Should not detect non-variable queries."""
        queries = [
            "check disk space on server1",
            "restart nginx",
            "list hosts",
            "what is running on port 80",
        ]
        for query in queries:
            result = planner._detect_variable_query(query)
            assert result is None, f"False positive for: {query}"


class TestGetUserVariables:
    """Test get_user_variables tool."""

    def test_returns_message_when_no_credentials(self):
        """Should return error when credentials not available."""
        from merlya.tools import base as tools_base
        from merlya.tools.base import ToolContext
        from merlya.tools.interaction import get_user_variables

        # Save and replace global context
        old_ctx = tools_base._ctx
        try:
            tools_base._ctx = ToolContext(credentials=None)
            result = get_user_variables()
            assert "not available" in result
        finally:
            tools_base._ctx = old_ctx

    def test_returns_empty_message_when_no_variables(self):
        """Should return helpful message when no variables defined."""
        from merlya.tools import base as tools_base
        from merlya.tools.base import ToolContext
        from merlya.tools.interaction import get_user_variables

        # Mock credentials with no variables
        mock_credentials = MagicMock()
        mock_credentials.list_variables_typed.return_value = {}

        old_ctx = tools_base._ctx
        try:
            tools_base._ctx = ToolContext(credentials=mock_credentials)
            result = get_user_variables()
            assert "No user variables defined" in result
            assert "/variables set" in result
        finally:
            tools_base._ctx = old_ctx


class TestGetVariableValue:
    """Test get_variable_value tool."""

    def test_returns_error_for_missing_variable(self):
        """Should return error when variable not found."""
        from merlya.tools import base as tools_base
        from merlya.tools.base import ToolContext
        from merlya.tools.interaction import get_variable_value

        # Mock credentials with no variables
        mock_credentials = MagicMock()
        mock_credentials.get_variable.return_value = None
        mock_credentials.list_variables.return_value = {}

        old_ctx = tools_base._ctx
        try:
            tools_base._ctx = ToolContext(credentials=mock_credentials)
            result = get_variable_value("nonexistent")
            assert "not found" in result
        finally:
            tools_base._ctx = old_ctx

    def test_returns_value_for_existing_variable(self):
        """Should return value when variable exists."""
        from merlya.security.credentials import VariableType
        from merlya.tools import base as tools_base
        from merlya.tools.base import ToolContext
        from merlya.tools.interaction import get_variable_value

        # Mock credentials with a variable
        mock_credentials = MagicMock()
        mock_credentials.get_variable.return_value = "test-value-123"
        mock_credentials.get_variable_type.return_value = VariableType.CONFIG

        old_ctx = tools_base._ctx
        try:
            tools_base._ctx = ToolContext(credentials=mock_credentials)
            result = get_variable_value("Test")
            assert "test-value-123" in result
            assert "@Test" in result
        finally:
            tools_base._ctx = old_ctx

    def test_masks_secret_variables(self):
        """Should mask secret variable values."""
        from merlya.security.credentials import VariableType
        from merlya.tools import base as tools_base
        from merlya.tools.base import ToolContext
        from merlya.tools.interaction import get_variable_value

        # Mock credentials with a secret
        mock_credentials = MagicMock()
        mock_credentials.get_variable.return_value = "super-secret-password"
        mock_credentials.get_variable_type.return_value = VariableType.SECRET

        old_ctx = tools_base._ctx
        try:
            tools_base._ctx = ToolContext(credentials=mock_credentials)
            result = get_variable_value("password")
            assert "super-secret-password" not in result
            assert "********" in result
            assert "secret" in result.lower()
        finally:
            tools_base._ctx = old_ctx

    def test_strips_at_prefix(self):
        """Should handle @prefix in variable name."""
        from merlya.security.credentials import VariableType
        from merlya.tools import base as tools_base
        from merlya.tools.base import ToolContext
        from merlya.tools.interaction import get_variable_value

        mock_credentials = MagicMock()
        mock_credentials.get_variable.return_value = "value"
        mock_credentials.get_variable_type.return_value = VariableType.CONFIG

        old_ctx = tools_base._ctx
        try:
            tools_base._ctx = ToolContext(credentials=mock_credentials)
            get_variable_value("@Test")
            # Should call get_variable with "Test", not "@Test"
            mock_credentials.get_variable.assert_called_with("Test")
        finally:
            tools_base._ctx = old_ctx


class TestBuildTaskWithContext:
    """Test _build_task_with_context with variable context."""

    @pytest.fixture
    def planner(self):
        """Create a minimal planner for testing."""
        from merlya.agents.orchestrator_service.planner import ExecutionPlanner

        mock_client = MagicMock()
        return ExecutionPlanner(
            model_client=mock_client,
            tools=[],
            env="test"
        )

    def test_includes_variable_context(self, planner):
        """Should include variable context when provided."""
        variable_ctx = "📌 VARIABLE QUERY DETECTED"
        result = planner._build_task_with_context(
            "show @Test",
            conversation_history=None,
            variable_context=variable_ctx
        )
        assert "VARIABLE QUERY DETECTED" in result
        assert "show @Test" in result

    def test_no_variable_context_when_none(self, planner):
        """Should not add variable hint when not provided."""
        result = planner._build_task_with_context(
            "check server status",
            conversation_history=None,
            variable_context=None
        )
        assert "VARIABLE" not in result
        assert "check server status" in result
