"""
Merlya Agent - File tools registration.

Extracted from `merlya.agent.tools` to keep modules under the ~600 LOC guideline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent, ModelRetry, RunContext

from merlya.agent.tools_common import check_recoverable_error

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
        """
        Read file content from a remote host.

        For config files, try standard paths FIRST (see system prompt).
        Auto-elevates if permission denied.

        Args:
            host: Host name or hostname.
            path: Absolute path to file.
            lines: Limit to first N lines (optional).
            tail: If True with lines, read last N lines instead.

        Example:
            read_file(host="web-server", path="/etc/nginx/nginx.conf")
            read_file(host="app-server", path="/var/log/app.log", lines=100, tail=True)
        """
        from merlya.tools.files import read_file as _read_file

        result = await _read_file(ctx.deps.context, host, path, lines=lines, tail=tail)
        if result.success:
            return {"content": result.data}
        if check_recoverable_error(result.error):
            raise ModelRetry(
                f"File '{path}' not found on '{host}'. "
                "Check the path or use search_files() to find it."
            )
        return {"error": result.error}

    @agent.tool
    async def write_file(
        ctx: RunContext[AgentDependencies],
        host: str,
        path: str,
        content: str,
        backup: bool = True,
    ) -> dict[str, Any]:
        """
        Write content to a file on a remote host.

        IMPORTANT: Creates automatic backup (.bak) by default.
        Auto-elevates if permission denied.

        Args:
            host: Host name or hostname.
            path: Absolute path to file.
            content: Full file content to write.
            backup: Create .bak backup before overwriting (default: True).

        Example:
            write_file(host="web-server", path="/etc/nginx/sites-enabled/app.conf",
                      content="server { listen 80; ... }")
        """
        from merlya.tools.files import write_file as _write_file

        result = await _write_file(ctx.deps.context, host, path, content, backup=backup)
        if result.success:
            return {"success": True, "message": result.data}
        if check_recoverable_error(result.error):
            raise ModelRetry(
                f"Cannot write to '{path}' on '{host}'. Check the path exists or verify host name."
            )
        return {"success": False, "error": result.error}

    @agent.tool
    async def list_directory(
        ctx: RunContext[AgentDependencies],
        host: str,
        path: str,
        all_files: bool = False,
        long_format: bool = False,
    ) -> dict[str, Any]:
        """
        List directory contents on a remote host.

        Args:
            host: Host name or hostname.
            path: Directory path to list.
            all_files: Include hidden files (default: False).
            long_format: Include permissions, size, date (default: False).

        Example:
            list_directory(host="web-server", path="/etc/nginx/sites-enabled")
            list_directory(host="app-server", path="/home/deploy", all_files=True)
        """
        from merlya.tools.files import list_directory as _list_directory

        result = await _list_directory(
            ctx.deps.context, host, path, all_files=all_files, long_format=long_format
        )
        if result.success:
            return {"entries": result.data}
        if check_recoverable_error(result.error):
            raise ModelRetry(
                f"Directory '{path}' not found on '{host}'. "
                "Check the path or use search_files() to find it."
            )
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
        """
        Search for files on a remote host.

        Use ONLY when you don't know the exact location.
        For known paths, use read_file directly (faster).

        Args:
            host: Host name or hostname.
            path: Starting directory for search.
            pattern: Filename pattern (glob: *.conf, *.log, nginx*).
            file_type: "f" for files, "d" for directories (optional).
            max_depth: Limit search depth (optional).

        Example:
            search_files(host="web-server", path="/etc", pattern="*.conf")
            search_files(host="app-server", path="/var/log", pattern="*.log", max_depth=2)
        """
        from merlya.tools.files import search_files as _search_files

        result = await _search_files(
            ctx.deps.context, host, path, pattern, file_type=file_type, max_depth=max_depth
        )
        if result.success:
            return {"files": result.data, "count": len(result.data) if result.data else 0}
        if check_recoverable_error(result.error):
            raise ModelRetry(
                f"Search path '{path}' not found on '{host}'. "
                "Check the path or verify host name with list_hosts()."
            )
        return {"error": result.error}


__all__ = ["register_file_tools"]
