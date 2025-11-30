"""
Resources scanner (CPU, RAM, Disk).
"""
import os
import platform
import subprocess
from typing import Any, Dict

from athena_ai.utils.logger import logger


def scan_resources() -> Dict[str, Any]:
    """Scan system resources (CPU, RAM, Disk)."""
    resources = {}

    # CPU info
    try:
        cpu_count = os.cpu_count()
        if cpu_count is None:
            logger.debug("os.cpu_count() returned None, defaulting to 1")
            cpu_count = 1
        resources["cpu"] = {
            "count": cpu_count,
        }

        # Load average (Unix only)
        if hasattr(os, "getloadavg"):
            load = os.getloadavg()
            resources["cpu"]["load_1m"]: float = load[0]
            resources["cpu"]["load_5m"]: float = load[1]
            resources["cpu"]["load_15m"]: float = load[2]

    except Exception as e:
        logger.debug(f"Could not get CPU info: {e}")

    # Memory info
    try:
        if platform.system() == "Linux":
            with open("/proc/meminfo", encoding="utf-8") as f:
                meminfo = {}
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

                resources["memory"] = {
                    "total_gb": round(total_kb / 1024 / 1024, 2),
                    "available_gb": round(available_kb / 1024 / 1024, 2),
                    "used_gb": round((total_kb - available_kb) / 1024 / 1024, 2),
                    "percent_used": round((total_kb - available_kb) / total_kb * 100, 1) if total_kb else 0,
                }

        elif platform.system() == "Darwin":
            # macOS: use vm_stat
            result = subprocess.run(
                ["vm_stat"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                # Parse vm_stat output
                page_size = 4096  # Default page size
                stats = {}
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
                if result2.returncode == 0:
                    total_bytes = int(result2.stdout.strip())
                    free_bytes = stats.get("Pages free", 0)
                    inactive_bytes = stats.get("Pages inactive", 0)
                    # Include inactive pages as they can be quickly reclaimed
                    available_bytes = free_bytes + inactive_bytes
                    used_bytes = total_bytes - available_bytes
                    resources["memory"] = {
                        "total_gb": round(total_bytes / 1024 / 1024 / 1024, 2),
                        "available_gb": round(available_bytes / 1024 / 1024 / 1024, 2),
                        "free_gb": round(free_bytes / 1024 / 1024 / 1024, 2),
                        "used_gb": round(used_bytes / 1024 / 1024 / 1024, 2),
                        "percent_used": round(used_bytes / total_bytes * 100, 2) if total_bytes else 0,
                    }

    except Exception as e:
        logger.debug(f"Could not get memory info: {e}")

    # Disk info
    try:
        result = subprocess.run(
            ["df", "-P", "-h", "/"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            lines = result.stdout.splitlines()
            if len(lines) >= 2:
                parts = lines[1].split()
                if len(parts) >= 5:
                    resources["disk"] = {
                        "filesystem": parts[0],
                        "total": parts[1],
                        "used": parts[2],
                        "available": parts[3],
                        "percent_used": parts[4],
                    }

    except Exception as e:
        logger.debug(f"Could not get disk info: {e}")

    return resources
