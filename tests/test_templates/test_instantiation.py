"""
Tests for template instantiation.

v0.9.0: Initial tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from merlya.templates.instantiation import TemplateInstantiator
from merlya.templates.loaders.embedded import EmbeddedTemplateLoader
from merlya.templates.models import (
    IaCBackend,
    Template,
    TemplateBackendConfig,
    TemplateCategory,
    TemplateValidationError,
    TemplateVariable,
)


class TestTemplateInstantiator:
    """Test TemplateInstantiator."""

    @pytest.fixture
    def instantiator(self) -> TemplateInstantiator:
        """Create an instantiator."""
        return TemplateInstantiator()

    @pytest.fixture
    def basic_template(self, tmp_path: Path) -> Template:
        """Create a basic template with files."""
        # Create template directory
        template_dir = tmp_path / "test-template" / "terraform"
        template_dir.mkdir(parents=True)

        # Create a simple template file
        (template_dir / "main.tf.j2").write_text("""
# VM: {{ vm_name }}
# Provider: {{ provider }}
resource "test" "{{ vm_name }}" {
  name = "{{ vm_name }}"
  size = "{{ size }}"
}
""")

        return Template(
            name="test-template",
            category=TemplateCategory.COMPUTE,
            providers=["aws", "gcp"],
            backends=[
                TemplateBackendConfig(
                    backend=IaCBackend.TERRAFORM,
                    entry_point="main.tf.j2",
                    files=["main.tf.j2"],
                )
            ],
            variables=[
                TemplateVariable(name="vm_name", required=True),
                TemplateVariable(name="size", required=False, default="small"),
            ],
            source_path=tmp_path / "test-template",
        )

    def test_instantiate_success(
        self, instantiator: TemplateInstantiator, basic_template: Template
    ) -> None:
        """Test successful instantiation."""
        instance = instantiator.instantiate(
            template=basic_template,
            variables={"vm_name": "my-vm"},
            provider="aws",
        )

        assert instance.template == basic_template
        assert instance.provider == "aws"
        assert instance.output_path is not None
        assert "main.tf" in instance.rendered_files

        # Check rendered content
        content = instance.rendered_files["main.tf"]
        assert "my-vm" in content
        assert "aws" in content
        assert "small" in content  # default value

        # Cleanup
        instantiator.cleanup()

    def test_instantiate_with_output_path(
        self, instantiator: TemplateInstantiator, basic_template: Template, tmp_path: Path
    ) -> None:
        """Test instantiation with custom output path."""
        output_path = tmp_path / "output"
        output_path.mkdir()

        instance = instantiator.instantiate(
            template=basic_template,
            variables={"vm_name": "test"},
            provider="aws",
            output_path=output_path,
        )

        assert instance.output_path == output_path
        assert (output_path / "main.tf").exists()

    def test_instantiate_missing_required(
        self, instantiator: TemplateInstantiator, basic_template: Template
    ) -> None:
        """Test validation error for missing required variable."""
        with pytest.raises(TemplateValidationError) as exc_info:
            instantiator.instantiate(
                template=basic_template,
                variables={},  # Missing vm_name
                provider="aws",
            )

        assert "validation failed" in str(exc_info.value).lower()

    def test_instantiate_unsupported_provider(
        self, instantiator: TemplateInstantiator, basic_template: Template
    ) -> None:
        """Test error for unsupported provider."""
        with pytest.raises(TemplateValidationError) as exc_info:
            instantiator.instantiate(
                template=basic_template,
                variables={"vm_name": "test"},
                provider="unsupported",
            )

        assert "unsupported" in str(exc_info.value).lower()

    def test_instantiate_unsupported_backend(
        self, instantiator: TemplateInstantiator, basic_template: Template
    ) -> None:
        """Test error for unsupported backend."""
        with pytest.raises(TemplateValidationError) as exc_info:
            instantiator.instantiate(
                template=basic_template,
                variables={"vm_name": "test"},
                provider="aws",
                backend=IaCBackend.PULUMI,
            )

        assert "pulumi" in str(exc_info.value).lower()


class TestBuiltinTemplateInstantiation:
    """Test instantiation of built-in templates."""

    @pytest.fixture
    def instantiator(self) -> TemplateInstantiator:
        """Create an instantiator."""
        return TemplateInstantiator()

    @pytest.fixture
    def basic_vm_template(self) -> Template:
        """Load the basic-vm template."""
        loader = EmbeddedTemplateLoader()
        template = loader.load("basic-vm")
        assert template is not None
        return template

    def test_instantiate_basic_vm_aws(
        self, instantiator: TemplateInstantiator, basic_vm_template: Template
    ) -> None:
        """Test instantiating basic-vm for AWS."""
        instance = instantiator.instantiate(
            template=basic_vm_template,
            variables={
                "vm_name": "web-server",
                "image_id": "ami-12345",
                "tags": {"env": "test"},
            },
            provider="aws",
        )

        assert instance.output_path is not None

        # Check main.tf was rendered
        assert "main.tf" in instance.rendered_files
        content = instance.rendered_files["main.tf"]
        assert "web-server" in content
        assert "ami-12345" in content
        assert "aws" in content.lower()

        instantiator.cleanup()

    def test_instantiate_basic_vm_gcp(
        self, instantiator: TemplateInstantiator, basic_vm_template: Template
    ) -> None:
        """Test instantiating basic-vm for GCP."""
        instance = instantiator.instantiate(
            template=basic_vm_template,
            variables={
                "vm_name": "compute-instance",
                "image_id": "debian-cloud/debian-11",
            },
            provider="gcp",
        )

        content = instance.rendered_files["main.tf"]
        assert "compute-instance" in content
        assert "google" in content.lower() or "gcp" in content.lower()

        instantiator.cleanup()
