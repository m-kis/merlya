"""
Local Scanner - Deep scan of the local machine.

Scans:
- OS/Kernel/Distribution
- Network interfaces
- Services (systemd, launchd, Docker)
- Processes
- Relevant /etc files
- Resources (CPU, RAM, Disk)

Caching:
- Stored in BDD
- Re-scanned only if no scan exists or scan > 12h old
"""

import os
import platform
import socket
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from athena_ai.utils.logger import logger


@dataclass
class LocalContext:
    """Complete local machine context."""

    os_info: Dict[str, Any] = field(default_factory=dict)
    network: Dict[str, Any] = field(default_factory=dict)
    services: Dict[str, Any] = field(default_factory=dict)
    processes: List[Dict[str, Any]] = field(default_factory=list)
    etc_files: Dict[str, Any] = field(default_factory=dict)
    resources: Dict[str, Any] = field(default_factory=dict)
    scanned_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "os_info": self.os_info,
            "network": self.network,
            "services": self.services,
            "processes": self.processes,
            "etc_files": self.etc_files,
            "resources": self.resources,
            "scanned_at": self.scanned_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LocalContext":
        """Create from dictionary."""
        scanned_at = data.get("scanned_at")
        if isinstance(scanned_at, str):
            try:
                scanned_at = datetime.fromisoformat(scanned_at)
            except (ValueError, TypeError):
                # Invalid timestamp - use sentinel to force rescan
                scanned_at = datetime.min
        elif scanned_at is None:
            # Missing timestamp - use sentinel to indicate unknown scan time
            # This will force a rescan rather than making old data appear fresh
            scanned_at = datetime.min

        return cls(
            os_info=data.get("os_info", {}),
            network=data.get("network", {}),
            services=data.get("services", {}),
            processes=data.get("processes", []),
            etc_files=data.get("etc_files", {}),
            resources=data.get("resources", {}),
            scanned_at=scanned_at,
        )


class LocalScanner:
    """
    Scanner for the local machine.

    Stored in BDD, re-scanned only if:
    - No scan exists
    - Scan is older than TTL (default: 12h)
    """

    DEFAULT_TTL_HOURS = 12

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

    def __init__(self, repo: Optional[Any] = None):
        """Initialize scanner with optional repository."""
        self._repo = repo

    @property
    def repo(self):
        """Lazy load repository to avoid circular imports."""
        if self._repo is None:
            from athena_ai.memory.persistence.inventory_repository import InventoryRepository
            self._repo = InventoryRepository()
        return self._repo

    def get_or_scan(self, force: bool = False, ttl_hours: Optional[int] = None) -> LocalContext:
        """
        Get local context from cache or scan if necessary.

        Logic:
        1. If force=True → always scan
        2. If no existing scan → scan
        3. If scan exists and < TTL → return cached
        4. If scan exists and >= TTL → rescan

        Args:
            force: Force a new scan even if cache is valid
            ttl_hours: Custom TTL (default: 12h)

        Returns:
            LocalContext with local machine information
        """
        ttl = ttl_hours if ttl_hours is not None else self.DEFAULT_TTL_HOURS

        if not force:
            # Check for existing scan
            existing = self.repo.get_local_context()

            if existing:
                scanned_at_str = existing.get("scanned_at")
                if scanned_at_str:
                    try:
                        scanned_at = datetime.fromisoformat(scanned_at_str)
                        # Normalize to UTC for consistent age calculation
                        if scanned_at.tzinfo is None:
                            scanned_at = scanned_at.replace(tzinfo=timezone.utc)
                        else:
                            scanned_at = scanned_at.astimezone(timezone.utc)
                        age_hours = (datetime.now(timezone.utc) - scanned_at).total_seconds() / 3600

                        if age_hours < ttl:
                            logger.debug(f"Using cached local context (age: {age_hours:.1f}h)")
                            return LocalContext.from_dict(existing)

                        logger.info(f"Local context expired ({age_hours:.1f}h > {ttl}h), rescanning...")
                    except (ValueError, TypeError):
                        logger.warning("Invalid scanned_at timestamp, rescanning...")

        # Perform scan
        logger.info("Scanning local machine...")
        context = self.scan_all()

        # Save to database
        self.repo.save_local_context(context.to_dict())
        logger.info(f"Local context saved (scanned at: {context.scanned_at})")

        return context

    def scan_all(self) -> LocalContext:
        """Perform a complete scan of the local machine."""
        return LocalContext(
            os_info=self._scan_os(),
            network=self._scan_network(),
            services=self._scan_services(),
            processes=self._scan_processes(),
            etc_files=self._scan_etc_files(),
            resources=self._scan_resources(),
            scanned_at=datetime.now(),
        )

    def _scan_os(self) -> Dict[str, Any]:
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
                    with open(os_release) as f:
                        for line in f:
                            line = line.strip()
                            if "=" in line:
                                key, value = line.split("=", 1)
                                release_info[key.lower()] = value.strip('"')
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
            except Exception:
                pass

        return info

    def _scan_network(self) -> Dict[str, Any]:
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

    def _scan_services(self) -> Dict[str, Any]:
        """
        Scan active services using multiple methods.

        Methods:
        - systemd (Linux)
        - launchd (macOS)
        - Docker containers
        """
        services = {
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
                pass
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
            pass
        except Exception as e:
            logger.debug(f"Could not list Docker containers: {e}")

        return services

    def _scan_processes(self) -> List[Dict[str, Any]]:
        """Scan top running processes."""
        processes = []

        try:
            if platform.system() == "Darwin":
                # macOS: use ps without --sort
                cmd = ["ps", "-eo", "pid,user,%cpu,%mem,comm"]
            else:
                # Linux: use ps with --sort
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
                if platform.system() == "Darwin":
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
                        processes.append({
                            "pid": int(parts[0]),
                            "user": parts[1],
                            "cpu_percent": float(parts[2]),
                            "mem_percent": float(parts[3]),
                            "command": parts[4],
                        })

        except Exception as e:
            logger.debug(f"Could not list processes: {e}")

        return processes

    def _scan_etc_files(self) -> Dict[str, Any]:
        """Scan relevant files in /etc."""
        files = {}

        for file_path in self.ETC_FILES_TO_SCAN:
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
                        files[file_path] = self._parse_etc_hosts(content)
                    elif file_path == "/etc/resolv.conf":
                        files[file_path] = self._parse_resolv_conf(content)
                    else:
                        # Store raw content (truncated)
                        files[file_path] = {
                            "content": content[:5000] if len(content) > 5000 else content,
                            "truncated": len(content) > 5000,
                        }

                except Exception as e:
                    files[file_path] = {"error": str(e)}

        return files

    def _parse_etc_hosts(self, content: str) -> Dict[str, Any]:
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

    def _parse_resolv_conf(self, content: str) -> Dict[str, Any]:
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

    def _scan_resources(self) -> Dict[str, Any]:
        """Scan system resources (CPU, RAM, Disk)."""
        resources = {}

        # CPU info
        try:
            cpu_count = os.cpu_count()
            resources["cpu"] = {
                "count": cpu_count,
            }

            # Load average (Unix only)
            if hasattr(os, "getloadavg"):
                load = os.getloadavg()
                resources["cpu"]["load_1m"] = load[0]
                resources["cpu"]["load_5m"] = load[1]
                resources["cpu"]["load_15m"] = load[2]

        except Exception as e:
            logger.debug(f"Could not get CPU info: {e}")

        # Memory info
        try:
            if platform.system() == "Linux":
                with open("/proc/meminfo") as f:
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
                            page_size = int(line.split()[-2])
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
                    total_bytes = int(result2.stdout.strip()) if result2.returncode == 0 else 0

                    free_bytes = stats.get("Pages free", 0)
                    resources["memory"] = {
                        "total_gb": round(total_bytes / 1024 / 1024 / 1024, 2),
                        "free_gb": round(free_bytes / 1024 / 1024 / 1024, 2),
                    }

        except Exception as e:
            logger.debug(f"Could not get memory info: {e}")

        # Disk info
        try:
            result = subprocess.run(
                ["df", "-h", "/"],
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


# Convenience function
def get_local_scanner(repo: Optional[Any] = None) -> LocalScanner:
    """Get a local scanner instance."""
    return LocalScanner(repo)
