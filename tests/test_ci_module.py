"""
Tests for the CI/CD module.

Tests core functionality without requiring actual CI platforms.
"""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path


class TestCIErrorType:
    """Tests for CIErrorType enum."""

    def test_error_types_exist(self):
        """Verify all expected error types exist."""
        from athena_ai.ci.models import CIErrorType

        expected = [
            "TEST_FAILURE",
            "SYNTAX_ERROR",
            "DEPENDENCY_ERROR",
            "PERMISSION_ERROR",
            "TIMEOUT",
            "NETWORK_ERROR",
            "RESOURCE_LIMIT",
            "TYPE_ERROR",
            "LINT_ERROR",
            "BUILD_FAILURE",
            "CONFIGURATION_ERROR",
            "FLAKY_TEST",
            "INFRASTRUCTURE_ERROR",
            "UNKNOWN",
        ]

        for error_type in expected:
            assert hasattr(CIErrorType, error_type), f"Missing error type: {error_type}"


class TestCIPlatformType:
    """Tests for CIPlatformType enum."""

    def test_platform_types_exist(self):
        """Verify all expected platform types exist."""
        from athena_ai.ci.protocols import CIPlatformType

        expected = ["GITHUB", "GITLAB", "JENKINS", "CIRCLECI"]

        for platform in expected:
            assert hasattr(CIPlatformType, platform), f"Missing platform: {platform}"


class TestRunStatus:
    """Tests for RunStatus enum."""

    def test_status_from_github(self):
        """Test GitHub status parsing."""
        from athena_ai.ci.protocols import RunStatus

        assert RunStatus.from_github("completed", "success") == RunStatus.SUCCESS
        assert RunStatus.from_github("completed", "failure") == RunStatus.FAILURE
        assert RunStatus.from_github("in_progress", None) == RunStatus.RUNNING
        assert RunStatus.from_github("queued", None) == RunStatus.QUEUED

    def test_status_from_gitlab(self):
        """Test GitLab status parsing."""
        from athena_ai.ci.protocols import RunStatus

        assert RunStatus.from_gitlab("success") == RunStatus.SUCCESS
        assert RunStatus.from_gitlab("failed") == RunStatus.FAILURE
        assert RunStatus.from_gitlab("running") == RunStatus.RUNNING
        assert RunStatus.from_gitlab("pending") == RunStatus.PENDING


class TestCIConfig:
    """Tests for CIConfig dataclass."""

    def test_github_factory(self):
        """Test GitHub config factory method."""
        from athena_ai.ci.config import CIConfig

        config = CIConfig.for_github(repo_owner="test", repo_name="repo")

        assert config.platform == "github"
        assert config.repo_owner == "test"
        assert config.repo_name == "repo"
        assert config.cli_command == "gh"
        assert config.get_repo_slug() == "test/repo"

    def test_gitlab_factory(self):
        """Test GitLab config factory method."""
        from athena_ai.ci.config import CIConfig

        config = CIConfig.for_gitlab(project_path="group/project")

        assert config.platform == "gitlab"
        assert config.project_path == "group/project"
        assert config.cli_command == "glab"


class TestCIPlatformRegistry:
    """Tests for CIPlatformRegistry singleton."""

    def test_singleton_pattern(self):
        """Test that registry is a singleton."""
        from athena_ai.ci.registry import CIPlatformRegistry

        # Reset for clean test
        CIPlatformRegistry.reset_instance()

        reg1 = CIPlatformRegistry()
        reg2 = CIPlatformRegistry()

        assert reg1 is reg2

        # Clean up
        CIPlatformRegistry.reset_instance()

    def test_register_and_get(self):
        """Test registering and retrieving platforms."""
        from athena_ai.ci.registry import CIPlatformRegistry

        CIPlatformRegistry.reset_instance()
        registry = CIPlatformRegistry()

        # Create a mock adapter class
        class MockAdapter:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        registry.register("test_platform", MockAdapter)

        assert registry.has("test_platform")
        assert "test_platform" in registry.list_all()

        adapter = registry.get("test_platform", foo="bar")
        assert adapter.kwargs == {"foo": "bar"}

        # Clean up
        CIPlatformRegistry.reset_instance()

    def test_decorator_registration(self):
        """Test decorator-based registration."""
        from athena_ai.ci.registry import CIPlatformRegistry

        CIPlatformRegistry.reset_instance()
        registry = CIPlatformRegistry()

        @registry.platform("decorated_platform")
        class DecoratedAdapter:
            pass

        assert registry.has("decorated_platform")

        # Clean up
        CIPlatformRegistry.reset_instance()


class TestCLIClient:
    """Tests for CLIClient."""

    def test_command_templates_exist(self):
        """Verify command templates are defined."""
        from athena_ai.ci.clients.cli_client import CLIClient

        assert "github" in CLIClient.COMMAND_TEMPLATES
        assert "gitlab" in CLIClient.COMMAND_TEMPLATES

        github_ops = CLIClient.COMMAND_TEMPLATES["github"]
        assert "list_workflows" in github_ops
        assert "list_runs" in github_ops
        assert "get_run" in github_ops

    def test_build_command(self):
        """Test command building."""
        from athena_ai.ci.clients.cli_client import CLIClient

        client = CLIClient(platform="github", repo_slug="owner/repo")

        # Test with simple params
        cmd = client._build_command(
            "gh run list --limit {limit}",
            {"limit": 5},
        )
        assert "5" in cmd
        assert "-R owner/repo" in cmd

    @patch("shutil.which")
    def test_is_available(self, mock_which):
        """Test availability check."""
        from athena_ai.ci.clients.cli_client import CLIClient

        mock_which.return_value = "/usr/bin/gh"
        client = CLIClient(platform="github")
        assert client.is_available()

        mock_which.return_value = None
        client._available = None  # Reset cache
        assert not client.is_available()


class TestCIErrorClassifier:
    """Tests for CIErrorClassifier."""

    def test_classify_fallback(self):
        """Test fallback classification without embeddings."""
        from athena_ai.ci.analysis.error_classifier import CIErrorClassifier
        from athena_ai.ci.models import CIErrorType

        classifier = CIErrorClassifier()

        # Test keyword-based fallback
        result = classifier._classify_fallback("FAILED tests/test_auth.py - AssertionError")
        assert result.error_type == CIErrorType.TEST_FAILURE

        result = classifier._classify_fallback("npm ERR! Could not resolve dependency")
        assert result.error_type == CIErrorType.DEPENDENCY_ERROR

        result = classifier._classify_fallback("Error: Permission denied - 403")
        assert result.error_type == CIErrorType.PERMISSION_ERROR

    def test_get_suggestions(self):
        """Test that suggestions are returned for each error type."""
        from athena_ai.ci.analysis.error_classifier import CIErrorClassifier
        from athena_ai.ci.models import CIErrorType

        classifier = CIErrorClassifier()

        for error_type in CIErrorType:
            suggestions = classifier.get_suggestions(error_type)
            assert isinstance(suggestions, list)
            assert len(suggestions) > 0


class TestCIPlatformManager:
    """Tests for CIPlatformManager."""

    def test_config_patterns(self):
        """Verify config detection patterns are defined."""
        from athena_ai.ci.manager import CIPlatformManager

        assert "github" in CIPlatformManager.CONFIG_PATTERNS
        assert "gitlab" in CIPlatformManager.CONFIG_PATTERNS

    def test_remote_patterns(self):
        """Verify git remote patterns are defined."""
        from athena_ai.ci.manager import CIPlatformManager

        assert "github" in CIPlatformManager.REMOTE_PATTERNS
        assert "gitlab" in CIPlatformManager.REMOTE_PATTERNS

    @patch("subprocess.run")
    def test_detect_from_git_remote(self, mock_run):
        """Test platform detection from git remote."""
        from athena_ai.ci.manager import CIPlatformManager
        from athena_ai.ci.protocols import CIPlatformType

        # Mock git remote
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="git@github.com:owner/repo.git",
        )

        manager = CIPlatformManager(project_path=Path("/tmp/test"))
        detected = {}
        manager._detect_from_git_remote(detected)

        assert "github" in detected
        assert detected["github"].platform == CIPlatformType.GITHUB


class TestCILearningEngine:
    """Tests for CILearningEngine."""

    def test_extract_error_text(self):
        """Test error text extraction from logs."""
        from athena_ai.ci.learning.engine import CILearningEngine
        from athena_ai.ci.models import RunLogs

        engine = CILearningEngine()

        logs = RunLogs(
            run_id="123",
            raw_logs="Some log output\nError: Something failed\nMore output",
            job_logs={},
        )

        text = engine._extract_error_text(logs)
        assert "Error: Something failed" in text


class TestModels:
    """Tests for CI data models."""

    def test_run_properties(self):
        """Test Run dataclass properties."""
        from athena_ai.ci.models import Run, Job
        from athena_ai.ci.protocols import RunStatus

        run = Run(
            id="123",
            name="Test Run",
            status=RunStatus.FAILURE,
            conclusion="failure",
            jobs=[
                Job(id="1", name="build", status="completed", conclusion="success"),
                Job(id="2", name="test", status="completed", conclusion="failure"),
            ],
        )

        assert run.is_failed
        assert not run.is_running
        assert len(run.failed_jobs) == 1
        assert run.failed_jobs[0].name == "test"

    def test_failure_analysis_creation(self):
        """Test FailureAnalysis creation."""
        from athena_ai.ci.models import FailureAnalysis, CIErrorType

        analysis = FailureAnalysis(
            run_id="123",
            error_type=CIErrorType.TEST_FAILURE,
            summary="Tests failed",
            raw_error="AssertionError: expected 1, got 2",
            confidence=0.85,
            failed_jobs=["test"],
            suggestions=["Run tests locally"],
        )

        assert analysis.error_type == CIErrorType.TEST_FAILURE
        assert analysis.confidence == 0.85
        assert len(analysis.suggestions) == 1


class TestGitHubCIAdapter:
    """Tests for GitHubCIAdapter."""

    def test_adapter_initialization(self):
        """Test adapter can be initialized."""
        from athena_ai.ci.adapters.github import GitHubCIAdapter
        from athena_ai.ci.config import CIConfig

        config = CIConfig.for_github()
        adapter = GitHubCIAdapter(config=config)

        assert adapter.platform_type.value == "github"
        assert "cli" in adapter._clients

    @patch("athena_ai.ci.clients.cli_client.CLIClient.is_available")
    @patch("athena_ai.ci.clients.cli_client.CLIClient.execute")
    def test_list_workflows(self, mock_execute, mock_available):
        """Test listing workflows."""
        from athena_ai.ci.adapters.github import GitHubCIAdapter

        mock_available.return_value = True
        mock_execute.return_value = {
            "data": [
                {"id": "1", "name": "CI", "path": ".github/workflows/ci.yml", "state": "active"},
            ],
            "raw": "",
        }

        adapter = GitHubCIAdapter()
        workflows = adapter.list_workflows()

        assert len(workflows) == 1
        assert workflows[0].name == "CI"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
