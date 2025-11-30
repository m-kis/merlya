"""
Base CI Client - Abstract base for CI platform clients.

Provides common functionality for CLI, MCP, and REST clients.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from athena_ai.utils.logger import logger


class CIClientError(Exception):
    """Exception raised when a CI client operation fails."""

    def __init__(
        self,
        message: str,
        operation: Optional[str] = None,
        exit_code: Optional[int] = None,
        stderr: Optional[str] = None,
    ):
        super().__init__(message)
        self.operation = operation
        self.exit_code = exit_code
        self.stderr = stderr


class BaseCIClient(ABC):
    """
    Abstract base class for CI platform clients.

    Implements the Strategy pattern for different access methods:
    - CLI: Execute commands via subprocess (gh, glab)
    - MCP: Use MCP server protocol
    - REST: Direct API calls

    Each subclass handles its specific communication method.
    """

    def __init__(self, platform: str):
        """
        Initialize the client.

        Args:
            platform: Platform name (e.g., "github", "gitlab")
        """
        self.platform = platform
        self._available: Optional[bool] = None

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if this client method is available and configured.

        Returns:
            True if client can be used
        """
        ...

    @abstractmethod
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

    # Patterns for sensitive data that should be redacted from logs
    SENSITIVE_PATTERNS = frozenset({
        "token", "secret", "password", "passwd", "pwd",
        "key", "api_key", "apikey", "auth", "credential",
        "bearer", "private", "cert", "ssh", "gpg",
    })

    def _log_operation(self, operation: str, params: Dict[str, Any]) -> None:
        """Log operation for debugging with sensitive data redaction."""
        safe_params = self._redact_sensitive(params)
        logger.debug(f"CI Client [{self.platform}] {operation}: {safe_params}")

    def _redact_sensitive(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively redact sensitive data from a dictionary.

        Args:
            data: Dictionary that may contain sensitive values

        Returns:
            Copy of dictionary with sensitive values replaced by "***"
        """
        result: Dict[str, Any] = {}
        for key, value in data.items():
            key_lower = key.lower()
            # Check if key matches any sensitive pattern
            is_sensitive = any(
                pattern in key_lower for pattern in self.SENSITIVE_PATTERNS
            )

            if is_sensitive:
                result[key] = "***"
            elif isinstance(value, dict):
                result[key] = self._redact_sensitive(value)
            elif isinstance(value, list):
                result[key] = [
                    self._redact_sensitive(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                result[key] = value

        return result
