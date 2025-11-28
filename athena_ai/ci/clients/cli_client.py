"""
CLI Client - Execute CI operations via command-line tools.

Supports gh (GitHub), glab (GitLab), and other CLI tools.
Follows Athena's philosophy: execute commands like a user would.
"""

import json
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from athena_ai.ci.clients.base import BaseCIClient, CIClientError
from athena_ai.utils.logger import logger


class CLIClient(BaseCIClient):
    """
    CI Client using command-line tools (gh, glab, etc.).

    This is the preferred access method as it:
    - Uses the user's existing authentication
    - Follows Athena's terminal-first philosophy
    - Provides transparent, auditable operations
    """

    # Command templates per platform and operation
    COMMAND_TEMPLATES: Dict[str, Dict[str, str]] = {
        "github": {
            # Auth
            "auth_status": "gh auth status",
            # Workflows
            "list_workflows": "gh workflow list --json id,name,path,state",
            "get_workflow": "gh workflow view {workflow_id} --json id,name,path",
            # Runs
            "list_runs": "gh run list --limit {limit} --json databaseId,displayTitle,status,conclusion,workflowName,headBranch,createdAt,updatedAt,url,event",
            "list_runs_filtered": "gh run list --workflow {workflow_id} --limit {limit} --json databaseId,displayTitle,status,conclusion,workflowName,headBranch,createdAt,updatedAt,url,event",
            "get_run": "gh run view {run_id} --json databaseId,displayTitle,status,conclusion,workflowName,headBranch,headSha,createdAt,updatedAt,url,event,jobs",
            "get_run_logs": "gh run view {run_id} --log-failed",
            "get_run_logs_full": "gh run view {run_id} --log",
            "get_run_jobs": "gh run view {run_id} --json jobs",
            # Actions
            "trigger_workflow": "gh workflow run {workflow_id} --ref {ref}",
            "trigger_workflow_inputs": "gh workflow run {workflow_id} --ref {ref} --field {inputs}",
            "cancel_run": "gh run cancel {run_id}",
            "retry_run": "gh run rerun {run_id}",
            "retry_run_failed": "gh run rerun {run_id} --failed",
            # Secrets (metadata only)
            "list_secrets": "gh secret list --json name,updatedAt",
            "list_variables": "gh variable list --json name,value,updatedAt",
        },
        "gitlab": {
            # Auth
            "auth_status": "glab auth status",
            # Pipelines
            "list_runs": "glab ci list --per-page {limit} --output json",
            "get_run": "glab ci view {run_id} --output json",
            "get_run_logs": "glab ci trace {run_id}",
            # Actions
            "trigger_workflow": "glab ci run --ref {ref}",
            "cancel_run": "glab ci cancel {run_id}",
            "retry_run": "glab ci retry {run_id}",
            # Variables
            "list_variables": "glab variable list --output json",
        },
    }

    # CLI commands per platform
    CLI_COMMANDS: Dict[str, str] = {
        "github": "gh",
        "gitlab": "glab",
    }

    def __init__(
        self,
        platform: str,
        cli_command: Optional[str] = None,
        repo_slug: Optional[str] = None,
    ):
        """
        Initialize CLI client.

        Args:
            platform: Platform name ("github", "gitlab")
            cli_command: Override CLI command (default: auto-detect)
            repo_slug: Repository slug (owner/repo) for context
        """
        super().__init__(platform)
        self.cli_command = cli_command or self.CLI_COMMANDS.get(platform, platform)
        self.repo_slug = repo_slug

    def is_available(self) -> bool:
        """Check if CLI tool is available in PATH."""
        if self._available is not None:
            return self._available

        self._available = shutil.which(self.cli_command) is not None
        if not self._available:
            logger.debug(f"CLI '{self.cli_command}' not found in PATH")

        return self._available

    def is_authenticated(self) -> bool:
        """Check if CLI is authenticated."""
        if not self.is_available():
            return False

        try:
            result = self.execute("auth_status", {}, timeout=10)
            return result.get("authenticated", False)
        except CIClientError:
            return False

    def execute(
        self,
        operation: str,
        params: Dict[str, Any],
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """
        Execute a CLI operation.

        Args:
            operation: Operation name from COMMAND_TEMPLATES
            params: Parameters to substitute in template
            timeout: Timeout in seconds

        Returns:
            Parsed JSON output or raw output dict

        Raises:
            CIClientError: If command fails
        """
        self._log_operation(operation, params)

        if not self.is_available():
            raise CIClientError(
                f"CLI '{self.cli_command}' not available",
                operation=operation,
            )

        # Get command template
        templates = self.COMMAND_TEMPLATES.get(self.platform, {})
        template = templates.get(operation)

        if not template:
            raise CIClientError(
                f"Unknown operation '{operation}' for platform '{self.platform}'",
                operation=operation,
            )

        # Build command
        cmd = self._build_command(template, params)

        # Execute
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            # Handle special case: auth_status
            if operation == "auth_status":
                return self._parse_auth_status(result)

            # Check for errors
            if result.returncode != 0:
                raise CIClientError(
                    f"Command failed: {result.stderr or result.stdout}",
                    operation=operation,
                    exit_code=result.returncode,
                    stderr=result.stderr,
                )

            # Parse output
            return self._parse_output(result.stdout, operation)

        except subprocess.TimeoutExpired:
            raise CIClientError(
                f"Command timed out after {timeout}s",
                operation=operation,
            )
        except Exception as e:
            if isinstance(e, CIClientError):
                raise
            raise CIClientError(
                f"Command execution failed: {e}",
                operation=operation,
            )

    def _build_command(self, template: str, params: Dict[str, Any]) -> str:
        """Build command string from template and params."""
        cmd = template

        # Handle special params
        if "inputs" in params and isinstance(params["inputs"], dict):
            # Convert dict to --field key=value pairs
            inputs_str = " ".join(
                f"--field {k}={v}" for k, v in params["inputs"].items()
            )
            params = {**params, "inputs": inputs_str}

        # Substitute params
        for key, value in params.items():
            placeholder = "{" + key + "}"
            if placeholder in cmd:
                cmd = cmd.replace(placeholder, str(value))

        # Add repo context if available
        if self.repo_slug and "-R" not in cmd and self.platform == "github":
            cmd = f"{cmd} -R {self.repo_slug}"

        return cmd

    def _parse_output(self, output: str, operation: str) -> Dict[str, Any]:
        """Parse command output, attempting JSON first."""
        output = output.strip()

        if not output:
            return {"data": None, "raw": ""}

        # Try JSON parse
        try:
            data = json.loads(output)
            return {"data": data, "raw": output}
        except json.JSONDecodeError:
            # Return raw output for non-JSON responses (like logs)
            return {"data": None, "raw": output}

    def _parse_auth_status(self, result: subprocess.CompletedProcess) -> Dict[str, Any]:
        """Parse authentication status output."""
        # gh auth status exits 0 if authenticated, 1 if not
        authenticated = result.returncode == 0
        output = result.stdout + result.stderr

        # Extract username if present
        username = None
        if "Logged in to" in output:
            # Parse: "Logged in to github.com as username"
            for line in output.split("\n"):
                if "Logged in to" in line and " as " in line:
                    username = line.split(" as ")[-1].split()[0].strip()
                    break

        return {
            "authenticated": authenticated,
            "username": username,
            "raw": output,
        }

    def get_supported_operations(self) -> List[str]:
        """Get list of supported operations for this platform."""
        return list(self.COMMAND_TEMPLATES.get(self.platform, {}).keys())
