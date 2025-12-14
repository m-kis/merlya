"""
Merlya MCP - Manager.

Handles MCP server configuration, connections, and tool execution.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger
from mcp.client.session_group import ClientSessionGroup
from mcp.client.stdio import StdioServerParameters, get_default_environment

from merlya.config.models import MCPServerConfig

if TYPE_CHECKING:
    from collections.abc import Iterator

# MCP-related logger names to suppress during connection
_MCP_LOGGERS = ("mcp", "mcp.client", "mcp.server", "httpx", "httpcore")


@contextmanager
def suppress_mcp_capability_warnings() -> Iterator[None]:
    """
    Suppress MCP capability warnings during server connection.

    MCP servers may not implement optional features (prompts, resources).
    These warnings are expected and should not clutter the output.
    Only suppresses MCP-related loggers, not the root logger.
    """
    # Suppress Python warnings
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*Method not found.*")
        warnings.filterwarnings("ignore", message=".*Could not fetch.*")

        # Suppress only MCP-related loggers, not the root logger
        original_levels: dict[str, int] = {}
        for logger_name in _MCP_LOGGERS:
            log = logging.getLogger(logger_name)
            original_levels[logger_name] = log.level
            log.setLevel(logging.ERROR)

        try:
            yield
        finally:
            for logger_name, level in original_levels.items():
                logging.getLogger(logger_name).setLevel(level)


if TYPE_CHECKING:
    from mcp.types import CallToolResult, Implementation

    from merlya.config.loader import Config
    from merlya.secrets import SecretStore


@dataclass(slots=True)
class MCPToolInfo:
    """Metadata for an MCP tool."""

    name: str
    description: str | None
    server: str
    input_schema: dict[str, Any] | None = None


class MCPManager:
    """Manage MCP server lifecycle and tool discovery."""

    _instance: MCPManager | None = None
    _instance_lock: asyncio.Lock | None = None
    _instance_lock_guard = threading.Lock()  # Guards lazy creation of _instance_lock

    def __init__(self, config: Config, secrets: SecretStore) -> None:
        self.config = config
        self.secrets = secrets
        self._group: ClientSessionGroup | None = None
        self._connected: set[str] = set()
        self._component_prefix: str | None = None
        self._lock: asyncio.Lock | None = None
        self._lock_guard = threading.Lock()  # Guards lazy creation of _lock

    def _get_lock(self) -> asyncio.Lock:
        """Get or create the instance lock (lazily, requires event loop)."""
        if self._lock is None:
            with self._lock_guard:
                if self._lock is None:
                    self._lock = asyncio.Lock()
        return self._lock

    @classmethod
    def _get_instance_lock(cls) -> asyncio.Lock:
        """Get or create the class-level instance lock."""
        if cls._instance_lock is None:
            with cls._instance_lock_guard:
                if cls._instance_lock is None:
                    cls._instance_lock = asyncio.Lock()
        return cls._instance_lock

    @classmethod
    async def create(cls, config: Config, secrets: SecretStore) -> MCPManager:
        """
        Create or get singleton instance (async-safe).

        Use this instead of __init__ for proper async safety.
        """
        async with cls._get_instance_lock():
            if cls._instance is None:
                cls._instance = cls(config, secrets)
            return cls._instance

    @classmethod
    def get_instance(cls) -> MCPManager | None:
        """Get the singleton instance (may be None if not created)."""
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (for testing)."""
        cls._instance = None
        cls._instance_lock = None

    def get_stats(self) -> dict[str, int]:
        """Return basic MCP manager stats for health checks."""
        total_servers = len(self.config.mcp.servers)
        loaded_servers = sum(1 for server in self.config.mcp.servers.values() if server.enabled)
        active_servers = len(self._connected)
        return {
            "total_servers": total_servers,
            "loaded_servers": loaded_servers,
            "active_servers": active_servers,
        }

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
        from pathlib import Path

        self.config.mcp.servers[name] = MCPServerConfig(
            command=command,
            args=args,
            env=env,
            cwd=Path(cwd) if cwd else None,
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
            # Tool names should be prefixed as "server.tool_name"
            if "." in name:
                server_prefix = name.split(".", 1)[0]
            else:
                # Unprefixed tool - should not happen with our hook, but handle it
                server_prefix = "unknown"
                logger.warning(f"⚠️ MCP tool without server prefix: {name}")

            # Filter by server if specified
            if server and server_prefix != server:
                continue

            # Extract input schema for LLM to know required parameters
            schema = None
            if hasattr(tool, "inputSchema") and tool.inputSchema:
                schema = dict(tool.inputSchema)

            tools.append(
                MCPToolInfo(
                    name=name,
                    description=tool.description,
                    server=server_prefix,
                    input_schema=schema,
                )
            )
        return sorted(tools, key=lambda t: t.name)

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Call a tool by aggregated name (server.tool).

        Args:
            tool_name: Tool name in format "server.tool_name".
            arguments: Optional arguments for the tool.

        Raises:
            ValueError: If tool_name is empty or missing server prefix.
        """
        if not tool_name:
            raise ValueError("Tool name is required")

        if "." not in tool_name:
            raise ValueError(
                f"Tool name '{tool_name}' must include server prefix (e.g., 'server.tool_name'). "
                "Use /mcp tools to list available tools."
            )

        server_prefix = tool_name.split(".", 1)[0]
        await self._ensure_connected(server_prefix)

        group = await self._ensure_group()
        result = await group.call_tool(tool_name, arguments=arguments or {})
        return self._format_tool_result(result)

    async def _ensure_group(self) -> ClientSessionGroup:
        """Initialize the session group if needed (thread-safe)."""
        if self._group is not None:
            return self._group

        async with self._get_lock():
            # Double-check after acquiring lock
            if self._group is None:
                group = ClientSessionGroup(component_name_hook=self._component_name_hook)
                await group.__aenter__()
                self._group = group
        return self._group

    async def _ensure_connected(self, name: str) -> ClientSessionGroup:
        """Ensure a server is connected and aggregated into the group."""
        if name not in self.config.mcp.servers:
            raise ValueError(f"Unknown MCP server: {name}")

        if not self.config.mcp.servers[name].enabled:
            raise ValueError(f"MCP server '{name}' is disabled")

        if name in self._connected:
            return await self._ensure_group()

        # IMPORTANT: Initialize group BEFORE acquiring lock to avoid deadlock.
        # _ensure_group has its own lock, calling it inside our lock would deadlock.
        group = await self._ensure_group()

        async with self._get_lock():
            # Double-check after acquiring lock
            if name in self._connected:
                return group

            params = self._build_server_params(name, self.config.mcp.servers[name])
            self._component_prefix = name
            try:
                # Suppress warnings about missing optional MCP features
                with suppress_mcp_capability_warnings():
                    await group.connect_to_server(params)
                self._connected.add(name)
                logger.info(f"✅ MCP server connected: {name}")
                return group
            finally:
                self._component_prefix = None

    def _build_server_params(self, _name: str, server: MCPServerConfig) -> StdioServerParameters:
        """
        Create stdio params with resolved environment.

        Merges custom env vars with the default MCP environment (PATH, HOME, etc.)
        to ensure subprocess can find executables like npx, python, etc.
        """
        # Start with the default environment (includes PATH, HOME, etc.)
        # This is crucial - without it, subprocess can't find executables
        merged_env: dict[str, str] | None = None

        if server.env:
            # Resolve custom env vars (${VAR} syntax)
            custom_env = self._resolve_env(server.env)
            # Merge with default environment
            merged_env = {**get_default_environment(), **custom_env}
            logger.debug(f"🔧 MCP env merged: {list(custom_env.keys())} added to default env")
        # If no custom env, pass None to let SDK use get_default_environment()

        return StdioServerParameters(
            command=server.command,
            args=server.args,
            env=merged_env,
            cwd=server.cwd,
        )

    def _resolve_env(self, env: dict[str, str]) -> dict[str, str]:
        """
        Resolve environment values, pulling from OS or secret store when templated.

        Supports two syntaxes:
        - ${VAR} - Required variable, raises ValueError if missing
        - ${VAR:-default} - Variable with default value if not found

        Raises:
            ValueError: If a required variable (without default) is missing.
        """
        resolved: dict[str, str] = {}
        missing_vars: list[str] = []

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
                        # Track missing required variables
                        missing_vars.append(f"{key} (needs ${{{ref}}})")
                else:
                    resolved[key] = resolved_value
            else:
                resolved[key] = value

        # Raise error if any required variables are missing
        if missing_vars:
            raise ValueError(
                f"Missing required environment variables for MCP server: {', '.join(missing_vars)}. "
                "Set them in your environment or use /secret set <name> <value>."
            )

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
