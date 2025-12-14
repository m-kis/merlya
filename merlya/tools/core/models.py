"""
Merlya Tools - Core models.

Contains the ToolResult dataclass used by all tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolResult:
    """Result of a tool execution."""

    success: bool
    data: Any
    error: str | None = None
