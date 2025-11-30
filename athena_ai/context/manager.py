"""
Context Manager for Athena.

Orchestrates local and remote scanning using:
- LocalScanner: Comprehensive local machine scanning with SQLite caching
- OnDemandScanner: Async parallel remote host scanning with rate limiting
"""
import asyncio
from typing import Any, Callable, Dict, Optional

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
    Intelligent context manager with unified scanning.

    Uses:
    - LocalScanner for local machine info (12h TTL, SQLite storage)
    - OnDemandScanner for remote hosts (async, parallel, with retry)
    - SmartCache for inventory parsing
    """

    # IPs and hostnames to skip when scanning remote hosts
    SKIP_IPS = frozenset([
        '127.0.0.1', '::1', '255.255.255.255', '0.0.0.0',
        'ff02::1', 'ff02::2'
    ])
    SKIP_HOSTNAMES = frozenset([
        'localhost', 'broadcasthost', 'ip6-localhost', 'ip6-loopback',
        'ip6-localnet', 'ip6-mcastprefix', 'ip6-allnodes', 'ip6-allrouters'
    ])

    def __init__(self, env: str = "dev"):
        self.env = env
        self.local_scanner = get_local_scanner()
        self.on_demand_scanner = get_on_demand_scanner()
        self.cache = SmartCache()

    def discover_environment(
        self,
        scan_remote: bool = True,
        force: bool = False,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> Dict[str, Any]:
        """
        Trigger a full discovery scan.

        Args:
            scan_remote: If True, also scan remote hosts via SSH
            force: If True, bypass cache and force refresh everything
            progress_callback: Optional callback(current, total, hostname) for progress

        Returns:
            Full infrastructure context
        """
        logger.info("🔄 Discovery scan requested")

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

        # Scan remote hosts if requested
        remote_hosts = {}
        if scan_remote and inventory:
            remote_hosts = self._scan_remote_hosts(inventory, progress_callback)
            self.cache.cache["remote_hosts"] = {
                "data": remote_hosts,
                "timestamp": __import__('time').time()
            }

        logger.info("✅ Discovery scan complete")

        return {
            "local": local_info,
            "inventory": inventory,
            "remote_hosts": remote_hosts,
        }

    def _scan_remote_hosts(
        self,
        inventory: Dict[str, str],
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> Dict[str, Any]:
        """
        Scan remote hosts using OnDemandScanner (async, parallel).

        Args:
            inventory: Dict of hostname -> IP mappings
            progress_callback: Optional progress callback

        Returns:
            Dict of hostname -> host_info
        """
        # Filter scannable hosts
        scannable = {
            h: ip for h, ip in inventory.items()
            if ip not in self.SKIP_IPS and h not in self.SKIP_HOSTNAMES
        }

        if not scannable:
            return {}

        hostnames = list(scannable.keys())
        logger.info(f"🖥️ Scanning {len(hostnames)} hosts from inventory...")

        # Run async scan
        results = asyncio.run(
            self.on_demand_scanner.scan_hosts(
                hostnames=hostnames,
                scan_type="system",
                force=False,
                progress_callback=progress_callback,
            )
        )

        # Convert results to dict format
        hosts_info = {}
        for result in results:
            if result.success:
                hosts_info[result.hostname] = {
                    "hostname": result.hostname,
                    "ip": scannable.get(result.hostname, result.hostname),
                    "accessible": result.data.get("reachable", False),
                    **result.data,
                }
            else:
                hosts_info[result.hostname] = {
                    "hostname": result.hostname,
                    "ip": scannable.get(result.hostname, result.hostname),
                    "accessible": False,
                    "error": result.error or "Scan failed",
                }

        accessible_count = sum(1 for h in hosts_info.values() if h.get("accessible"))
        logger.info(f"✅ Scan complete: {accessible_count}/{len(hosts_info)} hosts accessible")

        return hosts_info

    def get_context(
        self,
        auto_refresh: bool = True,
        include_remote: bool = False
    ) -> Dict[str, Any]:
        """
        Get current context with intelligent auto-refresh.

        Args:
            auto_refresh: If True, automatically refresh stale data
            include_remote: If True, include remote hosts (triggers SSH scan if not cached)

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

        # Get local context (uses LocalScanner's 12h cache)
        local_context = self.local_scanner.get_or_scan(force=False)
        local_info = local_context.to_dict()

        # Get inventory with smart cache
        inventory = self.cache.get("inventory", _parse_inventory)

        context = {
            "local": local_info,
            "inventory": inventory,
        }

        # Remote hosts: only scan if explicitly requested
        if include_remote:
            # Check if we have fresh cached data first
            remote_cache = self.cache.cache.get("remote_hosts", {})
            if remote_cache and remote_cache.get("data"):
                context["remote_hosts"] = remote_cache["data"]
            else:
                context["remote_hosts"] = self._scan_remote_hosts(inventory)
        else:
            # Return cached remote_hosts if exists
            context["remote_hosts"] = self.cache.cache.get("remote_hosts", {}).get("data", {})

        return context

    def refresh_inventory(self) -> Dict[str, str]:
        """Force refresh just the inventory (fast)."""
        logger.info("🔄 Refreshing inventory only")
        self.cache.invalidate("inventory")
        return self.cache.get("inventory", _parse_inventory)

    def scan_host(self, hostname_or_ip: str, force: bool = False) -> Dict[str, Any]:
        """
        Scan a single host just-in-time.

        Uses OnDemandScanner for robust scanning with retry and caching.

        Args:
            hostname_or_ip: Hostname or IP to scan
            force: If True, bypass cache

        Returns:
            Host information dict
        """
        logger.info(f"🖥️ Scanning single host: {hostname_or_ip}")

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
                "accessible": result.data.get("reachable", False),
                **result.data,
            }
        else:
            return {
                "hostname": result.hostname,
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
