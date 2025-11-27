"""
File scanner.
"""
import os
from pathlib import Path
from typing import Any, Dict


# /etc files to scan
# NOTE: Deliberately excludes sensitive security files:
# - /etc/passwd, /etc/group (PII - user identities)
# - /etc/ssh/* (SSH security configuration)
# - /etc/sudoers (privilege escalation rules)
ETC_FILES_TO_SCAN = [
    "/etc/hosts",
    "/etc/hostname",
    "/etc/resolv.conf",
    "/etc/os-release",
    "/etc/fstab",
    "/etc/crontab",
]


def scan_etc_files() -> Dict[str, Any]:
    """Scan relevant files in /etc."""
    files = {}

    for file_path in ETC_FILES_TO_SCAN:
        path = Path(file_path)
        if path.exists() and path.is_file():
            try:
                # Check file size to avoid reading huge files
                if path.stat().st_size > 100 * 1024:  # 100KB limit
                    files[file_path] = {"error": "file too large", "size": path.stat().st_size}
                    continue

                # Check if readable
                if not os.access(path, os.R_OK):
                    files[file_path] = {"error": "permission denied"}
                    continue

                content = path.read_text(errors="replace")

                # Parse specific files
                if file_path == "/etc/hosts":
                    files[file_path] = _parse_etc_hosts(content)
                elif file_path == "/etc/resolv.conf":
                    files[file_path] = _parse_resolv_conf(content)
                else:
                    # Store raw content (truncated)
                    files[file_path] = {
                        "content": content[:5000] if len(content) > 5000 else content,
                        "truncated": len(content) > 5000,
                    }

            except Exception as e:
                files[file_path] = {"error": str(e)}

    return files


def _parse_etc_hosts(content: str) -> Dict[str, Any]:
    """Parse /etc/hosts file."""
    hosts = []
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            parts = line.split()
            if len(parts) >= 2:
                ip = parts[0]
                hostnames = parts[1:]
                hosts.append({"ip": ip, "hostnames": hostnames})
    return {"entries": hosts, "count": len(hosts)}


def _parse_resolv_conf(content: str) -> Dict[str, Any]:
    """Parse /etc/resolv.conf file."""
    nameservers = []
    search_domains = []

    for line in content.splitlines():
        line = line.strip()
        if line.startswith("nameserver"):
            parts = line.split()
            if len(parts) >= 2:
                nameservers.append(parts[1])
        elif line.startswith("search"):
            parts = line.split()
            search_domains.extend(parts[1:])

    return {"nameservers": nameservers, "search_domains": search_domains}
