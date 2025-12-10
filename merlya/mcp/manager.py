"""
Merlya MCP - Manager.

Handles MCP server configuration, connections, and tool execution.
"""

from __future__ import annotations

import asyncio
import logging
import os
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger
from mcp.client.session_group import ClientSessionGroup
from mcp.client.stdio import StdioServerParameters

from merlya.config.models import MCPServerConfig


@contextmanager
def suppress_mcp_capability_warnings() -> Iterator[None]:
    """
    Suppress MCP capability warnings during server connection.

    MCP servers may not implement optional features (prompts, resources).
    These warnings are expected and should not clutter the output.
    """
    # Suppress Python warnings
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*Method not found.*")
        warnings.filterwarnings("ignore", message=".*Could not fetch.*")

        # Also suppress root logger warnings for MCP
        root_logger = logging.getLogger()
        mcp_logger = logging.getLogger("mcp")
        original_root_level = root_logger.level
        original_mcp_level = mcp_logger.level

        # Temporarily raise log levels to suppress warnings
        root_logger.setLevel(logging.ERROR)
        mcp_logger.setLevel(logging.ERROR)

        try:
            yield
        finally:
            root_logger.setLevel(original_root_level)
            mcp_logger.setLevel(original_mcp_level)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from mcp.types import CallToolResult, Implementation

    from merlya.config.loader import Config
    from merlya.secrets import SecretStore


@dataclass(slots=True)
class MCPToolInfo:
    """Metadata for an MCP tool."""

    name: str
    description: str | None
    server: str


class MCPManager:
    """Manage MCP server lifecycle and tool discovery."""

    def __init__(self, config: Config, secrets: SecretStore) -> None:
        self.config = config
        self.secrets = secrets
        self._group: ClientSessionGroup | None = None
        self._connected: set[str] = set()
        self._component_prefix: str | None = None
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        """Close all MCP sessions."""
        if self._group is not None:
            try:
                await self._group.__aexit__(None, None, None)
            except Exception as e:  # pragma: no cover - defensive
                logger.debug(f"Failed to close MCP session group: {e}")
            finally:
                self._group = None
                self._connected.clear()

    async def list_servers(self) -> list[dict[str, Any]]:
        """Return configured MCP servers."""
        servers = []
        for name, server in self.config.mcp.servers.items():
            servers.append(
                {
                    "name": name,
                    "command": server.command,
                    "args": server.args,
                    "env_keys": sorted(server.env.keys()),
                    "cwd": str(server.cwd) if server.cwd else None,
                    "enabled": server.enabled,
                }
            )
        return servers

    async def add_server(
        self,
        name: str,
        command: str,
        args: list[str],
        env: dict[str, str],
        cwd: str | None = None,
    ) -> None:
        """Add a new MCP server configuration and persist it."""
        self.config.mcp.servers[name] = MCPServerConfig(
            command=command,
            args=args,
            env=env,
            cwd=cwd,
            enabled=True,
        )
        self.config.save()
        logger.info(f"✅ MCP server '{name}' added")

    async def remove_server(self, name: str) -> bool:
        """Remove an MCP server configuration."""
        removed = self.config.mcp.servers.pop(name, None) is not None
        if removed:
            self.config.save()
            logger.info(f"✅ MCP server '{name}' removed")
        return removed

    async def show_server(self, name: str) -> MCPServerConfig | None:
        """Get server configuration."""
        return self.config.mcp.servers.get(name)

    async def test_server(self, name: str) -> dict[str, Any]:
        """Connect to a server and return tool discovery info."""
        await self._ensure_connected(name)
        tools = await self.list_tools(name)
        return {
            "server": name,
            "server_info": None,
            "tools": tools,
            "tool_count": len(tools),
        }

    async def list_tools(self, server: str | None = None) -> list[MCPToolInfo]:
        """
        List MCP tools.

        Args:
            server: Optional server name to filter.
        """
        if not self.config.mcp.servers:
            return []

        group = await self._ensure_group()

        # Connect required servers
        target_servers = [server] if server else list(self.config.mcp.servers.keys())
        for srv in target_servers:
            await self._ensure_connected(srv)

        tools: list[MCPToolInfo] = []
        for name, tool in group.tools.items():
            server_prefix = name.split(".", 1)[0] if "." in name else None
            if server and server_prefix != server:
                continue
            tools.append(
                MCPToolInfo(
                    name=name,
                    description=tool.description,
                    server=server_prefix or server or "unknown",
                )
            )
        return sorted(tools, key=lambda t: t.name)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call a tool by aggregated name (server.tool)."""
        if not tool_name:
            raise ValueError("Tool name is required")

        server_prefix = tool_name.split(".", 1)[0] if "." in tool_name else None
        if server_prefix:
            await self._ensure_connected(server_prefix)
        else:
            # Best effort: connect all servers to resolve mapping
            for srv in self.config.mcp.servers:
                await self._ensure_connected(srv)

        group = await self._ensure_group()
        result = await group.call_tool(tool_name, arguments=arguments or {})
        return self._format_tool_result(result)

    async def _ensure_group(self) -> ClientSessionGroup:
        """Initialize the session group if needed."""
        if self._group is None:
            self._group = ClientSessionGroup(component_name_hook=self._component_name_hook)
            await self._group.__aenter__()
        return self._group

    async def _ensure_connected(self, name: str) -> ClientSessionGroup:
        """Ensure a server is connected and aggregated into the group."""
        if name not in self.config.mcp.servers:
            raise ValueError(f"Unknown MCP server: {name}")

        if not self.config.mcp.servers[name].enabled:
            raise ValueError(f"MCP server '{name}' is disabled")

        if name in self._connected:
            return await self._ensure_group()

        async with self._lock:
            if name in self._connected:
                return await self._ensure_group()

            params = self._build_server_params(name, self.config.mcp.servers[name])
            self._component_prefix = name
            try:
                group = await self._ensure_group()
                # Suppress warnings about missing optional MCP features
                with suppress_mcp_capability_warnings():
                    await group.connect_to_server(params)
                self._connected.add(name)
                logger.info(f"✅ MCP server connected: {name}")
                return group
            finally:
                self._component_prefix = None

    def _build_server_params(self, _name: str, server: MCPServerConfig) -> StdioServerParameters:
        """Create stdio params with resolved environment."""
        env = self._resolve_env(server.env)
        return StdioServerParameters(
            command=server.command,
            args=server.args,
            env=env,
            cwd=server.cwd,
        )

    def _resolve_env(self, env: dict[str, str]) -> dict[str, str]:
        """
        Resolve environment values, pulling from OS or secret store when templated.

        Supports two syntaxes:
        - ${VAR} - Required variable, logs warning if missing
        - ${VAR:-default} - Variable with default value if not found
        """
        resolved: dict[str, str] = {}
        for key, value in env.items():
            if value.startswith("${") and value.endswith("}"):
                inner = value[2:-1]

                # Handle ${VAR:-default} syntax
                if ":-" in inner:
                    ref, default = inner.split(":-", 1)
                else:
                    ref = inner
                    default = None

                # Try OS env first, then Merlya secrets
                resolved_value = os.getenv(ref) or self.secrets.get(ref)

                if resolved_value is None:
                    if default is not None:
                        resolved[key] = default
                        logger.debug(f"📋 Using default value for '{ref}' in MCP env {key}")
                    else:
                        logger.warning(f"⚠️ Missing environment or secret for '{ref}' (used in MCP env {key})")
                    continue
                resolved[key] = resolved_value
            else:
                resolved[key] = value
        return resolved

    def _component_name_hook(self, component_name: str, server_info: Implementation) -> str:
        """Prefix component names with server name for collision safety."""
        prefix = self._component_prefix or server_info.name
        return f"{prefix}.{component_name}"

    def _format_tool_result(self, result: CallToolResult) -> dict[str, Any]:
        """Normalize tool result for agent/command consumption."""
        content_text = self._content_to_text(result.content)
        return {
            "content": content_text,
            "structured": result.structuredContent,
            "is_error": result.isError,
        }

    def _content_to_text(self, content: list[Any]) -> str:
        """Convert MCP content blocks to plain text."""
        parts: list[str] = []
        for block in content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
            elif hasattr(block, "data"):
                parts.append("[binary]")
            else:
                parts.append(str(block))
        return "\n".join(parts)
