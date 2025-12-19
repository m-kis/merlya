"""
Merlya Tools - Host management.

List and get host information from inventory.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.tools.core.models import ToolResult

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


async def list_hosts(
    ctx: SharedContext,
    tag: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> ToolResult:
    """
    List hosts from inventory.

    Args:
        ctx: Shared context.
        tag: Filter by tag.
        status: Filter by health status.
        limit: Maximum hosts to return.

    Returns:
        ToolResult with list of hosts.
    """
    # Validate limit
    if limit < 1:
        limit = 1
    elif limit > 1000:
        limit = 1000

    try:
        if tag:
            hosts = await ctx.hosts.get_by_tag(tag)
        else:
            hosts = await ctx.hosts.get_all()

        # Filter by status if specified (case-insensitive)
        if status:
            status_lower = status.lower()
            hosts = [h for h in hosts if (h.health_status or "").lower() == status_lower]

        # Apply limit
        hosts = hosts[:limit]

        # Convert to simple dicts
        host_list = [
            {
                "name": h.name,
                "hostname": h.hostname,
                "status": h.health_status,
                "tags": h.tags,
                "last_seen": str(h.last_seen) if h.last_seen else None,
                # Elevation method helps LLM choose sudo vs su
                "elevation_method": h.elevation_method,
            }
            for h in hosts
        ]

        logger.debug(f"📋 Listed {len(host_list)} hosts")
        return ToolResult(success=True, data=host_list)

    except Exception as e:
        logger.error(f"❌ Failed to list hosts: {e}")
        return ToolResult(success=False, data=[], error=str(e))


async def get_host(
    ctx: SharedContext,
    name: str,
    include_metadata: bool = True,
) -> ToolResult:
    """
    Get detailed information about a host.

    Args:
        ctx: Shared context.
        name: Host name.
        include_metadata: Include enriched metadata.

    Returns:
        ToolResult with host details.
    """
    # Validate host name
    if not name or not name.strip():
        return ToolResult(
            success=False,
            data=None,
            error="Host name cannot be empty",
        )

    try:
        host = await ctx.hosts.get_by_name(name)
        if not host:
            return ToolResult(
                success=False,
                data=None,
                error=f"Host '{name}' not found",
            )

        host_data: dict[str, Any] = {
            "id": host.id,
            "name": host.name,
            "hostname": host.hostname,
            "port": host.port,
            "username": host.username,
            "tags": host.tags,
            "health_status": host.health_status,
            "last_seen": str(host.last_seen) if host.last_seen else None,
            # Elevation method for this host: "sudo", "su", "doas", or None
            # Use this to choose the correct privilege escalation command
            "elevation_method": host.elevation_method,
        }

        if include_metadata:
            host_data["metadata"] = host.metadata
            if host.os_info:
                host_data["os_info"] = {
                    "name": host.os_info.name,
                    "version": host.os_info.version,
                    "kernel": host.os_info.kernel,
                    "arch": host.os_info.arch,
                }

        return ToolResult(success=True, data=host_data)

    except Exception as e:
        logger.error(f"❌ Failed to get host: {e}")
        return ToolResult(success=False, data=None, error=str(e))
