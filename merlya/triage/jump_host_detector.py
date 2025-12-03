"""
Jump Host Detection for SSH Pivoting.

Detects patterns in user queries that indicate a jump/bastion host should be used
for SSH connections. Supports multiple languages (EN/FR).

Examples:
    - "connect to 10.0.0.5 via @bastion"
    - "check disk on server1 through @jumphost"
    - "accessible qu'à travers @ansible"
    - "en passant par @bastion"
"""
import ipaddress
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from merlya.utils.logger import logger

# RFC 1123 compliant hostname pattern (max 253 chars, labels max 63 chars)
# Allows: alphanumeric, hyphens (not at start/end of label), dots between labels
HOSTNAME_PATTERN = re.compile(
    r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?'
    r'(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
)

# Simple alphanumeric pattern for variable names (more permissive for inventory aliases)
VARIABLE_NAME_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_\-]{0,62}$')


def is_valid_hostname(hostname: str) -> bool:
    """
    Validate hostname according to RFC 1123.

    Args:
        hostname: Hostname to validate

    Returns:
        True if valid, False otherwise
    """
    if not hostname or len(hostname) > 253:
        return False
    # Allow simple alphanumeric names (inventory aliases like "ansible", "bastion")
    if VARIABLE_NAME_PATTERN.match(hostname):
        return True
    # Or full RFC 1123 hostnames
    return HOSTNAME_PATTERN.match(hostname) is not None


def is_valid_ip(ip_str: str) -> bool:
    """
    Validate IP address strictly.

    Args:
        ip_str: IP address string to validate

    Returns:
        True if valid IPv4 or IPv6, False otherwise
    """
    try:
        ipaddress.ip_address(ip_str)
        return True
    except ValueError:
        return False


@dataclass
class JumpHostInfo:
    """Information about a detected jump host requirement."""

    jump_host: str  # The jump host name (without @)
    target_host: Optional[str]  # The target host if detected
    pattern_matched: str  # The pattern that matched
    confidence: float  # Confidence score (0.0 - 1.0)
    _validated: bool = field(default=False, repr=False)

    def __post_init__(self):
        """Validate hostname after initialization to prevent injection."""
        if not is_valid_hostname(self.jump_host):
            raise ValueError(f"Invalid jump host name: {self.jump_host!r}")
        if self.target_host and not is_valid_hostname(self.target_host) and not is_valid_ip(self.target_host):
            raise ValueError(f"Invalid target host: {self.target_host!r}")
        self._validated = True

    def __str__(self) -> str:
        target = f" -> {self.target_host}" if self.target_host else ""
        return f"JumpHost({self.jump_host}{target}, conf={self.confidence:.2f})"


class JumpHostDetector:
    """
    Detects jump host requirements in user queries.

    Supports patterns in English and French indicating that a connection
    should be made through/via an intermediate host.
    """

    # Patterns that indicate jump host usage (multilingual)
    # Format: (pattern_regex, confidence, description)
    # Pattern should have named groups: (?P<jump>...) and optionally (?P<target>...)
    JUMP_PATTERNS: List[Tuple[str, float, str]] = [
        # English patterns
        (
            r"(?:via|through|using)\s+@(?P<jump>[\w\-]+)",
            0.95,
            "via/through @host"
        ),
        (
            r"(?:connect|ssh|access)\s+(?:to\s+)?(?P<target>[\w\.\-]+)\s+(?:via|through)\s+@(?P<jump>[\w\-]+)",
            0.98,
            "connect to X via @host"
        ),
        (
            r"@(?P<jump>[\w\-]+)\s+(?:as\s+)?(?:jump|bastion|gateway)\s*(?:host)?",
            0.90,
            "@host as jump/bastion"
        ),
        (
            r"(?:jump|bastion|gateway)\s*(?:host)?\s*(?:is\s+)?@(?P<jump>[\w\-]+)",
            0.90,
            "jump host is @host"
        ),
        # French patterns
        (
            r"(?:via|par|depuis)\s+(?:la\s+)?(?:machine\s+)?@(?P<jump>[\w\-]+)",
            0.95,
            "via/par @host"
        ),
        (
            r"(?:à\s+travers|au\s+travers\s+de)\s+(?:la\s+)?(?:machine\s+)?@(?P<jump>[\w\-]+)",
            0.98,
            "à travers @host"
        ),
        (
            r"(?:en\s+passant\s+par)\s+(?:la\s+)?(?:machine\s+)?@(?P<jump>[\w\-]+)",
            0.95,
            "en passant par @host"
        ),
        (
            r"(?:accessible|joignable)\s+(?:que\s+)?(?:via|par|depuis|à\s+travers)\s+(?:la\s+)?(?:machine\s+)?@(?P<jump>[\w\-]+)",
            0.98,
            "accessible via @host"
        ),
        (
            r"(?:n'est\s+accessible\s+qu'?)\s*(?:[àa]\s+travers|via|par)\s+(?:la\s+)?(?:machine\s+)?@(?P<jump>[\w\-]+)",
            0.99,
            "n'est accessible qu'à travers @host"
        ),
        # Simpler pattern for "accessible qu'à/qu'a travers"
        (
            r"accessible\s+qu['']\s*[àa]?\s*travers\s+(?:la\s+)?(?:machine\s+)?@(?P<jump>[\w\-]+)",
            0.98,
            "accessible qu'à travers @host (simple)"
        ),
        # IP-based target with jump host (various patterns)
        (
            r"(?P<target>\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+.*?(?:via|through|[àa]\s+travers|par)\s+(?:la\s+)?(?:machine\s+)?@(?P<jump>[\w\-]+)",
            0.97,
            "IP via @host"
        ),
        # French: "machine X ... accessible ... @jump"
        (
            r"machine\s+(?P<target>\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}).*?(?:accessible|joignable).*?@(?P<jump>[\w\-]+)",
            0.96,
            "machine IP accessible @host"
        ),
        (
            r"(?:sur|on)\s+(?:la\s+)?(?:machine\s+)?(?P<target>[\w\.\-]+)\s+.*?(?:via|through|à\s+travers|par)\s+@(?P<jump>[\w\-]+)",
            0.95,
            "on X via @host"
        ),
    ]

    # Keywords that strengthen jump host detection
    CONTEXT_KEYWORDS = [
        "pivot", "bastion", "jump", "gateway", "proxy",
        "indirect", "relay", "tunnel",
        # French
        "rebond", "passerelle", "intermédiaire",
    ]

    # Compiled pattern for IP extraction (reused)
    IP_PATTERN = re.compile(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b')

    def __init__(self):
        # Compile patterns for efficiency
        self._compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), conf, desc)
            for pattern, conf, desc in self.JUMP_PATTERNS
        ]

    def _extract_valid_ip(self, query: str) -> Optional[str]:
        """
        Extract and validate IP address from query.

        Args:
            query: Query text to search

        Returns:
            Valid IP string or None
        """
        for match in self.IP_PATTERN.finditer(query):
            ip_str = match.group(1)
            if is_valid_ip(ip_str):
                return ip_str
        return None

    def detect(self, query: str) -> Optional[JumpHostInfo]:
        """
        Detect if the query specifies a jump host requirement.

        Args:
            query: User query text

        Returns:
            JumpHostInfo if a jump host is detected, None otherwise
        """
        if not query or "@" not in query:
            return None

        best_match: Optional[JumpHostInfo] = None
        best_confidence = 0.0

        for pattern, base_conf, desc in self._compiled_patterns:
            match = pattern.search(query)
            if match:
                groups = match.groupdict()
                jump_host = groups.get("jump")
                target_host = groups.get("target")

                if not jump_host:
                    continue

                # Validate jump_host before proceeding
                if not is_valid_hostname(jump_host):
                    logger.warning(f"Invalid jump host name rejected: {jump_host!r}")
                    continue

                # Validate target_host if present (hostname OR valid IP)
                if target_host:
                    # Check if it looks like an IP (contains only digits and dots)
                    looks_like_ip = all(c.isdigit() or c == '.' for c in target_host)
                    if looks_like_ip:
                        if not is_valid_ip(target_host):
                            logger.warning(f"Invalid IP target rejected: {target_host!r}")
                            target_host = None
                    elif not is_valid_hostname(target_host):
                        logger.warning(f"Invalid target host rejected: {target_host!r}")
                        target_host = None

                # Adjust confidence based on context keywords
                confidence = base_conf
                query_lower = query.lower()
                for keyword in self.CONTEXT_KEYWORDS:
                    if keyword in query_lower:
                        confidence = min(1.0, confidence + 0.02)
                        break

                if confidence > best_confidence:
                    best_confidence = confidence
                    try:
                        best_match = JumpHostInfo(
                            jump_host=jump_host,
                            target_host=target_host,
                            pattern_matched=desc,
                            confidence=confidence,
                        )
                    except ValueError as e:
                        # Validation failed in dataclass
                        logger.warning(f"Jump host validation failed: {e}")
                        continue

        if best_match:
            # If we found a jump host but no target, try to extract valid IP from query
            if not best_match.target_host:
                extracted_ip = self._extract_valid_ip(query)
                if extracted_ip:
                    try:
                        best_match = JumpHostInfo(
                            jump_host=best_match.jump_host,
                            target_host=extracted_ip,
                            pattern_matched=best_match.pattern_matched,
                            confidence=best_match.confidence,
                        )
                    except ValueError:
                        pass  # Keep original match without target

            logger.info(f"Jump host detected: {best_match}")

        return best_match

    def extract_jump_and_target(self, query: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Convenience method to extract just the jump host and target.

        Args:
            query: User query text

        Returns:
            Tuple of (jump_host, target_host), both can be None
        """
        info = self.detect(query)
        if info:
            return info.jump_host, info.target_host
        return None, None


# Singleton instance
_detector: Optional[JumpHostDetector] = None


def get_jump_host_detector() -> JumpHostDetector:
    """Get or create the singleton jump host detector."""
    global _detector
    if _detector is None:
        _detector = JumpHostDetector()
    return _detector


def detect_jump_host(query: str) -> Optional[JumpHostInfo]:
    """
    Convenience function to detect jump host in a query.

    Args:
        query: User query text

    Returns:
        JumpHostInfo if detected, None otherwise
    """
    return get_jump_host_detector().detect(query)
