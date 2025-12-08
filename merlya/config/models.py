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
        default="info", description="Console log level"
    )
    data_dir: Path = Field(default=Path.home() / ".merlya", description="Data directory path")


class LLMConfig(BaseModel):
    """LLM provider configuration."""

    provider: str = Field(default="openrouter", description="LLM provider name")
    model: str = Field(default="amazon/nova-2-lite-v1:free", description="Model identifier")
    api_key_env: str | None = Field(default=None, description="Environment variable for API key")
    base_url: str | None = Field(default=None, description="Provider base URL (e.g., Ollama)")


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

    file_level: Literal["debug", "info", "warning", "error"] = Field(
        default="debug", description="File log level"
    )
    max_size_mb: int = Field(default=10, ge=1, le=100, description="Max log file size in MB")
    max_files: int = Field(default=5, ge=1, le=20, description="Max number of log files")
    retention_days: int = Field(default=7, ge=1, le=90, description="Log retention in days")
