"""
MCP Tool Adapter - Bridges MCP servers with the Tool Registry.

Allows MCP-provided tools to be discovered and used as native Athena tools.
"""
import json
import subprocess
from typing import Any, Dict, List, Optional

from athena_ai.mcp.manager import MCPManager
from athena_ai.utils.logger import logger

from .base import BaseTool, ToolCategory, ToolMetadata, ToolParameter


class MCPToolAdapter(BaseTool):
    """
    Adapter that wraps an MCP server tool as a BaseTool.

    Follows Adapter Pattern to integrate external MCP tools.
    """

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        description: str,
        parameters: List[ToolParameter],
        mcp_manager: MCPManager
    ):
        """
        Initialize MCP tool adapter.

        Args:
            server_name: Name of MCP server
            tool_name: Name of the tool from the MCP server
            description: Tool description
            parameters: Tool parameters
            mcp_manager: MCPManager instance
        """
        super().__init__()
        self.server_name = server_name
        self.tool_name = tool_name
        self._description = description
        self._parameters = parameters
        self.mcp_manager = mcp_manager

    def get_metadata(self) -> ToolMetadata:
        """Get tool metadata."""
        return ToolMetadata(
            name=f"mcp_{self.server_name}_{self.tool_name}",
            description=f"[MCP/{self.server_name}] {self._description}",
            category=ToolCategory.INFRASTRUCTURE,
            parameters=self._parameters,
            version="1.0.0-mcp",
            author=f"mcp-{self.server_name}"
        )

    def execute(self, **kwargs) -> Any:
        """
        Execute MCP tool by calling the MCP server.

        Args:
            **kwargs: Tool-specific parameters

        Returns:
            Tool execution result
        """
        server_config = self.mcp_manager.get_server(self.server_name)

        if not server_config:
            raise ValueError(f"MCP server '{self.server_name}' not configured")

        try:
            # Build MCP request
            mcp_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": self.tool_name,
                    "arguments": kwargs
                }
            }

            # Execute MCP server
            result = self._call_mcp_server(server_config, mcp_request)

            return result.get("result", {}).get("content", "")

        except Exception as e:
            logger.error(f"MCP tool execution failed: {e}")
            return f"Error executing MCP tool: {str(e)}"

    def _call_mcp_server(self, config: Dict[str, Any], request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call MCP server using stdio protocol.

        Args:
            config: MCP server configuration
            request: JSON-RPC request

        Returns:
            JSON-RPC response
        """
        if config.get("type") != "stdio":
            raise ValueError("Only stdio MCP servers are supported")

        command = config.get("command")
        args = config.get("args", [])
        env = config.get("env", {})

        # Build full command
        full_command = [command] + args

        # Prepare environment
        import os
        full_env = os.environ.copy()
        full_env.update(env)

        # Execute command and send JSON-RPC request
        process = subprocess.Popen(
            full_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=full_env
        )

        # Send request
        request_json = json.dumps(request)
        stdout, stderr = process.communicate(input=request_json.encode())

        if process.returncode != 0:
            logger.error(f"MCP server failed: {stderr.decode()}")
            raise RuntimeError(f"MCP server error: {stderr.decode()}")

        # Parse response
        response = json.loads(stdout.decode())
        return response


class MCPToolDiscovery:
    """
    Discovers tools from configured MCP servers.

    Follows Discovery Pattern for dynamic tool registration.
    """

    def __init__(self, mcp_manager: MCPManager):
        """
        Initialize MCP tool discovery.

        Args:
            mcp_manager: MCPManager instance
        """
        self.mcp_manager = mcp_manager

    def discover_tools(self) -> List[MCPToolAdapter]:
        """
        Discover all available tools from configured MCP servers.

        Returns:
            List of MCPToolAdapter instances
        """
        tools = []
        servers = self.mcp_manager.list_servers()

        for server_name, server_config in servers.items():
            try:
                server_tools = self._discover_server_tools(server_name, server_config)
                tools.extend(server_tools)
                logger.info(f"Discovered {len(server_tools)} tools from MCP server '{server_name}'")
            except Exception as e:
                logger.error(f"Failed to discover tools from MCP server '{server_name}': {e}")

        return tools

    def _discover_server_tools(
        self,
        server_name: str,
        server_config: Dict[str, Any]
    ) -> List[MCPToolAdapter]:
        """
        Discover tools from a single MCP server.

        Args:
            server_name: Server name
            server_config: Server configuration

        Returns:
            List of MCPToolAdapter instances
        """
        # Build MCP request to list tools
        mcp_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list"
        }

        try:
            # Execute MCP server
            response = self._call_mcp_server(server_config, mcp_request)
            tools_list = response.get("result", {}).get("tools", [])

            # Convert each tool to MCPToolAdapter
            adapters = []
            for tool_info in tools_list:
                adapter = self._create_adapter(server_name, tool_info)
                if adapter:
                    adapters.append(adapter)

            return adapters

        except Exception as e:
            logger.error(f"Failed to list tools from {server_name}: {e}")
            return []

    def _create_adapter(
        self,
        server_name: str,
        tool_info: Dict[str, Any]
    ) -> Optional[MCPToolAdapter]:
        """
        Create MCPToolAdapter from tool info.

        Args:
            server_name: Server name
            tool_info: Tool information from MCP

        Returns:
            MCPToolAdapter or None if failed
        """
        try:
            tool_name = tool_info.get("name", "")
            description = tool_info.get("description", "")

            # Convert MCP parameters to ToolParameter
            mcp_params = tool_info.get("inputSchema", {}).get("properties", {})
            required = tool_info.get("inputSchema", {}).get("required", [])

            parameters = []
            for param_name, param_info in mcp_params.items():
                param = ToolParameter(
                    name=param_name,
                    type=param_info.get("type", "string"),
                    description=param_info.get("description", ""),
                    required=param_name in required
                )
                parameters.append(param)

            return MCPToolAdapter(
                server_name=server_name,
                tool_name=tool_name,
                description=description,
                parameters=parameters,
                mcp_manager=self.mcp_manager
            )

        except Exception as e:
            logger.error(f"Failed to create adapter for tool: {e}")
            return None

    def _call_mcp_server(self, config: Dict[str, Any], request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call MCP server using stdio protocol.

        Args:
            config: MCP server configuration
            request: JSON-RPC request

        Returns:
            JSON-RPC response
        """
        if config.get("type") != "stdio":
            raise ValueError("Only stdio MCP servers are supported")

        command = config.get("command")
        args = config.get("args", [])
        env = config.get("env", {})

        # Build full command
        full_command = [command] + args

        # Prepare environment
        import os
        full_env = os.environ.copy()
        full_env.update(env)

        # Execute command and send JSON-RPC request
        process = subprocess.Popen(
            full_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=full_env
        )

        # Send request
        request_json = json.dumps(request)
        stdout, stderr = process.communicate(input=request_json.encode())

        if process.returncode != 0:
            logger.error(f"MCP server failed: {stderr.decode()}")
            raise RuntimeError(f"MCP server error: {stderr.decode()}")

        # Parse response
        response = json.loads(stdout.decode())
        return response
