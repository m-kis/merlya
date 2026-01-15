"""
Delegation tools for the orchestrator.

This module aggregates all tool registration functions.
"""

from __future__ import annotations

from pydantic_ai import Agent  # noqa: TC002 - required at runtime

from .center_tools import register_center_tools
from .mcp_tools import register_mcp_tools
from .models import OrchestratorDeps, OrchestratorResponse  # noqa: TC001
from .specialist_tools import register_specialist_tools
from .utility_tools import register_utility_tools


def register_delegation_tools(
    agent: Agent[OrchestratorDeps, OrchestratorResponse],
) -> None:
    """Register all delegation tools on the orchestrator."""
    # Register MCP tools
    register_mcp_tools(agent)

    # Register specialist delegation tools
    register_specialist_tools(agent)

    # Register center delegation tools
    register_center_tools(agent)

    # Register utility tools
    register_utility_tools(agent)
