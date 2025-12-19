"""
Merlya Tools - Reference resolution.

Resolves @hostname and @secret references in commands.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.secrets import SecretStore

# Private/internal IP ranges - warn when DNS resolves to these
# (not blocked, as internal DNS is legitimate for infrastructure tools)
PRIVATE_IP_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("127.0.0.0/8"),  # Loopback
    ipaddress.ip_network("10.0.0.0/8"),  # Private Class A
    ipaddress.ip_network("172.16.0.0/12"),  # Private Class B
    ipaddress.ip_network("192.168.0.0/16"),  # Private Class C
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),  # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
)


# Pattern to match @reference references in commands
# Only match @ preceded by whitespace, start of string, or shell operators (not emails/URLs)
# Examples matched: @api-key, --password @db-pass, echo @token, @sudo:hostname:password, @pine64
# Examples NOT matched: user@github.com, git@repo.com
# Supports colons for structured keys like @service:host:field
REFERENCE_PATTERN = re.compile(r"(?:^|(?<=[\s;|&='\"]))\@([a-zA-Z][a-zA-Z0-9_:.-]*)")

# Keywords that indicate a reference is a SECRET, not a HOST
# These should NEVER be resolved as hostnames (skip in resolve_host_references)
SECRET_KEYWORDS: tuple[str, ...] = (
    "secret",
    "password",
    "passwd",
    "pass",
    "sudo",
    "root",
    "cred",
    "key",
    "token",
    "api",
    "auth",
)


def _is_private_ip(ip_str: str) -> bool:
    """
    Check if an IP address is in a private/internal range.

    This is used to warn about potential DNS rebinding or SSRF risks.
    Private IPs are NOT blocked since internal DNS is legitimate for infrastructure tools.

    Args:
        ip_str: IP address string (IPv4 or IPv6).

    Returns:
        True if IP is in a private/internal range.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
        return any(ip in network for network in PRIVATE_IP_NETWORKS)
    except ValueError:
        return False


def _is_secret_keyword_match(ref_name: str, hosts: list[Any]) -> bool:
    """
    Check if a reference name should be treated as a secret reference.

    This function avoids false positives where legitimate hostnames
    are incorrectly classified as secrets. It uses a conservative approach:

    1. First checks if the reference exists in inventory or resolves via DNS
    2. Only treats as secret if it contains specific secret-related patterns

    False positives avoided:
    - "keystone" (contains "key" but is a legitimate hostname)
    - "apiserver" (contains "api" but is a legitimate hostname)
    - "passport-office" (contains "pass" but is a legitimate hostname)

    Secret patterns that DO match:
    - Exact secret keywords: "password", "secret", "token", etc.
    - Secret with suffix: "api-key", "auth-token", "sudo-password"
    - Common secret formats: "secret-sudo", "root-password"

    Args:
        ref_name: The reference name to check (e.g., "api-key", "keystone").
        hosts: List of Host objects from inventory for fallback checks.

    Returns:
        True if the reference should be treated as a secret, False otherwise.
    """
    ref_lower = ref_name.lower()

    # Safe fallback: try to resolve against inventory first
    host_lookup = {h.name.lower(): h.hostname or h.name for h in hosts}
    if ref_name.lower() in host_lookup:
        logger.debug(f"🏠 @{ref_name} found in inventory, treating as host (not secret)")
        return False

    # Safe fallback: try DNS resolution
    try:
        socket.gethostbyname(ref_name)
        logger.debug(f"🌐 @{ref_name} resolves via DNS, treating as host (not secret)")
        return False
    except socket.gaierror:
        pass  # DNS failed, continue with keyword check

    # Check for obvious secret patterns (most specific first)
    secret_patterns = [
        # Exact secret keywords
        r"^password$",
        r"^secret$",
        r"^token$",
        r"^key$",
        r"^cred$",
        # Legacy secret patterns
        r"^secret-",
        r"-password$",
        r"-key$",
        r"-token$",
        r"-cred$",
        r"-secret$",
        # Common secret combinations (requires both parts)
        r"\b(api|auth|sudo|root|cred)\b.*\b(key|password|token|secret|cred)\b",
    ]

    for pattern in secret_patterns:
        if re.search(pattern, ref_lower):
            logger.debug(f"🔐 @{ref_name} matches secret pattern '{pattern}'")
            return True

    return False


async def resolve_host_references(
    command: str,
    hosts: list[Any],
    ui: Any | None = None,
) -> str:
    """
    Resolve @hostname references in a command to actual hostnames/IPs.

    Resolution order (sysadmin logic):
    1. Check inventory - if host exists, use its hostname
    2. Try DNS resolution
    3. Ask user for IP if unresolved

    Args:
        command: Command string potentially containing @hostname references.
        hosts: List of Host objects from inventory.
        ui: ConsoleUI for user prompts (optional).

    Returns:
        Command with @hostname replaced by actual hostname/IP.
    """
    resolved = command

    # Build lookup dict: name -> hostname
    host_lookup: dict[str, str] = {}
    for h in hosts:
        host_lookup[h.name.lower()] = h.hostname or h.name

    # Collect matches and sort by position (reverse to replace from end)
    matches = list(REFERENCE_PATTERN.finditer(command))
    matches.sort(key=lambda m: m.start(), reverse=True)

    for match in matches:
        ref_name = match.group(1)

        # Skip structured references (secrets like @sudo:host:password)
        if ":" in ref_name:
            continue

        # Skip references that look like secrets (e.g., @sudo-password, @api-key)
        # These should be resolved by resolve_secrets, not as hosts
        if _is_secret_keyword_match(ref_name, hosts):
            logger.debug(f"🔐 Skipping @{ref_name} in host resolution (looks like a secret)")
            continue

        start, end = match.span(0)
        replacement = None

        # 1. Check inventory
        if ref_name.lower() in host_lookup:
            replacement = host_lookup[ref_name.lower()]
            logger.debug(f"🖥️ Resolved @{ref_name} from inventory → {replacement}")

        # 2. Try DNS resolution with security checks
        if replacement is None:
            try:
                resolved_ip = socket.gethostbyname(ref_name)
                replacement = ref_name  # DNS works, use the name as-is

                # Security: Warn if external hostname resolves to private IP
                # This could indicate DNS rebinding attack or misconfiguration
                if _is_private_ip(resolved_ip):
                    logger.warning(
                        f"⚠️ SECURITY: @{ref_name} resolves to private IP {resolved_ip} - "
                        "verify this is expected (potential DNS rebinding)"
                    )
                else:
                    logger.debug(f"🌐 Resolved @{ref_name} via DNS → {resolved_ip}")
            except socket.gaierror:
                pass  # DNS failed, continue to user prompt

        # 3. Ask user for IP
        if replacement is None and ui:
            logger.info(f"❓ Host @{ref_name} not found in inventory and DNS failed")
            user_ip = await ui.prompt(f"Enter IP/hostname for '{ref_name}'", default="")
            if user_ip:
                replacement = user_ip
                logger.info(f"📝 User provided: @{ref_name} → {replacement}")
            else:
                logger.warning(f"⚠️ No resolution for @{ref_name}, keeping as-is")

        # Apply replacement if found
        if replacement:
            resolved = resolved[:start] + replacement + resolved[end:]

    return resolved


def _find_secret_with_fallback(secret_name: str, secrets: SecretStore) -> str | None:
    """
    Find a secret with fallback patterns for common formats.

    Tries:
    1. Exact match: @sudo:192.168.1.7:password
    2. Legacy format fallback: @secret-sudo → look for sudo:*:password patterns
    3. Simple fallback: @sudo-password → look for sudo:*:password patterns

    Args:
        secret_name: The secret name from the @reference.
        secrets: SecretStore instance.

    Returns:
        Secret value if found, None otherwise.
    """
    # 1. Try exact match first
    value = secrets.get(secret_name)
    if value is not None:
        return value

    # 2. Try fallback patterns for common elevation secrets
    # Map legacy formats to structured formats
    legacy_patterns = {
        "secret-sudo": "sudo",
        "secret-root": "root",
        "sudo-password": "sudo",
        "root-password": "root",
        "secret-password": "sudo",  # Common LLM mistake
    }

    name_lower = secret_name.lower()

    # Check if it's a known legacy pattern
    for legacy, service in legacy_patterns.items():
        if legacy in name_lower:
            # Find all matching structured secrets
            matches = [
                n
                for n in secrets.list_names()
                if n.startswith(f"{service}:") and n.endswith(":password")
            ]
            if matches:
                if len(matches) > 1:
                    logger.warning(
                        f"⚠️ Multiple secrets found for @{secret_name}: {matches}. Using: {matches[0]}"
                    )
                stored_name = matches[0]
                value = secrets.get(stored_name)
                if value is not None:
                    logger.debug(f"🔐 Fallback: @{secret_name} → {stored_name}")
                    return value

    return None


def resolve_secrets(
    command: str, secrets: SecretStore, resolved_hosts: set[str] | None = None
) -> tuple[str, str]:
    """
    Resolve @secret-name references in a command.

    SECURITY: This function should only be called at execution time,
    never before sending commands to the LLM.

    Supports both structured (@sudo:host:password) and legacy (@secret-sudo)
    formats with intelligent fallback.

    Args:
        command: Command string potentially containing @secret-name references.
        secrets: SecretStore instance.
        resolved_hosts: Set of host names already resolved (to skip).

    Returns:
        Tuple of (resolved_command, safe_command_for_logging).
        The safe_command replaces secret values with '***'.
    """
    resolved = command
    safe = command
    resolved_hosts = resolved_hosts or set()

    # Collect all matches and sort by start position in reverse order
    matches = list(REFERENCE_PATTERN.finditer(command))
    matches.sort(key=lambda m: m.start(), reverse=True)

    for match in matches:
        secret_name = match.group(1)

        # Skip if this was already resolved as a host reference
        if secret_name in resolved_hosts or secret_name.lower() in resolved_hosts:
            continue

        # Try to find secret with fallback patterns
        secret_value = _find_secret_with_fallback(secret_name, secrets)
        start, end = match.span(0)
        if secret_value is not None:  # Allow empty strings as valid secrets
            resolved = resolved[:start] + secret_value + resolved[end:]
            safe = safe[:start] + "***" + safe[end:]
            logger.debug(f"🔐 Resolved secret @{secret_name}")
        else:
            # Warn with helpful message - REDACT potential passwords
            if ":" in secret_name:
                parts = secret_name.split(":")
                service = parts[0]
                host = parts[1] if len(parts) > 1 else ""
                field = parts[2] if len(parts) > 2 else ""

                # Detect if field looks like a password value (not a keyword)
                # Valid keywords: password, passwd, pass, key, token, secret
                field_is_password_value = field and field.lower() not in (
                    "password",
                    "passwd",
                    "pass",
                    "key",
                    "token",
                    "secret",
                    "",
                )

                if field_is_password_value:
                    # SECURITY: The agent put the actual password in the reference!
                    # Log redacted version and give clear guidance
                    redacted_ref = f"@{service}:{host}:[REDACTED]"
                    logger.warning(
                        f"⚠️ WRONG FORMAT: {redacted_ref} - You put the password in the reference!\n"
                        f"   The correct format is: @{service}:{host}:password (literal keyword 'password')\n"
                        f"   Steps:\n"
                        f"   1. request_credentials(service='{service}', host='{host}')\n"
                        f"   2. Then use stdin='@{service}:{host}:password'"
                    )
                else:
                    logger.warning(
                        f"⚠️ Secret @{secret_name} not found. "
                        f"Use request_credentials(service='{service}', host='{host}') to store it."
                    )
            else:
                logger.warning(f"⚠️ Secret @{secret_name} not found in store")

    return resolved, safe


def get_resolved_host_names(hosts: list[Any]) -> set[str]:
    """
    Get a set of all host names (both original and lowercase) for exclusion.

    Args:
        hosts: List of Host objects from inventory.

    Returns:
        Set of host names to exclude from secret resolution.
    """
    return {h.name for h in hosts} | {h.name.lower() for h in hosts}


async def resolve_all_references(
    command: str,
    ctx: SharedContext,
) -> tuple[str, str]:
    """
    Resolve all @references (hosts and secrets) in a command.

    This is a convenience function that combines host and secret resolution
    in the correct order. Use this instead of calling resolve_host_references
    and resolve_secrets separately.

    Resolution order:
    1. @hostname references → inventory lookup → DNS → user prompt
    2. @secret references → keyring lookup

    Args:
        command: Command string potentially containing @references.
        ctx: Shared context with hosts, secrets, and ui.

    Returns:
        Tuple of (resolved_command, safe_command_for_logging).
        The safe_command replaces secret values with '***'.
    """
    # Get hosts for reference resolution
    all_hosts = await ctx.hosts.get_all()

    # 1. Resolve @hostname references → actual hostnames/IPs
    resolved_command = await resolve_host_references(command, all_hosts, ctx.ui)

    # Track which host names were resolved (to skip in secret resolution)
    resolved_host_names = get_resolved_host_names(all_hosts)

    # 2. Resolve @secret references → actual values
    resolved_command, safe_command = resolve_secrets(
        resolved_command, ctx.secrets, resolved_host_names
    )

    return resolved_command, safe_command


# Unified pattern for hostnames and IPv4 addresses
# Matches: "webserver", "192.168.1.7", "db-prod.local", etc.
_HOST_PATTERN = r"(?:[a-zA-Z0-9][a-zA-Z0-9._-]*|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"

# Pattern to extract credential hints from user messages
# Matches patterns like:
#   "pour 192.168.1.7 c'est @pine-pass"
#   "pour webserver c'est @pine-pass"
#   "password for host1 is @my-secret"
#   "192.168.1.5 ... @secret-name" (IP followed by @ref in same sentence)
_CREDENTIAL_HINT_PATTERNS = [
    # French: "pour HOST c'est/cest @secret"
    re.compile(
        rf"pour\s+({_HOST_PATTERN})\s+(?:c'?est|utilise|avec)\s+@([a-zA-Z][a-zA-Z0-9_-]*)",
        re.IGNORECASE,
    ),
    # English: "password for HOST is @secret"
    re.compile(
        rf"(?:password|pass|mot de passe|credential)\s+(?:for|de|du|pour)\s+({_HOST_PATTERN})\s+(?:is|est|:|=)\s*@([a-zA-Z][a-zA-Z0-9_-]*)",
        re.IGNORECASE,
    ),
    # Direct: "HOST ... celui ci @secret" (French: this is the password)
    # Limited to 30 chars between host and @secret to avoid cross-sentence matching
    re.compile(
        rf"({_HOST_PATTERN})[^@]{{1,30}}(?:celui\s+ci|celui-ci)\s+@([a-zA-Z][a-zA-Z0-9_-]*)",
        re.IGNORECASE,
    ),
    # Direct: "HOST ... le pass/password est @secret"
    re.compile(
        rf"({_HOST_PATTERN})[^@]{{1,40}}(?:le\s+)?(?:pass|password)\s+(?:est|c'?est|:)\s*@([a-zA-Z][a-zA-Z0-9_-]*)",
        re.IGNORECASE,
    ),
]

# Patterns to detect passwordless sudo/su elevation hints
# Matches: "pour devenir root sur 192.168.1.5 c'est sudo su sans password"
#          "pour devenir root sur webserver c'est sudo su sans password"
# Returns: (host, method) where method is "sudo" for passwordless sudo
_PASSWORDLESS_ELEVATION_PATTERNS = [
    # French: "sur/pour HOST c'est sudo/sudo su sans password"
    re.compile(
        rf"(?:sur|pour)\s+({_HOST_PATTERN})\s+[^.]*?(?:c'?est\s+)?(?:sudo\s+su|sudo)\s+sans\s+(?:mot de passe|password)",
        re.IGNORECASE,
    ),
    # French: "HOST ... sudo sans password"
    re.compile(
        rf"({_HOST_PATTERN})[^.]*?(?:sudo\s+su|sudo)\s+sans\s+(?:mot de passe|password)",
        re.IGNORECASE,
    ),
    # English: "HOST uses passwordless sudo"
    re.compile(
        rf"({_HOST_PATTERN})\s+[^.]*?(?:passwordless\s+sudo|sudo\s+without\s+password)",
        re.IGNORECASE,
    ),
]


def extract_credential_hints(user_message: str) -> list[tuple[str, str]]:
    """
    Extract credential hints from a user message.

    Looks for patterns where the user associates a host with a secret reference,
    such as:
    - "pour 192.168.1.7 c'est @pine-pass"
    - "password for server1 is @my-secret"
    - "192.168.1.7 ... le pass est @pine-pass"

    Args:
        user_message: The user's input message.

    Returns:
        List of (host, secret_key) tuples found in the message.
        The secret_key does NOT include the @ prefix.
    """
    hints: list[tuple[str, str]] = []

    for pattern in _CREDENTIAL_HINT_PATTERNS:
        for match in pattern.finditer(user_message):
            host = match.group(1)
            secret_key = match.group(2)
            hints.append((host, secret_key))
            logger.debug(f"🔑 Extracted credential hint: {host} -> @{secret_key}")

    return hints


def extract_elevation_hints(user_message: str) -> list[tuple[str, str]]:
    """
    Extract elevation method hints from a user message.

    Looks for patterns where the user indicates a host uses passwordless sudo,
    such as:
    - "pour devenir root sur 192.168.1.5 c'est sudo su sans password"
    - "192.168.1.5 uses passwordless sudo"

    Args:
        user_message: The user's input message.

    Returns:
        List of (host, method) tuples. Method is "sudo" for passwordless sudo.
    """
    hints: list[tuple[str, str]] = []

    for pattern in _PASSWORDLESS_ELEVATION_PATTERNS:
        for match in pattern.finditer(user_message):
            host = match.group(1)
            # These patterns all indicate passwordless sudo
            hints.append((host, "sudo"))
            logger.info(f"🔑 Detected passwordless sudo for {host}")

    return hints


def apply_credential_hints_from_message(user_message: str) -> int:
    """
    Extract and apply credential and elevation hints from a user message.

    This should be called when processing user input to automatically
    set up credential associations and elevation methods that were mentioned
    by the user.

    Args:
        user_message: The user's input message.

    Returns:
        Number of hints applied.
    """
    from merlya.tools.core.ssh import set_credential_hint
    from merlya.tools.core.ssh_patterns import set_cached_elevation_method

    total_hints = 0

    # Apply credential hints (@secret references)
    cred_hints = extract_credential_hints(user_message)
    for host, secret_key in cred_hints:
        set_credential_hint(host, secret_key)
        total_hints += 1

    # Apply elevation method hints (passwordless sudo detection)
    elev_hints = extract_elevation_hints(user_message)
    for host, method in elev_hints:
        set_cached_elevation_method(host, method)
        total_hints += 1

    return total_hints
