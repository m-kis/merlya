"""
Structured format parsers (CSV, JSON, YAML).
"""
import csv
import io
import json
from typing import Any, Dict, List, Optional, Tuple

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

# Fields that indicate a dict is likely a host object
HOST_INDICATOR_FIELDS = set(
    HOSTNAME_FIELDS + [
        "ip",
        "ip_address",
        "ipaddress",
        "address",
        "ansible_host",
        "ssh_port",
        "port",
        "groups",
        "aliases",
        "role",
        "service",
        "environment",
        "env",
    ]
)

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
    """Get a field value from a dict using candidate names (case-insensitive)."""
    # Build a lowercase-key mapping for case-insensitive lookup
    lower_map = {k.lower(): v for k, v in item.items()}
    for candidate in candidates:
        if candidate.lower() in lower_map:
            value = lower_map[candidate.lower()]
            return str(value) if value is not None else None
    return None


def _get_list_field(item: Dict, key: str) -> List[str]:
    """Get a list field value from a dict (case-insensitive)."""
    lower_map = {k.lower(): v for k, v in item.items()}
    val = lower_map.get(key.lower())
    if isinstance(val, list):
        return [str(v) for v in val if v is not None]
    return []


def _looks_like_host(item: Any) -> bool:
    """Check if an item looks like a host object.

    A valid host object must be a dict and contain at least one
    field that indicates it's a host (hostname, ip, etc.).
    """
    if not isinstance(item, dict):
        return False
    # Check if any key in the dict matches known host indicator fields
    item_keys_lower = {k.lower() for k in item.keys()}
    return bool(item_keys_lower & HOST_INDICATOR_FIELDS)


def _parse_list_field(value: str) -> List[str]:
    """Parse a list field from CSV that may be JSON-encoded or delimited.

    Tries JSON first (preferred format), then falls back to splitting by
    pipe or comma for backward compatibility.
    """
    if not value or not value.strip():
        return []

    value = value.strip()

    # Try JSON first (preferred format from export)
    if value.startswith("["):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if item]
        except json.JSONDecodeError:
            pass

    # Fall back to delimiter splitting for backward compatibility
    # Try pipe first (safer delimiter), then comma
    if "|" in value:
        return [item.strip() for item in value.split("|") if item.strip()]
    else:
        return [item.strip() for item in value.split(",") if item.strip()]


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
                ip_address=(row.get(ip_field) or "").strip() or None if ip_field else None,
                environment=(row.get(env_field) or "").strip() or None if env_field else None,
            )

            # Add remaining fields as metadata
            for key, value in row.items():
                if key not in [hostname_field, ip_field, env_field] and value:
                    if key.lower() == "groups" or key.lower() == "group":
                        host.groups = _parse_list_field(value)
                    elif key.lower() == "aliases" or key.lower() == "alias":
                        host.aliases = _parse_list_field(value)
                    elif key.lower() == "role":
                        host.role = value.strip()
                    elif key.lower() == "service":
                        host.service = value.strip()
                    elif key.lower() in ["port", "ssh_port"]:
                        try:
                            host.ssh_port = int(value)
                        except ValueError:
                            host.ssh_port = 22  # default, consistent with JSON parser
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
            elif _looks_like_host(data):
                # Single host object
                items = [data]
            else:
                # Possibly a dict-of-hosts (e.g., {"web1": {...}, "web2": {...}})
                # Validate that values look like host objects before processing
                potential_hosts = list(data.values())
                if potential_hosts and all(_looks_like_host(v) for v in potential_hosts):
                    items = potential_hosts
                else:
                    # Not a recognized host structure, skip with warning
                    logger.warning(
                        "JSON dict does not contain 'hosts' key and values do not appear "
                        "to be host objects. Skipping. Keys found: %s",
                        list(data.keys())[:10]  # Limit to first 10 keys for readability
                    )
                    return hosts, errors
        else:
            errors.append("Invalid JSON structure")
            return hosts, errors

        for item in items:
            if not isinstance(item, dict):
                continue

            # Find hostname (case-insensitive)
            hostname = _get_field(item, HOSTNAME_FIELDS)
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

            # Build exclusion set from all known structured fields (case-insensitive)
            exclude_keys_lower = {k.lower() for k in (
                HOSTNAME_FIELDS + IP_FIELDS + ENV_FIELDS +
                ["groups", "aliases", "role", "service", "ssh_port", "port"]
            )}

            host = ParsedHost(
                hostname=str(hostname).lower(),
                ip_address=_get_field(item, IP_FIELDS),
                environment=_get_field(item, ENV_FIELDS),
                groups=_get_list_field(item, "groups"),
                aliases=_get_list_field(item, "aliases"),
                role=_get_field(item, ["role"]),
                service=_get_field(item, ["service"]),
                ssh_port=ssh_port,
                metadata={k: v for k, v in item.items() if k.lower() not in exclude_keys_lower},
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
