"""
Merlya Subagents - Result models.

Pydantic models for subagent execution results and aggregation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field, computed_field, field_validator

# Size limits for safety
MAX_OUTPUT_LENGTH = 500_000  # 500KB max for output
MAX_ERROR_LENGTH = 100_000  # 100KB max for error messages
MAX_RAW_OUTPUT_SIZE = 1_000_000  # 1MB max for raw_output (serialized)

# ID length constants
SUBAGENT_ID_LENGTH = 8
EXECUTION_ID_LENGTH = 8


class SubagentStatus(str, Enum):
    """Status of a subagent execution."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


# Status emoji mapping
STATUS_EMOJI = {
    "pending": "⏳",
    "running": "🔄",
    "success": "✅",
    "failed": "❌",
    "timeout": "⏱️",
    "cancelled": "🚫",
}


class SubagentResult(BaseModel):
    """Result from a single subagent execution on one host.

    Captures the outcome of running a task on a specific host,
    including output, errors, timing, and tool usage metrics.

    Example:
        >>> result = SubagentResult(
        ...     host="web-01",
        ...     success=True,
        ...     output="Disk usage: 45%",
        ...     duration_ms=1500,
        ...     tool_calls=3,
        ... )
        >>> print(result.to_summary())
        ✅ web-01: success (1500ms, 3 tools)
    """

    # Host identification
    host: str = Field(description="Host identifier where subagent executed")
    subagent_id: str | None = Field(
        default=None,
        description="Unique subagent execution ID",
    )

    # Execution status
    success: bool = Field(description="Whether execution succeeded")
    status: SubagentStatus = Field(
        default=SubagentStatus.PENDING,
        description="Detailed execution status",
    )

    # Output and errors
    output: str | None = Field(
        default=None,
        description="Execution output (may be truncated)",
    )
    error: str | None = Field(
        default=None,
        description="Error message if failed",
    )
    raw_output: dict[str, Any] = Field(
        default_factory=dict,
        description="Raw structured output for programmatic access",
    )

    # Timing
    started_at: datetime | None = Field(
        default=None,
        description="When execution started",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="When execution completed",
    )
    duration_ms: int = Field(
        default=0,
        ge=0,
        description="Execution time in milliseconds",
    )

    # Metrics
    tool_calls: int = Field(
        default=0,
        ge=0,
        description="Number of tool calls made",
    )
    tokens_used: int = Field(
        default=0,
        ge=0,
        description="Estimated tokens consumed",
    )

    # Log reference
    log_ref: str | None = Field(
        default=None,
        description="Reference to raw log in log store",
    )

    @field_validator("output")
    @classmethod
    def validate_output_length(cls, v: str | None) -> str | None:
        """Validate and truncate output to prevent memory issues."""
        if v and len(v) > MAX_OUTPUT_LENGTH:
            logger.warning(f"Output exceeds {MAX_OUTPUT_LENGTH} chars, truncating")
            return v[:MAX_OUTPUT_LENGTH] + "\n\n[... output truncated ...]"
        return v

    @field_validator("error")
    @classmethod
    def validate_error_length(cls, v: str | None) -> str | None:
        """Validate and truncate error message."""
        if v and len(v) > MAX_ERROR_LENGTH:
            logger.warning(f"Error exceeds {MAX_ERROR_LENGTH} chars, truncating")
            return v[:MAX_ERROR_LENGTH] + "..."
        return v

    @field_validator("raw_output")
    @classmethod
    def validate_raw_output_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Validate raw_output doesn't exceed size limits."""
        try:
            serialized = json.dumps(v)
            if len(serialized) > MAX_RAW_OUTPUT_SIZE:
                logger.warning("raw_output exceeds size limit, replacing with error")
                return {"error": "Output too large", "truncated": True}
        except (TypeError, ValueError) as e:
            logger.warning(f"Failed to validate raw_output size: {e}")
            return {"error": "Failed to serialize output"}
        return v

    def to_summary(self) -> str:
        """Generate a one-line summary of the result."""
        emoji = STATUS_EMOJI.get(self.status.value, "❓")
        base = f"{emoji} {self.host}: {self.status.value}"

        if self.duration_ms > 0:
            base += f" ({self.duration_ms}ms"
            if self.tool_calls > 0:
                base += f", {self.tool_calls} tools"
            base += ")"

        if self.error:
            # Truncate error for summary
            error_short = self.error[:50] + "..." if len(self.error) > 50 else self.error
            base += f" - {error_short}"

        return base


class AggregatedResults(BaseModel):
    """Aggregated results from multiple subagent executions.

    Provides statistics and summary across all hosts targeted
    by a parallel subagent execution.

    Example:
        >>> results = AggregatedResults(
        ...     results=[result1, result2, result3],
        ...     total_duration_ms=5000,
        ... )
        >>> print(f"Success rate: {results.success_rate}%")
        Success rate: 66.67%
    """

    # Individual results
    results: list[SubagentResult] = Field(
        default_factory=list,
        description="Results from each subagent",
    )

    # Execution metadata
    execution_id: str | None = Field(
        default=None,
        description="Unique execution batch ID",
    )
    skill_name: str | None = Field(
        default=None,
        description="Name of the skill that was executed",
    )
    task: str | None = Field(
        default=None,
        description="Original task description",
    )

    # Timing
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When batch execution started",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="When batch execution completed",
    )
    total_duration_ms: int = Field(
        default=0,
        ge=0,
        description="Total wall-clock time for all executions",
    )

    # Aggregated metrics
    total_tool_calls: int = Field(
        default=0,
        ge=0,
        description="Sum of tool calls across all subagents",
    )
    total_tokens_used: int = Field(
        default=0,
        ge=0,
        description="Sum of tokens used across all subagents",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_hosts(self) -> int:
        """Total number of hosts targeted."""
        return len(self.results)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def succeeded_hosts(self) -> int:
        """Number of hosts that succeeded."""
        return sum(1 for r in self.results if r.success)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def failed_hosts(self) -> int:
        """Number of hosts that failed."""
        return sum(1 for r in self.results if not r.success)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def success_rate(self) -> float:
        """Success rate as a percentage (0.0-100.0)."""
        if self.total_hosts == 0:
            return 0.0
        return (self.succeeded_hosts / self.total_hosts) * 100

    @property
    def is_complete_success(self) -> bool:
        """Check if all hosts succeeded."""
        return self.total_hosts > 0 and self.succeeded_hosts == self.total_hosts

    @property
    def is_partial_success(self) -> bool:
        """Check if some (but not all) hosts succeeded."""
        return 0 < self.succeeded_hosts < self.total_hosts

    @property
    def is_complete_failure(self) -> bool:
        """Check if all hosts failed."""
        return self.total_hosts > 0 and self.failed_hosts == self.total_hosts

    def get_successful_results(self) -> list[SubagentResult]:
        """Get only successful results."""
        return [r for r in self.results if r.success]

    def get_failed_results(self) -> list[SubagentResult]:
        """Get only failed results."""
        return [r for r in self.results if not r.success]

    def get_result_by_host(self, host: str) -> SubagentResult | None:
        """Get result for a specific host."""
        if not host:
            return None
        for r in self.results:
            if r.host == host:
                return r
        return None

    def compute_totals(self) -> None:
        """Compute aggregated totals from individual results."""
        self.total_tool_calls = sum(r.tool_calls for r in self.results)
        self.total_tokens_used = sum(r.tokens_used for r in self.results)

    def to_summary(self) -> str:
        """Generate a summary of all results."""
        if self.total_hosts == 0:
            return "No hosts targeted"

        # Determine overall status
        if self.is_complete_success:
            emoji = "✅"
            status = "All succeeded"
        elif self.is_complete_failure:
            emoji = "❌"
            status = "All failed"
        else:
            emoji = "⚠️"
            status = "Partial success"

        lines = [
            f"{emoji} {status}: {self.succeeded_hosts}/{self.total_hosts} hosts "
            f"({self.success_rate:.1f}%)"
        ]

        if self.total_duration_ms > 0:
            lines[0] += f" in {self.total_duration_ms}ms"

        # Add failed hosts summary
        failed = self.get_failed_results()
        if failed:
            lines.append("Failed hosts:")
            for r in failed[:5]:  # Limit to first 5
                error_short = r.error[:30] + "..." if r.error and len(r.error) > 30 else r.error
                lines.append(f"  - {r.host}: {error_short or 'Unknown error'}")
            if len(failed) > 5:
                lines.append(f"  ... and {len(failed) - 5} more")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "execution_id": self.execution_id,
            "skill_name": self.skill_name,
            "task": self.task,
            "total_hosts": self.total_hosts,
            "succeeded_hosts": self.succeeded_hosts,
            "failed_hosts": self.failed_hosts,
            "success_rate": self.success_rate,
            "total_duration_ms": self.total_duration_ms,
            "total_tool_calls": self.total_tool_calls,
            "total_tokens_used": self.total_tokens_used,
            "results": [r.model_dump() for r in self.results],
        }
