"""
Core Exceptions - Unified error hierarchy for Athena.

Follows SRP: each exception type handles one category of errors.
"""


class AthenaError(Exception):
    """Base exception for all Athena errors."""

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

class ValidationError(AthenaError):
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


class InvalidCommandError(ValidationError):
    """Command validation failed."""
    pass


# =============================================================================
# Execution Errors
# =============================================================================

class ExecutionError(AthenaError):
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

class ConnectionError(AthenaError):
    """Generic connection error."""
    pass


class DatabaseConnectionError(ConnectionError):
    """Database connection failed."""
    pass


class APIConnectionError(ConnectionError):
    """External API connection failed."""
    pass


# =============================================================================
# Planning Errors
# =============================================================================

class PlanError(AthenaError):
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

class AgentError(AthenaError):
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

class SecurityError(AthenaError):
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

class ConfigurationError(AthenaError):
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
