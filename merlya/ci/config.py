"""
CI Platform Configuration.

Dataclass for configuring CI/CD platform connections.
Supports multiple authentication methods and client preferences.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CIConfig:
    """
    Configuration for a CI platform connection.

    Supports:
    - Multiple authentication methods (env vars, secrets, CLI auth)
    - Client preferences (CLI > MCP > API)
    - Platform-specific options
    """

    # Platform identification
    platform: str  # "github", "gitlab", "jenkins", etc.

    # Repository context (auto-detected if not provided)
    repo_owner: Optional[str] = None
    repo_name: Optional[str] = None
    project_path: Optional[str] = None  # For GitLab: "owner/repo" or "group/subgroup/repo"

    # Authentication (secrets handled via CredentialManager - never persisted)
    token_env_var: str = ""  # e.g., "GITHUB_TOKEN", "GITLAB_TOKEN"
    token_secret_key: str = ""  # Key in Merlya's secret store

    # API configuration
    api_base_url: Optional[str] = None  # Custom API URL (for self-hosted)

    # Client preferences (order of preference for accessing the platform)
    preferred_clients: List[str] = field(
        default_factory=lambda: ["cli", "mcp", "api"]
    )

    # MCP server configuration
    mcp_server_name: Optional[str] = None  # e.g., "github"

    # CLI configuration
    cli_command: Optional[str] = None  # e.g., "gh", "glab", "jenkins-cli"

    # Platform-specific options
    options: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def for_github(
        cls,
        repo_owner: Optional[str] = None,
        repo_name: Optional[str] = None,
        api_base_url: Optional[str] = None,
    ) -> "CIConfig":
        """Create config for GitHub Actions."""
        return cls(
            platform="github",
            repo_owner=repo_owner,
            repo_name=repo_name,
            token_env_var="GITHUB_TOKEN",
            token_secret_key="github_token",
            api_base_url=api_base_url or "https://api.github.com",
            mcp_server_name="github",
            cli_command="gh",
        )

    @classmethod
    def for_gitlab(
        cls,
        project_path: Optional[str] = None,
        api_base_url: Optional[str] = None,
    ) -> "CIConfig":
        """Create config for GitLab CI."""
        return cls(
            platform="gitlab",
            project_path=project_path,
            token_env_var="GITLAB_TOKEN",
            token_secret_key="gitlab_token",
            api_base_url=api_base_url or "https://gitlab.com/api/v4",
            cli_command="glab",
        )

    @classmethod
    def for_jenkins(
        cls,
        api_base_url: str,
        job_name: Optional[str] = None,
    ) -> "CIConfig":
        """Create config for Jenkins."""
        return cls(
            platform="jenkins",
            token_env_var="JENKINS_API_TOKEN",
            token_secret_key="jenkins_token",
            api_base_url=api_base_url,
            preferred_clients=["api"],  # Jenkins is primarily API-based
            options={"job_name": job_name} if job_name else {},
        )

    @classmethod
    def for_circleci(
        cls,
        project_slug: Optional[str] = None,
    ) -> "CIConfig":
        """Create config for CircleCI."""
        return cls(
            platform="circleci",
            project_path=project_slug,  # e.g., "gh/owner/repo"
            token_env_var="CIRCLECI_TOKEN",
            token_secret_key="circleci_token",
            api_base_url="https://circleci.com/api/v2",
            preferred_clients=["api"],
        )

    def get_repo_slug(self) -> Optional[str]:
        """Get repository slug (owner/repo format)."""
        if self.repo_owner and self.repo_name:
            return f"{self.repo_owner}/{self.repo_name}"
        return self.project_path
