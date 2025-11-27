"""
Network scanner.
"""
import platform
import socket
import subprocess
from typing import Any, Dict

from athena_ai.utils.logger import logger


def scan_network() -> Dict[str, Any]:
    """Scan network interfaces and configuration."""
    info = {
        "hostname": socket.gethostname(),
        "fqdn": socket.getfqdn(),
        "interfaces": [],
    }

    # Get all IP addresses (with timeout to prevent indefinite blocking)
    try:
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(5.0)
        try:
            info["all_ips"] = socket.gethostbyname_ex(socket.gethostname())[2]
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
                import json
                interfaces = json.loads(result.stdout)
                for iface in interfaces:
                    iface_info = {
                        "name": iface.get("ifname"),
                        "state": iface.get("operstate"),
                        "mac": iface.get("address"),
                        "ips": [],
                    }
                    for addr_info in iface.get("addr_info", []):
                        iface_info["ips"].append({
                            "address": addr_info.get("local"),
                            "prefix": addr_info.get("prefixlen"),
                            "family": addr_info.get("family"),
                        })
                    info["interfaces"].append(iface_info)

        elif platform.system() == "Darwin":
            result = subprocess.run(
                ["ifconfig"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # Simple parsing for macOS
                current_iface = None
                for line in result.stdout.splitlines():
                    if not line.startswith("\t") and ":" in line:
                        iface_name = line.split(":")[0]
                        current_iface = {"name": iface_name, "ips": []}
                        info["interfaces"].append(current_iface)
                    elif current_iface and "inet " in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            current_iface["ips"].append({
                                "address": parts[1],
                                "family": "inet",
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
                parts = result.stdout.split()
                if len(parts) >= 3:
                    info["default_gateway"] = parts[2]

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
                        info["default_gateway"] = line.split(":")[1].strip()
                        break

    except Exception as e:
        logger.debug(f"Could not get default gateway: {e}")

    return info
