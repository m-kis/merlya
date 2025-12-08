"""
Merlya Setup - SSH config parser.

Parses ~/.ssh/config file format.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.setup.parsers.utils import safe_parse_port

if TYPE_CHECKING:
    from merlya.setup.models import HostData


async def parse_ssh_config(path: Path) -> list[HostData]:
    """
    Parse SSH config and extract hosts with all connection details.

    Args:
        path: Path to SSH config.

    Returns:
        List of HostData objects.
    """

    hosts: list[HostData] = []
    current_host: dict[str, Any] = {}

    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if line.lower().startswith("host "):
                # Save previous host if valid
                if current_host.get("name") and current_host["name"] != "*":
                    hosts.append(_create_host_data(current_host))
                # Start new host
                host_name = line.split()[1]
                current_host = {"name": host_name}

            elif "=" in line or " " in line:
                _parse_ssh_option(line, current_host)

        # Don't forget the last host
        if current_host.get("name") and current_host["name"] != "*":
            hosts.append(_create_host_data(current_host))

    except Exception as e:
        logger.error(f"❌ Failed to parse SSH config: {e}")

    return hosts


def _parse_ssh_option(line: str, current_host: dict[str, Any]) -> None:
    """Parse a single SSH config option line."""
    key, _, value = line.partition("=")
    if not value:
        parts = line.split(None, 1)
        if len(parts) == 2:
            key, value = parts

    key = key.strip().lower()
    value = value.strip()

    if key == "hostname":
        current_host["hostname"] = value
    elif key == "port":
        current_host["port"] = value
    elif key == "user":
        current_host["username"] = value
    elif key == "identityfile":
        if value.startswith("~"):
            value = str(Path(value).expanduser())
        current_host["private_key"] = value
    elif key == "proxyjump":
        current_host["jump_host"] = value
    elif key == "proxycommand" and "jump_host" not in current_host:
        # Extract jump host from ProxyCommand if possible
        match = re.search(r"ssh\s+.*?(\S+)\s*$", value)
        if match:
            current_host["jump_host"] = match.group(1)


def _create_host_data(current_host: dict[str, Any]) -> HostData:
    """Create HostData from parsed SSH config dict."""
    from merlya.setup.models import HostData

    return HostData(
        name=current_host["name"],
        hostname=current_host.get("hostname", current_host["name"]),
        port=safe_parse_port(current_host.get("port"), 22),
        username=current_host.get("username"),
        private_key=current_host.get("private_key"),
        jump_host=current_host.get("jump_host"),
        tags=["ssh-config"],
        source="~/.ssh/config",
    )


def count_ssh_hosts(path: Path) -> int:
    """Count hosts in SSH config."""
    count = 0
    try:
        for line in path.read_text().splitlines():
            if line.strip().lower().startswith("host "):
                hosts = line.split()[1:]
                for h in hosts:
                    if h != "*" and not h.startswith("!"):
                        count += 1
    except Exception:
        pass
    return count


def import_from_ssh_config(path: Path) -> list[dict[str, Any]]:
    """
    Import hosts from SSH config file (sync version for commands).

    Args:
        path: Path to SSH config file.

    Returns:
        List of host dictionaries.
    """
    hosts: list[dict[str, Any]] = []
    current_host: dict[str, Any] = {}

    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if line.lower().startswith("host "):
                if current_host.get("name") and current_host["name"] != "*":
                    hosts.append(current_host)
                host_name = line.split()[1]
                current_host = {"name": host_name}

            elif "=" in line or " " in line:
                key, _, value = line.partition("=")
                if not value:
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        key, value = parts

                key = key.strip().lower()
                value = value.strip()

                if key == "hostname":
                    current_host["hostname"] = value
                elif key == "port":
                    current_host["port"] = safe_parse_port(value, 22)
                elif key == "user":
                    current_host["user"] = value
                elif key == "identityfile":
                    if value.startswith("~"):
                        value = str(Path(value).expanduser())
                    current_host["identityfile"] = value
                elif key == "proxyjump":
                    current_host["proxyjump"] = value

        if current_host.get("name") and current_host["name"] != "*":
            hosts.append(current_host)

    except Exception as e:
        logger.error(f"❌ Failed to import SSH config: {e}")

    return hosts
