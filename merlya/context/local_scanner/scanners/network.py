"""
Network scanner.
"""
import ipaddress
import json
import platform
import socket
import subprocess
import threading
from typing import Any, Dict, List, Optional

from merlya.utils.logger import logger

# Lock to protect global socket timeout changes during DNS resolution
_socket_timeout_lock = threading.Lock()


def _is_valid_ip(value: str) -> bool:
    """Check if value is a valid IPv4 or IPv6 address."""
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _extract_gateway_from_route(output: str) -> Optional[str]:
    """
    Extract and validate gateway IP from 'ip route show default' output.

    Looks for 'via <ip>' pattern first, then falls back to finding
    the first valid IP-like token in the line.
    """
    parts = output.split()

    # Look for "via" token and validate the following token
    try:
        via_idx = parts.index("via")
        if via_idx + 1 < len(parts):
            candidate = parts[via_idx + 1]
            if _is_valid_ip(candidate):
                return candidate
            else:
                logger.debug(f"Gateway token after 'via' is not a valid IP: {candidate}")
    except ValueError:
        # "via" not found in output
        pass

    # Fallback: find the first valid IP-like token in the line
    for token in parts:
        if _is_valid_ip(token):
            return token

    logger.debug(f"Could not extract valid gateway IP from route output: {output.strip()}")
    return None


def scan_network() -> Dict[str, Any]:
    """Scan network interfaces and configuration."""
    # Get hostname and FQDN with timeout protection (getfqdn can block on reverse DNS)
    try:
        with _socket_timeout_lock:
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(5.0)
            try:
                hostname = socket.gethostname()
                fqdn = socket.getfqdn()
            finally:
                socket.setdefaulttimeout(old_timeout)
    except (socket.gaierror, socket.timeout, OSError):
        # Fallback with timeout protection for consistency
        try:
            with _socket_timeout_lock:
                old_timeout = socket.getdefaulttimeout()
                socket.setdefaulttimeout(5.0)
                try:
                    hostname = socket.gethostname()
                finally:
                    socket.setdefaulttimeout(old_timeout)
            fqdn = hostname
        except Exception:
            hostname = "unknown"
            fqdn = "unknown"

    interfaces: List[Dict[str, Any]] = []
    info: Dict[str, Any] = {
        "hostname": hostname,
        "fqdn": fqdn,
        "interfaces": interfaces,
    }

    # Get all IP addresses (with timeout to prevent indefinite blocking)
    # Use lock to protect global socket timeout modification from concurrent access
    try:
        with _socket_timeout_lock:
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(5.0)
            try:
                # Reuse hostname from above to avoid extra system call and potential inconsistency
                info["all_ips"] = socket.gethostbyname_ex(hostname)[2]
            finally:
                socket.setdefaulttimeout(old_timeout)
    except (socket.gaierror, socket.timeout, OSError):
        info["all_ips"] = []

    # Get interface details
    try:
        if platform.system() == "Linux":
            result = subprocess.run(
                ["ip", "-j", "addr"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                iface_list = json.loads(result.stdout)
                for iface in iface_list:
                    iface_ips: List[Dict[str, Any]] = []
                    iface_info: Dict[str, Any] = {
                        "name": iface.get("ifname"),
                        "state": iface.get("operstate"),
                        "mac": iface.get("address"),
                        "ips": iface_ips,
                    }
                    for addr_info in iface.get("addr_info", []):
                        iface_ips.append({
                            "address": addr_info.get("local"),
                            "prefix": addr_info.get("prefixlen"),
                            "family": addr_info.get("family"),
                        })
                    interfaces.append(iface_info)

        elif platform.system() == "Darwin":
            result = subprocess.run(
                ["ifconfig"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # Simple parsing for macOS
                current_iface: Optional[Dict[str, Any]] = None
                for line in result.stdout.splitlines():
                    if not line.startswith("\t") and ":" in line:
                        iface_name = line.split(":")[0]
                        current_iface = {"name": iface_name, "ips": []}
                        interfaces.append(current_iface)
                    elif current_iface and ("inet " in line or "inet6 " in line):
                        parts = line.split()
                        if len(parts) >= 2:
                            # Determine family based on which token is present
                            if "inet6 " in line:
                                family = "inet6"
                                # inet6 address may have %scope suffix, strip it
                                address = parts[1].split("%")[0]
                            else:
                                family = "inet"
                                address = parts[1]
                            current_iface["ips"].append({
                                "address": address,
                                "family": family,
                            })

    except Exception as e:
        logger.debug(f"Could not get interface details: {e}")

    # Get default gateway
    try:
        if platform.system() == "Linux":
            result = subprocess.run(
                ["ip", "route", "show", "default"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout:
                gateway = _extract_gateway_from_route(result.stdout)
                if gateway:
                    info["default_gateway"] = gateway

        elif platform.system() == "Darwin":
            result = subprocess.run(
                ["route", "-n", "get", "default"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if "gateway:" in line:
                        candidate = line.split(":", 1)[1].strip()
                        if _is_valid_ip(candidate):
                            info["default_gateway"] = candidate
                        else:
                            logger.debug(f"macOS gateway value is not a valid IP: {candidate}")
                        break

    except Exception as e:
        logger.debug(f"Could not get default gateway: {e}")

    return info
