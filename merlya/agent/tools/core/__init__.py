"""
Core tools registration for Merlya agent.

This module provides the register_core_tools() function that registers
all core tools (hosts, bash, ssh, user interaction, credentials).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from merlya.agent.tools.core import bash, credentials, hosts, ssh, user_interaction

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from merlya.agent.main import AgentDependencies, AgentResponse


def register_core_tools(agent: Agent[AgentDependencies, AgentResponse]) -> None:
    """Register all core tools on the agent."""
    hosts.register(agent)
    bash.register(agent)
    ssh.register(agent)
    user_interaction.register(agent)
    credentials.register(agent)


__all__ = ["register_core_tools"]
