"""
Merlya Commands - Host import/export format implementations.

Concrete implementations of importers and exporters for various formats.
"""

from __future__ import annotations

import csv
import io
import json
from typing import TYPE_CHECKING, Any, ClassVar

from loguru import logger

from merlya.commands.handlers.hosts_registry import (
    BaseExporter,
    BaseImporter,
    ExporterRegistry,
    ImporterRegistry,
)
from merlya.persistence.models import (
    MAX_PORT,
    MIN_PORT,
    TAG_PATTERN,
    ElevationMethod,
    Host,
)

if TYPE_CHECKING:
    from pathlib import Path

    from merlya.core.context import SharedContext


# ============================================================================
# Shared utilities
# ============================================================================

DEFAULT_SSH_PORT = 22

# Map elevation strings to ElevationMethod enum
ELEVATION_MAP: dict[str, ElevationMethod] = {
    "none": ElevationMethod.NONE,
    "sudo": ElevationMethod.SUDO,
    "sudo_password": ElevationMethod.SUDO_PASSWORD,
    "sudo-password": ElevationMethod.SUDO_PASSWORD,
    "sudo-s": ElevationMethod.SUDO_PASSWORD,  # Legacy
    "doas": ElevationMethod.DOAS,
    "doas_password": ElevationMethod.DOAS_PASSWORD,
    "doas-password": ElevationMethod.DOAS_PASSWORD,
    "su": ElevationMethod.SU,
}


def _validate_port(port_str: str, default: int = DEFAULT_SSH_PORT) -> int:
    """Validate and parse port number using constants from models.py."""
    try:
        port = int(port_str)
        if MIN_PORT <= port <= MAX_PORT:
            return port
        return default
    except ValueError:
        return default


def _validate_tag(tag: str) -> bool:
    """Check if tag is valid using TAG_PATTERN from models.py."""
    return bool(tag and TAG_PATTERN.match(tag))


def _create_host_from_dict(item: dict[str, Any]) -> Host:
    """Create Host from dictionary with validated fields."""
    raw_tags = item.get("tags", [])
    valid_tags = [t for t in raw_tags if isinstance(t, str) and _validate_tag(t)]

    elevation_str = item.get("elevation_method", item.get("elevation"))
    elevation = (
        ELEVATION_MAP.get(str(elevation_str).lower(), ElevationMethod.NONE)
        if elevation_str
        else ElevationMethod.NONE
    )

    return Host(
        name=item["name"],
        hostname=item.get("hostname", item.get("host", item["name"])),
        port=_validate_port(str(item.get("port", DEFAULT_SSH_PORT))),
        username=item.get("username", item.get("user")),
        tags=valid_tags,
        private_key=item.get("private_key", item.get("key")),
        jump_host=item.get("jump_host", item.get("bastion")),
        elevation_method=elevation,
        elevation_user=item.get("elevation_user", "root"),
    )


def _host_to_dict(h: Host) -> dict[str, Any]:
    """Convert Host to dictionary for export."""
    item: dict[str, Any] = {"name": h.name, "hostname": h.hostname, "port": h.port}
    if h.username:
        item["username"] = h.username
    if h.tags:
        item["tags"] = h.tags
    if h.private_key:
        item["private_key"] = h.private_key
    if h.jump_host:
        item["jump_host"] = h.jump_host
    if h.elevation_method and h.elevation_method != ElevationMethod.NONE:
        elevation_value = (
            h.elevation_method.value
            if hasattr(h.elevation_method, "value")
            else str(h.elevation_method)
        )
        item["elevation_method"] = elevation_value
        if h.elevation_user and h.elevation_user != "root":
            item["elevation_user"] = h.elevation_user
    return item


# ============================================================================
# JSON Format
# ============================================================================


@ImporterRegistry.register
class JsonImporter(BaseImporter):
    """JSON format importer."""

    format_id: ClassVar[str] = "json"
    extensions: ClassVar[tuple[str, ...]] = (".json",)
    display_name: ClassVar[str] = "JSON"

    async def import_hosts(
        self,
        ctx: SharedContext,
        content: str,
        _file_path: Path | None = None,
    ) -> tuple[int, list[str]]:
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


@ExporterRegistry.register
class JsonExporter(BaseExporter):
    """JSON format exporter."""

    format_id: ClassVar[str] = "json"
    extensions: ClassVar[tuple[str, ...]] = (".json",)
    display_name: ClassVar[str] = "JSON"

    def export_hosts(self, hosts: list[dict[str, Any]]) -> str:
        """Export to JSON string."""
        return json.dumps(hosts, indent=2)


# ============================================================================
# YAML Format
# ============================================================================


@ImporterRegistry.register
class YamlImporter(BaseImporter):
    """YAML format importer."""

    format_id: ClassVar[str] = "yaml"
    extensions: ClassVar[tuple[str, ...]] = (".yaml", ".yml")
    display_name: ClassVar[str] = "YAML"

    async def import_hosts(
        self,
        ctx: SharedContext,
        content: str,
        _file_path: Path | None = None,
    ) -> tuple[int, list[str]]:
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


@ExporterRegistry.register
class YamlExporter(BaseExporter):
    """YAML format exporter."""

    format_id: ClassVar[str] = "yaml"
    extensions: ClassVar[tuple[str, ...]] = (".yaml", ".yml")
    display_name: ClassVar[str] = "YAML"

    def export_hosts(self, hosts: list[dict[str, Any]]) -> str:
        """Export to YAML string."""
        import yaml

        return yaml.dump(hosts, default_flow_style=False)


# ============================================================================
# CSV Format
# ============================================================================


@ImporterRegistry.register
class CsvImporter(BaseImporter):
    """CSV format importer."""

    format_id: ClassVar[str] = "csv"
    extensions: ClassVar[tuple[str, ...]] = (".csv",)
    display_name: ClassVar[str] = "CSV"

    async def import_hosts(
        self,
        ctx: SharedContext,
        content: str,
        _file_path: Path | None = None,
    ) -> tuple[int, list[str]]:
        """Import from CSV content."""
        imported = 0
        errors: list[str] = []
        reader = csv.DictReader(io.StringIO(content))

        for row in reader:
            try:
                tags_raw = row.get("tags", "").split(",") if row.get("tags") else []
                valid_tags = [t.strip() for t in tags_raw if t.strip() and _validate_tag(t.strip())]

                elevation_raw = row.get("elevation_method", "").strip().lower()
                elevation = ELEVATION_MAP.get(elevation_raw, ElevationMethod.NONE)

                host = Host(
                    name=row["name"],
                    hostname=row.get("hostname", row.get("host", row["name"])),
                    port=_validate_port(row.get("port", "22")),
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


@ExporterRegistry.register
class CsvExporter(BaseExporter):
    """CSV format exporter."""

    format_id: ClassVar[str] = "csv"
    extensions: ClassVar[tuple[str, ...]] = (".csv",)
    display_name: ClassVar[str] = "CSV"

    def export_hosts(self, hosts: list[dict[str, Any]]) -> str:
        """Export to CSV string."""
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
        for item in hosts:
            row_item = dict(item)
            row_item["tags"] = ",".join(row_item.get("tags", []))
            writer.writerow({k: row_item.get(k, "") or "" for k in fieldnames})
        return output.getvalue()


# ============================================================================
# TOML Format
# ============================================================================


@ImporterRegistry.register
class TomlImporter(BaseImporter):
    """TOML format importer."""

    format_id: ClassVar[str] = "toml"
    extensions: ClassVar[tuple[str, ...]] = (".toml", ".tml")
    display_name: ClassVar[str] = "TOML"

    async def import_hosts(
        self,
        ctx: SharedContext,
        content: str,
        _file_path: Path | None = None,
    ) -> tuple[int, list[str]]:
        """
        Import from TOML content.

        Supports format:
            [hosts.internal-db]
            hostname = "10.0.1.50"
            user = "dbadmin"
            port = 22
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
            # Try flat structure
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

                host = _create_host_from_dict(host_data)
                await ctx.hosts.create(host)
                imported += 1
                logger.debug(f"🖥️ Imported host from TOML: {name}")
            except Exception as e:
                errors.append(f"{name}: {e}")

        return imported, errors


# ============================================================================
# SSH Config Format
# ============================================================================


@ImporterRegistry.register
class SshConfigImporter(BaseImporter):
    """SSH config format importer (~/.ssh/config)."""

    format_id: ClassVar[str] = "ssh"
    extensions: ClassVar[tuple[str, ...]] = (".conf",)
    display_name: ClassVar[str] = "SSH Config"

    async def import_hosts(
        self,
        ctx: SharedContext,
        _content: str,
        file_path: Path | None = None,
    ) -> tuple[int, list[str]]:
        """Import from SSH config file."""
        from merlya.setup import import_from_ssh_config

        imported = 0
        errors: list[str] = []

        if file_path is None:
            errors.append("SSH config import requires file path")
            return imported, errors

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


# ============================================================================
# /etc/hosts Format
# ============================================================================


@ImporterRegistry.register
class EtcHostsImporter(BaseImporter):
    """/etc/hosts format importer."""

    format_id: ClassVar[str] = "etc_hosts"
    extensions: ClassVar[tuple[str, ...]] = ()  # Detected by path, not extension
    display_name: ClassVar[str] = "/etc/hosts"

    async def import_hosts(
        self,
        ctx: SharedContext,
        content: str,
        _file_path: Path | None = None,
    ) -> tuple[int, list[str]]:
        """Import from /etc/hosts format."""
        imported = 0
        errors: list[str] = []

        # Skip entries
        skip_hosts = {"localhost", "localhost.localdomain", "broadcasthost"}
        skip_ips = {"127.0.0.1", "::1", "255.255.255.255", "fe80::1%lo0"}

        for line_num, line in enumerate(content.splitlines(), 1):
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            parts = line.split()
            if len(parts) < 2:
                continue

            ip_addr = parts[0]
            hostname = parts[1]

            if hostname in skip_hosts or ip_addr in skip_ips:
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


# Export utilities for backward compatibility
create_host_from_dict = _create_host_from_dict
host_to_dict = _host_to_dict
