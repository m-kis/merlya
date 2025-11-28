"""
Data models for inventory parser.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
    source_name: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Check if parsing was successful."""
        return len(self.hosts) > 0 and len(self.errors) == 0
