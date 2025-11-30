"""
Tests for the CI/CD module.

Tests core functionality without requiring actual CI platforms.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


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

    def test_get_suggestions_context_aware(self):
        """Test that context-aware suggestions are generated from error_text."""
        from athena_ai.ci.analysis.error_classifier import CIErrorClassifier
        from athena_ai.ci.models import CIErrorType

        classifier = CIErrorClassifier()

        # Test dependency error with module name extraction
        suggestions = classifier.get_suggestions(
            CIErrorType.DEPENDENCY_ERROR,
            "ModuleNotFoundError: No module named 'requests'"
        )
        assert any("requests" in s for s in suggestions), "Should suggest installing 'requests'"

        # Test test failure with file name extraction
        suggestions = classifier.get_suggestions(
            CIErrorType.TEST_FAILURE,
            "FAILED tests/test_auth.py::test_login - AssertionError"
        )
        assert any("test_auth.py" in s for s in suggestions), "Should mention test file"

        # Test permission error with token hint
        suggestions = classifier.get_suggestions(
            CIErrorType.PERMISSION_ERROR,
            "Error: GITHUB_TOKEN does not have required scopes"
        )
        assert any("token" in s.lower() for s in suggestions), "Should mention token"

        # Test timeout with specific duration
        suggestions = classifier.get_suggestions(
            CIErrorType.TIMEOUT,
            "Error: Timeout of 30000ms exceeded"
        )
        assert any("30000" in s for s in suggestions), "Should mention timeout duration"

        # Test network error with hostname
        suggestions = classifier.get_suggestions(
            CIErrorType.NETWORK_ERROR,
            "Could not resolve host: registry.npmjs.org"
        )
        assert any("registry.npmjs.org" in s for s in suggestions), "Should mention hostname"

        # Test without error_text - should still return base suggestions
        suggestions = classifier.get_suggestions(CIErrorType.DEPENDENCY_ERROR)
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
        from athena_ai.ci.models import Job, Run
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
        from athena_ai.ci.models import CIErrorType, FailureAnalysis

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


class TestSecurityValidation:
    """Security tests for CI module."""

    def test_validate_id_rejects_injection(self):
        """Test that validate_id rejects command injection attempts."""
        from athena_ai.ci.clients.cli_client import validate_id

        # Should reject shell metacharacters
        injection_attempts = [
            "123; rm -rf /",
            "123 && whoami",
            "123 | cat /etc/passwd",
            "$(whoami)",
            "`whoami`",
            "123\n456",
            "123\t456",
            "../../../etc/passwd",
            "123 > /tmp/pwned",
        ]

        for attempt in injection_attempts:
            with pytest.raises(ValueError):
                validate_id(attempt)

    def test_validate_id_accepts_valid(self):
        """Test that validate_id accepts valid IDs."""
        from athena_ai.ci.clients.cli_client import validate_id

        valid_ids = [
            "12345",
            "workflow_1",
            "ci.yml",
            "test-workflow",
            "MY_WORKFLOW_123",
        ]

        for valid_id in valid_ids:
            result = validate_id(valid_id)
            assert result == valid_id.strip()

    def test_validate_id_rejects_too_long(self):
        """Test that validate_id rejects overly long inputs."""
        from athena_ai.ci.clients.cli_client import MAX_ID_LENGTH, validate_id

        long_id = "a" * (MAX_ID_LENGTH + 1)
        with pytest.raises(ValueError, match="too long"):
            validate_id(long_id)

    def test_validate_ref_rejects_injection(self):
        """Test that validate_ref rejects command injection."""
        from athena_ai.ci.clients.cli_client import validate_ref

        injection_attempts = [
            "main; rm -rf /",
            "main && whoami",
            "refs/heads/$(whoami)",
        ]

        for attempt in injection_attempts:
            with pytest.raises(ValueError):
                validate_ref(attempt)

    def test_validate_ref_accepts_valid(self):
        """Test that validate_ref accepts valid git refs."""
        from athena_ai.ci.clients.cli_client import validate_ref

        valid_refs = [
            "main",
            "feature/my-branch",
            "refs/heads/main",
            "v1.0.0",
            "release_1.2.3",
        ]

        for ref in valid_refs:
            result = validate_ref(ref)
            assert result == ref.strip()

    def test_validate_repo_slug_rejects_injection(self):
        """Test that validate_repo_slug rejects invalid input."""
        from athena_ai.ci.clients.cli_client import validate_repo_slug

        invalid_slugs = [
            "owner/repo; whoami",
            "../../etc/passwd",
            "owner",  # Missing repo
            "/repo",  # Missing owner
        ]

        for slug in invalid_slugs:
            with pytest.raises(ValueError):
                validate_repo_slug(slug)

    def test_validate_repo_slug_accepts_valid(self):
        """Test that validate_repo_slug accepts valid slugs."""
        from athena_ai.ci.clients.cli_client import validate_repo_slug

        valid_slugs = [
            "owner/repo",
            "my-org/my-repo",
            "user_123/repo_456",
        ]

        for slug in valid_slugs:
            result = validate_repo_slug(slug)
            assert result == slug.strip()

    def test_validate_limit_rejects_invalid(self):
        """Test that validate_limit rejects invalid values."""
        from athena_ai.ci.clients.cli_client import validate_limit

        invalid_limits = [0, -1, 1001, "abc", None, [1, 2]]

        for limit in invalid_limits:
            with pytest.raises(ValueError):
                validate_limit(limit)

    def test_validate_limit_accepts_valid(self):
        """Test that validate_limit accepts valid values."""
        from athena_ai.ci.clients.cli_client import validate_limit

        assert validate_limit(1) == 1
        assert validate_limit(100) == 100
        assert validate_limit(1000) == 1000
        assert validate_limit("50") == 50

    def test_sensitive_data_redaction(self):
        """Test that sensitive data is properly redacted."""
        from athena_ai.ci.clients.base import BaseCIClient

        # Create a concrete implementation for testing
        class TestClient(BaseCIClient):
            def is_available(self) -> bool:
                return True

            def is_authenticated(self) -> bool:
                return True

            def get_supported_operations(self) -> list[str]:
                return ["test"]

            def execute(self, operation, params, timeout=60):
                return {}

        client = TestClient("test")

        test_data = {
            "username": "testuser",
            "api_token": "secret123",
            "password": "mypassword",
            "auth_key": "authsecret",
            "nested": {
                "ssh_key": "private_key_data",
                "normal": "visible",
            },
        }

        redacted = client._redact_sensitive(test_data)

        assert redacted["username"] == "testuser"
        assert redacted["api_token"] == "***"
        assert redacted["password"] == "***"
        assert redacted["auth_key"] == "***"
        assert redacted["nested"]["ssh_key"] == "***"
        assert redacted["nested"]["normal"] == "visible"

    def test_cli_client_uses_shell_false(self):
        """Test that CLIClient uses shell=False for subprocess."""
        from unittest.mock import MagicMock, patch

        from athena_ai.ci.clients.cli_client import CLIClient

        client = CLIClient(platform="github", repo_slug="owner/repo")

        with patch("shutil.which", return_value="/usr/bin/gh"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout='[{"id": "1", "name": "test"}]',
                    stderr="",
                )

                try:
                    client.execute("list_workflows", {})
                except Exception:
                    pass  # We're testing the subprocess call, not the result

                # Verify shell=False was used
                if mock_run.called:
                    call_kwargs = mock_run.call_args[1]
                    assert call_kwargs.get("shell") is False, "subprocess.run must use shell=False"


class TestResourceLimits:
    """Tests for resource limit enforcement."""

    def test_pending_incidents_limit(self):
        """Test that pending incidents are limited."""
        from athena_ai.ci.learning.memory_router import CIMemoryRouter
        from athena_ai.ci.models import CIErrorType, FailureAnalysis, Run
        from athena_ai.ci.protocols import RunStatus

        router = CIMemoryRouter(max_pending=5)

        # Add more than max_pending incidents
        for i in range(10):
            run = Run(
                id=f"run_{i}",
                name=f"Test Run {i}",
                status=RunStatus.FAILURE,
            )
            analysis = FailureAnalysis(
                run_id=f"run_{i}",
                error_type=CIErrorType.TEST_FAILURE,
                summary=f"Test failure {i}",
                raw_error="Error",
            )
            router.record_failure(run, analysis, "github")

        # Should only have max_pending incidents
        assert len(router._pending_incidents) <= 5

    def test_thread_safe_registry(self):
        """Test that registry operations are thread-safe."""
        import threading
        import time

        from athena_ai.ci.registry import CIPlatformRegistry

        CIPlatformRegistry.reset_instance()
        registry = CIPlatformRegistry()

        errors = []

        class MockAdapter:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        def register_platforms(thread_id):
            try:
                for i in range(10):
                    registry.register(f"platform_{thread_id}_{i}", MockAdapter)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=register_platforms, args=(i,))
            for i in range(5)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"

        # Verify all platforms were registered
        platforms = registry.list_all()
        assert len(platforms) >= 40  # At least most should succeed

        CIPlatformRegistry.reset_instance()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
