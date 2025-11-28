"""
CI/CD Data Models - Unified dataclasses for multi-platform CI/CD.

These models provide a platform-agnostic representation of CI/CD concepts,
allowing the same code to work with GitHub Actions, GitLab CI, Jenkins, etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from athena_ai.ci.protocols import CIPlatformType, RunStatus


class CIErrorType(Enum):
    """Types of CI/CD errors for semantic classification."""

    # Test failures
    TEST_FAILURE = "test_failure"
    FLAKY_TEST = "flaky_test"

    # Code quality
    SYNTAX_ERROR = "syntax_error"
    TYPE_ERROR = "type_error"
    LINT_ERROR = "lint_error"

    # Build & Dependencies
    BUILD_FAILURE = "build_failure"
    DEPENDENCY_ERROR = "dependency_error"

    # Authentication/Authorization
    PERMISSION_ERROR = "permission_error"

    # Resource & Performance
    TIMEOUT = "timeout"
    RESOURCE_LIMIT = "resource_limit"
    NETWORK_ERROR = "network_error"

    # Configuration
    CONFIGURATION_ERROR = "configuration_error"

    # Infrastructure
    INFRASTRUCTURE_ERROR = "infrastructure_error"

    # Unknown
    UNKNOWN = "unknown"


@dataclass
class Workflow:
    """Unified workflow/pipeline definition."""

    id: str
    name: str
    path: Optional[str] = None  # e.g., ".github/workflows/ci.yml"
    state: str = "unknown"  # "active", "disabled", etc.
    platform: Optional["CIPlatformType"] = None  # type: ignore
    triggers: List[str] = field(default_factory=list)  # ["push", "pull_request"]
    inputs: Dict[str, Any] = field(default_factory=dict)  # workflow_dispatch inputs
    description: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)  # Platform-specific data


@dataclass
class Step:
    """Unified step within a job."""

    name: str
    status: str  # Will be RunStatus.value
    number: int = 0
    conclusion: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    log_excerpt: Optional[str] = None


@dataclass
class Job:
    """Unified job/stage within a run."""

    id: str
    name: str
    status: str  # Will be RunStatus.value
    conclusion: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    runner_name: Optional[str] = None
    steps: Optional[List[Step]] = None
    logs: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Run:
    """Unified run/build/pipeline execution."""

    id: str
    name: str
    status: "RunStatus"  # Import at runtime to avoid circular
    workflow_id: str = ""
    workflow_name: Optional[str] = None
    conclusion: Optional[str] = None
    branch: str = ""
    commit_sha: Optional[str] = None
    url: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    event: Optional[str] = None  # "push", "workflow_dispatch", "schedule"
    jobs: Optional[List[Job]] = None
    platform: Optional["CIPlatformType"] = None  # type: ignore
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_failed(self) -> bool:
        """Check if run has failed."""
        return self.conclusion == "failure" or str(self.status) == "failure"

    @property
    def is_running(self) -> bool:
        """Check if run is still in progress."""
        from athena_ai.ci.protocols import RunStatus
        return self.status in (RunStatus.RUNNING, RunStatus.QUEUED, RunStatus.PENDING)

    @property
    def failed_jobs(self) -> List[Job]:
        """Get list of failed jobs."""
        if not self.jobs:
            return []
        return [j for j in self.jobs if j.conclusion == "failure"]


@dataclass
class RunLogs:
    """Logs from a run execution."""

    run_id: str
    raw_logs: str
    job_logs: Dict[str, str] = field(default_factory=dict)  # job_name -> log
    truncated: bool = False
    error: Optional[str] = None


@dataclass
class PermissionReport:
    """Report on CI/CD permissions and access."""

    authenticated: bool = False
    permissions: List[str] = field(default_factory=list)
    missing_permissions: List[str] = field(default_factory=list)
    scopes: List[str] = field(default_factory=list)
    can_read: bool = False
    can_write: bool = False
    can_admin: bool = False
    username: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class FailureAnalysis:
    """Analysis of a failed run with suggestions."""

    run_id: str
    error_type: CIErrorType
    summary: str
    raw_error: str
    confidence: float = 0.0  # 0.0 to 1.0
    failed_jobs: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    matched_pattern: Optional[str] = None  # Pattern that matched (for debugging)
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DetectedPlatform:
    """Result of platform detection."""

    platform: "CIPlatformType"  # type: ignore - forward ref
    confidence: float = 1.0  # Detection confidence
    detection_source: str = ""  # "config_file", "git_remote", "env_var", "cli"
    details: Dict[str, Any] = field(default_factory=dict)
