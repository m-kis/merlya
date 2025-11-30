"""
Context Manager for Athena.

Orchestrates local and remote scanning using:
- LocalScanner: Comprehensive local machine scanning with SQLite caching
- OnDemandScanner: On-demand single host scanning (JIT - Just In Time)

Scanning Philosophy:
- Local machine: Scanned on demand, cached for 12h
- Remote hosts: Scanned JIT only when first connecting to a new host
- No bulk scanning of inventory - inefficient and often unnecessary
"""
import asyncio
from typing import Any, Dict, Optional

from athena_ai.utils.logger import logger

from .local_scanner import get_local_scanner
from .on_demand_scanner import get_on_demand_scanner
from .smart_cache import SmartCache


def _parse_inventory(inventory_path: str = "/etc/hosts") -> Dict[str, str]:
    """
    Parse /etc/hosts or similar file to build simple inventory.

    Args:
        inventory_path: Path to the hosts file

    Returns:
        Dictionary mapping hostname -> IP
    """
    hosts = {}
    try:
        with open(inventory_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split()
                    if len(parts) >= 2:
                        ip = parts[0]
                        for hostname in parts[1:]:
                            hosts[hostname] = ip
    except Exception:
        pass
    return hosts


class ContextManager:
    """
    Intelligent context manager with JIT scanning.

    Uses:
    - LocalScanner for local machine info (12h TTL, SQLite storage)
    - OnDemandScanner for remote hosts (JIT only, on first connection)
    - SmartCache for inventory parsing
    """

    def __init__(self, env: str = "dev"):
        self.env = env
        self.local_scanner = get_local_scanner()
        self.on_demand_scanner = get_on_demand_scanner()
        self.cache = SmartCache()

    def discover_environment(self, force: bool = False) -> Dict[str, Any]:
        """
        Scan local environment only.

        Args:
            force: If True, bypass cache and force refresh

        Returns:
            Local infrastructure context
        """
        logger.info("Scanning local environment...")

        if force:
            self.cache.invalidate_all()

        # Scan local machine using LocalScanner (comprehensive, with SQLite caching)
        local_context = self.local_scanner.get_or_scan(force=force)
        local_info = local_context.to_dict()

        # Parse inventory
        inventory = self.cache.get("inventory", _parse_inventory)

        # Update local cache
        self.cache.cache["local"] = {
            "data": local_info,
            "timestamp": __import__('time').time()
        }

        logger.info("Local scan complete")

        return {
            "local": local_info,
            "inventory": inventory,
        }

    def get_context(self, auto_refresh: bool = True) -> Dict[str, Any]:
        """
        Get current local context with intelligent auto-refresh.

        Args:
            auto_refresh: If True, automatically refresh stale data

        Returns:
            Local infrastructure context
        """
        if not auto_refresh:
            # Return cached data without refresh
            return {
                "local": self.cache.cache.get("local", {}).get("data", {}),
                "inventory": self.cache.cache.get("inventory", {}).get("data", {}),
            }

        # Get local context (uses LocalScanner's 12h cache)
        local_context = self.local_scanner.get_or_scan(force=False)
        local_info = local_context.to_dict()

        # Get inventory with smart cache
        inventory = self.cache.get("inventory", _parse_inventory)

        return {
            "local": local_info,
            "inventory": inventory,
        }

    def refresh_inventory(self) -> Dict[str, str]:
        """Force refresh just the inventory (fast)."""
        logger.info("Refreshing inventory...")
        self.cache.invalidate("inventory")
        return self.cache.get("inventory", _parse_inventory)

    def scan_host(self, hostname_or_ip: str, force: bool = False) -> Dict[str, Any]:
        """
        Scan a single host on-demand (JIT scanning).

        This is the primary method for scanning remote hosts.
        Called automatically when connecting to a new host.

        Args:
            hostname_or_ip: Hostname or IP to scan
            force: If True, bypass cache

        Returns:
            Host information dict
        """
        logger.info(f"Scanning host: {hostname_or_ip}")

        result = asyncio.run(
            self.on_demand_scanner.scan_host(
                hostname=hostname_or_ip,
                scan_type="system",
                force=force,
            )
        )

        if result.success:
            return {
                "hostname": result.hostname,
                "ip": result.data.get("ip", hostname_or_ip),
                "accessible": result.data.get("reachable", False),
                **result.data,
            }
        else:
            return {
                "hostname": result.hostname,
                "ip": hostname_or_ip,
                "accessible": False,
                "error": result.error or "Scan failed",
            }

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for debugging."""
        return self.cache.get_cache_stats()


# Singleton instance
_context_manager: Optional[ContextManager] = None


def get_context_manager(env: str = "dev") -> ContextManager:
    """Get the global ContextManager instance."""
    global _context_manager

    if _context_manager is None:
        _context_manager = ContextManager(env=env)

    return _context_manager
