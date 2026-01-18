"""
Merlya Commands - Host import/export utilities.

Import and export hosts from/to various file formats.
Uses the Registry pattern for extensible format support (OCP-compliant).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

# Import format implementations to trigger registration
import merlya.commands.handlers.hosts_formats as _formats  # noqa: F401

# Re-export utilities for backward compatibility
from merlya.commands.handlers.hosts_formats import (
    create_host_from_dict,
    host_to_dict,
)

# Import registry
from merlya.commands.handlers.hosts_registry import (
    ExporterRegistry,
    ImporterRegistry,
)
from merlya.common.validation import validate_file_path as common_validate_file_path

if TYPE_CHECKING:
    from merlya.core.context import SharedContext

# Constants
DEFAULT_SSH_PORT = 22
MIN_PORT = 1
MAX_PORT = 65535
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
TAG_PATTERN = re.compile(r"^[a-zA-Z0-9_:-]{1,50}$")
ALLOWED_IMPORT_DIRS = [Path.home(), Path("/etc"), Path("/tmp")]

# Re-export for backward compatibility
__all__ = [
    "check_file_size",
    "create_host_from_dict",
    "detect_export_format",
    "detect_import_format",
    "host_to_dict",
    "import_hosts",
    "serialize_hosts",
    "validate_file_path",
    "validate_port",
    "validate_tag",
]


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
    """Detect file format from args or file extension using registry."""
    return ImporterRegistry.detect_format(file_path, args)


def detect_export_format(file_path: Path, args: list[str]) -> str:
    """Detect export format from args or file extension using registry."""
    return ExporterRegistry.detect_format(file_path, args)


async def import_hosts(
    ctx: SharedContext,
    file_path: Path,
    file_format: str,
) -> tuple[int, list[str]]:
    """Import hosts from file using registry. Returns (imported_count, errors)."""
    errors: list[str] = []

    # Get importer from registry
    importer_class = ImporterRegistry.get(file_format)
    if importer_class is None:
        errors.append(f"Unknown import format: {file_format}")
        available = ", ".join(f[0] for f in ImporterRegistry.list_formats())
        errors.append(f"Available formats: {available}")
        return 0, errors

    content = file_path.read_text()

    try:
        importer = importer_class()
        imported, import_errors = await importer.import_hosts(ctx, content, file_path)
        return imported, import_errors
    except Exception as e:
        logger.error(f"❌ Import failed: {e}")
        errors.append(str(e))
        return 0, errors


def serialize_hosts(data: list[dict[str, Any]], file_format: str) -> str:
    """Serialize hosts data to string using registry."""
    import json

    # Get exporter from registry
    exporter_class = ExporterRegistry.get(file_format)
    if exporter_class is None:
        logger.warning(f"⚠️ Unknown export format '{file_format}', using JSON")
        return json.dumps(data, indent=2)

    exporter = exporter_class()
    return exporter.export_hosts(data)
