"""
Merlya Router - Data models.

Separated from `classifier.py` to keep modules under the ~600 LOC guideline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from merlya.router.router_primitives import request_limit_for, tool_calls_limit_for

if TYPE_CHECKING:
    from merlya.router.intent_classifier import AgentMode


@dataclass
class RouterResult:
    """Result of intent classification."""

    mode: AgentMode
    tools: list[str]
    entities: dict[str, list[str]] = field(default_factory=dict)
    confidence: float = 0.0
    delegate_to: str | None = None
    reasoning: str | None = None  # For LLM fallback explanation
    credentials_required: bool = False
    elevation_required: bool = False
    jump_host: str | None = None  # Detected jump/bastion host for SSH tunneling
    fast_path: str | None = None  # Fast path intent if detected (e.g., "host.list")
    fast_path_args: dict[str, str] = field(default_factory=dict)  # Args extracted from pattern
    skill_match: str | None = None  # Matched skill name if detected
    skill_confidence: float = 0.0  # Confidence of skill match
    unresolved_hosts: list[str] = field(default_factory=list)

    @property
    def is_fast_path(self) -> bool:
        return self.fast_path is not None

    @property
    def is_skill_match(self) -> bool:
        return self.skill_match is not None and self.skill_confidence >= 0.5

    @property
    def tool_calls_limit(self) -> int:
        return tool_calls_limit_for(self.mode)

    @property
    def request_limit(self) -> int:
        return request_limit_for(self.mode)


__all__ = ["RouterResult"]
