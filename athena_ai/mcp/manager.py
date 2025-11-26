"""
MCP (Model Context Protocol) Server Manager.

Manages MCP server configurations and provides simple access to MCP tools.
Users can add MCP servers with simple JSON configs and use them via @mcp references.

Features:
- Add/remove/list MCP server configurations
- Persistent storage in ~/.athena/mcp_servers.json
- Simple JSON configuration format
- Integration with AutoGen multi-agent system
"""
import json
from pathlib import Path
from typing import Any, Dict, Optional

from athena_ai.utils.logger import logger


class MCPManager:
    """
    Manages MCP server configurations.

    Example configs:
    {
        "filesystem": {
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
            "env": {"ALLOWED_PATHS": "/tmp,/home/user"}
        },
        "git": {
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-git"]
        }
    }
    """

    def __init__(self):
        """Initialize MCP manager."""
        self.config_dir = Path.home() / ".athena"
        self.config_file = self.config_dir / "mcp_servers.json"
        self.servers: Dict[str, Dict[str, Any]] = {}
        self._load_servers()

    def _load_servers(self):
        """Load MCP server configurations from disk."""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    self.servers = json.load(f)
                logger.debug(f"Loaded {len(self.servers)} MCP server configs from {self.config_file}")
            except Exception as e:
                logger.error(f"Failed to load MCP server configs: {e}")
                self.servers = {}
        else:
            logger.debug("No MCP server configs found, starting fresh")
            self.servers = {}

    def _save_servers(self):
        """Save MCP server configurations to disk."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.servers, f, indent=2)
            logger.debug(f"Saved {len(self.servers)} MCP server configs to {self.config_file}")
        except Exception as e:
            logger.error(f"Failed to save MCP server configs: {e}")

    def add_server(self, name: str, config: Dict[str, Any]) -> bool:
        """
        Add or update an MCP server configuration.

        Args:
            name: Server name (used in @mcp references)
            config: Server configuration dict

        Returns:
            True if successful, False otherwise

        Example:
            manager.add_server("filesystem", {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem"]
            })
        """
        # Validate config has required fields
        if 'type' not in config:
            logger.error("MCP server config must have 'type' field")
            return False

        if config['type'] == 'stdio':
            if 'command' not in config:
                logger.error("stdio MCP server must have 'command' field")
                return False

        self.servers[name] = config
        self._save_servers()
        logger.info(f"Added MCP server: {name}")
        return True

    def delete_server(self, name: str) -> bool:
        """
        Delete an MCP server configuration.

        Args:
            name: Server name

        Returns:
            True if deleted, False if not found
        """
        if name in self.servers:
            del self.servers[name]
            self._save_servers()
            logger.info(f"Deleted MCP server: {name}")
            return True
        else:
            logger.warning(f"MCP server not found: {name}")
            return False

    def get_server(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get MCP server configuration.

        Args:
            name: Server name

        Returns:
            Server config dict or None if not found
        """
        return self.servers.get(name)

    def list_servers(self) -> Dict[str, Dict[str, Any]]:
        """
        List all MCP server configurations.

        Returns:
            Dict of {name: config}
        """
        return self.servers.copy()

    def parse_mcp_reference(self, query: str) -> Optional[tuple[str, str]]:
        """
        Parse @mcp reference from query.

        Args:
            query: User query

        Returns:
            (server_name, remaining_query) or None if no @mcp found

        Examples:
            "@mcp filesystem list files in /tmp" -> ("filesystem", "list files in /tmp")
            "@mcp git show recent commits" -> ("git", "show recent commits")
            "normal query" -> None
        """
        if not query.strip().startswith('@mcp'):
            return None

        # Remove @mcp prefix
        parts = query.strip()[4:].strip().split(None, 1)

        if len(parts) == 0:
            return None

        server_name = parts[0]
        remaining_query = parts[1] if len(parts) > 1 else ""

        return (server_name, remaining_query)

    def get_example_configs(self) -> Dict[str, Dict[str, Any]]:
        """
        Get example MCP server configurations.

        Returns:
            Dict of example configs
        """
        return {
            "filesystem": {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem"],
                "env": {"ALLOWED_PATHS": "/tmp,/home"}
            },
            "git": {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-git"]
            },
            "github": {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {"GITHUB_TOKEN": "your-token-here"}
            },
            "postgres": {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-postgres"],
                "env": {"POSTGRES_URL": "postgresql://user:pass@localhost/db"}
            },
            "brave-search": {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-brave-search"],
                "env": {"BRAVE_API_KEY": "your-api-key"}
            }
        }
