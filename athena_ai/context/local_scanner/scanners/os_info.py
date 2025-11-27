"""
OS information scanner.
"""
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict

from athena_ai.utils.logger import logger


def scan_os() -> Dict[str, Any]:
    """Scan OS, kernel, distribution info."""
    info = {
        "hostname": platform.node(),
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
    }

    # Linux-specific: get distribution info
    if platform.system() == "Linux":
        try:
            # Try reading /etc/os-release
            os_release = Path("/etc/os-release")
            if os_release.exists():
                release_info = {}
                with open(os_release, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, value = line.split("=", 1)
                            value = value.strip()
                            # Remove surrounding quotes (single or double)
                            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                                value = value[1:-1]
                            release_info[key.lower()] = value
                info["distro"] = release_info.get("name", "Unknown")
                info["distro_version"] = release_info.get("version_id", "")
                info["distro_codename"] = release_info.get("version_codename", "")
        except Exception as e:
            logger.debug(f"Could not read /etc/os-release: {e}")

    # macOS-specific
    elif platform.system() == "Darwin":
        info["distro"] = "macOS"
        try:
            result = subprocess.run(
                ["sw_vers", "-productVersion"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                info["distro_version"] = result.stdout.strip()
        except Exception as e:
            logger.debug(f"Could not get macOS version: {e}")

    return info
