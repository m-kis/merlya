"""
Merlya Templates - Template Registry.

Central registry for discovering and managing templates.

v0.9.0: Initial implementation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

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

    Singleton pattern with reset_instance() for testing.
    """

    _instance: TemplateRegistry | None = None

    def __init__(self) -> None:
        """Initialize the registry."""
        self._templates: dict[str, Template] = {}
        self._loaders: list[AbstractTemplateLoader] = []
        self._loaded = False

    @classmethod
    def get_instance(cls) -> TemplateRegistry:
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (for testing)."""
        cls._instance = None

    def register_loader(self, loader: AbstractTemplateLoader) -> None:
        """Register a template loader."""
        self._loaders.append(loader)
        self._loaded = False  # Force reload on next access

    def load_templates(self, force: bool = False) -> None:
        """Load templates from all registered loaders."""
        if self._loaded and not force:
            return

        self._templates.clear()

        for loader in self._loaders:
            try:
                templates = loader.load_all()
                for template in templates:
                    self._register(template)
            except Exception as e:
                logger.warning(f"Failed to load templates from {loader}: {e}")

        self._loaded = True
        logger.debug(f"Loaded {len(self._templates)} templates")

    def _register(self, template: Template) -> None:
        """Register a single template."""
        key = f"{template.name}:{template.version}"
        if key in self._templates:
            logger.warning(f"Template {key} already registered, overwriting")
        self._templates[key] = template

        # Also register without version for latest lookup
        self._templates[template.name] = template

    def register(self, template: Template) -> None:
        """Manually register a template."""
        self._register(template)
        # Mark as loaded so load_templates() doesn't clear manual registrations
        self._loaded = True

    def get(self, name: str, version: str | None = None) -> Template:
        """
        Get a template by name and optional version.

        Args:
            name: Template name.
            version: Optional version string.

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
        """Unregister a template by name."""
        removed = False
        keys_to_remove = [k for k in self._templates if k == name or k.startswith(f"{name}:")]
        for key in keys_to_remove:
            del self._templates[key]
            removed = True
        return removed

    def clear(self) -> None:
        """Clear all registered templates."""
        self._templates.clear()
        self._loaded = False
