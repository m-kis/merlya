"""
Host Models.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class HostData:
    """Data container for host bulk imports.

    Validates input data on creation to catch errors early before database operations.

    Attributes:
        hostname: Required hostname (will be lowercased during storage).
        ip_address: Optional IP address string.
        aliases: Optional list of hostname aliases (must be strings).
        environment: Optional environment name (e.g., 'production', 'staging').
        groups: Optional list of group names (must be strings).
        role: Optional role name.
        service: Optional service name.
        ssh_port: Optional SSH port (must be 1-65535 if provided).
        metadata: Optional metadata dictionary.

    Raises:
        ValueError: If validation fails (invalid port, non-string list elements, etc.).
    """

    hostname: str
    ip_address: Optional[str] = None
    aliases: Optional[List[str]] = None
    environment: Optional[str] = None
    groups: Optional[List[str]] = None
    role: Optional[str] = None
    service: Optional[str] = None
    ssh_port: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        """Validate fields after initialization."""
        # Validate hostname
        if not self.hostname or not isinstance(self.hostname, str):
            raise ValueError("hostname must be a non-empty string")
        if len(self.hostname) > 253:  # DNS max length
            raise ValueError(f"hostname too long: {len(self.hostname)} chars (max 253)")

        # Validate SSH port
        if self.ssh_port is not None:
            if not isinstance(self.ssh_port, int) or isinstance(self.ssh_port, bool):
                raise ValueError(f"ssh_port must be an integer, got {type(self.ssh_port).__name__}")
            if not (1 <= self.ssh_port <= 65535):
                raise ValueError(f"ssh_port must be 1-65535, got {self.ssh_port}")

        # Validate aliases list
        if self.aliases is not None:
            if not isinstance(self.aliases, list):
                raise ValueError(f"aliases must be a list, got {type(self.aliases).__name__}")
            for i, alias in enumerate(self.aliases):
                if not isinstance(alias, str):
                    raise ValueError(
                        f"aliases[{i}] must be a string, got {type(alias).__name__}"
                    )

        # Validate groups list
        if self.groups is not None:
            if not isinstance(self.groups, list):
                raise ValueError(f"groups must be a list, got {type(self.groups).__name__}")
            for i, group in enumerate(self.groups):
                if not isinstance(group, str):
                    raise ValueError(
                        f"groups[{i}] must be a string, got {type(group).__name__}"
                    )

        # Validate metadata dict
        if self.metadata is not None:
            if not isinstance(self.metadata, dict):
                raise ValueError(f"metadata must be a dict, got {type(self.metadata).__name__}")
