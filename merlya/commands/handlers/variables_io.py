"""
Merlya Commands - Variable import/export utilities.

Import and export variables from/to various file formats.
"""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from merlya.core.context import SharedContext

from merlya.common.validation import validate_file_path as common_validate_file_path

# Constants
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
ALLOWED_IMPORT_DIRS = [Path.home(), Path("/etc")]

# Patterns for detecting potentially sensitive values in files
# These should NEVER be imported - secrets must be prompted
SENSITIVE_VALUE_PATTERNS = [
    re.compile(r"^[A-Za-z0-9_-]{32,}$"),  # Long random strings
    re.compile(r"^sk-[A-Za-z0-9]+$"),  # OpenAI keys
    re.compile(r"^ghp_[A-Za-z0-9]+$"),  # GitHub tokens
    re.compile(r"^A[KBS]IA[A-Z0-9]{16}$"),  # AWS keys
    re.compile(r"-----BEGIN.*KEY-----"),  # PEM keys
]


# Use centralized validation with module-specific constraints
def validate_file_path(file_path: Path) -> tuple[bool, str]:
    """
    Validate file path for security (prevent path traversal and unsafe file access).

    This function uses centralized validation with additional constraints
    specific to variables import/export operations.

    Returns (is_valid, error_message).
    """
    # First validate with centralized function
    is_valid, error_msg = common_validate_file_path(file_path)
    if not is_valid:
        return False, error_msg

    # Additional module-specific constraints for variables
    try:
        resolved = file_path.resolve()

        # Reject symlinks to prevent symlink-based attacks
        if file_path.is_symlink():
            return False, "Access denied: Symlinks are not allowed for security reasons"

        # Check if path is within allowed directories
        is_allowed = any(
            resolved.is_relative_to(allowed.resolve()) for allowed in ALLOWED_IMPORT_DIRS
        )
        if not is_allowed:
            return False, "Access denied: Path must be within home directory or /etc"

        # Reject special filesystem paths
        resolved_str = str(resolved)
        if resolved_str.startswith("/proc") or resolved_str.startswith("/sys"):
            return False, "Access denied: Special filesystem paths not allowed"

        # If file exists, perform ownership and permission checks
        if resolved.exists():
            file_stat = resolved.stat()

            # Reject world-writable files
            if file_stat.st_mode & stat.S_IWOTH:
                return False, "Access denied: File is world-writable"

            # Reject files not owned by current user or root
            current_uid = os.getuid()
            if file_stat.st_uid != current_uid and file_stat.st_uid != 0:
                return False, "Access denied: File must be owned by current user or root"

            # Check parent directory is not world-writable
            parent_stat = resolved.parent.stat()
            if parent_stat.st_mode & stat.S_IWOTH:
                return False, "Access denied: Parent directory is world-writable"

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


def _format_from_extension(ext: str, default: str = "yaml") -> str:
    """Map file extension to format name."""
    ext = ext.lower()
    if ext in (".yml", ".yaml"):
        return "yaml"
    elif ext == ".json":
        return "json"
    elif ext == ".env":
        return "env"
    return default


def detect_import_format(file_path: Path) -> str:
    """Detect file format from file extension for import."""
    return _format_from_extension(file_path.suffix, default="yaml")


def detect_export_format(file_path: Path) -> str:
    """Detect export format from file extension."""
    ext = file_path.suffix
    # Empty extension defaults to env for export
    if ext == "":
        return "env"
    return _format_from_extension(ext, default="yaml")


def _looks_like_secret(value: str) -> bool:
    """Check if a value looks like a secret/credential."""
    if not value or len(value) < 16:
        return False
    return any(p.search(value) for p in SENSITIVE_VALUE_PATTERNS)


async def import_variables(
    ctx: SharedContext,
    file_path: Path,
    file_format: str,
    merge: bool = True,
    dry_run: bool = False,
) -> tuple[int, int, int, list[str], list[str]]:
    """
    Import variables from file.

    Returns:
        Tuple of (variables_imported, secrets_to_set, hosts_imported, secrets_names, errors)
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return 0, 0, 0, [], [f"File not found: {file_path}"]
    except PermissionError:
        return 0, 0, 0, [], [f"Permission denied reading file: {file_path}"]
    except UnicodeDecodeError as e:
        return 0, 0, 0, [], [f"File encoding error (expected UTF-8): {e}"]
    except OSError as e:
        return 0, 0, 0, [], [f"Error reading file: {e}"]

    if file_format == "json":
        return await _import_json(ctx, content, merge, dry_run)
    elif file_format == "yaml":
        return await _import_yaml(ctx, content, merge, dry_run)
    elif file_format == "env":
        return await _import_env(ctx, content, merge, dry_run)
    else:
        return 0, 0, 0, [], [f"Unsupported format: {file_format}"]


async def _import_json(
    ctx: SharedContext,
    content: str,
    merge: bool,
    dry_run: bool,
) -> tuple[int, int, int, list[str], list[str]]:
    """Import from JSON content."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return 0, 0, 0, [], [f"Invalid JSON: {e}"]
    return await _process_import_data(ctx, data, merge, dry_run)


async def _import_yaml(
    ctx: SharedContext,
    content: str,
    merge: bool,
    dry_run: bool,
) -> tuple[int, int, int, list[str], list[str]]:
    """Import from YAML content."""
    import yaml

    try:
        data = yaml.safe_load(content) or {}
    except yaml.YAMLError as e:
        return 0, 0, 0, [], [f"Invalid YAML: {e}"]
    return await _process_import_data(ctx, data, merge, dry_run)


async def _import_env(
    ctx: SharedContext,
    content: str,
    merge: bool,
    dry_run: bool,
) -> tuple[int, int, int, list[str], list[str]]:
    """
    Import from .env format.

    Format:
        VAR_NAME=value
        # Comments start with #
        SECRET_DB_PASSWORD=   # Empty = prompt for value
    """
    variables: dict[str, str] = {}
    secrets: list[str] = []
    errors: list[str] = []

    for line_num, line in enumerate(content.splitlines(), 1):
        line = line.strip()

        # Skip empty lines and comments
        if not line or line.startswith("#"):
            continue

        # Parse key=value
        if "=" not in line:
            errors.append(f"Line {line_num}: Invalid format (missing '=')")
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()

        # Remove quotes if present
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]

        # Check if it's a secret (prefixed with SECRET_ or empty value)
        if key.startswith("SECRET_") or not value:
            secret_name = key.removeprefix("SECRET_").lower().replace("_", "-")
            secrets.append(secret_name)
        else:
            # Convert KEY_NAME to key-name for consistency
            var_name = key.lower().replace("_", "-")

            # Security check: don't import values that look like secrets
            if _looks_like_secret(value):
                errors.append(
                    f"Line {line_num}: Value for '{key}' looks like a secret. "
                    "Add SECRET_ prefix to prompt for value instead."
                )
                continue

            variables[var_name] = value

    # Process import
    var_count = 0
    if not dry_run:
        if not merge:
            # Clear existing variables first
            for v in await ctx.variables.get_all():
                await ctx.variables.delete(v.name)

        for name, value in variables.items():
            await ctx.variables.set(name, value)
            var_count += 1
    else:
        var_count = len(variables)

    return var_count, len(secrets), 0, secrets, errors


async def _process_import_data(
    ctx: SharedContext,
    data: dict[str, Any],
    merge: bool,
    dry_run: bool,
) -> tuple[int, int, int, list[str], list[str]]:
    """
    Process structured import data (JSON/YAML).

    Expected structure:
        {
            "variables": {"name": "value", ...},
            "hosts": {"alias": "hostname", ...},
            "secrets": ["secret-name", ...]
        }
    """
    variables = data.get("variables", {})
    hosts = data.get("hosts", {})
    secrets = data.get("secrets", [])
    errors: list[str] = []

    var_count = 0
    host_count = 0

    # Security check: ensure secrets list contains only names, not values
    if isinstance(secrets, dict):
        errors.append("'secrets' must be a list of names, not a dict with values")
        secrets = list(secrets.keys())

    # Check variables for sensitive values
    safe_variables: dict[str, str] = {}
    for name, value in variables.items():
        if not isinstance(value, str):
            value = str(value)
        if _looks_like_secret(value):
            errors.append(
                f"Variable '{name}' looks like a secret. "
                "Move it to 'secrets' list to prompt for value."
            )
        else:
            safe_variables[name] = value

    if not dry_run:
        if not merge:
            # Clear existing variables
            for v in await ctx.variables.get_all():
                await ctx.variables.delete(v.name)

            # Clear existing hosts
            for h in await ctx.hosts.get_all():
                await ctx.hosts.delete(h.id)

        # Import variables
        for name, value in safe_variables.items():
            try:
                await ctx.variables.set(name, value)
                var_count += 1
            except Exception as e:
                errors.append(f"Variable '{name}': {e}")

        # Import hosts (simple alias -> hostname mapping)
        for alias, hostname in hosts.items():
            try:
                # Create simple host entry
                from merlya.persistence.models import Host

                existing = await ctx.hosts.get_by_name(alias)
                if existing:
                    if merge:
                        errors.append(f"Host '{alias}': already exists (skipped)")
                        continue
                    # In replace mode, update
                    existing.hostname = hostname
                    await ctx.hosts.update(existing)
                else:
                    host = Host(
                        name=alias,
                        hostname=hostname,
                        port=22,
                    )
                    await ctx.hosts.create(host)
                host_count += 1
            except Exception as e:
                errors.append(f"Host '{alias}': {e}")
    else:
        var_count = len(safe_variables)
        host_count = len(hosts)

    return var_count, len(secrets), host_count, list(secrets), errors


async def export_variables(
    ctx: SharedContext,
    file_format: str,
    include_secrets: bool = False,
) -> str:
    """
    Export variables to string.

    Args:
        ctx: Shared context
        file_format: Export format (yaml, json, env)
        include_secrets: Include secret names (not values!) in export

    Returns:
        Serialized content
    """
    # Get all variables
    variables = await ctx.variables.get_all()
    var_dict = {v.name: v.value for v in variables}

    # Get secret names (never values!)
    secret_names: list[str] = []
    if include_secrets:
        secret_names = ctx.secrets.list_keys()

    data: dict[str, dict[str, str] | list[str]] = {
        "variables": var_dict,
    }

    if include_secrets and secret_names:
        data["secrets"] = secret_names

    if file_format == "json":
        return json.dumps(data, indent=2)
    elif file_format == "yaml":
        import yaml

        return yaml.dump(data, default_flow_style=False, allow_unicode=True)
    elif file_format == "env":
        lines = ["# Merlya Variables Export", ""]
        for name, value in var_dict.items():
            # Convert name-with-dashes to NAME_WITH_UNDERSCORES
            env_name = name.upper().replace("-", "_")
            # Escape special characters for .env format
            # Escape backslashes first, then double quotes, then wrap in quotes if needed
            if '"' in value or "'" in value or " " in value or "\\" in value or "\n" in value:
                escaped_value = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
                value = f'"{escaped_value}"'
            lines.append(f"{env_name}={value}")

        if include_secrets and secret_names:
            lines.append("")
            lines.append("# Secrets (fill in values)")
            for name in secret_names:
                env_name = f"SECRET_{name.upper().replace('-', '_')}"
                lines.append(f"{env_name}=")

        return "\n".join(lines) + "\n"

    return json.dumps(data, indent=2)


def generate_template(file_format: str) -> str:
    """Generate a template file for variables import."""
    if file_format == "yaml":
        return """# Merlya Variables Template
# Edit this file and import with: /variable import <file>

variables:
  deploy-env: production
  log-level: info
  max-connections: 100

# Optional: Quick host aliases
hosts:
  db-master: 10.0.1.10
  web-01: 10.0.2.10

# Secrets (will be prompted during import - never put values here!)
secrets:
  - db-password
  - api-key
"""
    elif file_format == "json":
        return json.dumps(
            {
                "variables": {
                    "deploy-env": "production",
                    "log-level": "info",
                    "max-connections": "100",
                },
                "hosts": {
                    "db-master": "10.0.1.10",
                    "web-01": "10.0.2.10",
                },
                "secrets": ["db-password", "api-key"],
            },
            indent=2,
        )
    elif file_format == "env":
        return """# Merlya Variables Template (.env format)
# Edit this file and import with: /variable import <file>

# Variables (will be converted to lowercase with dashes)
DEPLOY_ENV=production
LOG_LEVEL=info
MAX_CONNECTIONS=100

# Secrets (will be prompted during import)
# Add SECRET_ prefix and leave value empty
SECRET_DB_PASSWORD=
SECRET_API_KEY=
"""
    return ""
