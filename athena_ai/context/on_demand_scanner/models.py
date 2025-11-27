"""
Data models for on-demand scanning.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class ScanResult:
    """Result of a host scan."""

    hostname: str
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    duration_ms: int = 0
    retries: int = 0
    scanned_at: str = ""

    def __post_init__(self):
        if not self.scanned_at:
            self.scanned_at = datetime.now(timezone.utc).isoformat()
