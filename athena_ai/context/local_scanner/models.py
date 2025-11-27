"""
Data models for local scanner.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List


# Sentinel for unknown/invalid scan timestamps.
# Using Unix epoch (1970-01-01) as it's recognizable, always triggers rescan
# checks (any TTL comparison will treat it as stale), and is clearly distinct
# from valid recent timestamps. Using UTC timezone for consistency.
UNKNOWN_SCAN_TIME = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass
class LocalContext:
    """Complete local machine context."""

    os_info: Dict[str, Any] = field(default_factory=dict)
    network: Dict[str, Any] = field(default_factory=dict)
    services: Dict[str, Any] = field(default_factory=dict)
    processes: List[Dict[str, Any]] = field(default_factory=list)
    etc_files: Dict[str, Any] = field(default_factory=dict)
    resources: Dict[str, Any] = field(default_factory=dict)
    scanned_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

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
        """Create from dictionary.

        Supports both new structure (with _metadata) and legacy (scanned_at at root).
        Also handles _value wrapper for non-dict values stored in repository.
        """
        # Get scanned_at from _metadata (new) or root level (legacy)
        # Use explicit None check to avoid issues with falsy but valid values
        metadata = data.get("_metadata", {})
        scanned_at_value = metadata.get("scanned_at")
        if scanned_at_value is None:
            scanned_at_value = data.get("scanned_at")
        scanned_at = _parse_scanned_at(scanned_at_value)

        return cls(
            os_info=_unwrap_value(data.get("os_info", {})),
            network=_unwrap_value(data.get("network", {})),
            services=_unwrap_value(data.get("services", {})),
            processes=_unwrap_value(data.get("processes", [])),
            etc_files=_unwrap_value(data.get("etc_files", {})),
            resources=_unwrap_value(data.get("resources", {})),
            scanned_at=scanned_at,
        )

    def needs_rescan(self, max_age_seconds: int = 3600) -> bool:
        """Check if context is stale and needs rescan.

        Args:
            max_age_seconds: Maximum age in seconds before rescan needed.

        Returns:
            True if scanned_at is unknown or older than max_age.
        """
        if self.scanned_at == UNKNOWN_SCAN_TIME:
            return True
        # Normalize scanned_at to UTC-aware datetime for consistent comparison
        scanned_at_utc = _ensure_utc_aware(self.scanned_at)
        now_utc = datetime.now(timezone.utc)
        age = (now_utc - scanned_at_utc).total_seconds()
        return age > max_age_seconds


def _ensure_utc_aware(dt: datetime) -> datetime:
    """Ensure datetime is UTC-aware.

    If dt is naive, assume it's UTC and attach timezone.
    If dt is aware, convert to UTC.

    Args:
        dt: The datetime to normalize.

    Returns:
        UTC-aware datetime.
    """
    if dt.tzinfo is None:
        # Naive datetime - assume UTC
        return dt.replace(tzinfo=timezone.utc)
    else:
        # Aware datetime - convert to UTC
        return dt.astimezone(timezone.utc)


def _unwrap_value(data: Any) -> Any:
    """Unwrap _value wrapper if present.

    The repository stores non-dict values as {"_value": original_value}.
    This function restores the original value.
    """
    if isinstance(data, dict) and "_value" in data and len(data) == 1:
        return data["_value"]
    return data


def _parse_scanned_at(value: Any) -> datetime:
    """Parse scanned_at from various input types.

    Args:
        value: The value to parse (str, datetime, None, or other).

    Returns:
        Parsed datetime, or UNKNOWN_SCAN_TIME if invalid/missing.
    """
    if value is None:
        return UNKNOWN_SCAN_TIME

    if isinstance(value, datetime):
        return value

    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return UNKNOWN_SCAN_TIME

    # Unexpected type - return sentinel
    return UNKNOWN_SCAN_TIME
