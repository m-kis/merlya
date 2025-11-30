"""
Resources scanner (CPU, RAM, Disk).
"""
import os
import platform
import subprocess
from typing import Any, Dict, Union

from athena_ai.utils.logger import logger

# Type alias for resource values
ResourceValue = Union[int, float, str]
ResourceDict = Dict[str, Any]


def scan_resources() -> Dict[str, Any]:
    """Scan system resources (CPU, RAM, Disk)."""
    resources: Dict[str, Any] = {}

    # CPU info
    try:
        cpu_count = os.cpu_count()
        if cpu_count is None:
            logger.debug("os.cpu_count() returned None, defaulting to 1")
            cpu_count = 1

        cpu_info: Dict[str, ResourceValue] = {"count": cpu_count}

        # Load average (Unix only)
        if hasattr(os, "getloadavg"):
            load = os.getloadavg()
            cpu_info["load_1m"] = load[0]
            cpu_info["load_5m"] = load[1]
            cpu_info["load_15m"] = load[2]

        resources["cpu"] = cpu_info

    except Exception as e:
        logger.debug(f"Could not get CPU info: {e}")

    # Memory info
    try:
        if platform.system() == "Linux":
            resources["memory"] = _scan_linux_memory()

        elif platform.system() == "Darwin":
            resources["memory"] = _scan_darwin_memory()

    except Exception as e:
        logger.debug(f"Could not get memory info: {e}")

    # Disk info
    try:
        disk_info = _scan_disk()
        if disk_info:
            resources["disk"] = disk_info

    except Exception as e:
        logger.debug(f"Could not get disk info: {e}")

    return resources


def _scan_linux_memory() -> Dict[str, ResourceValue]:
    """Scan memory on Linux systems."""
    with open("/proc/meminfo", encoding="utf-8") as f:
        meminfo: Dict[str, int] = {}
        for line in f:
            parts = line.split(":")
            if len(parts) == 2:
                key = parts[0].strip()
                value_parts = parts[1].strip().split()
                if value_parts:
                    try:
                        meminfo[key] = int(value_parts[0])
                    except ValueError:
                        # Skip non-numeric values
                        pass

        total_kb = meminfo.get("MemTotal", 0)
        free_kb = meminfo.get("MemFree", 0)
        available_kb = meminfo.get("MemAvailable", free_kb)

        percent_used: float = 0.0
        if total_kb > 0:
            percent_used = round((total_kb - available_kb) / total_kb * 100, 1)

        return {
            "total_gb": round(total_kb / 1024 / 1024, 2),
            "available_gb": round(available_kb / 1024 / 1024, 2),
            "used_gb": round((total_kb - available_kb) / 1024 / 1024, 2),
            "percent_used": percent_used,
        }


def _scan_darwin_memory() -> Dict[str, ResourceValue]:
    """Scan memory on macOS systems."""
    result = subprocess.run(
        ["vm_stat"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        return {}

    # Parse vm_stat output
    page_size = 4096  # Default page size
    stats: Dict[str, int] = {}

    for line in result.stdout.splitlines():
        if "page size of" in line:
            parts = line.split()
            if len(parts) >= 2:
                try:
                    page_size = int(parts[-2])
                except (ValueError, IndexError):
                    logger.debug(f"Could not parse page size from: {line}")
        elif ":" in line:
            parts = line.split(":")
            key = parts[0].strip()
            try:
                value = int(parts[1].strip().rstrip("."))
                stats[key] = value * page_size
            except ValueError:
                pass

    # Get total memory
    result2 = subprocess.run(
        ["sysctl", "-n", "hw.memsize"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result2.returncode != 0:
        return {}

    total_bytes = int(result2.stdout.strip())
    free_bytes = stats.get("Pages free", 0)
    inactive_bytes = stats.get("Pages inactive", 0)
    # Include inactive pages as they can be quickly reclaimed
    available_bytes = free_bytes + inactive_bytes
    used_bytes = total_bytes - available_bytes

    percent_used: float = 0.0
    if total_bytes > 0:
        percent_used = round(used_bytes / total_bytes * 100, 2)

    return {
        "total_gb": round(total_bytes / 1024 / 1024 / 1024, 2),
        "available_gb": round(available_bytes / 1024 / 1024 / 1024, 2),
        "free_gb": round(free_bytes / 1024 / 1024 / 1024, 2),
        "used_gb": round(used_bytes / 1024 / 1024 / 1024, 2),
        "percent_used": percent_used,
    }


def _scan_disk() -> Dict[str, str]:
    """Scan disk usage."""
    result = subprocess.run(
        ["df", "-P", "-h", "/"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        return {}

    lines = result.stdout.splitlines()
    if len(lines) < 2:
        return {}

    parts = lines[1].split()
    if len(parts) < 5:
        return {}

    return {
        "filesystem": parts[0],
        "total": parts[1],
        "used": parts[2],
        "available": parts[3],
        "percent_used": parts[4],
    }
