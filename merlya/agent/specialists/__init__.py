"""
Merlya Agent - Specialist agents package.

Four specialist agents that perform the actual work:
- DiagnosticAgent: Investigation, read-only checks (40 tool calls)
- ExecutionAgent: Actions that modify state (30 tool calls)
- SecurityAgent: Security scans, compliance (25 tool calls)
- QueryAgent: Quick inventory queries (15 tool calls)
"""

from __future__ import annotations

from merlya.agent.specialists.deps import SpecialistDeps
from merlya.agent.specialists.diagnostic import run_diagnostic_agent
from merlya.agent.specialists.execution import run_execution_agent
from merlya.agent.specialists.prompts import (
    DIAGNOSTIC_PROMPT,
    EXECUTION_PROMPT,
    QUERY_PROMPT,
    SECURITY_PROMPT,
)
from merlya.agent.specialists.query import run_query_agent
from merlya.agent.specialists.security import run_security_agent
from merlya.agent.specialists.types import (
    FileReadResult,
    HostInfo,
    HostListResult,
    ScanResult,
    SSHResult,
)

__all__ = [
    "DIAGNOSTIC_PROMPT",
    "EXECUTION_PROMPT",
    "QUERY_PROMPT",
    "SECURITY_PROMPT",
    "FileReadResult",
    "HostInfo",
    "HostListResult",
    "SSHResult",
    "ScanResult",
    "SpecialistDeps",
    "run_diagnostic_agent",
    "run_execution_agent",
    "run_query_agent",
    "run_security_agent",
]
