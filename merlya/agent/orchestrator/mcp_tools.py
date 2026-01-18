"""
MCP (Model Context Protocol) tools for the orchestrator.

Contains tools for interacting with MCP servers.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent, ModelRetry, RunContext

from .models import OrchestratorDeps, OrchestratorResponse  # noqa: TC001


def register_mcp_tools(
    agent: Agent[OrchestratorDeps, OrchestratorResponse],
) -> None:
    """Register MCP tools on the orchestrator."""

    @agent.tool
    async def list_mcp_tools(
        ctx: RunContext[OrchestratorDeps],
    ) -> dict[str, object]:
        """
        List available MCP tools with their schemas.

        MCP (Model Context Protocol) tools are external capabilities
        provided by configured MCP servers (e.g., context7, filesystem).

        Returns:
            List of tools with names, descriptions, and parameter schemas.
        """
        manager = await ctx.deps.context.get_mcp_manager()
        tools = await manager.list_tools()

        tool_details: list[dict[str, Any]] = []
        for tool in tools:
            detail: dict[str, Any] = {
                "name": tool.name,
                "description": tool.description or "No description",
                "server": tool.server,
            }
            if tool.input_schema:
                detail["parameters"] = tool.input_schema
                if "required" in tool.input_schema:
                    detail["required_params"] = tool.input_schema["required"]
            tool_details.append(detail)

        return {"tools": tool_details, "count": len(tools)}

    @agent.tool
    async def call_mcp_tool(
        ctx: RunContext[OrchestratorDeps],
        tool: str,
        arguments: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """
        Call an MCP tool directly.

        MCP tools provide external capabilities (file access, context7, etc.).
        Use list_mcp_tools() first to see available tools and their parameters.

        WARNING: This is NOT for bash/ssh/system commands! Use delegate_* for those.

        Args:
            tool: Tool name in format "server.tool" (e.g., "context7.resolve-library-id").
            arguments: Arguments dict matching the tool's schema.

        Returns:
            Tool execution result.
        """
        # Prevent hallucination: reject tool names that look like system commands
        invalid_tools = {"bash", "ssh", "ssh_execute", "shell", "exec", "command", "run"}
        tool_lower = tool.lower()
        if tool_lower in invalid_tools or "." not in tool:
            raise ModelRetry(
                f"'{tool}' is not a valid MCP tool. MCP tools must be in format 'server.tool' "
                f"(e.g., 'context7.resolve-library-id'). "
                f"For bash/ssh commands, use delegate_diagnostic or delegate_execution instead."
            )

        manager = await ctx.deps.context.get_mcp_manager()
        try:
            return await manager.call_tool(tool, arguments or {})
        except ValueError as e:
            # Handle "Unknown MCP server" gracefully
            if "Unknown MCP server" in str(e):
                raise ModelRetry(
                    f"MCP server not configured: {e}. "
                    f"Use list_mcp_tools() to see available MCP tools, or delegate to specialists instead."
                ) from None
            raise
