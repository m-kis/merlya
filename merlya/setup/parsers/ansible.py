"""
Merlya Setup - Ansible inventory parser.

Parses Ansible inventory files (INI and YAML formats).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.setup.parsers.utils import safe_parse_port

if TYPE_CHECKING:
    from pathlib import Path

    from merlya.setup.models import HostData


def _expand_ansible_range(pattern: str) -> list[str]:
    """
    Expand Ansible host range patterns.

    Examples:
    - web[01:03].example.com -> web01, web02, web03.example.com
    - db[a:c] -> dba, dbb, dbc
    - server[1:3:2] -> server1, server3 (step of 2)
    """
    # Pattern: prefix[start:end:step]suffix
    match = re.match(r"(.*)\[(\d+):(\d+)(?::(\d+))?\](.*)", pattern)

    if not match:
        # Check for letter range
        match = re.match(r"(.*)\[([a-z]):([a-z])\](.*)", pattern, re.IGNORECASE)
        if match:
            prefix, start, end, suffix = match.groups()
            return [f"{prefix}{chr(c)}{suffix}" for c in range(ord(start), ord(end) + 1)]
        return [pattern]

    prefix, start, end, step, suffix = match.groups()
    step = int(step) if step else 1

    # Preserve leading zeros
    width = len(start)
    start_num = int(start)
    end_num = int(end)

    return [f"{prefix}{str(i).zfill(width)}{suffix}" for i in range(start_num, end_num + 1, step)]


async def parse_ansible_inventory(path: Path) -> list[HostData]:
    """
    Parse Ansible inventory file (INI or YAML format).

    Args:
        path: Path to inventory file.

    Returns:
        List of HostData objects.
    """

    hosts: list[HostData] = []

    try:
        content = path.read_text()

        # Detect format
        if path.suffix in (".yml", ".yaml") or content.strip().startswith("---"):
            hosts = await _parse_ansible_yaml(path, content)
        else:
            hosts = await _parse_ansible_ini(content)

    except Exception as e:
        logger.error(f"❌ Failed to parse Ansible inventory: {e}")

    return hosts


async def _parse_ansible_ini(content: str) -> list[HostData]:
    """Parse Ansible INI format inventory."""

    hosts: list[HostData] = []
    current_group: str | None = "ungrouped"

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue

        # Group header
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1]
            # Skip :vars and :children sections
            current_group = group if ":" not in group else None
            continue

        # Skip if in :vars or :children section
        if current_group is None:
            continue

        # Skip variable-only definitions
        parts = line.split()
        if parts and "=" in parts[0]:
            continue

        host_data_list = _parse_ini_host_line(line, current_group)
        hosts.extend(host_data_list)

    return hosts


def _parse_ini_host_line(line: str, current_group: str | None) -> list[HostData]:
    """Parse a single host line from INI format, expanding ranges."""
    from merlya.setup.models import HostData

    hosts: list[HostData] = []
    parts = line.split()
    if not parts:
        return hosts

    host_pattern = parts[0]
    hostname = None
    port = 22
    username = None

    # Parse inline variables
    for part in parts[1:]:
        if "=" in part:
            key, _, value = part.partition("=")
            if key == "ansible_host":
                hostname = value
            elif key == "ansible_port":
                port = safe_parse_port(value, 22)
            elif key in ("ansible_user", "ansible_ssh_user"):
                username = value

    tags = ["ansible"]
    if current_group and current_group != "ungrouped":
        tags.append(f"ansible:{current_group}")

    # Expand ranges
    expanded_names = _expand_ansible_range(host_pattern)

    for name in expanded_names:
        hosts.append(
            HostData(
                name=name,
                hostname=hostname or name,
                port=port,
                username=username,
                tags=tags.copy(),
                source="ansible-inventory",
            )
        )

    return hosts


async def _parse_ansible_yaml(_path: Path, content: str) -> list[HostData]:
    """Parse Ansible YAML format inventory."""

    hosts: list[HostData] = []

    try:
        import yaml

        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            return hosts

        # Parse all groups
        for group_name, group_data in data.items():
            if not isinstance(group_data, dict):
                continue

            group_hosts = _extract_hosts_from_group(group_data, group_name)
            hosts.extend(group_hosts)

    except ImportError:
        logger.warning("⚠️ PyYAML not installed - cannot parse YAML inventory")
    except Exception as e:
        logger.error(f"❌ Failed to parse YAML inventory: {e}")

    return hosts


def _extract_hosts_from_group(group_data: dict[str, Any], group_name: str) -> list[HostData]:
    """Extract hosts from a group definition."""
    from merlya.setup.models import HostData

    hosts: list[HostData] = []

    # Direct hosts under group
    hosts_section = group_data.get("hosts", {})
    if isinstance(hosts_section, dict):
        for host_name, host_vars in hosts_section.items():
            host_vars = host_vars or {}
            hosts.append(
                HostData(
                    name=host_name,
                    hostname=host_vars.get("ansible_host", host_name),
                    port=safe_parse_port(host_vars.get("ansible_port"), 22),
                    username=host_vars.get("ansible_user") or host_vars.get("ansible_ssh_user"),
                    tags=["ansible", group_name],
                    source="ansible-inventory",
                )
            )

    # Nested children groups
    children = group_data.get("children", {})
    if isinstance(children, dict):
        for child_name, child_data in children.items():
            if isinstance(child_data, dict):
                child_hosts = _extract_hosts_from_group(child_data, child_name)
                hosts.extend(child_hosts)

    return hosts


def count_ansible_hosts(path: Path) -> int:
    """Count hosts in Ansible inventory."""
    count = 0
    try:
        content = path.read_text()
        if path.suffix in (".yml", ".yaml") or content.strip().startswith("---"):
            import yaml

            data = yaml.safe_load(content)
            count = _count_yaml_hosts(data)
        else:
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith(("#", ";", "[")):
                    continue
                if "=" not in line.split()[0] if line.split() else True:
                    count += 1
    except Exception:
        pass
    return count


def _count_yaml_hosts(data: dict[str, Any] | None, depth: int = 0) -> int:
    """Recursively count hosts in YAML inventory."""
    if not isinstance(data, dict) or depth > 10:
        return 0

    count = 0
    hosts_section = data.get("hosts", {})
    if isinstance(hosts_section, dict):
        count += len(hosts_section)

    children = data.get("children", {})
    if isinstance(children, dict):
        for child_data in children.values():
            if isinstance(child_data, dict):
                count += _count_yaml_hosts(child_data, depth + 1)

    return count
