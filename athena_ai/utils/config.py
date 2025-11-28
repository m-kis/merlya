"""
Configuration manager for Athena user preferences.

Stores non-LLM settings in ~/.athena/config.json
For LLM/model configuration, use ModelConfig from athena_ai.llm.model_config
"""
import json
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo


# Default timezone for interpreting naive timestamps from legacy DB records.
# Set to "local" to use system local timezone, or an IANA timezone name (e.g., "America/New_York").
DEFAULT_LOCAL_TIMEZONE = "local"


def get_local_timezone() -> ZoneInfo:
    """Get the configured local timezone for naive timestamp interpretation.

    Returns:
        ZoneInfo for the configured timezone, or system local timezone if "local".
    """
    from datetime import datetime

    config = ConfigManager()
    tz_setting = config.get("local_timezone", DEFAULT_LOCAL_TIMEZONE)

    if tz_setting == "local":
        # Get system's local timezone - more portable than ZoneInfo("localtime")
        try:
            local_tz = datetime.now().astimezone().tzinfo
            if local_tz is None:
                return ZoneInfo("UTC")
            # If it's already a ZoneInfo, return it
            if isinstance(local_tz, ZoneInfo):
                return local_tz
            # Try to get the zone name (works on most systems)
            if hasattr(local_tz, 'key'):
                return ZoneInfo(local_tz.key)
            # Last resort: try "localtime" (works on some Unix systems)
            return ZoneInfo("localtime")
        except (KeyError, OSError, AttributeError):
            return ZoneInfo("UTC")

    try:
        return ZoneInfo(tz_setting)
    except (KeyError, ValueError):
        # Invalid timezone name - fallback to UTC
        return ZoneInfo("UTC")


class ConfigManager:
    """
    Manage user configuration and preferences (non-LLM settings).

    For LLM configuration (provider, models), use ModelConfig instead.
    This class handles: language, theme, and other UI preferences.
    """

    def __init__(self):
        self.config_dir = Path.home() / ".athena"
        self.config_file = self.config_dir / "config.json"
        self.config = self._load_config()

    def _load_config(self) -> dict:
        """Load config from file, or return defaults."""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except Exception:
                pass

        # Default config (non-LLM settings only)
        return {
            "language": None,  # Will be set on first run
            "theme": "default",
            "local_timezone": DEFAULT_LOCAL_TIMEZONE,
        }

    def _save_config(self):
        """Save config to file."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, 'w') as f:
            json.dump(self.config, indent=2, fp=f)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value."""
        return self.config.get(key, default)

    def set(self, key: str, value: Any):
        """Set a config value and save."""
        self.config[key] = value
        self._save_config()

    @property
    def language(self) -> Optional[str]:
        """Get language preference (en or fr)."""
        return self.config.get("language")

    @language.setter
    def language(self, value: str):
        """Set language preference."""
        if value not in ['en', 'fr']:
            raise ValueError("Language must be 'en' or 'fr'")
        self.set("language", value)

    @property
    def theme(self) -> str:
        """Get UI theme."""
        return self.config.get("theme", "default")

    @theme.setter
    def theme(self, value: str):
        """Set UI theme."""
        self.set("theme", value)

    @property
    def local_timezone(self) -> str:
        """Get local timezone setting for naive timestamp interpretation.

        Returns "local" for system local timezone, or an IANA timezone name.
        """
        return self.config.get("local_timezone", DEFAULT_LOCAL_TIMEZONE)

    @local_timezone.setter
    def local_timezone(self, value: str):
        """Set local timezone for naive timestamp interpretation.

        Args:
            value: "local" for system timezone, or IANA timezone name (e.g., "America/New_York").
        """
        if value != "local":
            # Validate it's a valid timezone
            try:
                ZoneInfo(value)
            except (KeyError, ValueError) as e:
                raise ValueError(f"Invalid timezone: {value}") from e
        self.set("local_timezone", value)
