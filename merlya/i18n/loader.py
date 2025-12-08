"""
Merlya i18n - Locale loader.

Loads and manages translations from JSON files.
"""

from __future__ import annotations

import json
import locale
from pathlib import Path
from typing import Any

from loguru import logger

# Supported languages
SUPPORTED_LANGUAGES = ["en", "fr"]
DEFAULT_LANGUAGE = "en"

# Path to locales
LOCALES_DIR = Path(__file__).parent / "locales"


class I18n:
    """
    Internationalization manager.

    Loads translations from JSON files and provides lookup.
    """

    _instance: I18n | None = None

    def __init__(self, language: str | None = None) -> None:
        """
        Initialize i18n with specified or system language.

        Args:
            language: Language code (en, fr). Defaults to system language.
        """
        self._language = self._detect_language(language)
        self._translations: dict[str, Any] = {}
        self._fallback: dict[str, Any] = {}
        self._load_translations()

    @classmethod
    def get_instance(cls, language: str | None = None) -> I18n:
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls(language)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for tests)."""
        cls._instance = None

    @property
    def language(self) -> str:
        """Current language code."""
        return self._language

    def set_language(self, language: str) -> None:
        """
        Change current language.

        Args:
            language: Language code (en, fr).
        """
        if language not in SUPPORTED_LANGUAGES:
            logger.warning(f"Unsupported language '{language}', using {DEFAULT_LANGUAGE}")
            language = DEFAULT_LANGUAGE

        self._language = language
        self._load_translations()
        logger.info(f"Language set to: {language}")

    def _detect_language(self, language: str | None) -> str:
        """Detect language from parameter or system."""
        if language and language in SUPPORTED_LANGUAGES:
            return language

        # Try system locale (Python 3.15+ compatible)
        try:
            # getdefaultlocale() is deprecated since Python 3.11, removed in 3.15
            sys_lang = locale.getlocale()[0]
            if sys_lang:
                lang_code = sys_lang.split("_")[0].lower()
                if lang_code in SUPPORTED_LANGUAGES:
                    return lang_code
        except Exception:
            pass

        return DEFAULT_LANGUAGE

    def _load_translations(self) -> None:
        """Load translation files."""
        # Load fallback (English)
        fallback_path = LOCALES_DIR / f"{DEFAULT_LANGUAGE}.json"
        if fallback_path.exists():
            with fallback_path.open(encoding="utf-8") as f:
                self._fallback = json.load(f)

        # Load current language
        if self._language == DEFAULT_LANGUAGE:
            self._translations = self._fallback
        else:
            lang_path = LOCALES_DIR / f"{self._language}.json"
            if lang_path.exists():
                with lang_path.open(encoding="utf-8") as f:
                    self._translations = json.load(f)
            else:
                logger.warning(f"Locale file not found: {lang_path}")
                self._translations = self._fallback

    def t(self, key: str, **kwargs: Any) -> str:
        """
        Get translation for key.

        Args:
            key: Dot-separated key (e.g., "commands.hosts.added")
            **kwargs: Format arguments for string interpolation

        Returns:
            Translated string or key if not found.
        """
        # Navigate nested keys
        value = self._get_nested(self._translations, key)

        # Fallback to English if not found
        if value is None:
            value = self._get_nested(self._fallback, key)

        # Return key if not found anywhere
        if value is None:
            logger.debug(f"Missing translation: {key}")
            return key

        # Format with kwargs if provided
        if kwargs:
            try:
                return value.format(**kwargs)
            except KeyError as e:
                logger.warning(f"Missing format key in translation: {e}")
                return value

        return value

    def _get_nested(self, data: dict[str, Any], key: str) -> str | None:
        """Get nested value from dict using dot notation."""
        keys = key.split(".")
        current: Any = data

        for k in keys:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return None

        return current if isinstance(current, str) else None

    def get_all_keys(self) -> list[str]:
        """Get all available translation keys (for validation)."""
        return self._collect_keys(self._fallback)

    def _collect_keys(self, data: dict[str, Any], prefix: str = "") -> list[str]:
        """Recursively collect all keys."""
        keys: list[str] = []
        for k, v in data.items():
            full_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                keys.extend(self._collect_keys(v, full_key))
            else:
                keys.append(full_key)
        return keys

    def validate_translations(self) -> list[str]:
        """
        Validate that all keys in fallback exist in current language.

        Returns:
            List of missing keys.
        """
        if self._language == DEFAULT_LANGUAGE:
            return []

        missing: list[str] = []
        for key in self.get_all_keys():
            if self._get_nested(self._translations, key) is None:
                missing.append(key)

        return missing


# Convenience functions
def get_i18n(language: str | None = None) -> I18n:
    """Get i18n instance."""
    return I18n.get_instance(language)


def t(key: str, **kwargs: Any) -> str:
    """
    Translate key.

    Shortcut for get_i18n().t(key, **kwargs)
    """
    return get_i18n().t(key, **kwargs)
