"""
Data models for local scanner.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List


@dataclass
class LocalContext:
    """Complete local machine context."""

    os_info: Dict[str, Any] = field(default_factory=dict)
    network: Dict[str, Any] = field(default_factory=dict)
    services: Dict[str, Any] = field(default_factory=dict)
    processes: List[Dict[str, Any]] = field(default_factory=list)
    etc_files: Dict[str, Any] = field(default_factory=dict)
    resources: Dict[str, Any] = field(default_factory=dict)
    scanned_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "os_info": self.os_info,
            "network": self.network,
            "services": self.services,
            "processes": self.processes,
            "etc_files": self.etc_files,
            "resources": self.resources,
            "scanned_at": self.scanned_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LocalContext":
        """Create from dictionary."""
        scanned_at = data.get("scanned_at")
        if isinstance(scanned_at, str):
            try:
                scanned_at = datetime.fromisoformat(scanned_at)
            except (ValueError, TypeError):
                # Invalid timestamp - use sentinel to force rescan
                scanned_at = datetime.min
        elif scanned_at is None:
            # Missing timestamp - use sentinel to indicate unknown scan time
            # This will force a rescan rather than making old data appear fresh
            scanned_at = datetime.min

        return cls(
            os_info=data.get("os_info", {}),
            network=data.get("network", {}),
            services=data.get("services", {}),
            processes=data.get("processes", []),
            etc_files=data.get("etc_files", {}),
            resources=data.get("resources", {}),
            scanned_at=scanned_at,
        )
