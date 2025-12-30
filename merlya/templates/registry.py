"""
Merlya Templates - Template Registry.

Central registry for discovering and managing templates.

v0.9.0: Initial implementation.
v0.9.1: Thread safety, version comparison, manual registration tracking.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from loguru import logger
from packaging import version as packaging_version

from merlya.templates.models import (
    IaCBackend,
    Template,
    TemplateCategory,
    TemplateNotFoundError,
)

if TYPE_CHECKING:
    from merlya.templates.loaders.base import AbstractTemplateLoader


class TemplateRegistry:
    """
    Central registry for IaC templates.

    Singleton pattern with thread safety and reset_instance() for testing.

    Thread Safety:
        The singleton pattern uses a lock to prevent race conditions
        when get_instance() is called concurrently from multiple threads.

    Version Management:
        Templates are stored both with versioned keys (name:version) and
        unversioned keys (name). The unversioned key always points to the
        highest semantic version, not the last registered.

    Manual Registrations:
        Templates registered via register() are tracked separately and
        preserved when load_templates(force=True) is called.
    """

    _instance: TemplateRegistry | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize the registry."""
        self._templates: dict[str, Template] = {}
        self._manual_templates: dict[str, Template] = {}
        self._loaders: list[AbstractTemplateLoader] = []
        self._loaded = False
        self._load_lock = threading.Lock()  # Protects _loaded flag and load operations

    @classmethod
    def get_instance(cls) -> TemplateRegistry:
        """Get or create the singleton instance (thread-safe)."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (for testing)."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance.clear()
            cls._instance = None

    def register_loader(self, loader: AbstractTemplateLoader) -> None:
        """Register a template loader (thread-safe)."""
        with self._load_lock:
            self._loaders.append(loader)
            self._loaded = False  # Force reload on next access

    def load_templates(self, force: bool = False) -> None:
        """
        Load templates from all registered loaders (thread-safe).

        Manual registrations are preserved when force=True.
        """
        with self._load_lock:
            if self._loaded and not force:
                return

            # Preserve manually registered templates
            manual_backup = self._manual_templates.copy()

            self._templates.clear()

            # Restore manual registrations first
            for template in manual_backup.values():
                self._register(template)
            self._manual_templates = manual_backup

            for loader in self._loaders:
                try:
                    templates = loader.load_all()
                    for template in templates:
                        self._register(template)
                except Exception as e:
                    logger.warning(f"⚠️ Failed to load templates from {loader}: {e}")

            self._loaded = True
            logger.debug(f"📁 Loaded {len(self._templates)} templates")

    def _register(self, template: Template) -> None:
        """Register a single template."""
        key = f"{template.name}:{template.version}"
        if key in self._templates:
            logger.warning(f"⚠️ Template {key} already registered, overwriting")
        self._templates[key] = template

        # Also register without version for latest lookup (highest version wins)
        current_latest = self._templates.get(template.name)
        if current_latest is None:
            self._templates[template.name] = template
        else:
            try:
                if packaging_version.parse(template.version) > packaging_version.parse(
                    current_latest.version
                ):
                    self._templates[template.name] = template
            except Exception:
                # If version parsing fails, keep current behavior (last registered wins)
                self._templates[template.name] = template

    def register(self, template: Template) -> None:
        """
        Manually register a template (thread-safe).

        Manually registered templates are preserved when load_templates(force=True)
        is called, unlike templates loaded from loaders.
        """
        with self._load_lock:
            self._register(template)

            # Track manual registrations separately for preservation
            key = f"{template.name}:{template.version}"
            self._manual_templates[key] = template
            self._manual_templates[template.name] = template

            # Mark as loaded so load_templates() doesn't clear manual registrations
            self._loaded = True

    def get(self, name: str, version: str | None = None) -> Template:
        """
        Get a template by name and optional version.

        Args:
            name: Template name.
            version: Optional version string. If not provided, returns the
                    highest semantic version available.

        Returns:
            The template.

        Raises:
            TemplateNotFoundError: If template not found.
        """
        self.load_templates()

        key = f"{name}:{version}" if version else name
        template = self._templates.get(key)

        if not template:
            raise TemplateNotFoundError(f"Template not found: {key}")

        return template

    def find(
        self,
        category: TemplateCategory | None = None,
        provider: str | None = None,
        backend: IaCBackend | None = None,
        tags: list[str] | None = None,
    ) -> list[Template]:
        """
        Find templates matching criteria.

        Args:
            category: Filter by category.
            provider: Filter by provider support.
            backend: Filter by backend support.
            tags: Filter by tags (all must match).

        Returns:
            List of matching templates.
        """
        self.load_templates()

        results = []
        seen = set()

        for _key, template in self._templates.items():
            # Skip version-specific duplicates
            if template.name in seen:
                continue

            # Apply filters
            if category and template.category != category:
                continue
            if provider and not template.supports_provider(provider):
                continue
            if backend and not template.supports_backend(backend):
                continue
            if tags and not all(t in template.tags for t in tags):
                continue

            results.append(template)
            seen.add(template.name)

        return results

    def list_all(self) -> list[Template]:
        """List all unique templates (latest versions)."""
        return self.find()

    def list_names(self) -> list[str]:
        """List all template names."""
        self.load_templates()
        return list({t.name for t in self._templates.values()})

    def has(self, name: str) -> bool:
        """Check if a template exists."""
        self.load_templates()
        return name in self._templates

    def unregister(self, name: str) -> bool:
        """Unregister a template by name (thread-safe)."""
        with self._load_lock:
            removed = False
            keys_to_remove = [k for k in self._templates if k == name or k.startswith(f"{name}:")]
            for key in keys_to_remove:
                del self._templates[key]
                # Also remove from manual registrations
                self._manual_templates.pop(key, None)
                removed = True

            # Reset loaded flag if registry is now empty (allows reload from loaders)
            if not self._templates:
                self._loaded = False

            return removed

    def clear(self) -> None:
        """Clear all registered templates (thread-safe)."""
        with self._load_lock:
            self._templates.clear()
            self._manual_templates.clear()
            self._loaded = False
