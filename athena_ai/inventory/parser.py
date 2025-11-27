"""
Inventory Parser - Multi-format parser with AI fallback.

Supports:
- CSV
- JSON
- YAML
- TXT (line-based)
- INI (Ansible-style)
- /etc/hosts format
- ~/.ssh/config format
- Any format via LLM fallback
"""

import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from athena_ai.utils.logger import logger


@dataclass
class ParsedHost:
    """Represents a parsed host entry."""

    hostname: str
    ip_address: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    environment: Optional[str] = None
    groups: List[str] = field(default_factory=list)
    role: Optional[str] = None
    service: Optional[str] = None
    ssh_port: int = 22
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "hostname": self.hostname,
            "ip_address": self.ip_address,
            "aliases": self.aliases,
            "environment": self.environment,
            "groups": self.groups,
            "role": self.role,
            "service": self.service,
            "ssh_port": self.ssh_port,
            "metadata": self.metadata,
        }


@dataclass
class ParseResult:
    """Result of parsing an inventory source."""

    hosts: List[ParsedHost]
    source_type: str
    file_path: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Check if parsing was successful."""
        return len(self.hosts) > 0 and len(self.errors) == 0


class InventoryParser:
    """
    Multi-format inventory parser.

    Supports structured formats (CSV, JSON, YAML) and
    falls back to LLM for non-standard formats.
    """

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

    def __init__(self, llm_router: Optional[Any] = None):
        """Initialize parser with optional LLM router."""
        self._llm = llm_router

    @property
    def llm(self):
        """Lazy load LLM router."""
        if self._llm is None:
            try:
                from athena_ai.llm.router import LLMRouter
                self._llm = LLMRouter()
            except Exception as e:
                logger.warning(f"Could not initialize LLM router: {e}")
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

        path = Path(source)
        if path.exists() and path.is_file():
            file_path = str(path.absolute())
            try:
                content = path.read_text(errors="replace")
            except Exception as e:
                return ParseResult(
                    hosts=[],
                    source_type="unknown",
                    file_path=file_path,
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
                hosts, errors = self._parse_csv(content)
            elif format_type == "json":
                hosts, errors = self._parse_json(content)
            elif format_type in ["yaml", "yml"]:
                hosts, errors = self._parse_yaml(content)
            elif format_type == "ini":
                hosts, errors = self._parse_ini(content)
            elif format_type == "etc_hosts":
                hosts, errors = self._parse_etc_hosts(content)
            elif format_type == "ssh_config":
                hosts, errors = self._parse_ssh_config(content)
            elif format_type == "txt":
                hosts, errors = self._parse_txt(content)
            else:
                # Fallback to LLM
                hosts, errors = self._parse_with_llm(content)
                format_type = "llm_parsed"

            return ParseResult(
                hosts=hosts,
                source_type=format_type,
                file_path=file_path,
                errors=errors,
            )

        except Exception as e:
            logger.error(f"Parsing failed: {e}")
            return ParseResult(
                hosts=[],
                source_type=format_type,
                file_path=file_path,
                errors=[f"Parsing failed: {e}"],
            )

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
            elif "hosts" in file_path.lower():
                return "etc_hosts"
            elif "ssh" in file_path.lower() and "config" in file_path.lower():
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

        # /etc/hosts format
        if re.match(r"^\d+\.\d+\.\d+\.\d+\s+\S+", content_stripped, re.MULTILINE):
            return "etc_hosts"

        # SSH config format
        if re.search(r"^Host\s+\S+", content_stripped, re.MULTILINE | re.IGNORECASE):
            return "ssh_config"

        # Default to TXT (line-based)
        return "txt"

    def _parse_csv(self, content: str) -> Tuple[List[ParsedHost], List[str]]:
        """Parse CSV content."""
        hosts = []
        errors = []

        try:
            reader = csv.DictReader(io.StringIO(content))
            fieldnames = [f.lower() for f in (reader.fieldnames or [])]

            # Find the hostname field
            hostname_field = None
            for field in self.HOSTNAME_FIELDS:
                if field in fieldnames:
                    hostname_field = reader.fieldnames[fieldnames.index(field)]
                    break

            if not hostname_field:
                errors.append(f"No hostname field found. Expected one of: {self.HOSTNAME_FIELDS}")
                return hosts, errors

            # Find other fields
            ip_field = self._find_field(reader.fieldnames, self.IP_FIELDS)
            env_field = self._find_field(reader.fieldnames, self.ENV_FIELDS)

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

    def _parse_json(self, content: str) -> Tuple[List[ParsedHost], List[str]]:
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
                for field in self.HOSTNAME_FIELDS:
                    if field in item:
                        hostname = item[field]
                        break

                if not hostname:
                    continue

                host = ParsedHost(
                    hostname=str(hostname).lower(),
                    ip_address=self._get_field(item, self.IP_FIELDS),
                    environment=self._get_field(item, self.ENV_FIELDS),
                    groups=item.get("groups", []) if isinstance(item.get("groups"), list) else [],
                    aliases=item.get("aliases", []) if isinstance(item.get("aliases"), list) else [],
                    role=item.get("role"),
                    service=item.get("service"),
                    ssh_port=item.get("ssh_port", item.get("port", 22)),
                    metadata={k: v for k, v in item.items()
                              if k not in ["hostname", "host", "ip", "ip_address", "environment", "env",
                                           "groups", "aliases", "role", "service", "ssh_port", "port"]},
                )
                hosts.append(host)

        except json.JSONDecodeError as e:
            errors.append(f"JSON parsing error: {e}")

        return hosts, errors

    def _parse_yaml(self, content: str) -> Tuple[List[ParsedHost], List[str]]:
        """Parse YAML content."""
        hosts = []
        errors = []

        try:
            import yaml
            data = yaml.safe_load(content)

            # Reuse JSON parsing logic
            if data:
                return self._parse_json(json.dumps(data))

        except ImportError:
            errors.append("PyYAML not installed. Install with: pip install pyyaml")
        except Exception as e:
            errors.append(f"YAML parsing error: {e}")

        return hosts, errors

    def _parse_ini(self, content: str) -> Tuple[List[ParsedHost], List[str]]:
        """Parse INI/Ansible inventory format."""
        hosts = []
        errors = []
        current_group = "ungrouped"

        for line in content.splitlines():
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith("#") or line.startswith(";"):
                continue

            # Group header
            if line.startswith("[") and line.endswith("]"):
                group_name = line[1:-1].strip()
                # Skip special Ansible groups
                if ":" not in group_name:
                    current_group = group_name
                continue

            # Host line: hostname ansible_host=IP var=value ...
            parts = line.split()
            if not parts:
                continue

            hostname = parts[0]

            # Skip if it looks like a child group reference
            if hostname.startswith("["):
                continue

            host = ParsedHost(
                hostname=hostname.lower(),
                groups=[current_group],
            )

            # Parse variables
            for part in parts[1:]:
                if "=" in part:
                    key, value = part.split("=", 1)
                    key = key.lower()

                    if key in ["ansible_host", "ip"]:
                        host.ip_address = value
                    elif key == "ansible_port":
                        try:
                            host.ssh_port = int(value)
                        except ValueError:
                            pass
                    elif key in ["ansible_user", "user"]:
                        host.metadata["ssh_user"] = value
                    else:
                        host.metadata[key] = value

            # Detect environment from group name
            group_lower = current_group.lower()
            if "prod" in group_lower:
                host.environment = "production"
            elif "staging" in group_lower or "stage" in group_lower:
                host.environment = "staging"
            elif "dev" in group_lower:
                host.environment = "development"
            elif "test" in group_lower:
                host.environment = "testing"

            hosts.append(host)

        return hosts, errors

    def _parse_etc_hosts(self, content: str) -> Tuple[List[ParsedHost], List[str]]:
        """Parse /etc/hosts format."""
        hosts = []
        errors = []

        # IPs to skip
        skip_ips = {"127.0.0.1", "::1", "255.255.255.255", "0.0.0.0"}
        skip_hosts = {"localhost", "broadcasthost", "ip6-localhost", "ip6-loopback"}

        for line in content.splitlines():
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue

            parts = line.split()
            if len(parts) < 2:
                continue

            ip = parts[0]
            hostnames = parts[1:]

            # Skip local/special entries
            if ip in skip_ips:
                continue

            # First hostname is primary, rest are aliases
            primary = hostnames[0].lower()
            if primary in skip_hosts:
                continue

            aliases = [h.lower() for h in hostnames[1:] if h.lower() not in skip_hosts]

            host = ParsedHost(
                hostname=primary,
                ip_address=ip,
                aliases=aliases,
            )
            hosts.append(host)

        return hosts, errors

    def _parse_ssh_config(self, content: str) -> Tuple[List[ParsedHost], List[str]]:
        """Parse SSH config format."""
        hosts = []
        errors = []
        current_host = None

        for line in content.splitlines():
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue

            # Host directive
            if line.lower().startswith("host "):
                # Save previous host
                if current_host and current_host.hostname:
                    hosts.append(current_host)

                # Guard against malformed "Host " line with no hostname
                parts = line.split(None, 1)
                if len(parts) < 2 or not parts[1].strip():
                    current_host = None
                    continue

                hostname = parts[1].strip()

                # Skip wildcards
                if "*" in hostname or "?" in hostname:
                    current_host = None
                    continue

                current_host = ParsedHost(hostname=hostname.lower())

            elif current_host:
                # Parse host options
                if " " in line:
                    key, value = line.split(None, 1)
                    key = key.lower()

                    if key == "hostname":
                        # Actual hostname/IP
                        if self._is_ip(value):
                            current_host.ip_address = value
                        else:
                            current_host.aliases.append(value.lower())
                    elif key == "port":
                        try:
                            current_host.ssh_port = int(value)
                        except ValueError:
                            pass
                    elif key == "user":
                        current_host.metadata["ssh_user"] = value
                    elif key == "identityfile":
                        current_host.metadata["ssh_key"] = value

        # Don't forget the last host
        if current_host and current_host.hostname:
            hosts.append(current_host)

        return hosts, errors

    def _parse_txt(self, content: str) -> Tuple[List[ParsedHost], List[str]]:
        """Parse simple TXT format (one hostname per line)."""
        hosts = []
        errors = []

        for line in content.splitlines():
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue

            # Try to extract hostname and optional IP
            parts = line.split()

            if len(parts) >= 2 and self._is_ip(parts[0]):
                # Format: IP hostname
                host = ParsedHost(
                    hostname=parts[1].lower(),
                    ip_address=parts[0],
                )
            elif len(parts) >= 2 and self._is_ip(parts[1]):
                # Format: hostname IP
                host = ParsedHost(
                    hostname=parts[0].lower(),
                    ip_address=parts[1],
                )
            else:
                # Just hostname
                host = ParsedHost(hostname=parts[0].lower())

            hosts.append(host)

        return hosts, errors

    def _parse_with_llm(self, content: str) -> Tuple[List[ParsedHost], List[str]]:
        """Use LLM to parse non-standard format."""
        hosts = []
        errors = []

        if not self.llm:
            errors.append("LLM not available for parsing non-standard format")
            return hosts, errors

        prompt = f"""Analyze this inventory content and extract host information.
Return ONLY a JSON array with objects containing these fields:
- hostname (required): the server hostname
- ip_address (optional): IP address if present
- environment (optional): prod/staging/dev if determinable
- groups (optional): array of group names
- metadata (optional): any other relevant info as key-value pairs

Content to parse:
```
{content[:3000]}
```

Return ONLY valid JSON, no explanations."""

        try:
            response = self.llm.generate(prompt, task="correction")

            # Extract JSON from response
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                for item in data:
                    if isinstance(item, dict) and item.get("hostname"):
                        host = ParsedHost(
                            hostname=item["hostname"].lower(),
                            ip_address=item.get("ip_address"),
                            environment=item.get("environment"),
                            groups=item.get("groups", []),
                            metadata=item.get("metadata", {}),
                        )
                        hosts.append(host)
            else:
                errors.append("LLM did not return valid JSON")

        except Exception as e:
            errors.append(f"LLM parsing failed: {e}")

        return hosts, errors

    def _find_field(self, fieldnames: List[str], candidates: List[str]) -> Optional[str]:
        """Find a field from a list of candidates."""
        if not fieldnames:
            return None
        fieldnames_lower = [f.lower() for f in fieldnames]
        for candidate in candidates:
            if candidate in fieldnames_lower:
                return fieldnames[fieldnames_lower.index(candidate)]
        return None

    def _get_field(self, item: Dict, candidates: List[str]) -> Optional[str]:
        """Get a field value from a dict using candidate names."""
        for candidate in candidates:
            if candidate in item:
                return str(item[candidate])
        return None

    def _is_ip(self, value: str) -> bool:
        """Check if value looks like an IP address."""
        # IPv4
        if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", value):
            return True
        # IPv6 (simplified check)
        if ":" in value and not "://" in value:
            return True
        return False


# Singleton
_parser: Optional[InventoryParser] = None


def get_inventory_parser() -> InventoryParser:
    """Get the inventory parser singleton."""
    global _parser
    if _parser is None:
        _parser = InventoryParser()
    return _parser
