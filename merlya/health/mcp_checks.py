"""
Merlya Health - MCP checks module.

Provides MCP servers health checks.
"""

from __future__ import annotations

from merlya.core.types import CheckStatus, HealthCheck
from merlya.mcp.manager import MCPManager


def check_mcp_servers(tier: str | None = None) -> HealthCheck:
    """Check if MCP servers are properly initialized and available."""
    try:
        manager = MCPManager.get_instance()

        if manager is None:
            # MCP is not required - it's initialized lazily in run_repl
            # At startup, no instance is expected
            return HealthCheck(
                name="mcp",
                status=CheckStatus.OK,
                message="ℹ️ MCP not initialized (will start on demand)",
                details={"info": "MCP servers start lazily when needed"},
            )

        # Get server stats
        stats = manager.get_stats()
        active_servers = stats.get("active_servers", 0)
        total_servers = stats.get("total_servers", 0)
        loaded_servers = stats.get("loaded_servers", 0)

        if total_servers == 0:
            return HealthCheck(
                name="mcp",
                status=CheckStatus.OK,
                message="ℹ️ No MCP servers configured",
                details={"stats": stats},
            )

        if loaded_servers == 0:
            return HealthCheck(
                name="mcp",
                status=CheckStatus.WARNING,
                message=f"⚠️ MCP servers configured but none loaded ({total_servers} configured)",
                details={"stats": stats},
            )

        # Check if any servers are actually running
        if active_servers == 0:
            return HealthCheck(
                name="mcp",
                status=CheckStatus.WARNING,
                message=f"⚠️ MCP servers loaded but none active ({loaded_servers}/{total_servers})",
                details={"stats": stats},
            )

        return HealthCheck(
            name="mcp",
            status=CheckStatus.OK,
            message=f"✅ MCP servers running ({active_servers}/{total_servers} active)",
            details={
                "stats": stats,
                "tier": tier or "auto",
            },
        )

    except Exception as e:
        return HealthCheck(
            name="mcp",
            status=CheckStatus.WARNING,
            message=f"⚠️ MCP manager error: {str(e)[:50]}",
            details={"error": str(e)},
        )
