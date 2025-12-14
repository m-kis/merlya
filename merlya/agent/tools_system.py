"""
Merlya Agent - System tools registration.

Extracted from `merlya.agent.tools` to keep modules under the ~600 LOC guideline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from pydantic_ai import Agent, RunContext  # noqa: TC002

if TYPE_CHECKING:
    from merlya.agent.main import AgentDependencies
else:
    AgentDependencies = Any  # type: ignore


def register_system_tools(agent: Agent[Any, Any]) -> None:
    """Register system tools with the agent."""

    @agent.tool
    async def get_system_info(
        ctx: RunContext[AgentDependencies],
        host: str,
    ) -> dict[str, Any]:
        """Get system information from a host."""
        from merlya.tools.system import get_system_info as _get_system_info

        result = await _get_system_info(ctx.deps.context, host)
        if result.success:
            return cast("dict[str, Any]", result.data)
        return {"error": result.error}

    @agent.tool
    async def check_disk_usage(
        ctx: RunContext[AgentDependencies],
        host: str,
        path: str = "/",
    ) -> dict[str, Any]:
        """Check disk usage on a host."""
        from merlya.tools.system import check_disk_usage as _check_disk_usage

        result = await _check_disk_usage(ctx.deps.context, host, path)
        if result.success:
            return cast("dict[str, Any]", result.data)
        return {"error": result.error}

    @agent.tool
    async def check_memory(
        ctx: RunContext[AgentDependencies],
        host: str,
    ) -> dict[str, Any]:
        """Check memory usage on a host."""
        from merlya.tools.system import check_memory as _check_memory

        result = await _check_memory(ctx.deps.context, host)
        if result.success:
            return cast("dict[str, Any]", result.data)
        return {"error": result.error}

    @agent.tool
    async def check_cpu(
        ctx: RunContext[AgentDependencies],
        host: str,
    ) -> dict[str, Any]:
        """Check CPU usage on a host."""
        from merlya.tools.system import check_cpu as _check_cpu

        result = await _check_cpu(ctx.deps.context, host)
        if result.success:
            return cast("dict[str, Any]", result.data)
        return {"error": result.error}

    @agent.tool
    async def check_service_status(
        ctx: RunContext[AgentDependencies],
        host: str,
        service: str,
    ) -> dict[str, Any]:
        """Check the status of a systemd service."""
        from merlya.tools.system import check_service_status as _check_service_status

        result = await _check_service_status(ctx.deps.context, host, service)
        if result.success:
            return cast("dict[str, Any]", result.data)
        return {"error": result.error}

    @agent.tool
    async def list_processes(
        ctx: RunContext[AgentDependencies],
        host: str,
        user: str | None = None,
        filter_name: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """List running processes on a host."""
        from merlya.tools.system import list_processes as _list_processes

        result = await _list_processes(
            ctx.deps.context,
            host,
            user=user,
            filter_name=filter_name,
            limit=limit,
        )
        if result.success:
            return cast("list[dict[str, Any]]", result.data)
        return []


__all__ = ["register_system_tools"]
