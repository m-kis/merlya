"""
Configuration manager for Athena user preferences.
Stores settings like language preference in ~/.athena/config.json
"""
import json
from pathlib import Path
from typing import Any, Optional


class ConfigManager:
    """Manage user configuration and preferences."""

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

        # Default config
        return {
            "language": None,  # Will be set on first run
            "theme": "default",
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
