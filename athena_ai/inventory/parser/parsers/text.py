"""
Text-based format parsers (INI, TXT, etc_hosts, ssh_config).
"""
import ipaddress
from typing import List, Tuple

from ..models import ParsedHost


def _is_ip(value: str) -> bool:
    """Check if value is a valid IP address (IPv4 or IPv6)."""
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def parse_ini(content: str) -> Tuple[List[ParsedHost], List[str]]:
    """Parse INI/Ansible inventory format."""
    hosts = []
    errors = []
    current_group = "ungrouped"

    for line_num, line in enumerate(content.splitlines(), 1):
        line = line.strip()

        # Skip empty lines and comments
        if not line or line.startswith("#") or line.startswith(";"):
            continue

        # Group header
        if line.startswith("[") and line.endswith("]"):
            group_name = line[1:-1].strip()
            if not group_name:
                errors.append(f"Line {line_num}: Empty group name")
                continue
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
                    if not _is_ip(value):
                        errors.append(f"Line {line_num}: Invalid IP address '{value}' for host '{hostname}'")
                    host.ip_address = value
                elif key == "ansible_port":
                    try:
                        host.ssh_port = int(value)
                    except ValueError:
                        errors.append(f"Line {line_num}: Invalid port '{value}' for host '{hostname}'")
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


def parse_etc_hosts(content: str) -> Tuple[List[ParsedHost], List[str]]:
    """Parse /etc/hosts format."""
    hosts = []
    errors = []

    # IPs to skip
    skip_ips = {"127.0.0.1", "::1", "255.255.255.255", "0.0.0.0"}
    skip_hosts = {"localhost", "broadcasthost", "ip6-localhost", "ip6-loopback"}

    for line_num, line in enumerate(content.splitlines(), 1):
        line = line.strip()

        # Skip empty lines and comments
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        if len(parts) < 2:
            errors.append(f"Line {line_num}: Malformed entry, expected 'IP hostname'")
            continue

        ip = parts[0]
        hostnames = parts[1:]

        # Validate IP address
        if not _is_ip(ip):
            errors.append(f"Line {line_num}: Invalid IP address '{ip}'")
            continue

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


def parse_ssh_config(content: str) -> Tuple[List[ParsedHost], List[str]]:
    """Parse SSH config format."""
    hosts = []
    errors = []
    current_host = None
    current_host_line = 0

    for line_num, line in enumerate(content.splitlines(), 1):
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
                errors.append(f"Line {line_num}: Empty Host directive")
                current_host = None
                continue

            hostname = parts[1].strip()

            # Skip wildcards
            if "*" in hostname or "?" in hostname:
                current_host = None
                continue

            current_host = ParsedHost(hostname=hostname.lower())
            current_host_line = line_num

        elif current_host:
            # Parse host options
            if " " in line:
                key, value = line.split(None, 1)
                key = key.lower()

                if key == "hostname":
                    # HostName is the actual target (FQDN or IP)
                    # Host (stored in current_host.hostname) is the alias
                    if _is_ip(value):
                        current_host.ip_address = value
                    else:
                        # HostName is the real FQDN/hostname
                        fqdn = value.lower()
                        # Move the Host alias to aliases if different from FQDN
                        if current_host.hostname and current_host.hostname != fqdn:
                            if current_host.hostname not in current_host.aliases:
                                current_host.aliases.append(current_host.hostname)
                        # Set the actual hostname to the FQDN
                        current_host.hostname = fqdn
                elif key == "port":
                    try:
                        current_host.ssh_port = int(value)
                    except ValueError:
                        errors.append(f"Line {line_num}: Invalid port '{value}' for host at line {current_host_line}")
                elif key == "user":
                    current_host.metadata["ssh_user"] = value
                elif key == "identityfile":
                    current_host.metadata["ssh_key"] = value

    # Don't forget the last host
    if current_host and current_host.hostname:
        hosts.append(current_host)

    return hosts, errors


def parse_txt(content: str) -> Tuple[List[ParsedHost], List[str]]:
    """Parse simple TXT format (one hostname per line)."""
    hosts = []
    errors = []

    for line_num, line in enumerate(content.splitlines(), 1):
        line = line.strip()

        # Skip empty lines and comments
        if not line or line.startswith("#"):
            continue

        # Try to extract hostname and optional IP
        parts = line.split()

        if not parts:
            continue

        if len(parts) >= 2 and _is_ip(parts[0]):
            # Format: IP hostname
            host = ParsedHost(
                hostname=parts[1].lower(),
                ip_address=parts[0],
            )
        elif len(parts) >= 2 and _is_ip(parts[1]):
            # Format: hostname IP
            host = ParsedHost(
                hostname=parts[0].lower(),
                ip_address=parts[1],
            )
        elif len(parts) >= 2:
            # Two parts but neither is a valid IP - report as warning
            errors.append(f"Line {line_num}: Neither '{parts[0]}' nor '{parts[1]}' is a valid IP address")
            host = ParsedHost(hostname=parts[0].lower())
        else:
            # Just hostname
            host = ParsedHost(hostname=parts[0].lower())

        hosts.append(host)

    return hosts, errors
