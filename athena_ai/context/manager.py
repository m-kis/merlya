from typing import Any, Dict

from athena_ai.context.discovery import Discovery
from athena_ai.context.smart_cache import SmartCache
from athena_ai.memory.storage import MemoryStorage
from athena_ai.utils.logger import logger


class ContextManager:
    """
    Intelligent context manager with auto-refresh.
    Uses smart caching to detect changes and refresh only what's needed.
    """

    def __init__(self, env: str = "dev"):
        self.env = env
        self.discovery = Discovery()
        self.storage = MemoryStorage(env)
        self.cache = SmartCache()

    def discover_environment(self, scan_remote: bool = True, force: bool = False, progress_callback=None) -> Dict[str, Any]:
        """
        Trigger a full discovery scan and force refresh all context.

        Args:
            scan_remote: If True, also SSH to remote hosts to gather their info
            force: If True, bypass cache and force refresh everything
            progress_callback: Optional callback(current, total, hostname) for progress updates
        """
        logger.info("🔄 Force discovery scan requested")

        if force:
            self.cache.invalidate_all()

        # Force refresh all components
        local_info = self.discovery.scan_local()
        inventory = self.discovery.parse_inventory()

        # Update cache
        self.cache.cache["local"] = {
            "data": local_info,
            "timestamp": __import__('time').time()
        }
        self.cache.cache["inventory"] = {
            "data": inventory,
            "timestamp": __import__('time').time()
        }

        # Scan remote hosts via SSH
        if scan_remote and inventory:
            remote_hosts = self.discovery.scan_remote_hosts(inventory, progress_callback=progress_callback)
            self.cache.cache["remote_hosts"] = {
                "data": remote_hosts,
                "timestamp": __import__('time').time()
            }

        # Build and save full context
        context = self.get_context()
        self.storage.save_context(context)

        logger.info("✅ Discovery scan complete")
        return context

    def get_context(self, auto_refresh: bool = True, include_remote: bool = False) -> Dict[str, Any]:
        """
        Get current context with intelligent auto-refresh.

        Args:
            auto_refresh: If True, automatically refresh stale data
            include_remote: If True, include remote hosts (scanned via SSH). Default False for performance.

        Returns:
            Full infrastructure context
        """
        if not auto_refresh:
            # Return cached data without refresh
            return {
                "local": self.cache.cache.get("local", {}).get("data", {}),
                "inventory": self.cache.cache.get("inventory", {}).get("data", {}),
                "remote_hosts": self.cache.cache.get("remote_hosts", {}).get("data", {}),
            }

        # Auto-refresh with smart cache (lightweight - no SSH)
        context = {
            "local": self.cache.get("local", self.discovery.scan_local),
            "inventory": self.cache.get("inventory", self.discovery.parse_inventory),
        }

        # Remote hosts: ONLY if explicitly requested or already cached
        if include_remote:
            inventory = context["inventory"]
            context["remote_hosts"] = self.cache.get(
                "remote_hosts",
                lambda: self.discovery.scan_remote_hosts(inventory) if inventory else {}
            )
        else:
            # Return cached remote_hosts if exists, otherwise empty
            context["remote_hosts"] = self.cache.cache.get("remote_hosts", {}).get("data", {})

        return context

    def refresh_inventory(self):
        """Force refresh just the inventory (fast)."""
        logger.info("🔄 Refreshing inventory only")
        self.cache.invalidate("inventory")
        inventory = self.cache.get("inventory", self.discovery.parse_inventory)
        return inventory

    def scan_host(self, hostname_or_ip: str, force: bool = False) -> Dict[str, Any]:
        """
        Scan a single host just-in-time before executing actions.
        Uses cache to avoid re-scanning the same host repeatedly.

        Args:
            hostname_or_ip: Hostname or IP to scan
            force: If True, bypass cache and force rescan

        Returns:
            Host information dict
        """
        # Check if we already have fresh info for this host
        current_remote_hosts = self.cache.cache.get("remote_hosts", {}).get("data", {})

        if not force and hostname_or_ip in current_remote_hosts:
            # Check if the cached info is fresh (< 30 minutes)
            cache_entry = self.cache.cache.get("remote_hosts", {})
            cache_age = __import__('time').time() - cache_entry.get("timestamp", 0)

            if cache_age < 1800:  # 30 minutes TTL for host scans
                logger.debug(f"🔍 Using cached info for {hostname_or_ip} (age: {int(cache_age)}s)")
                return current_remote_hosts[hostname_or_ip]

        logger.info(f"🖥️ Scanning {hostname_or_ip} (cache miss or expired)")

        # Resolve hostname to IP if needed
        inventory = self.cache.get("inventory", self.discovery.parse_inventory)
        target_ip = inventory.get(hostname_or_ip, hostname_or_ip)

        # Create mini-inventory for single host
        mini_inventory = {hostname_or_ip: target_ip}

        # Scan this specific host
        host_info = self.discovery.scan_remote_hosts(mini_inventory)

        # Update cache with this host info
        current_remote_hosts.update(host_info)

        self.cache.cache["remote_hosts"] = {
            "data": current_remote_hosts,
            "timestamp": __import__('time').time()
        }

        return host_info.get(hostname_or_ip, {})

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for debugging."""
        return self.cache.get_cache_stats()


# Singleton instance
_context_manager = None


def get_context_manager(env: str = "dev") -> ContextManager:
    """Get the global ContextManager instance."""
    global _context_manager

    if _context_manager is None:
        _context_manager = ContextManager(env=env)

    return _context_manager
