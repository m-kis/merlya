"""
Unified Host Resolution Module.

This module provides a single source of truth for resolving hostnames to IPs
and vice versa. It consolidates the previously scattered resolution logic
from SSHManager, Scanner, and other components.

Resolution priority:
1. Inventory database (hosts_v2 table)
2. DNS resolution
3. Original hostname as fallback

Key guarantees:
- Canonical hostname is always preserved for connection pooling
- IP is resolved for connectivity checks
- All components use the same resolution logic
"""
import socket
from dataclasses import dataclass
from typing import Optional

from merlya.utils.logger import logger


@dataclass
class ResolvedHost:
    """
    Result of host resolution.

    Attributes:
        canonical_name: The original hostname (for connection pooling, credentials)
        ip_address: Resolved IP address (for connectivity)
        source: Where the IP was resolved from ('inventory', 'dns', 'none')
        ssh_port: SSH port from inventory (default 22)
        ssh_user: SSH user from inventory metadata (if any)
    """
    canonical_name: str
    ip_address: Optional[str]
    source: str  # 'inventory', 'dns', 'none'
    ssh_port: int = 22
    ssh_user: Optional[str] = None

    @property
    def connect_address(self) -> str:
        """Address to use for actual connection (IP if available, else hostname)."""
        return self.ip_address if self.ip_address else self.canonical_name

    def __repr__(self) -> str:
        return f"ResolvedHost({self.canonical_name} -> {self.ip_address or 'unresolved'} via {self.source})"


def resolve_host(hostname: str, dns_timeout: float = 5.0) -> ResolvedHost:
    """
    Resolve a hostname to its connection details.

    This is the SINGLE source of truth for host resolution across Merlya.
    All components (SSHManager, Scanner, etc.) should use this function.

    Args:
        hostname: Hostname to resolve
        dns_timeout: Timeout for DNS resolution (seconds)

    Returns:
        ResolvedHost with canonical name, IP, and metadata
    """
    # Try inventory first
    inventory_result = _resolve_from_inventory(hostname)
    if inventory_result:
        return inventory_result

    # Fall back to DNS
    dns_ip = _resolve_from_dns(hostname, dns_timeout)
    if dns_ip:
        return ResolvedHost(
            canonical_name=hostname,
            ip_address=dns_ip,
            source='dns',
        )

    # No resolution - return hostname only
    return ResolvedHost(
        canonical_name=hostname,
        ip_address=None,
        source='none',
    )


def _resolve_from_inventory(hostname: str) -> Optional[ResolvedHost]:
    """
    Resolve hostname from inventory database.

    Args:
        hostname: Hostname to look up

    Returns:
        ResolvedHost if found in inventory, None otherwise
    """
    try:
        from merlya.memory.persistence.inventory_repository import get_inventory_repository
        repo = get_inventory_repository()
        host = repo.get_host_by_name(hostname)

        if not host:
            return None

        # Get IP address (the field is 'ip_address' in schema, but check 'ip' for compat)
        ip = host.get("ip_address") or host.get("ip")
        if ip == "unknown":
            ip = None

        # Get SSH port
        ssh_port = host.get("ssh_port", 22) or 22

        # Get SSH user from metadata
        metadata = host.get("metadata", {}) or {}
        ssh_user = metadata.get("ssh_user") or metadata.get("user")

        if ip:
            logger.debug(f"📍 Resolved {hostname} -> {ip} from inventory")

        return ResolvedHost(
            canonical_name=hostname,
            ip_address=ip,
            source='inventory',
            ssh_port=ssh_port,
            ssh_user=ssh_user,
        )

    except ImportError:
        logger.debug("Inventory repository not available")
        return None
    except Exception as e:
        logger.debug(f"Inventory lookup failed for {hostname}: {e}")
        return None


def _resolve_from_dns(hostname: str, timeout: float = 5.0) -> Optional[str]:
    """
    Resolve hostname via DNS.

    Args:
        hostname: Hostname to resolve
        timeout: DNS timeout in seconds

    Returns:
        IP address string or None
    """
    old_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(timeout)
        # Use getaddrinfo for IPv4/IPv6 support
        addrinfo = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        if addrinfo:
            # First result's sockaddr, IP is always index 0
            # sockaddr is (ip, port) for IPv4 or (ip, port, flow, scope) for IPv6
            ip: str = str(addrinfo[0][4][0])
            logger.debug(f"📍 Resolved {hostname} -> {ip} from DNS")
            return ip
    except socket.gaierror:
        logger.debug(f"DNS resolution failed for {hostname}")
    except socket.timeout:
        logger.debug(f"DNS resolution timed out for {hostname}")
    except Exception as e:
        logger.debug(f"DNS resolution error for {hostname}: {e}")
    finally:
        socket.setdefaulttimeout(old_timeout)

    return None


def get_canonical_hostname(host_or_ip: str) -> str:
    """
    Get the canonical hostname for a host identifier.

    If the input is an IP, tries to find the hostname from inventory.
    Otherwise returns the input unchanged.

    This is critical for connection pooling - we always want to pool
    by hostname, not by IP.

    Args:
        host_or_ip: Either a hostname or IP address

    Returns:
        Canonical hostname
    """
    # Check if it looks like an IP
    if _is_ip_address(host_or_ip):
        # Try to find hostname in inventory by IP
        canonical = _find_hostname_by_ip(host_or_ip)
        if canonical:
            return canonical

    # Return as-is (already a hostname or IP not in inventory)
    return host_or_ip


def _is_ip_address(value: str) -> bool:
    """Check if a string is an IP address (v4 or v6)."""
    try:
        socket.inet_pton(socket.AF_INET, value)
        return True
    except socket.error:
        pass

    try:
        socket.inet_pton(socket.AF_INET6, value)
        return True
    except socket.error:
        pass

    return False


def _find_hostname_by_ip(ip: str) -> Optional[str]:
    """
    Find hostname in inventory by IP address.

    Args:
        ip: IP address to look up

    Returns:
        Hostname if found, None otherwise
    """
    try:
        from merlya.memory.persistence.inventory_repository import get_inventory_repository
        repo = get_inventory_repository()

        # Get all hosts and search by IP
        # Note: This could be optimized with an index if performance becomes an issue
        hosts = repo.get_all_hosts()
        for host in hosts:
            host_ip = host.get("ip_address") or host.get("ip")
            if host_ip == ip:
                return host.get("hostname")

    except Exception as e:
        logger.debug(f"Could not find hostname for IP {ip}: {e}")

    return None
