"""
Merlya Config - Configuration models.

Pydantic models for type-safe configuration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class GeneralConfig(BaseModel):
    """General application settings."""

    language: str = Field(default="en", description="UI language (en, fr)")
    log_level: Literal["debug", "info", "warning", "error"] = Field(
        default="info", description="DEPRECATED: Use logging.console_level instead"
    )
    data_dir: Path = Field(default=Path.home() / ".merlya", description="Data directory path")


class LLMConfig(BaseModel):
    """LLM provider configuration."""

    provider: str = Field(default="openrouter", description="LLM provider name")
    model: str = Field(default="z-ai/glm-4.6", description="Default/orchestrator model")
    api_key_env: str | None = Field(default=None, description="Environment variable for API key")
    base_url: str | None = Field(default=None, description="Provider base URL (e.g., Ollama)")

    # Request timeout override (optional)
    # If not set, uses provider-specific defaults from constants.py
    timeout: int | None = Field(
        default=None,
        ge=10,
        le=600,
        description="LLM request timeout in seconds (default: provider-specific)",
    )

    # Agent-specific model overrides (optional)
    # If not set, uses provider defaults from providers.py
    reasoning_model: str | None = Field(
        default=None,
        description="Override for reasoning agents (diagnostic, security)",
    )
    fast_model: str | None = Field(
        default=None,
        description="Override for fast agents (query, execution)",
    )

    def get_orchestrator_model(self) -> str:
        """Get model for orchestrator (main brain). Uses reasoning_model or default."""
        return self.reasoning_model or self.model

    def get_reasoning_model(self) -> str:
        """Get model for reasoning tasks (diagnostic, security)."""
        from merlya.config.providers import get_model_for_role

        return get_model_for_role(self.provider, "reasoning", self.reasoning_model)

    def get_fast_model(self) -> str:
        """Get model for fast tasks (query, execution)."""
        from merlya.config.providers import get_model_for_role

        return get_model_for_role(self.provider, "fast", self.fast_model)

    def get_timeout(self) -> int:
        """
        Get LLM request timeout in seconds.

        Returns user-configured timeout if set, otherwise provider-specific default.
        Always returns an int - never returns None.
        """
        # If user configured a timeout, use it
        if self.timeout is not None:
            return self.timeout

        # Otherwise use provider-specific default or global default
        from merlya.config.constants import LLM_PROVIDER_TIMEOUTS, LLM_TIMEOUT_DEFAULT

        provider_key = self.provider.lower() if self.provider else ""
        return LLM_PROVIDER_TIMEOUTS.get(provider_key, LLM_TIMEOUT_DEFAULT)


class RouterConfig(BaseModel):
    """Intent router configuration."""

    type: Literal["local", "llm"] = Field(default="local", description="Router type")
    model: str | None = Field(default=None, description="Local embedding model ID")
    tier: str | None = Field(
        default=None, description="Model tier (performance, balanced, lightweight)"
    )
    llm_fallback: str = Field(
        default="openrouter:google/gemini-2.0-flash-lite-001",
        description="LLM fallback for routing",
    )


class SSHConfig(BaseModel):
    """SSH connection settings."""

    pool_timeout: int = Field(default=600, ge=60, le=3600, description="Pool timeout in seconds")
    connect_timeout: int = Field(
        default=30, ge=5, le=120, description="Connection timeout in seconds"
    )
    command_timeout: int = Field(
        default=60, ge=5, le=3600, description="Command timeout in seconds"
    )
    default_user: str | None = Field(default=None, description="Default SSH username")
    default_key: Path | None = Field(default=None, description="Default private key path")


class UIConfig(BaseModel):
    """UI settings."""

    theme: Literal["auto", "light", "dark"] = Field(default="auto", description="Color theme")
    markdown: bool = Field(default=True, description="Enable markdown rendering")
    syntax_highlight: bool = Field(default=True, description="Enable syntax highlighting")


class LoggingConfig(BaseModel):
    """Logging settings."""

    console_level: Literal["debug", "info", "warning", "error"] = Field(
        default="info", description="Console log level"
    )
    file_level: Literal["debug", "info", "warning", "error"] = Field(
        default="debug", description="File log level"
    )
    max_size_mb: int = Field(default=10, ge=1, le=100, description="Max log file size in MB")
    max_files: int = Field(default=5, ge=1, le=20, description="Max number of log files")
    retention_days: int = Field(default=7, ge=1, le=90, description="Log retention in days")


class MCPServerConfig(BaseModel):
    """Configuration for an MCP server."""

    command: str = Field(description="Executable to start the MCP server")
    args: list[str] = Field(default_factory=list, description="Arguments for the server command")
    env: dict[str, str] = Field(
        default_factory=dict, description="Environment variables for server"
    )
    cwd: Path | None = Field(default=None, description="Working directory for the server")
    enabled: bool = Field(default=True, description="Whether this server should be used")


class MCPConfig(BaseModel):
    """MCP integration configuration."""

    servers: dict[str, MCPServerConfig] = Field(default_factory=dict, description="MCP servers")
    default_timeout: int = Field(
        default=30, ge=5, le=300, description="Default timeout (seconds) for MCP requests"
    )


class PolicyConfig(BaseModel):
    """Policy configuration for context and execution limits.

    Controls context tier selection, token budgets, and execution guardrails.
    """

    # Context tier: auto (ContextTierPredictor) or manual override
    context_tier: Literal["auto", "minimal", "standard", "extended"] = Field(
        default="auto",
        description="Context tier: auto (predicted) or manual override",
    )

    # Token limits
    max_tokens_per_call: int = Field(
        default=8000,
        ge=1000,
        le=200000,
        description="Maximum tokens per LLM call",
    )

    # Parser settings
    parser_confidence_threshold: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for parser results",
    )

    # Execution limits
    max_hosts_per_skill: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum hosts per skill execution",
    )

    max_parallel_subagents: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum parallel subagents",
    )

    subagent_timeout: int = Field(
        default=120,
        ge=10,
        le=600,
        description="Subagent timeout in seconds",
    )

    # Safety guardrails
    require_confirmation_for_write: bool = Field(
        default=True,
        description="Require confirmation for write/destructive operations",
    )

    audit_logging: bool = Field(
        default=True,
        description="Enable audit logging for executed commands",
    )

    # Memory limits
    max_messages_in_memory: int = Field(
        default=1000,
        ge=100,
        le=10000,
        description="Maximum messages to keep in memory before forced summarization",
    )

    # Summarization
    auto_summarize: bool = Field(
        default=True,
        description="Enable automatic context summarization",
    )

    summarize_threshold: float = Field(
        default=0.75,
        ge=0.5,
        le=0.95,
        description="Threshold (% of max) to trigger summarization",
    )
