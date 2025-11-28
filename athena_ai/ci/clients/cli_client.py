"""
CLI Client - Execute CI operations via command-line tools.

Supports gh (GitHub), glab (GitLab), and other CLI tools.
Follows Athena's philosophy: execute commands like a user would.

SECURITY: Uses list-based subprocess execution (shell=False) to prevent
command injection. All user inputs are validated before use.
"""

import json
import re
import shlex
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from athena_ai.ci.clients.base import BaseCIClient, CIClientError
from athena_ai.utils.logger import logger


# Input validation patterns
VALID_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_.-]+$')
VALID_REF_PATTERN = re.compile(r'^[a-zA-Z0-9/_.-]+$')
VALID_REPO_SLUG_PATTERN = re.compile(r'^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$')

# Maximum lengths to prevent DoS
MAX_ID_LENGTH = 100
MAX_REF_LENGTH = 200
MAX_REPO_SLUG_LENGTH = 200


def validate_id(value: str, name: str = "id") -> str:
    """Validate an ID parameter (run_id, workflow_id, etc.)."""
    if not value or not isinstance(value, str):
        raise ValueError(f"Invalid {name}: must be non-empty string")

    value = value.strip()

    if len(value) > MAX_ID_LENGTH:
        raise ValueError(f"Invalid {name}: too long (max {MAX_ID_LENGTH})")

    if not VALID_ID_PATTERN.match(value):
        raise ValueError(f"Invalid {name}: contains invalid characters")

    return value


def validate_ref(value: str) -> str:
    """Validate a git ref parameter (branch, tag)."""
    if not value or not isinstance(value, str):
        raise ValueError("Invalid ref: must be non-empty string")

    value = value.strip()

    if len(value) > MAX_REF_LENGTH:
        raise ValueError(f"Invalid ref: too long (max {MAX_REF_LENGTH})")

    if not VALID_REF_PATTERN.match(value):
        raise ValueError("Invalid ref: contains invalid characters")

    return value


def validate_repo_slug(value: str) -> str:
    """Validate a repository slug (owner/repo)."""
    if not value or not isinstance(value, str):
        raise ValueError("Invalid repo slug: must be non-empty string")

    value = value.strip()

    if len(value) > MAX_REPO_SLUG_LENGTH:
        raise ValueError(f"Invalid repo slug: too long (max {MAX_REPO_SLUG_LENGTH})")

    if not VALID_REPO_SLUG_PATTERN.match(value):
        raise ValueError("Invalid repo slug: must be owner/repo format")

    return value


def validate_limit(value: Any) -> int:
    """Validate a limit parameter."""
    try:
        limit = int(value)
        if limit < 1 or limit > 1000:
            raise ValueError("Invalid limit: must be between 1 and 1000")
        return limit
    except (TypeError, ValueError):
        raise ValueError("Invalid limit: must be a positive integer")


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

        Raises:
            ValueError: If repo_slug is invalid
        """
        super().__init__(platform)
        self.cli_command = cli_command or self.CLI_COMMANDS.get(platform, platform)
        # Validate repo_slug if provided
        self.repo_slug = validate_repo_slug(repo_slug) if repo_slug else None

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

    def _validate_params(self, operation: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and sanitize parameters based on operation type.

        Args:
            operation: Operation name
            params: Raw parameters

        Returns:
            Validated parameters

        Raises:
            ValueError: If validation fails
        """
        validated = {}

        for key, value in params.items():
            if key == "run_id":
                validated[key] = validate_id(value, "run_id")
            elif key == "workflow_id":
                validated[key] = validate_id(value, "workflow_id")
            elif key == "ref":
                validated[key] = validate_ref(value)
            elif key == "limit":
                validated[key] = validate_limit(value)
            elif key == "inputs":
                # Inputs dict - validate keys and values
                if isinstance(value, dict):
                    validated_inputs = {}
                    for k, v in value.items():
                        # Keys must be alphanumeric with underscores
                        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', str(k)):
                            raise ValueError(f"Invalid input key: {k}")
                        # Values are quoted when building command
                        validated_inputs[str(k)] = str(v)
                    validated[key] = validated_inputs
                else:
                    raise ValueError("inputs must be a dictionary")
            else:
                # Unknown params - reject for safety
                raise ValueError(f"Unknown parameter: {key}")

        return validated

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

        # Validate params before use
        try:
            validated_params = self._validate_params(operation, params)
        except ValueError as e:
            raise CIClientError(
                f"Parameter validation failed: {e}",
                operation=operation,
            )

        # Build command as list (shell=False for security)
        cmd_list = self._build_command_list(template, validated_params)

        # Execute with shell=False to prevent command injection
        try:
            result = subprocess.run(
                cmd_list,
                shell=False,
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
        """
        Build command string from template and params.

        DEPRECATED: Use _build_command_list for secure execution.
        Kept for backwards compatibility with tests.
        """
        cmd_list = self._build_command_list(template, params.copy())
        return " ".join(shlex.quote(arg) for arg in cmd_list)

    def _build_command_list(self, template: str, params: Dict[str, Any]) -> List[str]:
        """
        Build command as list for subprocess with shell=False.

        Args:
            template: Command template string
            params: Validated parameters

        Returns:
            Command as list of arguments
        """
        # Start with template, substitute simple params
        cmd_str = template

        # Handle inputs separately - they need special handling
        inputs_dict = params.pop("inputs", None) if "inputs" in params else None

        # Substitute simple params
        for key, value in params.items():
            placeholder = "{" + key + "}"
            if placeholder in cmd_str:
                cmd_str = cmd_str.replace(placeholder, str(value))

        # Parse template into list using shlex (safe for static templates)
        cmd_list = shlex.split(cmd_str)

        # Add inputs as separate --field arguments
        if inputs_dict:
            for k, v in inputs_dict.items():
                cmd_list.extend(["--field", f"{k}={v}"])

        # Add repo context if available (validated at init)
        if self.repo_slug and "-R" not in cmd_str and self.platform == "github":
            cmd_list.extend(["-R", self.repo_slug])

        return cmd_list

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
