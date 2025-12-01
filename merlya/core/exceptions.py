"""
Core Exceptions - Unified error hierarchy for Merlya.

Follows SRP: each exception type handles one category of errors.
"""


class MerlyaError(Exception):
    """Base exception for all Merlya errors."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | {self.details}"
        return self.message


# =============================================================================
# Validation Errors
# =============================================================================

class ValidationError(MerlyaError):
    """Input validation failed."""
    pass


class HostNotFoundError(ValidationError):
    """Host not found in inventory."""

    def __init__(self, hostname: str):
        super().__init__(
            f"Host '{hostname}' not found in inventory",
            {"hostname": hostname}
        )
        self.hostname = hostname


class SourceNotFoundError(ValidationError):
    """Inventory source not found."""

    def __init__(self, source_id: int):
        super().__init__(
            f"Source with ID {source_id} not found in inventory",
            {"source_id": source_id}
        )
        self.source_id = source_id


class InvalidCommandError(ValidationError):
    """Command validation failed."""
    pass


# =============================================================================
# Execution Errors
# =============================================================================

class ExecutionError(MerlyaError):
    """Command or action execution failed."""
    pass


class SSHConnectionError(ExecutionError):
    """SSH connection failed."""

    def __init__(self, host: str, reason: str):
        super().__init__(
            f"SSH connection to '{host}' failed: {reason}",
            {"host": host, "reason": reason}
        )
        self.host = host
        self.reason = reason


class CommandTimeoutError(ExecutionError):
    """Command execution timed out."""

    def __init__(self, command: str, timeout_seconds: int):
        super().__init__(
            f"Command timed out after {timeout_seconds}s",
            {"command": command, "timeout": timeout_seconds}
        )


class CommandFailedError(ExecutionError):
    """Command returned non-zero exit code."""

    def __init__(self, command: str, exit_code: int, stderr: str = ""):
        super().__init__(
            f"Command failed with exit code {exit_code}",
            {"command": command, "exit_code": exit_code, "stderr": stderr}
        )
        self.exit_code = exit_code
        self.stderr = stderr


# =============================================================================
# Connection Errors
# =============================================================================

class ConnectionError(MerlyaError):
    """Generic connection error."""
    pass


class DatabaseConnectionError(ConnectionError):
    """Database connection failed."""
    pass


class PersistenceError(MerlyaError):
    """Database persistence operation failed (insert, update, delete).

    Use this for transactional failures where data could not be saved.
    """

    def __init__(self, operation: str, reason: str, details: dict | None = None):
        super().__init__(
            f"Persistence error during {operation}: {reason}",
            {**(details or {}), "operation": operation, "reason": reason}
        )
        self.operation = operation
        self.reason = reason


class APIConnectionError(ConnectionError):
    """External API connection failed."""
    pass


# =============================================================================
# Planning Errors
# =============================================================================

class PlanError(MerlyaError):
    """Planning or plan execution failed."""
    pass


class PlanValidationError(PlanError):
    """Plan validation failed."""
    pass


class PlanExecutionError(PlanError):
    """Plan step execution failed."""

    def __init__(self, step_id: int, step_name: str, reason: str):
        super().__init__(
            f"Step {step_id} '{step_name}' failed: {reason}",
            {"step_id": step_id, "step_name": step_name}
        )


# =============================================================================
# Agent Errors
# =============================================================================

class AgentError(MerlyaError):
    """Agent execution error."""
    pass


class AgentNotFoundError(AgentError):
    """Agent not registered."""

    def __init__(self, agent_name: str):
        super().__init__(
            f"Agent '{agent_name}' not found in registry",
            {"agent_name": agent_name}
        )


class OrchestratorError(AgentError):
    """Orchestrator-level error."""
    pass


# =============================================================================
# Security Errors
# =============================================================================

class SecurityError(MerlyaError):
    """Security validation failed."""
    pass


class PermissionDeniedError(SecurityError):
    """Insufficient permissions."""

    def __init__(self, action: str, required_permission: str):
        super().__init__(
            f"Permission denied for '{action}': requires {required_permission}",
            {"action": action, "required": required_permission}
        )


class RiskLevelExceededError(SecurityError):
    """Action risk level exceeds threshold."""

    def __init__(self, action: str, risk_level: str):
        super().__init__(
            f"Action '{action}' has {risk_level} risk level - confirmation required",
            {"action": action, "risk_level": risk_level}
        )


# =============================================================================
# Configuration Errors
# =============================================================================

class ConfigurationError(MerlyaError):
    """Configuration error."""
    pass


class MissingAPIKeyError(ConfigurationError):
    """Required API key not configured."""

    def __init__(self, key_name: str):
        super().__init__(
            f"Missing required API key: {key_name}",
            {"key_name": key_name}
        )


class InvalidConfigError(ConfigurationError):
    """Invalid configuration value."""
    pass


class LLMInitializationError(ConfigurationError):
    """LLM router initialization failed.

    Raised when the LLM router cannot be initialized, typically due to
    missing API keys, network issues, or misconfiguration.
    """

    def __init__(self, reason: str, original_error: Exception | None = None):
        details = {"reason": reason}
        if original_error:
            details["original_error"] = str(original_error)
            details["original_error_type"] = type(original_error).__name__
        super().__init__(
            f"LLM router initialization failed: {reason}",
            details
        )
        self.reason = reason
        self.original_error = original_error
