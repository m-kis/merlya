"""
Tests for template loaders.

v0.9.0: Initial tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from merlya.templates.loaders.embedded import EmbeddedTemplateLoader
from merlya.templates.loaders.filesystem import FilesystemTemplateLoader
from merlya.templates.models import IaCBackend, TemplateCategory


class TestFilesystemTemplateLoader:
    """Test FilesystemTemplateLoader."""

    @pytest.fixture
    def temp_template_dir(self, tmp_path: Path) -> Path:
        """Create a temporary template directory."""
        template_dir = tmp_path / "test-template"
        template_dir.mkdir()

        # Create template.yaml
        (template_dir / "template.yaml").write_text("""
name: test-template
version: "1.0.0"
description: Test template
category: compute
providers:
  - aws
backends:
  - backend: terraform
    entry_point: main.tf
variables:
  - name: vm_name
    type: string
    required: true
outputs:
  - name: instance_id
    value_path: id
""")
        return tmp_path

    def test_load_all(self, temp_template_dir: Path) -> None:
        """Test loading all templates."""
        loader = FilesystemTemplateLoader(temp_template_dir)
        templates = loader.load_all()

        assert len(templates) == 1
        assert templates[0].name == "test-template"
        assert templates[0].category == TemplateCategory.COMPUTE

    def test_load_specific(self, temp_template_dir: Path) -> None:
        """Test loading a specific template."""
        loader = FilesystemTemplateLoader(temp_template_dir)
        template = loader.load("test-template")

        assert template is not None
        assert template.name == "test-template"
        assert template.supports_backend(IaCBackend.TERRAFORM)

    def test_load_nonexistent(self, temp_template_dir: Path) -> None:
        """Test loading non-existent template."""
        loader = FilesystemTemplateLoader(temp_template_dir)
        template = loader.load("nonexistent")
        assert template is None

    def test_load_from_nonexistent_dir(self, tmp_path: Path) -> None:
        """Test loading from non-existent directory."""
        loader = FilesystemTemplateLoader(tmp_path / "nonexistent")
        templates = loader.load_all()
        assert templates == []


class TestEmbeddedTemplateLoader:
    """Test EmbeddedTemplateLoader."""

    def test_load_builtin_templates(self) -> None:
        """Test loading built-in templates."""
        loader = EmbeddedTemplateLoader()
        templates = loader.load_all()

        # Should have at least basic-vm
        assert len(templates) >= 1

        template_names = [t.name for t in templates]
        assert "basic-vm" in template_names

    def test_load_basic_vm(self) -> None:
        """Test loading the basic-vm template."""
        loader = EmbeddedTemplateLoader()
        template = loader.load("basic-vm")

        assert template is not None
        assert template.name == "basic-vm"
        assert template.category == TemplateCategory.COMPUTE
        assert template.supports_provider("aws")
        assert template.supports_provider("gcp")
        assert template.supports_backend(IaCBackend.TERRAFORM)

        # Check variables
        assert template.get_variable("vm_name") is not None
        assert template.get_variable("instance_type") is not None
        assert template.get_variable("image_id") is not None
