"""
Merlya Agent - System tools registration.

Extracted from `merlya.agent.tools` to keep modules under the ~600 LOC guideline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from pydantic_ai import Agent, ModelRetry, RunContext

from merlya.agent.tools_common import check_recoverable_error

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
        """
        Get comprehensive system information from a host.

        Returns OS, kernel, architecture, hostname, uptime, and load averages.
        Use for initial host assessment or troubleshooting.

        Args:
            host: Host name or hostname.

        Example:
            get_system_info(host="web-server")
            # Returns: {os, kernel, arch, hostname, uptime, load_avg}
        """
        from merlya.tools.system import get_system_info as _get_system_info

        result = await _get_system_info(ctx.deps.context, host)
        if result.success:
            return cast("dict[str, Any]", result.data)
        if check_recoverable_error(result.error):
            raise ModelRetry(f"Host '{host}' not found. Check the name or use list_hosts().")
        return {"error": result.error}

    @agent.tool
    async def check_disk_usage(
        ctx: RunContext[AgentDependencies],
        host: str,
        path: str = "/",
    ) -> dict[str, Any]:
        """
        Check disk usage on a host.

        Returns filesystem, size, used, available, and percentage for each mount.
        Use when user asks about disk space, storage, or "disk full" issues.

        Args:
            host: Host name or hostname.
            path: Path to check (default: "/" for all mounts).

        Example:
            check_disk_usage(host="db-server")
            check_disk_usage(host="web-server", path="/var/log")
        """
        from merlya.tools.system import check_disk_usage as _check_disk_usage

        result = await _check_disk_usage(ctx.deps.context, host, path)
        if result.success:
            return cast("dict[str, Any]", result.data)
        if check_recoverable_error(result.error):
            raise ModelRetry(f"Host '{host}' not found. Check the name or use list_hosts().")
        return {"error": result.error}

    @agent.tool
    async def check_memory(
        ctx: RunContext[AgentDependencies],
        host: str,
    ) -> dict[str, Any]:
        """
        Check memory usage on a host.

        Returns total, used, free, available, and swap information.
        Use when user asks about RAM, memory issues, or OOM problems.

        Args:
            host: Host name or hostname.

        Example:
            check_memory(host="app-server")
            # Returns: {total, used, free, available, swap_total, swap_used}
        """
        from merlya.tools.system import check_memory as _check_memory

        result = await _check_memory(ctx.deps.context, host)
        if result.success:
            return cast("dict[str, Any]", result.data)
        if check_recoverable_error(result.error):
            raise ModelRetry(f"Host '{host}' not found. Check the name or use list_hosts().")
        return {"error": result.error}

    @agent.tool
    async def check_cpu(
        ctx: RunContext[AgentDependencies],
        host: str,
    ) -> dict[str, Any]:
        """
        Check CPU usage on a host.

        Returns CPU count, model, and current usage percentages.
        Use when user asks about CPU load, performance, or slowness.

        Args:
            host: Host name or hostname.

        Example:
            check_cpu(host="compute-node")
            # Returns: {cpu_count, model, usage_percent, load_avg}
        """
        from merlya.tools.system import check_cpu as _check_cpu

        result = await _check_cpu(ctx.deps.context, host)
        if result.success:
            return cast("dict[str, Any]", result.data)
        if check_recoverable_error(result.error):
            raise ModelRetry(f"Host '{host}' not found. Check the name or use list_hosts().")
        return {"error": result.error}

    @agent.tool
    async def check_service_status(
        ctx: RunContext[AgentDependencies],
        host: str,
        service: str,
    ) -> dict[str, Any]:
        """
        Check the status of a systemd service.

        Returns active state, sub-state, and recent logs.
        Use when user asks if a service is running or why it failed.

        Args:
            host: Host name or hostname.
            service: Service name (e.g., "nginx", "docker", "postgresql").

        Example:
            check_service_status(host="web-server", service="nginx")
            check_service_status(host="db-server", service="postgresql")
        """
        from merlya.tools.system import check_service_status as _check_service_status

        result = await _check_service_status(ctx.deps.context, host, service)
        if result.success:
            return cast("dict[str, Any]", result.data)
        if check_recoverable_error(result.error):
            raise ModelRetry(
                f"Host '{host}' or service '{service}' not found. "
                "Check names or use list_hosts()/ssh_execute to list services."
            )
        return {"error": result.error}

    @agent.tool
    async def list_processes(
        ctx: RunContext[AgentDependencies],
        host: str,
        user: str | None = None,
        filter_name: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        List running processes on a host.

        Returns top processes by CPU/memory usage.
        Use to find resource-hungry processes or check if a process is running.

        Args:
            host: Host name or hostname.
            user: Filter by username (optional).
            filter_name: Filter by process name (optional).
            limit: Max processes to return (default: 10).

        Example:
            list_processes(host="app-server")
            list_processes(host="web-server", filter_name="nginx")
            list_processes(host="db-server", user="postgres", limit=5)
        """
        from merlya.tools.system import list_processes as _list_processes

        result = await _list_processes(
            ctx.deps.context,
            host,
            user=user,
            filter_name=filter_name,
            limit=limit,
        )
        if result.success:
            return {"processes": result.data}
        if check_recoverable_error(result.error):
            raise ModelRetry(f"Host '{host}' not found. Check the name or use list_hosts().")
        return {"error": result.error, "processes": []}


__all__ = ["register_system_tools"]
