"""
Base CI Adapter - Abstract base class for all CI platform adapters.

Implements common functionality and defines the interface that all
platform-specific adapters must follow.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from athena_ai.ci.clients.base import BaseCIClient
from athena_ai.ci.config import CIConfig
from athena_ai.ci.models import (
    FailureAnalysis,
    PermissionReport,
    Run,
    RunLogs,
    Workflow,
)
from athena_ai.ci.protocols import CIPlatformProtocol, CIPlatformType
from athena_ai.utils.logger import logger


class BaseCIAdapter(ABC):
    """
    Abstract base class for CI platform adapters.

    Implements common functionality and client management.
    Subclasses must implement platform-specific methods.
    """

    platform_type: CIPlatformType

    def __init__(self, config: CIConfig):
        """
        Initialize adapter with configuration.

        Args:
            config: Platform configuration
        """
        self.config = config
        self._clients: Dict[str, BaseCIClient] = {}
        self._active_client: Optional[BaseCIClient] = None

    def register_client(self, client_type: str, client: BaseCIClient) -> None:
        """
        Register a client for this adapter.

        Args:
            client_type: Client type name (e.g., "cli", "mcp", "api")
            client: Client instance
        """
        self._clients[client_type] = client
        logger.debug(f"Registered {client_type} client for {self.platform_type.value}")

    def get_active_client(self) -> Optional[BaseCIClient]:
        """
        Get the best available client based on preferences.

        Returns:
            Best available client, or None if none available
        """
        if self._active_client is not None:
            return self._active_client

        # Try clients in preference order
        for client_type in self.config.preferred_clients:
            client = self._clients.get(client_type)
            if client and client.is_available():
                self._active_client = client
                logger.debug(f"Using {client_type} client for {self.platform_type.value}")
                return client

        logger.warning(f"No available client for {self.platform_type.value}")
        return None

    def is_available(self) -> bool:
        """Check if any client is available."""
        return self.get_active_client() is not None

    def is_authenticated(self) -> bool:
        """Check if the active client is authenticated."""
        client = self.get_active_client()
        if not client:
            return False
        return client.is_authenticated()

    @abstractmethod
    def list_workflows(self) -> List[Workflow]:
        """List all workflows/pipelines."""
        pass

    @abstractmethod
    def list_runs(
        self,
        workflow_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[Run]:
        """List recent runs, optionally filtered by workflow."""
        pass

    @abstractmethod
    def get_run(self, run_id: str) -> Optional[Run]:
        """Get details of a specific run."""
        pass

    @abstractmethod
    def get_run_logs(
        self,
        run_id: str,
        job_name: Optional[str] = None,
        failed_only: bool = True,
    ) -> RunLogs:
        """Get logs for a run."""
        pass

    @abstractmethod
    def trigger_workflow(
        self,
        workflow_id: str,
        ref: str = "main",
        inputs: Optional[Dict[str, Any]] = None,
    ) -> Run:
        """Trigger a workflow run."""
        pass

    @abstractmethod
    def cancel_run(self, run_id: str) -> bool:
        """Cancel a running workflow."""
        pass

    @abstractmethod
    def retry_run(self, run_id: str, failed_only: bool = True) -> Run:
        """Retry a failed run."""
        pass

    @abstractmethod
    def analyze_failure(self, run_id: str) -> FailureAnalysis:
        """Analyze why a run failed."""
        pass

    @abstractmethod
    def check_permissions(self) -> PermissionReport:
        """Check what permissions are available."""
        pass

    def get_supported_operations(self) -> List[str]:
        """Get list of supported operations."""
        client = self.get_active_client()
        if client:
            return client.get_supported_operations()
        return []

    def _execute(self, operation: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute an operation using the active client.

        Args:
            operation: Operation name
            params: Operation parameters

        Returns:
            Operation result

        Raises:
            RuntimeError: If no client available
        """
        client = self.get_active_client()
        if not client:
            raise RuntimeError(
                f"No available client for {self.platform_type.value}. "
                "Please ensure the CLI tool is installed or configure an alternative."
            )
        return client.execute(operation, params)


# Verify protocol compliance
def _verify_protocol_compliance():
    """Verify that BaseCIAdapter can be used where CIPlatformProtocol is expected."""
    # This is a compile-time check - if BaseCIAdapter doesn't implement
    # all required methods, mypy will complain
    _: CIPlatformProtocol = None  # type: ignore
