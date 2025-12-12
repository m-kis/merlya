"""
Merlya Skills - Data models.

Pydantic models for skill configuration and results.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Required at runtime for Pydantic
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

# Constants for skill configuration limits
DEFAULT_MAX_HOSTS = 5
MIN_MAX_HOSTS = 1
MAX_MAX_HOSTS = 100

# Timeout configuration
# With activity-based timeout, we can allow longer max timeouts safely
# The idle timeout (default 60s) catches truly stuck executions
DEFAULT_TIMEOUT_SECONDS = 300  # 5 minutes default (activity timeout protects us)
MIN_TIMEOUT_SECONDS = 30  # Minimum 30s to allow LLM response time
MAX_TIMEOUT_SECONDS = 1800  # 30 minutes max for complex operations

# Limits for validation
MAX_INTENT_PATTERNS = 50
MAX_PATTERN_LENGTH = 500
MAX_NAME_LENGTH = 50
MAX_DESCRIPTION_LENGTH = 1000
MAX_SYSTEM_PROMPT_LENGTH = 10000

# Status emoji mapping
STATUS_EMOJI = {
    "success": "✅",
    "partial": "⚠️",
    "failed": "❌",
    "timeout": "⏱️",
    "cancelled": "🚫",
    "running": "🔄",
    "pending": "⏳",
}


class SkillStatus(str, Enum):
    """Skill execution status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"  # Some hosts succeeded, some failed
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class SkillConfig(BaseModel):
    """Configuration for a skill.

    Skills are reusable workflows that execute on one or more hosts.
    They define what tools are allowed, timeouts, and execution parameters.

    Example YAML:
        name: disk_audit
        version: "1.0"
        description: "Check disk usage across hosts"
        intent_patterns:
          - "disk.*"
          - "storage.*"
        tools_allowed:
          - ssh_execute
          - read_file
        max_hosts: 10
        timeout_seconds: 120
    """

    # Identity
    name: str = Field(description="Unique skill name")
    version: str = Field(default="1.0", description="Skill version")
    # IMPORTANT: description is used for semantic matching via ONNX embeddings
    # Write a clear, descriptive text that explains what this skill does
    # Example: "Audit disk usage and storage capacity across servers"
    description: str = Field(
        default="",
        description="Skill description - used for semantic intent matching",
    )

    # Intent matching
    # NOTE: intent_patterns is DEPRECATED - use description for semantic matching
    # The description field is now used by the ONNX embedding model to understand
    # when this skill should be triggered. Regex patterns are kept for backward
    # compatibility but semantic matching is preferred.
    intent_patterns: list[str] = Field(
        default_factory=list,
        description="DEPRECATED: Regex patterns for fallback matching. Use description instead.",
    )

    # Input/Output schemas (optional)
    input_schema: str | None = Field(
        default=None,
        description="Pydantic model name for input validation",
    )
    output_schema: str | None = Field(
        default=None,
        description="Pydantic model name for output structure",
    )

    # Tool permissions
    tools_allowed: list[str] = Field(
        default_factory=list,
        description="List of tool names this skill can use",
    )

    # Execution limits
    max_hosts: int = Field(
        default=DEFAULT_MAX_HOSTS,
        ge=MIN_MAX_HOSTS,
        le=MAX_MAX_HOSTS,
        description="Maximum hosts to execute on in parallel",
    )
    timeout_seconds: int = Field(
        default=DEFAULT_TIMEOUT_SECONDS,
        ge=MIN_TIMEOUT_SECONDS,
        le=MAX_TIMEOUT_SECONDS,
        description="Maximum execution time per host",
    )

    # Localhost safety
    localhost_safe: bool = Field(
        default=False,
        description="Whether this skill can safely default to localhost when no hosts specified and max_hosts == 1",
    )

    # Confirmation requirements
    require_confirmation_for: list[str] = Field(
        default_factory=lambda: ["restart", "kill", "delete", "stop"],
        description="Operations requiring user confirmation",
    )

    # System prompt for LLM
    system_prompt: str | None = Field(
        default=None,
        description="Custom system prompt for this skill's LLM context",
    )

    # Metadata
    author: str | None = Field(default=None, description="Skill author")
    tags: list[str] = Field(default_factory=list, description="Categorization tags")
    builtin: bool = Field(default=False, description="Whether this is a builtin skill")

    # Source
    source_path: str | None = Field(
        default=None,
        description="Path to the YAML file (set by loader)",
    )

    @field_validator("intent_patterns")
    @classmethod
    def validate_intent_patterns(cls, v: list[str]) -> list[str]:
        """Validate intent patterns count, length, and specificity."""
        if v is None:
            return []  # Empty means skill won't auto-match

        # Reject catch-all patterns
        forbidden = {".*", ".+", "^.*$", "^.+$", r"[\s\S]*", r"[\s\S]+"}
        filtered = []
        for pattern in v:
            if pattern in forbidden:
                # Skip catch-all patterns silently (warning logged in registry)
                continue
            if len(pattern) > MAX_PATTERN_LENGTH:
                raise ValueError(f"Pattern too long (max {MAX_PATTERN_LENGTH} chars)")
            filtered.append(pattern)

        if len(filtered) > MAX_INTENT_PATTERNS:
            raise ValueError(f"Too many intent patterns (max {MAX_INTENT_PATTERNS})")

        return filtered

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate skill name format."""
        if len(v) > MAX_NAME_LENGTH:
            raise ValueError(f"Name too long (max {MAX_NAME_LENGTH} chars)")
        if not v or len(v) < 2:
            raise ValueError("Name must be at least 2 characters")
        # Only allow alphanumeric, underscore, hyphen
        import re

        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", v):
            raise ValueError("Name must start with letter and contain only letters, numbers, _, -")
        return v.lower()

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        """Validate description length."""
        if v is None:
            return ""
        if len(v) > MAX_DESCRIPTION_LENGTH:
            raise ValueError(f"Description too long (max {MAX_DESCRIPTION_LENGTH} chars)")
        return v

    @field_validator("system_prompt")
    @classmethod
    def validate_system_prompt(cls, v: str | None) -> str | None:
        """Validate system prompt length."""
        if v is None:
            return None
        if v and len(v) > MAX_SYSTEM_PROMPT_LENGTH:
            raise ValueError(f"System prompt too long (max {MAX_SYSTEM_PROMPT_LENGTH} chars)")
        return v


class HostResult(BaseModel):
    """Result from executing a skill on a single host."""

    host: str = Field(description="Host identifier")
    success: bool = Field(description="Whether execution succeeded")
    output: str | None = Field(default=None, description="Execution output")
    error: str | None = Field(default=None, description="Error message if failed")
    duration_ms: int = Field(default=0, description="Execution time in milliseconds")
    tool_calls: int = Field(default=0, description="Number of tool calls made")


class SkillResult(BaseModel):
    """Result from executing a skill.

    Contains aggregated results from all hosts and metadata.
    """

    # Identity
    skill_name: str = Field(description="Name of the executed skill")
    execution_id: str = Field(description="Unique execution identifier")

    # Status
    status: SkillStatus = Field(description="Overall execution status")

    # Timing
    started_at: datetime = Field(description="When execution started")
    completed_at: datetime | None = Field(default=None, description="When execution completed")
    duration_ms: int = Field(default=0, description="Total execution time")

    # Results per host
    host_results: list[HostResult] = Field(
        default_factory=list,
        description="Results from each host",
    )

    # Aggregated stats
    total_hosts: int = Field(default=0, description="Number of hosts targeted")
    succeeded_hosts: int = Field(default=0, description="Number of successful hosts")
    failed_hosts: int = Field(default=0, description="Number of failed hosts")

    # Summary
    summary: str | None = Field(default=None, description="Human-readable summary")

    # Raw data for further processing
    raw_output: dict[str, Any] = Field(
        default_factory=dict,
        description="Raw output data for programmatic access",
    )

    @property
    def success_rate(self) -> float:
        """Calculate success rate as a percentage."""
        if self.total_hosts == 0:
            return 0.0
        return (self.succeeded_hosts / self.total_hosts) * 100

    @property
    def is_success(self) -> bool:
        """Check if all hosts succeeded."""
        return self.status == SkillStatus.SUCCESS

    @property
    def is_partial(self) -> bool:
        """Check if some hosts failed."""
        return self.status == SkillStatus.PARTIAL

    def to_summary(self) -> str:
        """Generate a summary string."""
        if self.summary:
            return self.summary

        emoji = STATUS_EMOJI.get(self.status.value, "❓")
        rate = f"{self.success_rate:.0f}%"

        return (
            f"{emoji} {self.skill_name}: {self.status.value} "
            f"({self.succeeded_hosts}/{self.total_hosts} hosts, {rate})"
        )
