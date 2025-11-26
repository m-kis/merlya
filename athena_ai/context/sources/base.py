from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class InventorySource(Enum):
    """Types of inventory sources."""
    # File-based sources
    ETC_HOSTS = "etc_hosts"
    SSH_CONFIG = "ssh_config"
    ANSIBLE_INVENTORY = "ansible_inventory"
    ANSIBLE_FILE = "ansible_file"  # Alias for inventory_setup compatibility
    CUSTOM_FILE = "custom_file"
    # Cloud sources
    CLOUD_AWS = "cloud_aws"
    CLOUD_GCP = "cloud_gcp"
    CLOUD_AZURE = "cloud_azure"
    AWS_EC2 = "aws_ec2"  # Alias
    GCP_COMPUTE = "gcp_compute"  # Alias
    # API sources
    NETBOX = "netbox"
    CMDB = "cmdb"
    # Manual
    MANUAL = "manual"


@dataclass
class Host:
    """A validated host entry."""
    hostname: str
    ip_address: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    source: InventorySource = InventorySource.MANUAL
    environment: Optional[str] = None  # prod, staging, dev
    groups: List[str] = field(default_factory=list)  # Ansible groups
    metadata: Dict[str, Any] = field(default_factory=dict)
    last_seen: Optional[datetime] = None
    accessible: Optional[bool] = None

    def matches(self, query: str) -> bool:
        """Check if this host matches a query (case-insensitive)."""
        query_lower = query.lower()
        if self.hostname.lower() == query_lower:
            return True
        if any(alias.lower() == query_lower for alias in self.aliases):
            return True
        if self.ip_address and self.ip_address == query:
            return True
        return False

    def similarity(self, query: str) -> float:
        """Calculate similarity score with a query."""
        query_lower = query.lower()

        # Exact match
        if self.matches(query):
            return 1.0

        # Calculate best similarity across hostname and aliases
        scores = [SequenceMatcher(None, query_lower, self.hostname.lower()).ratio()]
        for alias in self.aliases:
            scores.append(SequenceMatcher(None, query_lower, alias.lower()).ratio())

        return max(scores)


@dataclass
class HostValidationResult:
    """Result of validating a hostname."""
    is_valid: bool
    host: Optional[Host] = None
    original_query: str = ""
    suggestions: List[Tuple[str, float]] = field(default_factory=list)  # (hostname, score)
    error_message: str = ""

    def get_suggestion_text(self) -> str:
        """Get human-readable suggestion text."""
        if self.is_valid:
            return f"✓ Host '{self.host.hostname}' is valid"

        if not self.suggestions:
            return f"✗ Host '{self.original_query}' not found. No similar hosts in inventory."

        lines = [f"✗ Host '{self.original_query}' not found in inventory."]
        lines.append("Did you mean one of these?")
        for hostname, score in self.suggestions[:5]:
            lines.append(f"  • {hostname} ({score:.0%} match)")
        return "\n".join(lines)


class BaseSource(ABC):
    """Abstract base class for inventory sources."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @abstractmethod
    def load(self) -> List[Host]:
        """Load hosts from this source."""
        pass
