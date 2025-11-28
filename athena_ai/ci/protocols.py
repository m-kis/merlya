"""
CI/CD Platform Protocols - Interfaces for multi-platform CI/CD support.

Follows LSP and DIP: depend on abstractions, not concretions.
All adapters must implement CIPlatformProtocol for polymorphic usage.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from athena_ai.ci.models import (
    FailureAnalysis,
    Job,
    PermissionReport,
    Run,
    RunLogs,
    Workflow,
)


class CIPlatformType(Enum):
    """Supported CI/CD platform types."""

    GITHUB = "github"
    GITLAB = "gitlab"
    JENKINS = "jenkins"
    CIRCLECI = "circleci"
    AZURE = "azure"
    BITBUCKET = "bitbucket"
    TRAVIS = "travis"
    CUSTOM = "custom"


class RunStatus(Enum):
    """Unified run/pipeline status across platforms."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"
    UNKNOWN = "unknown"

    @classmethod
    def from_github(cls, status: str, conclusion: Optional[str] = None) -> "RunStatus":
        """Convert GitHub Actions status/conclusion to unified status."""
        if status == "queued":
            return cls.QUEUED
        if status == "in_progress":
            return cls.RUNNING
        if status == "completed":
            if conclusion == "success":
                return cls.SUCCESS
            if conclusion == "failure":
                return cls.FAILURE
            if conclusion == "cancelled":
                return cls.CANCELLED
            if conclusion == "skipped":
                return cls.SKIPPED
            if conclusion == "timed_out":
                return cls.TIMED_OUT
        return cls.UNKNOWN

    @classmethod
    def from_gitlab(cls, status: str) -> "RunStatus":
        """Convert GitLab CI status to unified status."""
        mapping = {
            "pending": cls.PENDING,
            "running": cls.RUNNING,
            "success": cls.SUCCESS,
            "failed": cls.FAILURE,
            "canceled": cls.CANCELLED,
            "skipped": cls.SKIPPED,
            "manual": cls.PENDING,
            "scheduled": cls.QUEUED,
        }
        return mapping.get(status, cls.UNKNOWN)

    @classmethod
    def from_jenkins(cls, result: str) -> "RunStatus":
        """Convert Jenkins build result to unified status."""
        mapping = {
            "SUCCESS": cls.SUCCESS,
            "FAILURE": cls.FAILURE,
            "UNSTABLE": cls.FAILURE,
            "ABORTED": cls.CANCELLED,
            "NOT_BUILT": cls.SKIPPED,
        }
        return mapping.get(result, cls.UNKNOWN)


@runtime_checkable
class CIClientProtocol(Protocol):
    """
    Strategy protocol for different access methods (CLI, MCP, API).

    Allows adapters to switch between gh CLI, MCP server, or direct API.
    Each client implementation handles its specific communication method.
    """

    def is_available(self) -> bool:
        """Check if this client method is available and configured."""
        ...

    def execute(
        self,
        operation: str,
        params: Dict[str, Any],
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """
        Execute an operation and return result.

        Args:
            operation: Operation name (e.g., "list_runs", "get_logs")
            params: Operation parameters
            timeout: Timeout in seconds

        Returns:
            Operation result as dictionary

        Raises:
            CIClientError: If operation fails
        """
        ...


@runtime_checkable
class CIPlatformProtocol(Protocol):
    """
    Protocol for CI/CD platform adapters.

    All adapters must implement this interface for polymorphic usage.
    This enables platform-agnostic code that works with any CI/CD system.
    """

    name: str
    platform_type: CIPlatformType

    def is_available(self) -> bool:
        """Check if platform is configured and accessible."""
        ...

    def check_permissions(self) -> PermissionReport:
        """
        Check current permissions and token scopes.

        Returns:
            PermissionReport with access levels and missing scopes
        """
        ...

    # Workflow operations
    def list_workflows(self, limit: int = 50) -> List[Workflow]:
        """List available workflows/pipelines."""
        ...

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get workflow details by ID or name."""
        ...

    # Run operations
    def list_runs(
        self,
        workflow_id: Optional[str] = None,
        branch: Optional[str] = None,
        status: Optional[RunStatus] = None,
        limit: int = 20,
    ) -> List[Run]:
        """List workflow runs with optional filters."""
        ...

    def get_run(self, run_id: str) -> Optional[Run]:
        """Get detailed run information including jobs."""
        ...

    def get_run_logs(
        self,
        run_id: str,
        job_id: Optional[str] = None,
    ) -> RunLogs:
        """Get logs from a run or specific job."""
        ...

    def get_run_jobs(self, run_id: str) -> List[Job]:
        """Get jobs for a specific run."""
        ...

    # Actions
    def trigger_workflow(
        self,
        workflow_id: str,
        ref: str = "main",
        inputs: Optional[Dict[str, Any]] = None,
    ) -> Run:
        """
        Trigger a workflow run.

        Args:
            workflow_id: Workflow ID or filename
            ref: Git ref (branch, tag, SHA)
            inputs: workflow_dispatch inputs

        Returns:
            Created Run object
        """
        ...

    def cancel_run(self, run_id: str) -> bool:
        """Cancel a running workflow."""
        ...

    def retry_run(self, run_id: str, failed_jobs_only: bool = True) -> Run:
        """
        Retry a failed run.

        Args:
            run_id: Run to retry
            failed_jobs_only: If True, only retry failed jobs

        Returns:
            New Run object
        """
        ...

    # Secrets/Variables (metadata only - values never exposed)
    def list_secrets(self, scope: str = "repository") -> List[str]:
        """List configured secret names (not values)."""
        ...

    def list_variables(self, scope: str = "repository") -> Dict[str, str]:
        """List configured variables with values."""
        ...

    # Analysis
    def analyze_failure(self, run_id: str) -> FailureAnalysis:
        """
        Analyze a failed run and suggest fixes.

        Uses semantic analysis via embeddings for intelligent suggestions.
        """
        ...
