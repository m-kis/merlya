"""
Structured format parsers (CSV, JSON, YAML).
"""
import csv
import io
import json
from typing import List, Tuple, Optional, Dict

from athena_ai.utils.logger import logger
from ..models import ParsedHost

# Common hostname field names in CSV/JSON
HOSTNAME_FIELDS = [
    "hostname",
    "host",
    "name",
    "server",
    "fqdn",
    "node",
    "machine",
]

IP_FIELDS = [
    "ip",
    "ip_address",
    "ipaddress",
    "address",
    "addr",
    "ansible_host",
]

ENV_FIELDS = [
    "environment",
    "env",
    "stage",
    "tier",
]


def _find_field(fieldnames: List[str], candidates: List[str]) -> Optional[str]:
    """Find a field from a list of candidates."""
    if not fieldnames:
        return None
    fieldnames_lower = [f.lower() for f in fieldnames]
    for candidate in candidates:
        if candidate in fieldnames_lower:
            return fieldnames[fieldnames_lower.index(candidate)]
    return None


def _get_field(item: Dict, candidates: List[str]) -> Optional[str]:
    """Get a field value from a dict using candidate names."""
    for candidate in candidates:
        if candidate in item:
            return str(item[candidate])
    return None


def parse_csv(content: str) -> Tuple[List[ParsedHost], List[str]]:
    """Parse CSV content."""
    hosts = []
    errors = []

    try:
        reader = csv.DictReader(io.StringIO(content))
        fieldnames = [f.lower() for f in (reader.fieldnames or [])]

        # Find the hostname field
        hostname_field = None
        for field in HOSTNAME_FIELDS:
            if field in fieldnames:
                hostname_field = reader.fieldnames[fieldnames.index(field)]
                break

        if not hostname_field:
            errors.append(f"No hostname field found. Expected one of: {HOSTNAME_FIELDS}")
            return hosts, errors

        # Find other fields
        ip_field = _find_field(reader.fieldnames, IP_FIELDS)
        env_field = _find_field(reader.fieldnames, ENV_FIELDS)

        for row in reader:
            hostname = row.get(hostname_field, "").strip()
            if not hostname:
                continue

            host = ParsedHost(
                hostname=hostname.lower(),
                ip_address=row.get(ip_field, "").strip() if ip_field else None,
                environment=row.get(env_field, "").strip() if env_field else None,
            )

            # Add remaining fields as metadata
            for key, value in row.items():
                if key not in [hostname_field, ip_field, env_field] and value:
                    if key.lower() == "groups" or key.lower() == "group":
                        host.groups = [g.strip() for g in value.split(",")]
                    elif key.lower() == "aliases" or key.lower() == "alias":
                        host.aliases = [a.strip() for a in value.split(",")]
                    elif key.lower() == "role":
                        host.role = value.strip()
                    elif key.lower() == "service":
                        host.service = value.strip()
                    elif key.lower() in ["port", "ssh_port"]:
                        try:
                            host.ssh_port = int(value)
                        except ValueError:
                            pass
                    else:
                        host.metadata[key] = value

            hosts.append(host)

    except Exception as e:
        errors.append(f"CSV parsing error: {e}")

    return hosts, errors


def parse_json(content: str) -> Tuple[List[ParsedHost], List[str]]:
    """Parse JSON content."""
    hosts = []
    errors = []

    try:
        data = json.loads(content)

        # Handle array of hosts
        if isinstance(data, list):
            items = data
        # Handle object with hosts key
        elif isinstance(data, dict):
            if "hosts" in data:
                items = data["hosts"]
            else:
                # Single host or dict of hosts
                items = [data] if "hostname" in data or "host" in data else list(data.values())
        else:
            errors.append("Invalid JSON structure")
            return hosts, errors

        for item in items:
            if not isinstance(item, dict):
                continue

            # Find hostname
            hostname = None
            for field in HOSTNAME_FIELDS:
                if field in item:
                    hostname = item[field]
                    break

            if not hostname:
                continue

            # Parse ssh_port with safe int conversion
            raw_port = item.get("ssh_port", item.get("port"))
            ssh_port = 22  # default
            if raw_port is not None:
                try:
                    ssh_port = int(raw_port)
                except (ValueError, TypeError):
                    logger.debug(f"Invalid ssh_port value '{raw_port}' for host {hostname}, using default 22")

            host = ParsedHost(
                hostname=str(hostname).lower(),
                ip_address=_get_field(item, IP_FIELDS),
                environment=_get_field(item, ENV_FIELDS),
                groups=item.get("groups", []) if isinstance(item.get("groups"), list) else [],
                aliases=item.get("aliases", []) if isinstance(item.get("aliases"), list) else [],
                role=item.get("role"),
                service=item.get("service"),
                ssh_port=ssh_port,
                metadata={k: v for k, v in item.items()
                          if k not in ["hostname", "host", "ip", "ip_address", "environment", "env",
                                       "groups", "aliases", "role", "service", "ssh_port", "port"]},
            )
            hosts.append(host)

    except json.JSONDecodeError as e:
        errors.append(f"JSON parsing error: {e}")

    return hosts, errors


def parse_yaml(content: str) -> Tuple[List[ParsedHost], List[str]]:
    """Parse YAML content."""
    hosts = []
    errors = []

    try:
        import yaml
        data = yaml.safe_load(content)

        # Reuse JSON parsing logic
        if data:
            return parse_json(json.dumps(data))

    except ImportError:
        errors.append("PyYAML not installed. Install with: pip install pyyaml")
    except Exception as e:
        errors.append(f"YAML parsing error: {e}")

    return hosts, errors
