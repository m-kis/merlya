"""
MCP Client - Shared client for calling MCP servers.

DRY: Single implementation of MCP stdio protocol communication.
"""
import json
import subprocess
from typing import Dict, Any
from athena_ai.utils.logger import logger


class MCPClient:
    """
    Client for calling MCP servers via stdio protocol.

    Shared by MCPToolAdapter and MCPToolDiscovery (DRY principle).
    """

    @staticmethod
    def call_server(
        config: Dict[str, Any],
        request: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Call MCP server using stdio protocol.

        Args:
            config: MCP server configuration
            request: JSON-RPC request

        Returns:
            JSON-RPC response

        Raises:
            ValueError: If config is invalid
            RuntimeError: If server execution fails
        """
        if config.get("type") != "stdio":
            raise ValueError("Only stdio MCP servers are supported")

        command = config.get("command")
        if not command:
            raise ValueError("MCP server config missing 'command' field")

        args = config.get("args", [])
        env = config.get("env", {})

        # Build full command
        full_command = [command] + args

        # Prepare environment
        import os
        full_env = os.environ.copy()
        full_env.update(env)

        try:
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

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON from MCP server: {e}")
            raise RuntimeError(f"Invalid JSON response from MCP server: {e}")
        except Exception as e:
            logger.error(f"MCP server communication failed: {e}")
            raise
