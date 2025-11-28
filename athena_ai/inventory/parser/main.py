"""
Main inventory parser module.
"""
import ipaddress
import json
import re
from pathlib import Path
from typing import Any, Optional

from athena_ai.core.exceptions import LLMInitializationError
from athena_ai.utils.logger import logger

from .models import ParseResult
from .parsers.llm import parse_with_llm
from .parsers.structured import parse_csv, parse_json, parse_yaml
from .parsers.text import parse_etc_hosts, parse_ini, parse_ssh_config, parse_txt


class InventoryParser:
    """
    Multi-format inventory parser.

    Supports structured formats (CSV, JSON, YAML) and
    falls back to LLM for non-standard formats.

    Configuration:
        LLM_CONTENT_LIMIT: Maximum characters to send to LLM for parsing.
            Set to None or 0 to disable truncation. Default: 8000.
            When content exceeds this limit, a warning is added to the
            ParseResult.warnings list with truncation details.
    """

    # Maximum characters to send to LLM for parsing (None or 0 to disable)
    LLM_CONTENT_LIMIT: Optional[int] = 8000

    SUPPORTED_FORMATS = [
        "csv",
        "json",
        "yaml",
        "yml",
        "txt",
        "ini",
        "etc_hosts",
        "ssh_config",
    ]

    def __init__(self, llm_router: Optional[Any] = None):
        """Initialize parser with optional LLM router."""
        self._llm = llm_router

    @property
    def llm(self):
        """Lazy load LLM router.

        Returns:
            LLMRouter: The initialized LLM router instance.

        Raises:
            LLMInitializationError: If the LLM router cannot be initialized.
                Contains the original exception details for debugging.
        """
        if self._llm is None:
            try:
                from athena_ai.llm.router import LLMRouter
                self._llm = LLMRouter()
            except Exception as e:
                logger.error(f"Could not initialize LLM router: {e}")
                raise LLMInitializationError(
                    reason=str(e),
                    original_error=e,
                ) from e
        return self._llm

    def parse(
        self,
        source: str,
        format_hint: Optional[str] = None,
        source_name: Optional[str] = None,
    ) -> ParseResult:
        """
        Parse an inventory source.

        Args:
            source: File path or raw content
            format_hint: Explicit format (optional)
            source_name: Name for the source (optional)

        Returns:
            ParseResult with hosts and any errors
        """
        # Determine if source is a file path or raw content
        content = source
        file_path = None

        # Guard against Path exceptions when source contains invalid characters
        # (null bytes, extremely long strings, etc.)
        try:
            path = Path(source)
            is_file = path.exists() and path.is_file()
        except (ValueError, OSError):
            # Path() can raise ValueError for null bytes, OSError for other issues
            # Treat as raw content instead of a file path
            is_file = False

        if is_file:
            file_path = str(path.absolute())
            try:
                content = path.read_text(errors="replace")
            except Exception as e:
                return ParseResult(
                    hosts=[],
                    source_type="unknown",
                    file_path=file_path,
                    source_name=source_name,
                    errors=[f"Could not read file: {e}"],
                )

        # Detect format
        if format_hint:
            format_type = format_hint.lower()
        else:
            # Always pass content (not source path) for content-based detection
            format_type = self._detect_format(content, file_path)

        logger.debug(f"Detected format: {format_type}")

        # Parse based on format
        try:
            if format_type == "csv":
                hosts, errors = parse_csv(content)
            elif format_type == "json":
                hosts, errors = parse_json(content)
            elif format_type in ["yaml", "yml"]:
                hosts, errors = parse_yaml(content)
            elif format_type == "ini":
                hosts, errors = parse_ini(content)
            elif format_type == "etc_hosts":
                hosts, errors = parse_etc_hosts(content)
            elif format_type == "ssh_config":
                hosts, errors = parse_ssh_config(content)
            elif format_type == "txt":
                hosts, errors = parse_txt(content)
            else:
                # Fallback to LLM
                try:
                    llm_router = self.llm
                except LLMInitializationError as e:
                    logger.error(f"LLM fallback unavailable: {e}")
                    return ParseResult(
                        hosts=[],
                        source_type="unknown",
                        file_path=file_path,
                        source_name=source_name,
                        errors=[
                            f"LLM_UNAVAILABLE: Could not initialize LLM for parsing "
                            f"non-standard format: {e.reason}"
                        ],
                    )

                hosts, errors, warnings = parse_with_llm(
                    content, llm_router, self.LLM_CONTENT_LIMIT
                )
                format_type = "llm_parsed"
                return ParseResult(
                    hosts=hosts,
                    source_type=format_type,
                    file_path=file_path,
                    source_name=source_name,
                    errors=errors,
                    warnings=warnings,
                )

            return ParseResult(
                hosts=hosts,
                source_type=format_type,
                file_path=file_path,
                source_name=source_name,
                errors=errors,
            )

        except Exception as e:
            logger.error(f"Parsing failed: {e}")
            return ParseResult(
                hosts=[],
                source_type=format_type,
                file_path=file_path,
                source_name=source_name,
                errors=[f"Parsing failed: {e}"],
            )

    def _is_etc_hosts_format(self, content: str) -> bool:
        """
        Check if content matches /etc/hosts format.

        Validates that at least one non-comment line starts with a valid
        IPv4 or IPv6 address followed by whitespace and a hostname.

        Supports:
            - IPv4: 192.168.1.1 hostname
            - IPv6: ::1 localhost, fe80::1 hostname, 2001:db8::1 hostname
            - IPv6 with zone ID: fe80::1%eth0 hostname (zone stripped for validation)
        """
        for line in content.splitlines():
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue
            # Split on whitespace: first token should be IP, rest are hostnames
            tokens = line.split()
            if len(tokens) < 2:
                continue
            ip_candidate = tokens[0]
            # Strip zone ID suffix for IPv6 (e.g., fe80::1%eth0 -> fe80::1)
            if "%" in ip_candidate:
                ip_candidate = ip_candidate.split("%")[0]
            try:
                ipaddress.ip_address(ip_candidate)
                # Valid IP followed by at least one hostname
                return True
            except ValueError:
                continue
        return False

    def _detect_format(self, content: str, file_path: Optional[str] = None) -> str:
        """Auto-detect the format of the content."""
        # Check file extension first
        if file_path:
            ext = Path(file_path).suffix.lower()
            if ext == ".csv":
                return "csv"
            elif ext == ".json":
                return "json"
            elif ext in [".yaml", ".yml"]:
                return "yaml"
            elif ext == ".ini":
                return "ini"
            # Match /etc/hosts or files named exactly "hosts" or "etc_hosts"
            filename = Path(file_path).name.lower()
            if filename in ("hosts", "etc_hosts"):
                return "etc_hosts"
            # Match ssh_config, .ssh/config, or config files in .ssh directory
            # Use path parts to avoid false positives like ".sshkeys" or ".ssh_backup"
            path_parts = Path(file_path).parts
            in_ssh_dir = ".ssh" in path_parts
            if (filename == "config" and in_ssh_dir) or filename == "ssh_config":
                return "ssh_config"

        # Check content patterns
        content_stripped = content.strip()

        # JSON
        if content_stripped.startswith("{") or content_stripped.startswith("["):
            try:
                json.loads(content_stripped)
                return "json"
            except json.JSONDecodeError:
                pass

        # YAML (but not JSON)
        if ":" in content and not content_stripped.startswith("{"):
            # Check for YAML indicators - use re.search for multiline matching
            if re.search(r"^---\s*$", content_stripped, re.MULTILINE):
                return "yaml"
            if re.search(r"^\w+:\s*\n", content_stripped, re.MULTILINE):
                return "yaml"

        # CSV (has commas and looks tabular)
        lines = content_stripped.splitlines()
        if len(lines) > 1:
            comma_counts = [line.count(",") for line in lines[:5]]
            if len(set(comma_counts)) == 1 and comma_counts[0] > 0:
                return "csv"

        # INI (has [sections])
        if re.search(r"^\[[\w\-_]+\]", content_stripped, re.MULTILINE):
            return "ini"

        # /etc/hosts format (allow optional leading whitespace, support IPv4 and IPv6)
        # IPv4: 192.168.1.1 hostname
        # IPv6: ::1 localhost, fe80::1 hostname, 2001:db8::1 hostname
        # Use ipaddress module for robust validation of both address types
        if self._is_etc_hosts_format(content_stripped):
            return "etc_hosts"

        # SSH config format
        if re.search(r"^Host\s+\S+", content_stripped, re.MULTILINE | re.IGNORECASE):
            return "ssh_config"

        # Default to TXT (line-based)
        return "txt"


# Singleton
_parser: Optional[InventoryParser] = None


def get_inventory_parser() -> InventoryParser:
    """Get the inventory parser singleton."""
    global _parser
    if _parser is None:
        _parser = InventoryParser()
    return _parser
