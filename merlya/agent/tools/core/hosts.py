"""
Host management tools for Merlya agent.

Provides tools to list and get host information from inventory.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from pydantic_ai import Agent, ModelRetry, RunContext

if TYPE_CHECKING:
    from merlya.agent.main import AgentDependencies
else:
    AgentDependencies = Any


async def list_hosts(
    ctx: RunContext[AgentDependencies],
    tag: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """
    List hosts from the inventory.

    Args:
        tag: Optional tag to filter hosts (e.g., "web", "database").
        limit: Maximum number of hosts to return (default: 20).

    Returns:
        List of hosts with name, hostname, status, and tags.
    """
    from merlya.tools.core import list_hosts as _list_hosts

    result = await _list_hosts(ctx.deps.context, tag=tag, limit=limit)
    if result.success:
        return {"hosts": result.data, "count": len(result.data)}
    # Return error info instead of retrying (system error, not recoverable)
    return {"hosts": [], "count": 0, "error": result.error}


async def get_host(
    ctx: RunContext[AgentDependencies],
    name: str,
) -> dict[str, Any]:
    """
    Get detailed information about a specific host.

    Args:
        name: Host name from inventory (e.g., "myserver", "db-prod").

    Returns:
        Host details including hostname, port, tags, and metadata.
    """
    from merlya.tools.core import get_host as _get_host

    result = await _get_host(ctx.deps.context, name)
    if result.success:
        return cast("dict[str, Any]", result.data)
    raise ModelRetry(f"Host not found: {result.error}")


def register(agent: Agent[Any, Any]) -> None:
    """Register host tools on agent."""
    agent.tool(list_hosts)
    agent.tool(get_host)
