"""
Tests for template loaders.

v0.9.0: Initial tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from merlya.templates.loaders.embedded import EmbeddedTemplateLoader
from merlya.templates.loaders.filesystem import FilesystemTemplateLoader
from merlya.templates.models import IaCBackend, TemplateCategory, TemplateParseError


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

    def test_load_rejects_path_traversal(self, temp_template_dir: Path) -> None:
        """Reject attempts to escape the configured template base directory."""
        base_dir = temp_template_dir
        outside_dir = base_dir.parent / "sensitive-template"
        outside_dir.mkdir()

        # This is outside the base_dir and should never be readable via load().
        (outside_dir / "template.yaml").write_text(
            """
name: sensitive-template
version: "1.0.0"
description: Should not be loadable
category: compute
providers:
  - aws
backends:
  - backend: terraform
    entry_point: main.tf
""",
            encoding="utf-8",
        )

        loader = FilesystemTemplateLoader(base_dir)
        assert loader.load("../sensitive-template") is None
        assert loader.load(str(outside_dir)) is None

    def test_load_from_nonexistent_dir(self, tmp_path: Path) -> None:
        """Test loading from non-existent directory."""
        loader = FilesystemTemplateLoader(tmp_path / "nonexistent")
        templates = loader.load_all()
        assert templates == []

    def test_parse_template_yaml_rejects_empty_yaml(self, tmp_path: Path) -> None:
        loader = FilesystemTemplateLoader(tmp_path)

        with pytest.raises(TemplateParseError, match=r"Template YAML is empty"):
            loader._parse_template_yaml("", source_path=tmp_path / "template")

    def test_parse_template_yaml_rejects_non_mapping_root(self, tmp_path: Path) -> None:
        loader = FilesystemTemplateLoader(tmp_path)

        with pytest.raises(TemplateParseError, match=r"root must be a mapping"):
            loader._parse_template_yaml("- name: test", source_path=tmp_path / "template")

    def test_parse_template_yaml_rejects_malformed_yaml(self, tmp_path: Path) -> None:
        loader = FilesystemTemplateLoader(tmp_path)

        with pytest.raises(TemplateParseError, match=r"Failed to parse template YAML"):
            loader._parse_template_yaml("name: [", source_path=tmp_path / "template")

    def test_parse_template_yaml_rejects_non_string_keys(self, tmp_path: Path) -> None:
        loader = FilesystemTemplateLoader(tmp_path)

        with pytest.raises(TemplateParseError, match=r"root keys must be strings"):
            loader._parse_template_yaml("1: a", source_path=tmp_path / "template")

    def test_parse_template_yaml_rejects_variable_missing_name(self, tmp_path: Path) -> None:
        loader = FilesystemTemplateLoader(tmp_path)

        content = """
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
  - type: string
"""

        with pytest.raises(TemplateParseError, match=r"missing required 'name'"):
            loader._parse_template_yaml(content, source_path=tmp_path / "template")


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
