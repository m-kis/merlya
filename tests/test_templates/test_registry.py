"""
Tests for template registry.

v0.9.0: Initial tests.
"""

from __future__ import annotations

import pytest

from merlya.templates.models import (
    IaCBackend,
    Template,
    TemplateBackendConfig,
    TemplateCategory,
    TemplateNotFoundError,
)
from merlya.templates.registry import TemplateRegistry


class TestTemplateRegistry:
    """Test TemplateRegistry."""

    @pytest.fixture(autouse=True)
    def reset_registry(self) -> None:
        """Reset singleton before each test."""
        TemplateRegistry.reset_instance()

    @pytest.fixture
    def registry(self) -> TemplateRegistry:
        """Get registry instance."""
        return TemplateRegistry.get_instance()

    @pytest.fixture
    def sample_template(self) -> Template:
        """Create a sample template."""
        return Template(
            name="test-template",
            version="1.0.0",
            category=TemplateCategory.COMPUTE,
            providers=["aws"],
            backends=[
                TemplateBackendConfig(
                    backend=IaCBackend.TERRAFORM,
                    entry_point="main.tf",
                )
            ],
            tags=["test", "compute"],
        )

    def test_singleton(self) -> None:
        """Test singleton pattern."""
        reg1 = TemplateRegistry.get_instance()
        reg2 = TemplateRegistry.get_instance()
        assert reg1 is reg2

    def test_reset_instance(self) -> None:
        """Test reset creates new instance."""
        reg1 = TemplateRegistry.get_instance()
        TemplateRegistry.reset_instance()
        reg2 = TemplateRegistry.get_instance()
        assert reg1 is not reg2

    def test_register_and_get(self, registry: TemplateRegistry, sample_template: Template) -> None:
        """Test registering and retrieving a template."""
        registry.register(sample_template)

        # Get by name
        result = registry.get("test-template")
        assert result.name == "test-template"

        # Get by name:version
        result = registry.get("test-template", "1.0.0")
        assert result.version == "1.0.0"

    def test_get_not_found(self, registry: TemplateRegistry) -> None:
        """Test getting non-existent template."""
        with pytest.raises(TemplateNotFoundError):
            registry.get("nonexistent")

    def test_has(self, registry: TemplateRegistry, sample_template: Template) -> None:
        """Test checking template existence."""
        assert registry.has("test-template") is False

        registry.register(sample_template)
        assert registry.has("test-template") is True

    def test_find_by_category(self, registry: TemplateRegistry, sample_template: Template) -> None:
        """Test finding templates by category."""
        registry.register(sample_template)

        results = registry.find(category=TemplateCategory.COMPUTE)
        assert len(results) == 1
        assert results[0].name == "test-template"

        results = registry.find(category=TemplateCategory.NETWORK)
        assert len(results) == 0

    def test_find_by_provider(self, registry: TemplateRegistry, sample_template: Template) -> None:
        """Test finding templates by provider."""
        registry.register(sample_template)

        results = registry.find(provider="aws")
        assert len(results) == 1

        results = registry.find(provider="gcp")
        assert len(results) == 0

    def test_find_by_backend(self, registry: TemplateRegistry, sample_template: Template) -> None:
        """Test finding templates by backend."""
        registry.register(sample_template)

        results = registry.find(backend=IaCBackend.TERRAFORM)
        assert len(results) == 1

        results = registry.find(backend=IaCBackend.PULUMI)
        assert len(results) == 0

    def test_find_by_tags(self, registry: TemplateRegistry, sample_template: Template) -> None:
        """Test finding templates by tags."""
        registry.register(sample_template)

        results = registry.find(tags=["test"])
        assert len(results) == 1

        results = registry.find(tags=["test", "compute"])
        assert len(results) == 1

        results = registry.find(tags=["nonexistent"])
        assert len(results) == 0

    def test_list_all(self, registry: TemplateRegistry, sample_template: Template) -> None:
        """Test listing all templates."""
        registry.register(sample_template)

        templates = registry.list_all()
        assert len(templates) == 1

    def test_list_names(self, registry: TemplateRegistry, sample_template: Template) -> None:
        """Test listing template names."""
        registry.register(sample_template)

        names = registry.list_names()
        assert "test-template" in names

    def test_unregister(self, registry: TemplateRegistry, sample_template: Template) -> None:
        """Test unregistering a template."""
        registry.register(sample_template)
        assert registry.has("test-template")

        result = registry.unregister("test-template")
        assert result is True
        assert registry.has("test-template") is False

    def test_clear(self, registry: TemplateRegistry, sample_template: Template) -> None:
        """Test clearing all templates."""
        registry.register(sample_template)
        registry.clear()

        assert len(registry.list_all()) == 0

    def test_version_comparison_highest_wins(self, registry: TemplateRegistry) -> None:
        """Test that unversioned key points to highest version."""
        # Register v1.0.0 first
        v1 = Template(
            name="versioned-template",
            version="1.0.0",
            category=TemplateCategory.COMPUTE,
            providers=["aws"],
        )
        registry.register(v1)

        # Register v2.0.0
        v2 = Template(
            name="versioned-template",
            version="2.0.0",
            category=TemplateCategory.COMPUTE,
            providers=["aws"],
        )
        registry.register(v2)

        # Unversioned lookup should return v2.0.0 (highest)
        result = registry.get("versioned-template")
        assert result.version == "2.0.0"

        # Now register v1.5.0 (lower than current highest)
        v15 = Template(
            name="versioned-template",
            version="1.5.0",
            category=TemplateCategory.COMPUTE,
            providers=["aws"],
        )
        registry.register(v15)

        # Unversioned lookup should still return v2.0.0
        result = registry.get("versioned-template")
        assert result.version == "2.0.0"

    def test_manual_registration_preserved_on_force_reload(
        self, registry: TemplateRegistry, sample_template: Template
    ) -> None:
        """Test that manual registrations are preserved when force reloading."""
        # Manually register a template
        registry.register(sample_template)
        assert registry.has("test-template")

        # Force reload (should preserve manual registrations)
        registry.load_templates(force=True)

        # Manual registration should still exist
        assert registry.has("test-template")

    def test_unregister_resets_loaded_when_empty(
        self, registry: TemplateRegistry, sample_template: Template
    ) -> None:
        """Test that _loaded is reset when registry becomes empty."""
        registry.register(sample_template)
        assert registry._loaded is True

        # Unregister the only template
        registry.unregister("test-template")

        # _loaded should be reset to False
        assert registry._loaded is False

    def test_reset_instance_clears_state(self) -> None:
        """Test that reset_instance clears the existing instance state."""
        reg1 = TemplateRegistry.get_instance()
        template = Template(
            name="temp-template",
            version="1.0.0",
            category=TemplateCategory.COMPUTE,
            providers=["aws"],
        )
        reg1.register(template)

        # Reset should clear state
        TemplateRegistry.reset_instance()

        # New instance should be empty
        reg2 = TemplateRegistry.get_instance()
        assert reg2.has("temp-template") is False
