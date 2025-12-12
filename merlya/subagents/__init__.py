"""
Merlya Subagents - Parallel execution system.

Provides ephemeral agents for parallel task execution across hosts.
"""

from merlya.subagents.factory import SubagentFactory, SubagentInstance, SubagentRunResult
from merlya.subagents.orchestrator import SubagentOrchestrator
from merlya.subagents.results import AggregatedResults, SubagentResult, SubagentStatus

__all__ = [
    "AggregatedResults",
    "SubagentFactory",
    "SubagentInstance",
    "SubagentOrchestrator",
    "SubagentResult",
    "SubagentRunResult",
    "SubagentStatus",
]
