"""Tests for BaseCIAdapter platform_type validation."""

from typing import Any, Dict, List, Optional

import pytest

from merlya.ci.adapters.base import BaseCIAdapter
from merlya.ci.config import CIConfig
from merlya.ci.models import (
    FailureAnalysis,
    PermissionReport,
    Run,
    RunLogs,
    Workflow,
)
from merlya.ci.protocols import CIPlatformType


class ValidAdapter(BaseCIAdapter):
    """Valid adapter with proper platform_type."""

    platform_type = CIPlatformType.GITHUB

    def list_workflows(self) -> List[Workflow]:
        return []

    def list_runs(self, workflow_id: Optional[str] = None, limit: int = 10) -> List[Run]:
        return []

    def get_run(self, run_id: str) -> Optional[Run]:
        return None

    def get_run_logs(self, run_id: str, job_name: Optional[str] = None, failed_only: bool = True) -> RunLogs:
        return RunLogs(run_id=run_id, jobs=[])

    def trigger_workflow(self, workflow_id: str, ref: str = "main", inputs: Optional[Dict[str, Any]] = None) -> Run:
        raise NotImplementedError

    def cancel_run(self, run_id: str) -> bool:
        return False

    def retry_run(self, run_id: str, failed_only: bool = True) -> Run:
        raise NotImplementedError

    def analyze_failure(self, run_id: str) -> FailureAnalysis:
        raise NotImplementedError

    def check_permissions(self) -> PermissionReport:
        raise NotImplementedError


class MissingPlatformTypeAdapter(BaseCIAdapter):
    """Invalid adapter without platform_type."""

    def list_workflows(self) -> List[Workflow]:
        return []

    def list_runs(self, workflow_id: Optional[str] = None, limit: int = 10) -> List[Run]:
        return []

    def get_run(self, run_id: str) -> Optional[Run]:
        return None

    def get_run_logs(self, run_id: str, job_name: Optional[str] = None, failed_only: bool = True) -> RunLogs:
        return RunLogs(run_id=run_id, jobs=[])

    def trigger_workflow(self, workflow_id: str, ref: str = "main", inputs: Optional[Dict[str, Any]] = None) -> Run:
        raise NotImplementedError

    def cancel_run(self, run_id: str) -> bool:
        return False

    def retry_run(self, run_id: str, failed_only: bool = True) -> Run:
        raise NotImplementedError

    def analyze_failure(self, run_id: str) -> FailureAnalysis:
        raise NotImplementedError

    def check_permissions(self) -> PermissionReport:
        raise NotImplementedError


class InvalidTypePlatformTypeAdapter(BaseCIAdapter):
    """Invalid adapter with wrong type for platform_type."""

    platform_type = "github"  # Should be CIPlatformType.GITHUB

    def list_workflows(self) -> List[Workflow]:
        return []

    def list_runs(self, workflow_id: Optional[str] = None, limit: int = 10) -> List[Run]:
        return []

    def get_run(self, run_id: str) -> Optional[Run]:
        return None

    def get_run_logs(self, run_id: str, job_name: Optional[str] = None, failed_only: bool = True) -> RunLogs:
        return RunLogs(run_id=run_id, jobs=[])

    def trigger_workflow(self, workflow_id: str, ref: str = "main", inputs: Optional[Dict[str, Any]] = None) -> Run:
        raise NotImplementedError

    def cancel_run(self, run_id: str) -> bool:
        return False

    def retry_run(self, run_id: str, failed_only: bool = True) -> Run:
        raise NotImplementedError

    def analyze_failure(self, run_id: str) -> FailureAnalysis:
        raise NotImplementedError

    def check_permissions(self) -> PermissionReport:
        raise NotImplementedError


def test_valid_adapter_initialization():
    """Test that a properly configured adapter initializes successfully."""
    config = CIConfig(platform="github")
    adapter = ValidAdapter(config)
    assert adapter.platform_type == CIPlatformType.GITHUB
    assert adapter.config == config


def test_missing_platform_type_raises_typeerror():
    """Test that missing platform_type raises descriptive TypeError."""
    config = CIConfig(platform="github")

    with pytest.raises(TypeError) as exc_info:
        MissingPlatformTypeAdapter(config)

    error_msg = str(exc_info.value)
    assert "MissingPlatformTypeAdapter" in error_msg
    assert "must define 'platform_type' class attribute" in error_msg
    assert "merlya/ci/adapters/base.py" in error_msg


def test_invalid_type_platform_type_raises_typeerror():
    """Test that invalid platform_type type raises descriptive TypeError."""
    config = CIConfig(platform="github")

    with pytest.raises(TypeError) as exc_info:
        InvalidTypePlatformTypeAdapter(config)

    error_msg = str(exc_info.value)
    assert "InvalidTypePlatformTypeAdapter" in error_msg
    assert "must be an instance of CIPlatformType" in error_msg
    assert "got str" in error_msg
    assert "'github'" in error_msg
    assert "merlya/ci/adapters/base.py" in error_msg


def test_github_adapter_still_works():
    """Test that existing GitHubCIAdapter still works with validation."""
    from merlya.ci.adapters.github import GitHubCIAdapter

    config = CIConfig(platform="github")
    adapter = GitHubCIAdapter(config)
    assert adapter.platform_type == CIPlatformType.GITHUB
