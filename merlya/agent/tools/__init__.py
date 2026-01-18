"""
Merlya Agent Tools Package.

This package contains all tool registrations for the Merlya agent.
The main entry point is register_all_tools() which registers all tools.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from merlya.agent.tools.core import register_core_tools
from merlya.agent.tools_files import register_file_tools
from merlya.agent.tools_mcp import register_mcp_tools
from merlya.agent.tools_security import register_security_tools
from merlya.agent.tools_system import register_system_tools
from merlya.agent.tools_web import register_web_tools

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from merlya.agent.main import AgentDependencies, AgentResponse


def register_all_tools(agent: Agent[AgentDependencies, AgentResponse]) -> None:
    """Register all Merlya tools on the provided agent."""
    register_core_tools(agent)
    register_system_tools(agent)
    register_file_tools(agent)
    register_security_tools(agent)
    register_web_tools(agent)
    register_mcp_tools(agent)


__all__ = ["register_all_tools", "register_core_tools"]
