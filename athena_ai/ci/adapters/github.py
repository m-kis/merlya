"""
GitHub CI Adapter - GitHub Actions integration.

Supports:
- CLI (gh) - primary method
- MCP server (github) - if available
- REST API - fallback

Follows Athena's philosophy: use whatever tool is available.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from athena_ai.ci.adapters.base import BaseCIAdapter
from athena_ai.ci.clients.base import CIClientError
from athena_ai.ci.clients.cli_client import CLIClient
from athena_ai.ci.config import CIConfig
from athena_ai.ci.models import (
    CIErrorType,
    FailureAnalysis,
    Job,
    PermissionReport,
    Run,
    RunLogs,
    Step,
    Workflow,
)
from athena_ai.ci.protocols import CIPlatformType, RunStatus
from athena_ai.ci.analysis.error_classifier import CIErrorClassifier
from athena_ai.utils.logger import logger


class GitHubCIAdapter(BaseCIAdapter):
    """
    GitHub Actions adapter.

    Uses gh CLI as primary client, with fallback to MCP and API.
    Implements full CI/CD operations: list, trigger, cancel, retry, analyze.
    """

    platform_type = CIPlatformType.GITHUB

    def __init__(self, config: Optional[CIConfig] = None):
        """
        Initialize GitHub adapter.

        Args:
            config: Optional configuration. If not provided, uses defaults.
        """
        if config is None:
            config = CIConfig.for_github()

        super().__init__(config)

        # Register CLI client
        cli_client = CLIClient(
            platform="github",
            repo_slug=config.get_repo_slug(),
        )
        self.register_client("cli", cli_client)

        # Error classifier (lazy-loaded, shared across adapter)
        self._error_classifier: Optional[CIErrorClassifier] = None

        # TODO: Register MCP client when available
        # TODO: Register API client when available

    @property
    def error_classifier(self) -> CIErrorClassifier:
        """Get or create error classifier."""
        if self._error_classifier is None:
            self._error_classifier = CIErrorClassifier()
        return self._error_classifier

    def list_workflows(self) -> List[Workflow]:
        """List all GitHub Actions workflows."""
        try:
            result = self._execute("list_workflows", {})
            data = result.get("data", [])

            workflows = []
            for item in data or []:
                workflows.append(
                    Workflow(
                        id=str(item.get("id", "")),
                        name=item.get("name", "Unknown"),
                        path=item.get("path", ""),
                        state=item.get("state", "unknown"),
                        platform=CIPlatformType.GITHUB,
                    )
                )

            return workflows

        except CIClientError as e:
            logger.error(f"Failed to list workflows: {e}")
            return []

    def list_runs(
        self,
        workflow_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[Run]:
        """List recent workflow runs."""
        try:
            if workflow_id:
                result = self._execute(
                    "list_runs_filtered",
                    {"workflow_id": workflow_id, "limit": limit},
                )
            else:
                result = self._execute("list_runs", {"limit": limit})

            data = result.get("data", [])

            runs = []
            for item in data or []:
                runs.append(self._parse_run(item))

            return runs

        except CIClientError as e:
            logger.error(f"Failed to list runs: {e}")
            return []

    def get_run(self, run_id: str) -> Optional[Run]:
        """Get details of a specific run."""
        try:
            result = self._execute("get_run", {"run_id": run_id})
            data = result.get("data")

            if not data:
                return None

            return self._parse_run(data, include_jobs=True)

        except CIClientError as e:
            logger.error(f"Failed to get run {run_id}: {e}")
            return None

    def get_run_logs(
        self,
        run_id: str,
        job_name: Optional[str] = None,
        failed_only: bool = True,
    ) -> RunLogs:
        """Get logs for a run."""
        try:
            operation = "get_run_logs" if failed_only else "get_run_logs_full"
            result = self._execute(operation, {"run_id": run_id})

            raw_logs = result.get("raw", "")

            # Parse logs by job
            job_logs = self._parse_job_logs(raw_logs)

            # Filter by job name if specified
            if job_name and job_name in job_logs:
                job_logs = {job_name: job_logs[job_name]}

            return RunLogs(
                run_id=run_id,
                raw_logs=raw_logs,
                job_logs=job_logs,
                truncated=len(raw_logs) > 100000,  # gh truncates at ~100KB
            )

        except CIClientError as e:
            logger.error(f"Failed to get logs for run {run_id}: {e}")
            return RunLogs(
                run_id=run_id,
                raw_logs=f"Error fetching logs: {e}",
                job_logs={},
                error=str(e),
            )

    def trigger_workflow(
        self,
        workflow_id: str,
        ref: str = "main",
        inputs: Optional[Dict[str, Any]] = None,
    ) -> Run:
        """Trigger a workflow run."""
        try:
            if inputs:
                self._execute(
                    "trigger_workflow_inputs",
                    {"workflow_id": workflow_id, "ref": ref, "inputs": inputs},
                )
            else:
                self._execute(
                    "trigger_workflow",
                    {"workflow_id": workflow_id, "ref": ref},
                )

            # gh workflow run doesn't return the run ID directly
            # We need to fetch the most recent run
            import time
            time.sleep(2)  # Wait for run to be created

            runs = self.list_runs(workflow_id=workflow_id, limit=1)
            if runs:
                return runs[0]

            # Return placeholder if we couldn't get the run
            return Run(
                id="pending",
                name=f"Triggered: {workflow_id}",
                status=RunStatus.QUEUED,
                workflow_id=workflow_id,
                branch=ref,
                platform=CIPlatformType.GITHUB,
            )

        except CIClientError as e:
            logger.error(f"Failed to trigger workflow {workflow_id}: {e}")
            raise RuntimeError(f"Failed to trigger workflow: {e}")

    def cancel_run(self, run_id: str) -> bool:
        """Cancel a running workflow."""
        try:
            self._execute("cancel_run", {"run_id": run_id})
            return True
        except CIClientError as e:
            logger.error(f"Failed to cancel run {run_id}: {e}")
            return False

    def retry_run(self, run_id: str, failed_only: bool = True) -> Run:
        """Retry a failed run."""
        try:
            operation = "retry_run_failed" if failed_only else "retry_run"
            self._execute(operation, {"run_id": run_id})

            # Fetch the new run
            import time
            time.sleep(2)

            run = self.get_run(run_id)
            if run:
                return run

            return Run(
                id=run_id,
                name="Retried run",
                status=RunStatus.QUEUED,
                platform=CIPlatformType.GITHUB,
            )

        except CIClientError as e:
            logger.error(f"Failed to retry run {run_id}: {e}")
            raise RuntimeError(f"Failed to retry run: {e}")

    def analyze_failure(self, run_id: str) -> FailureAnalysis:
        """
        Analyze why a run failed.

        Uses semantic analysis via EmbeddingCache for error classification.
        """
        # Get run details and logs
        run = self.get_run(run_id)
        logs = self.get_run_logs(run_id, failed_only=True)

        if not run:
            return FailureAnalysis(
                run_id=run_id,
                error_type=CIErrorType.UNKNOWN,
                summary="Could not retrieve run information",
                raw_error="",
            )

        # Extract error messages from logs
        error_messages = self._extract_errors(logs.raw_logs)
        raw_error = "\n".join(error_messages[:10])  # First 10 errors

        # Classify using semantic analysis
        classification = self.error_classifier.classify(raw_error)
        error_type = classification.error_type

        # Build summary
        summary = self._build_failure_summary(run, error_type, error_messages)

        # Find failed jobs
        failed_jobs = []
        if run.jobs:
            failed_jobs = [j.name for j in run.jobs if j.conclusion == "failure"]

        return FailureAnalysis(
            run_id=run_id,
            error_type=error_type,
            summary=summary,
            raw_error=raw_error,
            failed_jobs=failed_jobs,
            suggestions=self.error_classifier.get_suggestions(error_type, raw_error),
            confidence=classification.confidence,
        )

    def check_permissions(self) -> PermissionReport:
        """Check available GitHub permissions."""
        permissions = []
        missing = []
        scopes: List[str] = []

        # Check authentication
        client = self.get_active_client()
        if not client:
            return PermissionReport(
                authenticated=False,
                permissions=[],
                missing_permissions=["cli_not_available"],
                scopes=[],
                can_read=False,
                can_write=False,
                can_admin=False,
            )

        authenticated = client.is_authenticated()

        if authenticated:
            # Test read permissions
            try:
                self.list_workflows()
                permissions.append("read:workflows")
            except Exception:
                missing.append("read:workflows")

            # Test run listing
            try:
                self.list_runs(limit=1)
                permissions.append("read:runs")
            except Exception:
                missing.append("read:runs")

            # Check secrets access (metadata only)
            try:
                self._execute("list_secrets", {})
                permissions.append("read:secrets")
            except CIClientError:
                missing.append("read:secrets")

        can_read = "read:workflows" in permissions or "read:runs" in permissions
        can_write = authenticated  # Assume write if authenticated
        can_admin = "read:secrets" in permissions

        return PermissionReport(
            authenticated=authenticated,
            permissions=permissions,
            missing_permissions=missing,
            scopes=scopes,
            can_read=can_read,
            can_write=can_write,
            can_admin=can_admin,
        )

    # Helper methods

    def _parse_run(self, data: Dict[str, Any], include_jobs: bool = False) -> Run:
        """Parse run data from gh JSON output."""
        # Parse timestamps
        created_at = None
        updated_at = None

        if data.get("createdAt"):
            try:
                created_at = datetime.fromisoformat(
                    data["createdAt"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        if data.get("updatedAt"):
            try:
                updated_at = datetime.fromisoformat(
                    data["updatedAt"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        # Parse jobs if included
        jobs = None
        if include_jobs and data.get("jobs"):
            jobs = [self._parse_job(j) for j in data["jobs"]]

        return Run(
            id=str(data.get("databaseId", "")),
            name=data.get("displayTitle", "Unknown"),
            status=RunStatus.from_github(
                data.get("status", "unknown"),
                data.get("conclusion"),
            ),
            conclusion=data.get("conclusion"),
            workflow_id=data.get("workflowName", ""),
            workflow_name=data.get("workflowName"),
            branch=data.get("headBranch", ""),
            commit_sha=data.get("headSha"),
            url=data.get("url"),
            created_at=created_at,
            updated_at=updated_at,
            event=data.get("event"),
            jobs=jobs,
            platform=CIPlatformType.GITHUB,
        )

    def _parse_job(self, data: Dict[str, Any]) -> Job:
        """Parse job data from gh JSON output."""
        # Parse timestamps
        started_at = None
        completed_at = None

        if data.get("startedAt"):
            try:
                started_at = datetime.fromisoformat(
                    data["startedAt"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        if data.get("completedAt"):
            try:
                completed_at = datetime.fromisoformat(
                    data["completedAt"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        # Parse steps
        steps = None
        if data.get("steps"):
            steps = [self._parse_step(s) for s in data["steps"]]

        return Job(
            id=str(data.get("databaseId", "")),
            name=data.get("name", "Unknown"),
            status=data.get("status", "unknown"),
            conclusion=data.get("conclusion"),
            started_at=started_at,
            completed_at=completed_at,
            steps=steps,
        )

    def _parse_step(self, data: Dict[str, Any]) -> Step:
        """Parse step data from gh JSON output."""
        return Step(
            name=data.get("name", "Unknown"),
            status=data.get("status", "unknown"),
            conclusion=data.get("conclusion"),
            number=data.get("number", 0),
        )

    def _parse_job_logs(self, raw_logs: str) -> Dict[str, str]:
        """Parse raw logs into job-specific sections."""
        job_logs: Dict[str, str] = {}
        current_job = "default"
        current_lines: List[str] = []

        for line in raw_logs.split("\n"):
            # gh output format: "jobname<TAB>stepname<TAB>log line"
            if "\t" in line:
                parts = line.split("\t", 2)
                if len(parts) >= 1:
                    job_name = parts[0].strip()
                    if job_name and job_name != current_job:
                        if current_lines:
                            job_logs[current_job] = "\n".join(current_lines)
                        current_job = job_name
                        current_lines = []

            current_lines.append(line)

        # Save last job
        if current_lines:
            job_logs[current_job] = "\n".join(current_lines)

        return job_logs

    def _extract_errors(self, logs: str) -> List[str]:
        """Extract error messages from logs."""
        errors = []
        error_indicators = [
            "error:",
            "Error:",
            "ERROR:",
            "failed:",
            "Failed:",
            "FAILED:",
            "exception:",
            "Exception:",
            "EXCEPTION:",
            "fatal:",
            "Fatal:",
            "FATAL:",
            "::error::",
            "❌",
            "✗",
        ]

        for line in logs.split("\n"):
            line_stripped = line.strip()
            if any(indicator in line for indicator in error_indicators):
                if len(line_stripped) > 10:  # Skip very short lines
                    errors.append(line_stripped[:500])  # Truncate long lines

        return errors

    def _build_failure_summary(
        self,
        run: Run,
        error_type: CIErrorType,
        error_messages: List[str],
    ) -> str:
        """Build a human-readable failure summary."""
        parts = [f"Run '{run.name}' failed with {error_type.value}"]

        if run.jobs:
            failed_jobs = [j.name for j in run.jobs if j.conclusion == "failure"]
            if failed_jobs:
                parts.append(f"Failed jobs: {', '.join(failed_jobs)}")

        if error_messages:
            # Add first error message
            first_error = error_messages[0][:200]
            parts.append(f"First error: {first_error}")

        return ". ".join(parts)
