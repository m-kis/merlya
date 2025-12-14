"""
Merlya Agent - File tools registration.

Extracted from `merlya.agent.tools` to keep modules under the ~600 LOC guideline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent, RunContext  # noqa: TC002

if TYPE_CHECKING:
    from merlya.agent.main import AgentDependencies
else:
    AgentDependencies = Any  # type: ignore


def register_file_tools(agent: Agent[Any, Any]) -> None:
    """Register file operation tools with the agent."""

    @agent.tool
    async def read_file(
        ctx: RunContext[AgentDependencies],
        host: str,
        path: str,
        lines: int | None = None,
        tail: bool = False,
    ) -> dict[str, Any]:
        """Read file content from a host."""
        from merlya.tools.files import read_file as _read_file

        result = await _read_file(ctx.deps.context, host, path, lines=lines, tail=tail)
        if result.success:
            return {"content": result.data}
        return {"error": result.error}

    @agent.tool
    async def write_file(
        ctx: RunContext[AgentDependencies],
        host: str,
        path: str,
        content: str,
        backup: bool = True,
    ) -> dict[str, Any]:
        """Write content to a file on a host."""
        from merlya.tools.files import write_file as _write_file

        result = await _write_file(ctx.deps.context, host, path, content, backup=backup)
        if result.success:
            return {"success": True, "message": result.data}
        return {"success": False, "error": result.error}

    @agent.tool
    async def list_directory(
        ctx: RunContext[AgentDependencies],
        host: str,
        path: str,
        all_files: bool = False,
        long_format: bool = False,
    ) -> dict[str, Any]:
        """List directory contents on a host."""
        from merlya.tools.files import list_directory as _list_directory

        result = await _list_directory(
            ctx.deps.context, host, path, all_files=all_files, long_format=long_format
        )
        if result.success:
            return {"entries": result.data}
        return {"error": result.error}

    @agent.tool
    async def search_files(
        ctx: RunContext[AgentDependencies],
        host: str,
        path: str,
        pattern: str,
        file_type: str | None = None,
        max_depth: int | None = None,
    ) -> dict[str, Any]:
        """Search for files on a host."""
        from merlya.tools.files import search_files as _search_files

        result = await _search_files(
            ctx.deps.context, host, path, pattern, file_type=file_type, max_depth=max_depth
        )
        if result.success:
            return {"files": result.data, "count": len(result.data) if result.data else 0}
        return {"error": result.error}


__all__ = ["register_file_tools"]
