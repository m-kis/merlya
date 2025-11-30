"""
Services and processes scanner.
"""
import platform
import subprocess
from typing import Any, Dict, List

from athena_ai.utils.logger import logger


def scan_services() -> Dict[str, Any]:
    """
    Scan active services using multiple methods.

    Methods:
    - systemd (Linux)
    - launchd (macOS)
    - Docker containers
    """
    services: Dict[str, List[Dict[str, Any]]] = {
        "systemd": [],
        "launchd": [],
        "docker": [],
    }

    system = platform.system()

    # systemd (Linux)
    if system == "Linux":
        try:
            result = subprocess.run(
                ["systemctl", "list-units", "--type=service", "--state=running", "--no-pager", "--no-legend"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    parts = line.split()
                    if parts:
                        service_name = parts[0].replace(".service", "")
                        services["systemd"].append({
                            "name": service_name,
                            "state": "running",
                        })
        except FileNotFoundError:
            logger.debug("systemctl not found")
        except Exception as e:
            logger.debug(f"Could not list systemd services: {e}")

    # launchd (macOS)
    if system == "Darwin":
        try:
            result = subprocess.run(
                ["launchctl", "list"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                lines = result.stdout.splitlines()[1:]  # Skip header
                for line in lines[:50]:  # Limit to 50
                    parts = line.split("\t")
                    if len(parts) >= 3:
                        services["launchd"].append({
                            "name": parts[2],
                            "pid": parts[0] if parts[0] != "-" else None,
                        })
        except FileNotFoundError:
            logger.debug("launchctl not found")
        except Exception as e:
            logger.debug(f"Could not list launchd services: {e}")

    # Docker containers
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) >= 3:
                    services["docker"].append({
                        "name": parts[0],
                        "image": parts[1],
                        "status": parts[2],
                    })
    except FileNotFoundError:
        logger.debug("docker not found")
    except Exception as e:
        logger.debug(f"Could not list Docker containers: {e}")

    return services


def scan_processes() -> List[Dict[str, Any]]:
    """Scan top running processes."""
    processes = []
    platform_system = platform.system()

    try:
        if platform_system == "Darwin":
            # macOS: use ps without --sort
            cmd = ["ps", "-eo", "pid,user,%cpu,%mem,comm"]
        else:
            # Non-macOS: use ps with --sort
            cmd = ["ps", "-eo", "pid,user,%cpu,%mem,comm", "--sort=-%cpu"]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            lines = result.stdout.splitlines()[1:]  # Skip header

            # For macOS, sort manually by CPU
            if platform_system == "Darwin":
                def parse_cpu(line):
                    parts = line.split()
                    try:
                        return float(parts[2]) if len(parts) > 2 else 0
                    except (ValueError, IndexError):
                        return 0
                lines = sorted(lines, key=parse_cpu, reverse=True)

            for line in lines[:20]:  # Top 20 processes
                parts = line.split(maxsplit=4)
                if len(parts) >= 5:
                    try:
                        processes.append({
                            "pid": int(parts[0]),
                            "user": parts[1],
                            "cpu_percent": float(parts[2]),
                            "mem_percent": float(parts[3]),
                            "command": parts[4],
                        })
                    except (ValueError, IndexError, TypeError) as e:
                        logger.debug(f"Skipping malformed process line: {line!r} ({e})")
                        continue

    except Exception as e:
        logger.debug(f"Could not list processes: {e}")

    return processes
