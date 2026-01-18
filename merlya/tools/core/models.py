"""
Merlya Tools - Core models.

Contains the ToolResult dataclass used by all tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

# Type variable for tool result data
T = TypeVar("T")


@dataclass
class ToolResult(Generic[T]):
    """Result of a tool execution with typed data."""

    success: bool
    data: T
    error: str | None = None
    severity: str | None = None
