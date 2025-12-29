"""
Merlya Commands - Host import/export utilities.

Import and export hosts from/to various file formats.
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.common.validation import validate_file_path as common_validate_file_path
from merlya.persistence.models import ElevationMethod, Host

if TYPE_CHECKING:
    from merlya.core.context import SharedContext

# Constants
DEFAULT_SSH_PORT = 22
MIN_PORT = 1
MAX_PORT = 65535
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
TAG_PATTERN = re.compile(r"^[a-zA-Z0-9_:-]{1,50}$")
ALLOWED_IMPORT_DIRS = [Path.home(), Path("/etc"), Path("/tmp")]


def validate_port(port_str: str, default: int = DEFAULT_SSH_PORT) -> int:
    """Validate and parse port number within valid bounds."""
    try:
        port = int(port_str)
        if MIN_PORT <= port <= MAX_PORT:
            return port
        logger.warning(f"⚠️ Port {port} out of range, using default {default}")
        return default
    except ValueError:
        return default


def validate_tag(tag: str) -> tuple[bool, str]:
    """Validate tag format. Returns (is_valid, error_message)."""
    if not tag:
        return False, "Tag cannot be empty"
    if not TAG_PATTERN.match(tag):
        return (
            False,
            f"Invalid tag format: '{tag}'. Use only letters, numbers, hyphens, underscores, and colons (max 50 chars)",
        )
    return True, ""


# Use centralized validation with module-specific constraints
def validate_file_path(file_path: Path) -> tuple[bool, str]:
    """
    Validate file path for security (prevent path traversal attacks).

    This function uses centralized validation with additional constraints
    specific to hosts import/export operations.

    Returns (is_valid, error_message).
    """
    # First validate with centralized function
    is_valid, error_msg = common_validate_file_path(file_path)
    if not is_valid:
        return False, error_msg
    # Additional module-specific constraints
    try:
        resolved = file_path.resolve()
        is_allowed = any(
            resolved.is_relative_to(allowed.resolve()) for allowed in ALLOWED_IMPORT_DIRS
        )
        if not is_allowed:
            return False, "Access denied: Path must be within home directory, /etc, or /tmp"

        path_str = str(file_path)
        if ".." in path_str or path_str.startswith("/proc") or path_str.startswith("/sys"):
            return False, "Access denied: Invalid path pattern"

        return True, ""
    except Exception as e:
        return False, f"Invalid path: {e}"


def check_file_size(file_path: Path) -> tuple[bool, str]:
    """Check if file size is within limits. Returns (is_valid, error_message)."""
    try:
        size = file_path.stat().st_size
        if size > MAX_FILE_SIZE_BYTES:
            size_mb = size / (1024 * 1024)
            max_mb = MAX_FILE_SIZE_BYTES / (1024 * 1024)
            return False, f"File too large: {size_mb:.1f}MB (max: {max_mb:.0f}MB)"
        return True, ""
    except OSError as e:
        return False, f"Cannot read file: {e}"


def detect_import_format(file_path: Path, args: list[str]) -> str:
    """Detect file format from args or file extension."""
    for arg in args[1:]:
        if arg.startswith("--format="):
            return arg[9:].lower()

    if file_path.name == "hosts" and str(file_path).startswith("/etc"):
        return "etc_hosts"

    ext = file_path.suffix.lower()
    if ext in (".yml", ".yaml"):
        return "yaml"
    elif ext == ".csv":
        return "csv"
    elif ext in (".toml", ".tml"):
        return "toml"
    elif ext == ".conf" or file_path.name == "config":
        return "ssh"
    return "json"


def detect_export_format(file_path: Path, args: list[str]) -> str:
    """Detect export format from args or file extension."""
    for arg in args[1:]:
        if arg.startswith("--format="):
            return arg[9:].lower()

    ext = file_path.suffix.lower()
    if ext in (".yml", ".yaml"):
        return "yaml"
    elif ext == ".csv":
        return "csv"
    return "json"


async def import_hosts(
    ctx: SharedContext,
    file_path: Path,
    file_format: str,
) -> tuple[int, list[str]]:
    """Import hosts from file. Returns (imported_count, errors)."""
    imported = 0
    errors: list[str] = []
    content = file_path.read_text()

    try:
        if file_format == "json":
            imported, errors = await _import_json(ctx, content)
        elif file_format == "yaml":
            imported, errors = await _import_yaml(ctx, content)
        elif file_format == "toml":
            imported, errors = await _import_toml(ctx, content)
        elif file_format == "csv":
            imported, errors = await _import_csv(ctx, content)
        elif file_format == "ssh":
            imported, errors = await _import_ssh_config(ctx, file_path)
        elif file_format == "etc_hosts":
            imported, errors = await _import_etc_hosts(ctx, content)
    except Exception as e:
        logger.error(f"❌ Import failed: {e}")
        errors.append(str(e))

    return imported, errors


async def _import_json(ctx: SharedContext, content: str) -> tuple[int, list[str]]:
    """Import from JSON content."""
    imported = 0
    errors: list[str] = []
    data = json.loads(content)
    if not isinstance(data, list):
        data = [data]

    for item in data:
        try:
            host = create_host_from_dict(item)
            await ctx.hosts.create(host)
            imported += 1
        except Exception as e:
            errors.append(f"{item.get('name', '?')}: {e}")

    return imported, errors


async def _import_yaml(ctx: SharedContext, content: str) -> tuple[int, list[str]]:
    """Import from YAML content."""
    import yaml

    imported = 0
    errors: list[str] = []
    data = yaml.safe_load(content)
    if not isinstance(data, list):
        data = [data]

    for item in data:
        try:
            host = create_host_from_dict(item)
            await ctx.hosts.create(host)
            imported += 1
        except Exception as e:
            errors.append(f"{item.get('name', '?')}: {e}")

    return imported, errors


async def _import_toml(ctx: SharedContext, content: str) -> tuple[int, list[str]]:
    """
    Import from TOML content.

    Supports format:
        [hosts.internal-db]
        hostname = "10.0.1.50"
        user = "dbadmin"
        jump_host = "bastion.example.com"
        port = 22
        tags = ["database", "production"]
    """
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    imported = 0
    errors: list[str] = []
    data = tomllib.loads(content)

    # Handle [hosts.xxx] format
    hosts_section = data.get("hosts", {})
    if not hosts_section:
        # Try flat structure where host entries are at root level
        hosts_section = {k: v for k, v in data.items() if isinstance(v, dict)}

    for name, item in hosts_section.items():
        if not isinstance(item, dict):
            continue
        try:
            host_data = {
                "name": name,
                "hostname": item.get("hostname") or item.get("host"),
                "port": item.get("port", DEFAULT_SSH_PORT),
                "username": item.get("user") or item.get("username"),
                "private_key": item.get("private_key") or item.get("key"),
                "jump_host": item.get("jump_host") or item.get("bastion"),
                "tags": item.get("tags", []),
                # Elevation configuration
                "elevation_method": item.get("elevation_method") or item.get("elevation"),
                "elevation_user": item.get("elevation_user", "root"),
            }

            if not host_data["hostname"]:
                errors.append(f"{name}: missing hostname")
                continue

            # Check if exists
            existing = await ctx.hosts.get_by_name(name)
            if existing:
                errors.append(f"{name}: already exists (skipped)")
                continue

            host = create_host_from_dict(host_data)
            await ctx.hosts.create(host)
            imported += 1
            logger.debug(f"🖥️ Imported host from TOML: {name}")
        except Exception as e:
            errors.append(f"{name}: {e}")

    return imported, errors


async def _import_csv(ctx: SharedContext, content: str) -> tuple[int, list[str]]:
    """Import from CSV content."""
    imported = 0
    errors: list[str] = []
    reader = csv.DictReader(io.StringIO(content))

    # Map elevation strings to ElevationMethod enum
    elevation_map = {
        "none": ElevationMethod.NONE,
        "sudo": ElevationMethod.SUDO,
        "sudo_password": ElevationMethod.SUDO_PASSWORD,
        "sudo-password": ElevationMethod.SUDO_PASSWORD,
        "sudo-s": ElevationMethod.SUDO_PASSWORD,  # Legacy support
        "doas": ElevationMethod.DOAS,
        "doas_password": ElevationMethod.DOAS_PASSWORD,
        "doas-password": ElevationMethod.DOAS_PASSWORD,
        "su": ElevationMethod.SU,
    }

    for row in reader:
        try:
            tags_raw = row.get("tags", "").split(",") if row.get("tags") else []
            valid_tags = [t.strip() for t in tags_raw if t.strip() and validate_tag(t.strip())[0]]
            # Map elevation string to ElevationMethod enum
            elevation_raw = row.get("elevation_method", "").strip().lower()
            elevation = elevation_map.get(elevation_raw, ElevationMethod.NONE)

            host = Host(
                name=row["name"],
                hostname=row.get("hostname", row.get("host", row["name"])),
                port=validate_port(row.get("port", "22")),
                username=row.get("username", row.get("user")),
                private_key=row.get("private_key") or None,
                jump_host=row.get("jump_host") or None,
                elevation_method=elevation,
                elevation_user=row.get("elevation_user", "root") or "root",
                tags=valid_tags,
            )
            await ctx.hosts.create(host)
            imported += 1
        except Exception as e:
            errors.append(f"{row.get('name', '?')}: {e}")

    return imported, errors


async def _import_ssh_config(ctx: SharedContext, file_path: Path) -> tuple[int, list[str]]:
    """Import from SSH config file."""
    from merlya.setup import import_from_ssh_config

    imported = 0
    errors: list[str] = []
    hosts_data = import_from_ssh_config(file_path)

    for item in hosts_data:
        try:
            port = validate_port(str(item.get("port", DEFAULT_SSH_PORT)))
            host = Host(
                name=item["name"],
                hostname=item.get("hostname", item["name"]),
                port=port,
                username=item.get("user"),
                private_key=item.get("identityfile"),
                jump_host=item.get("proxyjump"),
            )
            await ctx.hosts.create(host)
            imported += 1
        except Exception as e:
            errors.append(f"{item.get('name', '?')}: {e}")

    return imported, errors


async def _import_etc_hosts(ctx: SharedContext, content: str) -> tuple[int, list[str]]:
    """Import from /etc/hosts format."""
    imported = 0
    errors: list[str] = []

    for line_num, line in enumerate(content.splitlines(), 1):
        line = line.strip()

        if not line or line.startswith("#"):
            continue

        parts = line.split()
        if len(parts) < 2:
            continue

        ip_addr = parts[0]
        hostname = parts[1]

        if hostname in ("localhost", "localhost.localdomain", "broadcasthost"):
            continue
        if ip_addr in ("127.0.0.1", "::1", "255.255.255.255", "fe80::1%lo0"):
            continue

        try:
            name = hostname.replace(".", "-")
            existing = await ctx.hosts.get_by_name(name)
            if existing:
                continue

            host = Host(
                name=name,
                hostname=ip_addr,
                port=DEFAULT_SSH_PORT,
                tags=["etc-hosts"],
            )
            await ctx.hosts.create(host)
            imported += 1
        except Exception as e:
            errors.append(f"Line {line_num} ({hostname}): {e}")

    return imported, errors


def create_host_from_dict(item: dict[str, Any]) -> Host:
    """Create Host from dictionary with validated port and tags."""
    from merlya.persistence.models import ElevationMethod

    raw_tags = item.get("tags", [])
    valid_tags = [t for t in raw_tags if isinstance(t, str) and validate_tag(t)[0]]

    # Map elevation string to ElevationMethod enum
    elevation_str = item.get("elevation_method", item.get("elevation"))
    elevation_map = {
        "none": ElevationMethod.NONE,
        "sudo": ElevationMethod.SUDO,
        "sudo_password": ElevationMethod.SUDO_PASSWORD,
        "sudo-password": ElevationMethod.SUDO_PASSWORD,
        "sudo-s": ElevationMethod.SUDO_PASSWORD,  # Legacy support
        "doas": ElevationMethod.DOAS,
        "doas_password": ElevationMethod.DOAS_PASSWORD,
        "doas-password": ElevationMethod.DOAS_PASSWORD,
        "su": ElevationMethod.SU,
    }
    elevation = (
        elevation_map.get(str(elevation_str).lower(), ElevationMethod.NONE)
        if elevation_str
        else ElevationMethod.NONE
    )

    return Host(
        name=item["name"],
        hostname=item.get("hostname", item.get("host", item["name"])),
        port=validate_port(str(item.get("port", DEFAULT_SSH_PORT))),
        username=item.get("username", item.get("user")),
        tags=valid_tags,
        private_key=item.get("private_key", item.get("key")),
        jump_host=item.get("jump_host", item.get("bastion")),
        elevation_method=elevation,
        elevation_user=item.get("elevation_user", "root"),
    )


def host_to_dict(h: Host) -> dict[str, Any]:
    """Convert Host to dictionary for export."""
    from merlya.persistence.models import ElevationMethod

    item: dict[str, Any] = {"name": h.name, "hostname": h.hostname, "port": h.port}
    if h.username:
        item["username"] = h.username
    if h.tags:
        item["tags"] = h.tags
    if h.private_key:
        item["private_key"] = h.private_key
    if h.jump_host:
        item["jump_host"] = h.jump_host
    # Export elevation_method as string if not NONE
    if h.elevation_method and h.elevation_method != ElevationMethod.NONE:
        elevation_value = (
            h.elevation_method.value
            if hasattr(h.elevation_method, "value")
            else str(h.elevation_method)
        )
        item["elevation_method"] = elevation_value
        # Also export elevation_user if different from default
        if h.elevation_user and h.elevation_user != "root":
            item["elevation_user"] = h.elevation_user
    return item


def serialize_hosts(data: list[dict[str, Any]], file_format: str) -> str:
    """Serialize hosts data to string."""
    if file_format == "json":
        return json.dumps(data, indent=2)
    elif file_format == "yaml":
        import yaml

        return yaml.dump(data, default_flow_style=False)
    elif file_format == "csv":
        output = io.StringIO()
        fieldnames = [
            "name",
            "hostname",
            "port",
            "username",
            "private_key",
            "jump_host",
            "elevation_method",
            "elevation_user",
            "tags",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for item in data:
            row_item = dict(item)
            row_item["tags"] = ",".join(row_item.get("tags", []))
            writer.writerow({k: row_item.get(k, "") or "" for k in fieldnames})
        return output.getvalue()
    return json.dumps(data, indent=2)
