"""
Discovery module - DEPRECATED.

This module is deprecated. Use instead:
- LocalScanner for local machine scanning
- OnDemandScanner for remote host scanning
- _parse_inventory() from manager.py for /etc/hosts parsing

Kept for backwards compatibility only.
"""
import warnings
from typing import Any, Dict


def parse_inventory(inventory_path: str = "/etc/hosts") -> Dict[str, str]:
    """
    Parse /etc/hosts or similar file to build simple inventory.

    This is a convenience function. For the authoritative implementation,
    use athena_ai.context.manager._parse_inventory().

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


class Discovery:
    """
    DEPRECATED: Use LocalScanner and OnDemandScanner instead.

    This class is kept for backwards compatibility only.
    All methods now delegate to the unified scanner infrastructure.
    """

    def __init__(self):
        warnings.warn(
            "Discovery class is deprecated. Use LocalScanner for local scans "
            "and OnDemandScanner for remote scans.",
            DeprecationWarning,
            stacklevel=2
        )

    def scan_local(self) -> Dict[str, Any]:
        """
        DEPRECATED: Use LocalScanner.get_or_scan() instead.

        Returns basic local info for backwards compatibility.
        """
        warnings.warn(
            "Discovery.scan_local() is deprecated. Use LocalScanner.get_or_scan()",
            DeprecationWarning,
            stacklevel=2
        )
        from athena_ai.context.local_scanner import get_local_scanner
        scanner = get_local_scanner()
        context = scanner.get_or_scan()
        # Return simplified format for backwards compatibility
        return {
            "hostname": context.os_info.get("hostname", ""),
            "os": context.os_info.get("os", ""),
            "release": context.os_info.get("release", ""),
            "version": context.os_info.get("version", ""),
            "machine": context.os_info.get("machine", ""),
            "processor": context.os_info.get("processor", ""),
            "services": list(context.services.get("active", [])),
            "processes": context.processes,
        }

    def parse_inventory(self, inventory_path: str = "/etc/hosts") -> Dict[str, str]:
        """Parse /etc/hosts file."""
        return parse_inventory(inventory_path)

    def scan_remote_hosts(
        self,
        inventory: Dict[str, str],
        progress_callback=None
    ) -> Dict[str, Any]:
        """
        DEPRECATED: Use OnDemandScanner.scan_hosts() instead.

        Scans remote hosts for backwards compatibility.
        """
        warnings.warn(
            "Discovery.scan_remote_hosts() is deprecated. Use OnDemandScanner.scan_hosts()",
            DeprecationWarning,
            stacklevel=2
        )
        import asyncio

        from athena_ai.context.on_demand_scanner import get_on_demand_scanner

        # Filter out local/broadcast IPs
        skip_ips = {'127.0.0.1', '::1', 'localhost', '255.255.255.255', '0.0.0.0'}
        skip_hostnames = {'localhost', 'broadcasthost', 'ip6-localhost', 'ip6-loopback'}

        scannable = {
            h: ip for h, ip in inventory.items()
            if ip not in skip_ips and h not in skip_hostnames
        }

        if not scannable:
            return {}

        scanner = get_on_demand_scanner()
        results = asyncio.run(
            scanner.scan_hosts(
                hostnames=list(scannable.keys()),
                scan_type="system",
                progress_callback=progress_callback,
            )
        )

        # Convert to old format
        hosts_info = {}
        for result in results:
            if result.success:
                hosts_info[result.hostname] = {
                    "hostname": result.hostname,
                    "ip": scannable.get(result.hostname, ""),
                    "accessible": result.data.get("reachable", False),
                    "os": result.data.get("os", "unknown"),
                    "kernel": result.data.get("kernel", ""),
                    "services": result.data.get("services", []),
                }
            else:
                hosts_info[result.hostname] = {
                    "hostname": result.hostname,
                    "ip": scannable.get(result.hostname, ""),
                    "accessible": False,
                    "error": result.error or "Connection failed",
                }

        return hosts_info
