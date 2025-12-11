"""
Merlya Skills - Data models.

Pydantic models for skill configuration and results.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


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
    description: str = Field(default="", description="Human-readable description")

    # Intent matching
    intent_patterns: list[str] = Field(
        default_factory=list,
        description="Regex patterns to match user intents",
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
        default=5,
        ge=1,
        le=100,
        description="Maximum hosts to execute on in parallel",
    )
    timeout_seconds: int = Field(
        default=120,
        ge=10,
        le=600,
        description="Maximum execution time per host",
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

        status_emoji = {
            SkillStatus.SUCCESS: "✅",
            SkillStatus.PARTIAL: "⚠️",
            SkillStatus.FAILED: "❌",
            SkillStatus.TIMEOUT: "⏱️",
            SkillStatus.CANCELLED: "🚫",
            SkillStatus.RUNNING: "🔄",
            SkillStatus.PENDING: "⏳",
        }

        emoji = status_emoji.get(self.status, "❓")
        rate = f"{self.success_rate:.0f}%"

        return (
            f"{emoji} {self.skill_name}: {self.status.value} "
            f"({self.succeeded_hosts}/{self.total_hosts} hosts, {rate})"
        )
