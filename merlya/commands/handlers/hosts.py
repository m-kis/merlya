"""
Merlya Commands - Host management handlers.

Implements /hosts command with subcommands: list, add, show, delete, tag, untag, edit, import, export.
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.commands.registry import CommandResult, command, subcommand
from merlya.persistence.models import Host

if TYPE_CHECKING:
    from merlya.core.context import SharedContext

# Constants
DEFAULT_SSH_PORT = 22
MIN_PORT = 1
MAX_PORT = 65535
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
TAG_PATTERN = re.compile(r"^[a-zA-Z0-9_:-]{1,50}$")
ALLOWED_IMPORT_DIRS = [Path.home(), Path("/etc"), Path("/tmp")]


def _validate_port(port_str: str, default: int = DEFAULT_SSH_PORT) -> int:
    """Validate and parse port number within valid bounds."""
    try:
        port = int(port_str)
        if MIN_PORT <= port <= MAX_PORT:
            return port
        logger.warning(f"⚠️ Port {port} out of range, using default {default}")
        return default
    except ValueError:
        return default


def _validate_tag(tag: str) -> tuple[bool, str]:
    """Validate tag format. Returns (is_valid, error_message)."""
    if not tag:
        return False, "Tag cannot be empty"
    if not TAG_PATTERN.match(tag):
        return (
            False,
            f"Invalid tag format: '{tag}'. Use only letters, numbers, hyphens, underscores, and colons (max 50 chars)",
        )
    return True, ""


def _validate_file_path(file_path: Path) -> tuple[bool, str]:
    """
    Validate file path for security (prevent path traversal attacks).

    Returns (is_valid, error_message).
    """
    try:
        # Resolve to absolute path and check for traversal
        resolved = file_path.resolve()

        # Ensure path is under allowed directories (handles symlinks like /etc -> /private/etc)
        is_allowed = any(resolved.is_relative_to(allowed.resolve()) for allowed in ALLOWED_IMPORT_DIRS)

        if not is_allowed:
            return False, "Access denied: Path must be within home directory, /etc, or /tmp"

        # Check for suspicious patterns
        path_str = str(file_path)
        if ".." in path_str or path_str.startswith("/proc") or path_str.startswith("/sys"):
            return False, "Access denied: Invalid path pattern"

        return True, ""
    except Exception as e:
        return False, f"Invalid path: {e}"


def _check_file_size(file_path: Path) -> tuple[bool, str]:
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


@command("hosts", "Manage hosts inventory", "/hosts <subcommand>")
async def cmd_hosts(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Manage hosts inventory."""
    if not args:
        return await cmd_hosts_list(ctx, [])

    return CommandResult(
        success=False,
        message="Unknown subcommand. Use `/help hosts` for available commands.",
        show_help=True,
    )


@subcommand("hosts", "list", "List all hosts", "/hosts list [--tag=<tag>]")
async def cmd_hosts_list(ctx: SharedContext, args: list[str]) -> CommandResult:
    """List all hosts."""
    tag = None
    for arg in args:
        if arg.startswith("--tag="):
            tag = arg[6:]

    if tag:
        hosts = await ctx.hosts.get_by_tag(tag)
    else:
        hosts = await ctx.hosts.get_all()

    if not hosts:
        return CommandResult(
            success=True,
            message="No hosts found. Use `/hosts add <name>` to add one.",
        )

    # Use Rich table for better display
    ctx.ui.table(
        headers=["Status", "Name", "Hostname", "Port", "Tags"],
        rows=[
            [
                "✅" if h.health_status == "healthy" else "❌",
                h.name,
                h.hostname,
                str(h.port),
                ", ".join(h.tags) if h.tags else "-",
            ]
            for h in hosts
        ],
        title=f"🖥️ Hosts ({len(hosts)})",
    )

    return CommandResult(success=True, message="", data=hosts)


@subcommand("hosts", "add", "Add a new host", "/hosts add <name>")
async def cmd_hosts_add(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Add a new host."""
    if not args:
        return CommandResult(success=False, message="Usage: `/hosts add <name>`")

    name = args[0]

    existing = await ctx.hosts.get_by_name(name)
    if existing:
        return CommandResult(success=False, message=f"Host '{name}' already exists.")

    hostname = await ctx.ui.prompt(f"Hostname or IP for {name}")
    if not hostname:
        return CommandResult(success=False, message="Hostname required.")

    port_str = await ctx.ui.prompt("SSH port", default="22")
    port = _validate_port(port_str)

    username = await ctx.ui.prompt("Username (optional)")

    host = Host(
        name=name,
        hostname=hostname,
        port=port,
        username=username if username else None,
    )

    await ctx.hosts.create(host)

    return CommandResult(
        success=True,
        message=f"Host '{name}' added ({hostname}:{port}).",
    )


@subcommand("hosts", "show", "Show host details", "/hosts show <name>")
async def cmd_hosts_show(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Show host details."""
    if not args:
        return CommandResult(success=False, message="Usage: `/hosts show <name>`")

    host = await ctx.hosts.get_by_name(args[0])
    if not host:
        return CommandResult(success=False, message=f"Host '{args[0]}' not found.")

    lines = [
        f"**{host.name}**\n",
        f"  Hostname: `{host.hostname}`",
        f"  Port: `{host.port}`",
        f"  Username: `{host.username or 'default'}`",
        f"  Status: `{host.health_status}`",
        f"  Tags: `{', '.join(host.tags) if host.tags else 'none'}`",
    ]

    if host.os_info:
        lines.append(f"\n  OS: `{host.os_info.name} {host.os_info.version}`")
        lines.append(f"  Kernel: `{host.os_info.kernel}`")

    if host.last_seen:
        lines.append(f"\n  Last seen: `{host.last_seen}`")

    return CommandResult(success=True, message="\n".join(lines), data=host)


@subcommand("hosts", "delete", "Delete a host", "/hosts delete <name>")
async def cmd_hosts_delete(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Delete a host."""
    if not args:
        return CommandResult(success=False, message="Usage: `/hosts delete <name>`")

    host = await ctx.hosts.get_by_name(args[0])
    if not host:
        return CommandResult(success=False, message=f"Host '{args[0]}' not found.")

    confirmed = await ctx.ui.prompt_confirm(f"Delete host '{args[0]}'?")
    if not confirmed:
        return CommandResult(success=True, message="Cancelled.")

    await ctx.hosts.delete(host.id)
    return CommandResult(success=True, message=f"Host '{args[0]}' deleted.")


@subcommand("hosts", "tag", "Add a tag to a host", "/hosts tag <name> <tag>")
async def cmd_hosts_tag(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Add a tag to a host."""
    if len(args) < 2:
        return CommandResult(success=False, message="Usage: `/hosts tag <name> <tag>`")

    host = await ctx.hosts.get_by_name(args[0])
    if not host:
        return CommandResult(success=False, message=f"Host '{args[0]}' not found.")

    tag = args[1]
    is_valid, error_msg = _validate_tag(tag)
    if not is_valid:
        return CommandResult(success=False, message=f"❌ {error_msg}")

    if tag not in host.tags:
        host.tags.append(tag)
        await ctx.hosts.update(host)

    return CommandResult(success=True, message=f"✅ Tag '{tag}' added to '{args[0]}'.")


@subcommand("hosts", "untag", "Remove a tag from a host", "/hosts untag <name> <tag>")
async def cmd_hosts_untag(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Remove a tag from a host."""
    if len(args) < 2:
        return CommandResult(success=False, message="Usage: `/hosts untag <name> <tag>`")

    host = await ctx.hosts.get_by_name(args[0])
    if not host:
        return CommandResult(success=False, message=f"Host '{args[0]}' not found.")

    tag = args[1]
    if tag in host.tags:
        host.tags.remove(tag)
        await ctx.hosts.update(host)
        return CommandResult(success=True, message=f"Tag '{tag}' removed from '{args[0]}'.")

    return CommandResult(success=False, message=f"Tag '{tag}' not found on '{args[0]}'.")


@subcommand("hosts", "edit", "Edit a host", "/hosts edit <name>")
async def cmd_hosts_edit(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Edit a host interactively."""
    if not args:
        return CommandResult(success=False, message="Usage: `/hosts edit <name>`")

    host = await ctx.hosts.get_by_name(args[0])
    if not host:
        return CommandResult(success=False, message=f"Host '{args[0]}' not found.")

    ctx.ui.info(f"⚙️ Editing host `{host.name}`...")
    ctx.ui.muted(f"Current: {host.hostname}:{host.port}, user={host.username or 'default'}")

    hostname = await ctx.ui.prompt("Hostname or IP", default=host.hostname)
    if hostname:
        host.hostname = hostname

    port_str = await ctx.ui.prompt("SSH port", default=str(host.port))
    host.port = _validate_port(port_str, default=host.port)

    username = await ctx.ui.prompt("Username", default=host.username or "")
    host.username = username if username else None

    current_tags = ", ".join(host.tags) if host.tags else ""
    tags_str = await ctx.ui.prompt("Tags (comma-separated)", default=current_tags)
    if tags_str:
        valid_tags = []
        for tag_raw in tags_str.split(","):
            tag = tag_raw.strip()
            if tag:
                is_valid, _ = _validate_tag(tag)
                if is_valid:
                    valid_tags.append(tag)
                else:
                    ctx.ui.muted(f"⚠️ Skipping invalid tag: {tag}")
        host.tags = valid_tags

    await ctx.hosts.update(host)

    return CommandResult(
        success=True,
        message=f"✅ Host `{host.name}` updated:\n"
        f"  - Hostname: `{host.hostname}`\n"
        f"  - Port: `{host.port}`\n"
        f"  - User: `{host.username or 'default'}`\n"
        f"  - Tags: `{', '.join(host.tags) if host.tags else 'none'}`",
    )


@subcommand("hosts", "import", "Import hosts from file", "/hosts import <file> [--format=<format>]")
async def cmd_hosts_import(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Import hosts from a file (JSON, YAML, CSV, SSH config, /etc/hosts)."""
    if not args:
        return CommandResult(
            success=False,
            message="Usage: `/hosts import <file> [--format=json|yaml|csv|ssh|etc_hosts]`\n\n"
            "Supported formats:\n"
            '  - `json`: `[{"name": "host1", "hostname": "1.2.3.4", ...}]`\n'
            "  - `yaml`: Same structure as JSON\n"
            "  - `csv`: `name,hostname,port,username,tags`\n"
            "  - `ssh`: SSH config format (~/.ssh/config)\n"
            "  - `etc_hosts`: /etc/hosts format (auto-detected)",
        )

    file_path = Path(args[0]).expanduser()
    if not file_path.exists():
        return CommandResult(success=False, message=f"❌ File not found: {file_path}")

    # Security: Validate file path
    is_valid, error_msg = _validate_file_path(file_path)
    if not is_valid:
        logger.warning(f"⚠️ Import blocked: {error_msg} ({file_path})")
        return CommandResult(success=False, message=f"❌ {error_msg}")

    # Security: Check file size
    is_valid, error_msg = _check_file_size(file_path)
    if not is_valid:
        return CommandResult(success=False, message=f"❌ {error_msg}")

    file_format = _detect_format(file_path, args)
    ctx.ui.info(f"📥 Importing hosts from `{file_path}` (format: {file_format})...")

    imported, errors = await _import_hosts(ctx, file_path, file_format)

    result_msg = f"✅ Imported {imported} host(s)"
    if errors:
        result_msg += f"\n\n⚠️ {len(errors)} error(s):\n"
        for err in errors[:5]:
            result_msg += f"  - {err}\n"
        if len(errors) > 5:
            result_msg += f"  ... and {len(errors) - 5} more"

    return CommandResult(success=True, message=result_msg)


def _detect_format(file_path: Path, args: list[str]) -> str:
    """Detect file format from args or file extension."""
    for arg in args[1:]:
        if arg.startswith("--format="):
            return arg[9:].lower()

    # Special case: /etc/hosts file
    if file_path.name == "hosts" and str(file_path).startswith("/etc"):
        return "etc_hosts"

    ext = file_path.suffix.lower()
    if ext in (".yml", ".yaml"):
        return "yaml"
    elif ext == ".csv":
        return "csv"
    elif ext == ".conf" or file_path.name == "config":
        return "ssh"
    return "json"


async def _import_hosts(
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
            host = _create_host_from_dict(item)
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
            host = _create_host_from_dict(item)
            await ctx.hosts.create(host)
            imported += 1
        except Exception as e:
            errors.append(f"{item.get('name', '?')}: {e}")

    return imported, errors


async def _import_csv(ctx: SharedContext, content: str) -> tuple[int, list[str]]:
    """Import from CSV content."""
    imported = 0
    errors: list[str] = []
    reader = csv.DictReader(io.StringIO(content))

    for row in reader:
        try:
            tags_raw = row.get("tags", "").split(",") if row.get("tags") else []
            valid_tags = [t.strip() for t in tags_raw if t.strip() and _validate_tag(t.strip())[0]]
            host = Host(
                name=row["name"],
                hostname=row.get("hostname", row.get("host", row["name"])),
                port=_validate_port(row.get("port", "22")),
                username=row.get("username", row.get("user")),
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
            port = _validate_port(str(item.get("port", DEFAULT_SSH_PORT)))
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
    """
    Import from /etc/hosts format.

    Format: IP_ADDRESS HOSTNAME [ALIASES...]
    Lines starting with # are comments.
    """
    imported = 0
    errors: list[str] = []

    for line_num, line in enumerate(content.splitlines(), 1):
        line = line.strip()

        # Skip empty lines and comments
        if not line or line.startswith("#"):
            continue

        # Parse: IP HOSTNAME [ALIASES...]
        parts = line.split()
        if len(parts) < 2:
            continue

        ip_addr = parts[0]
        hostname = parts[1]

        # Skip localhost entries
        if hostname in ("localhost", "localhost.localdomain", "broadcasthost"):
            continue
        if ip_addr in ("127.0.0.1", "::1", "255.255.255.255", "fe80::1%lo0"):
            continue

        # Use first hostname as name, IP as hostname
        try:
            # Sanitize name (replace dots with dashes for valid host names)
            name = hostname.replace(".", "-")

            # Check if already exists
            existing = await ctx.hosts.get_by_name(name)
            if existing:
                continue

            host = Host(
                name=name,
                hostname=ip_addr,  # The IP is the actual hostname to connect to
                port=DEFAULT_SSH_PORT,
                tags=["etc-hosts"],
            )
            await ctx.hosts.create(host)
            imported += 1
        except Exception as e:
            errors.append(f"Line {line_num} ({hostname}): {e}")

    return imported, errors


def _create_host_from_dict(item: dict[str, Any]) -> Host:
    """Create Host from dictionary with validated port and tags."""
    # Validate tags
    raw_tags = item.get("tags", [])
    valid_tags = [t for t in raw_tags if isinstance(t, str) and _validate_tag(t)[0]]

    return Host(
        name=item["name"],
        hostname=item.get("hostname", item.get("host", item["name"])),
        port=_validate_port(str(item.get("port", DEFAULT_SSH_PORT))),
        username=item.get("username", item.get("user")),
        tags=valid_tags,
        private_key=item.get("private_key", item.get("key")),
        jump_host=item.get("jump_host", item.get("bastion")),
    )


@subcommand("hosts", "export", "Export hosts to file", "/hosts export <file> [--format=<format>]")
async def cmd_hosts_export(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Export hosts to a file (JSON, YAML, CSV)."""
    if not args:
        return CommandResult(
            success=False,
            message="Usage: `/hosts export <file> [--format=json|yaml|csv]`",
        )

    file_path = Path(args[0]).expanduser()
    file_format = _detect_export_format(file_path, args)

    hosts = await ctx.hosts.get_all()
    if not hosts:
        return CommandResult(success=False, message="No hosts to export.")

    ctx.ui.info(f"📤 Exporting {len(hosts)} hosts to `{file_path}`...")

    data = [_host_to_dict(h) for h in hosts]
    content = _serialize_hosts(data, file_format)

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)

    return CommandResult(success=True, message=f"✅ Exported {len(hosts)} hosts to `{file_path}`")


def _detect_export_format(file_path: Path, args: list[str]) -> str:
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


def _host_to_dict(h: Host) -> dict[str, Any]:
    """Convert Host to dictionary for export."""
    item = {"name": h.name, "hostname": h.hostname, "port": h.port}
    if h.username:
        item["username"] = h.username
    if h.tags:
        item["tags"] = h.tags
    if h.private_key:
        item["private_key"] = h.private_key
    if h.jump_host:
        item["jump_host"] = h.jump_host
    return item


def _serialize_hosts(data: list[dict[str, Any]], file_format: str) -> str:
    """Serialize hosts data to string."""
    if file_format == "json":
        return json.dumps(data, indent=2)
    elif file_format == "yaml":
        import yaml

        return yaml.dump(data, default_flow_style=False)
    elif file_format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["name", "hostname", "port", "username", "tags"])
        writer.writeheader()
        for item in data:
            item["tags"] = ",".join(item.get("tags", []))
            writer.writerow(
                {k: item.get(k, "") for k in ["name", "hostname", "port", "username", "tags"]}
            )
        return output.getvalue()
    return json.dumps(data, indent=2)
