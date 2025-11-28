"""
File scanner.
"""
import os
from pathlib import Path
from typing import Any, Dict

# File scanning limits
MAX_FILE_SIZE_BYTES = 10 * 1024  # 10KB - aligned with content truncation
MAX_CONTENT_CHARS = 5000

# Base directory for /etc file scanning
ETC_BASE = Path("/etc")

# /etc files to scan
# NOTE: Deliberately excludes sensitive security files:
# - /etc/passwd, /etc/group (PII - user identities)
# - /etc/ssh/* (SSH security configuration)
# - /etc/sudoers (privilege escalation rules)
# - /etc/fstab (may contain mount credentials for NFS/CIFS)
# - /etc/crontab (reveals operational patterns and scheduled tasks)
#
# PRIVACY NOTE: The included files may still expose organizational information:
# - /etc/hosts may contain internal hostnames (project names, network topology)
# - /etc/hostname exposes machine identity
# - /etc/resolv.conf reveals internal DNS infrastructure
# This data is collected locally for the user's own context and is not transmitted
# externally. Users should review their organization's data handling policies.
ETC_FILES_TO_SCAN = [
    "/etc/hosts",
    "/etc/hostname",
    "/etc/resolv.conf",
    "/etc/os-release",
]


def scan_etc_files() -> Dict[str, Any]:
    """Scan relevant files in /etc."""
    files = {}

    for file_path in ETC_FILES_TO_SCAN:
        path = Path(file_path)
        # Resolve symlinks (strict=False to handle non-existent paths gracefully)
        try:
            resolved_path = path.resolve(strict=False)
        except (OSError, RuntimeError):
            files[file_path] = {"error": "path resolution failed"}
            continue

        # Validate the resolved path is contained within /etc
        # Use try/except to handle edge cases where paths have no common base
        try:
            etc_resolved = ETC_BASE.resolve(strict=False)
            common = os.path.commonpath([str(resolved_path), str(etc_resolved)])
            if common != str(etc_resolved):
                files[file_path] = {"error": "symlink outside /etc"}
                continue
        except ValueError:
            # commonpath raises ValueError if paths are on different drives (Windows)
            # or have no common path
            files[file_path] = {"error": "invalid path"}
            continue

        # Check existence and file type on resolved path
        if not resolved_path.exists():
            files[file_path] = {"error": "file not found"}
            continue

        if not resolved_path.is_file():
            files[file_path] = {"error": "not a regular file"}
            continue

        try:
            # Check file size to avoid reading huge files
            stat = resolved_path.stat()
            if stat.st_size > MAX_FILE_SIZE_BYTES:
                files[file_path] = {"error": "file too large", "size": stat.st_size}
                continue

            # Check if readable
            if not os.access(resolved_path, os.R_OK):
                files[file_path] = {"error": "permission denied"}
                continue

            content = resolved_path.read_text(errors="replace")

            # Parse specific files
            if file_path == "/etc/hosts":
                files[file_path] = _parse_etc_hosts(content)
            elif file_path == "/etc/resolv.conf":
                files[file_path] = _parse_resolv_conf(content)
            else:
                # Store raw content (truncated)
                files[file_path] = {
                    "content": content[:MAX_CONTENT_CHARS] if len(content) > MAX_CONTENT_CHARS else content,
                    "truncated": len(content) > MAX_CONTENT_CHARS,
                }

        except Exception as e:
            files[file_path] = {"error": str(e)}

    return files


def _parse_etc_hosts(content: str) -> Dict[str, Any]:
    """Parse /etc/hosts file."""
    hosts = []
    for line in content.splitlines():
        # Remove inline comments
        line = line.split('#', 1)[0].strip()
        if line:
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
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if not parts:
            continue
        directive = parts[0]
        if directive == "nameserver":
            if len(parts) >= 2:
                nameservers.append(parts[1])
        elif directive == "search":
            search_domains.extend(parts[1:])
        elif directive == "domain":
            # "domain" is equivalent to a single search entry
            if len(parts) >= 2:
                search_domains.insert(0, parts[1])

    return {"nameservers": nameservers, "search_domains": search_domains}
