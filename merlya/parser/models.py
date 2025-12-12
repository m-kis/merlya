"""
Merlya Parser - Pydantic models for parsing results.

Defines structured output types for the parser service:
- ParsingResult: Base result with metadata
- IncidentInput: Structured incident description
- ParsedLog: Structured log output
- HostQueryInput: Structured host query
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Required at runtime for Pydantic
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, Enum):
    """Incident severity levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Environment(str, Enum):
    """Environment types."""

    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"
    TESTING = "testing"
    UNKNOWN = "unknown"


class LogLevel(str, Enum):
    """Log level types."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    DEBUG = "debug"
    TRACE = "trace"


class ParsingResult(BaseModel):
    """
    Base result for all parsing operations.

    Contains metadata about parsing quality and coverage.
    """

    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score of the parsing (0.0-1.0)",
    )
    coverage_ratio: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Ratio of text successfully parsed",
    )
    has_unparsed_blocks: bool = Field(
        default=True,
        description="Whether there are unparsed blocks in the input",
    )
    truncated: bool = Field(
        default=False,
        description="Whether the input was truncated",
    )
    total_lines: int | None = Field(
        default=None,
        description="Total number of lines in the original input",
    )
    backend_used: str = Field(
        default="unknown",
        description="Backend that performed the parsing (heuristic/onnx)",
    )
    parse_time_ms: float = Field(
        default=0.0,
        description="Time taken to parse in milliseconds",
    )


class IncidentInput(BaseModel):
    """
    Structured incident description extracted from user input.

    Captures key information about an infrastructure incident.
    """

    description: str = Field(
        default="",
        description="Main incident description",
    )
    severity: Severity = Field(
        default=Severity.MEDIUM,
        description="Detected or inferred severity",
    )
    environment: Environment = Field(
        default=Environment.UNKNOWN,
        description="Detected environment (prod/staging/dev)",
    )
    affected_hosts: list[str] = Field(
        default_factory=list,
        description="List of affected host names",
    )
    affected_services: list[str] = Field(
        default_factory=list,
        description="List of affected service names",
    )
    symptoms: list[str] = Field(
        default_factory=list,
        description="List of observed symptoms",
    )
    error_messages: list[str] = Field(
        default_factory=list,
        description="Error messages extracted from input",
    )
    timestamps: list[datetime] = Field(
        default_factory=list,
        description="Timestamps mentioned in the incident",
    )
    paths: list[str] = Field(
        default_factory=list,
        description="File paths mentioned",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="Key technical terms extracted",
    )


class IncidentParsingResult(ParsingResult):
    """Result of parsing an incident description."""

    incident: IncidentInput = Field(
        default_factory=lambda: IncidentInput(),
        description="Structured incident data",
    )


class LogEntry(BaseModel):
    """Single log entry extracted from raw logs."""

    timestamp: datetime | None = Field(
        default=None,
        description="Log entry timestamp",
    )
    level: LogLevel = Field(
        default=LogLevel.INFO,
        description="Log level",
    )
    source: str = Field(
        default="",
        description="Log source (service name, file, etc.)",
    )
    message: str = Field(
        description="Log message content",
    )
    line_number: int | None = Field(
        default=None,
        description="Original line number in the log",
    )
    raw: str = Field(
        default="",
        description="Original raw log line",
    )


class ParsedLog(BaseModel):
    """
    Structured log output from parsing raw logs.

    Groups log entries and provides summary information.
    """

    entries: list[LogEntry] = Field(
        default_factory=list,
        description="Parsed log entries",
    )
    error_count: int = Field(
        default=0,
        description="Number of error-level entries",
    )
    warning_count: int = Field(
        default=0,
        description="Number of warning-level entries",
    )
    time_range_start: datetime | None = Field(
        default=None,
        description="Earliest timestamp in logs",
    )
    time_range_end: datetime | None = Field(
        default=None,
        description="Latest timestamp in logs",
    )
    sources: list[str] = Field(
        default_factory=list,
        description="Unique log sources found",
    )
    key_errors: list[str] = Field(
        default_factory=list,
        description="Summary of key error messages",
    )
    patterns_detected: list[str] = Field(
        default_factory=list,
        description="Detected patterns (e.g., 'connection refused', 'timeout')",
    )


class LogParsingResult(ParsingResult):
    """Result of parsing log output."""

    parsed_log: ParsedLog = Field(
        default_factory=ParsedLog,
        description="Structured log data",
    )
    log_ref: str | None = Field(
        default=None,
        description="Reference to stored raw log (for retrieval)",
    )


class HostQueryInput(BaseModel):
    """
    Structured host query extracted from user input.

    Captures what the user wants to know about hosts.
    """

    target_hosts: list[str] = Field(
        default_factory=list,
        description="Target host names or patterns",
    )
    target_groups: list[str] = Field(
        default_factory=list,
        description="Target host groups",
    )
    filters: dict[str, Any] = Field(
        default_factory=dict,
        description="Filters to apply (tags, status, etc.)",
    )
    query_type: str = Field(
        default="list",
        description="Type of query (list/details/status/check)",
    )
    fields_requested: list[str] = Field(
        default_factory=list,
        description="Specific fields requested",
    )


class HostQueryParsingResult(ParsingResult):
    """Result of parsing a host query."""

    query: HostQueryInput = Field(
        default_factory=HostQueryInput,
        description="Structured host query",
    )


class CommandInput(BaseModel):
    """
    Structured command extracted from user input.

    Captures command execution context.
    """

    command: str = Field(
        description="Command to execute",
    )
    target_host: str | None = Field(
        default=None,
        description="Target host for execution",
    )
    via_host: str | None = Field(
        default=None,
        description="Jump host if specified",
    )
    timeout: int = Field(
        default=60,
        ge=1,
        le=3600,
        description="Command timeout in seconds",
    )
    requires_elevation: bool = Field(
        default=False,
        description="Whether command requires sudo/root",
    )
    is_destructive: bool = Field(
        default=False,
        description="Whether command is potentially destructive",
    )
    secrets_referenced: list[str] = Field(
        default_factory=list,
        description="Secret references (@secret-name) in command",
    )


class CommandParsingResult(ParsingResult):
    """Result of parsing a command."""

    command: CommandInput = Field(
        default_factory=lambda: CommandInput(command=""),
        description="Structured command data",
    )
