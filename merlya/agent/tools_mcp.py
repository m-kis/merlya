"""
Merlya Agent - MCP tools registration.

Extracted from `merlya.agent.tools` to keep modules under the ~600 LOC guideline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent, RunContext  # noqa: TC002

if TYPE_CHECKING:
    from merlya.agent.main import AgentDependencies
else:
    AgentDependencies = Any  # type: ignore


def register_mcp_tools(agent: Agent[Any, Any]) -> None:
    """Register MCP bridge tools."""

    @agent.tool
    async def list_mcp_tools(ctx: RunContext[AgentDependencies]) -> dict[str, Any]:
        """
        List available MCP tools with their schemas.

        MCP (Model Context Protocol) tools are external capabilities
        provided by configured MCP servers. Use this to discover:
        - Available tools and what they do
        - Required and optional parameters for each tool
        - Proper usage sequence (some tools require IDs from other tools)

        IMPORTANT: Before calling an MCP tool, check its schema to know:
        1. What parameters are required vs optional
        2. The expected parameter types
        3. If it needs IDs from other tools first

        Returns:
            List of tools with names, descriptions, and parameter schemas.
        """
        manager = await ctx.deps.context.get_mcp_manager()
        tools = await manager.list_tools()

        # Build detailed tool info for LLM
        tool_details = []
        for tool in tools:
            detail: dict[str, Any] = {
                "name": tool.name,
                "description": tool.description or "No description",
                "server": tool.server,
            }
            # Include schema so LLM knows required parameters
            if tool.input_schema:
                detail["parameters"] = tool.input_schema
                # Extract required fields for clarity
                if "required" in tool.input_schema:
                    detail["required_params"] = tool.input_schema["required"]
            tool_details.append(detail)

        return {"tools": tool_details, "count": len(tools)}

    @agent.tool
    async def call_mcp_tool(
        ctx: RunContext[AgentDependencies],
        tool: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Call an MCP tool by name with arguments.

        IMPORTANT: Before calling, use list_mcp_tools() to see:
        1. Available tools and their descriptions
        2. Required parameters (you MUST provide these)
        3. Parameter types and formats

        Args:
            tool: Tool name in format "server.tool" (e.g., "context7.resolve-library-id").
            arguments: Arguments dict matching the tool's schema. Check required params!

        Returns:
            Tool execution result with content and any structured data.
        """
        manager = await ctx.deps.context.get_mcp_manager()
        return await manager.call_tool(tool, arguments or {})

    @agent.tool
    async def request_confirmation(
        ctx: RunContext[AgentDependencies],
        action: str,
        risk_level: str = "moderate",
    ) -> bool:
        """
        Request user confirmation before a destructive action.

        Use this tool before restart, delete, stop, or other risky operations.
        """
        from merlya.tools.core import request_confirmation as _request_confirmation

        result = await _request_confirmation(
            ctx.deps.context,
            action,
            risk_level=risk_level,
        )
        return result.data if result.success else False


__all__ = ["register_mcp_tools"]
