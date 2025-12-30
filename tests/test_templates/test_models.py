"""
Tests for templates models.

v0.9.0: Initial tests.
"""

from __future__ import annotations

import pytest

from merlya.templates.models import (
    IaCBackend,
    Template,
    TemplateBackendConfig,
    TemplateCategory,
    TemplateInstance,
    TemplateOutput,
    TemplateVariable,
    VariableType,
)


class TestTemplateCategory:
    """Test TemplateCategory enum."""

    def test_category_values(self) -> None:
        """Test category enum values."""
        assert TemplateCategory.COMPUTE.value == "compute"
        assert TemplateCategory.NETWORK.value == "network"
        assert TemplateCategory.DATABASE.value == "database"


class TestVariableType:
    """Test VariableType enum."""

    def test_variable_type_values(self) -> None:
        """Test variable type values."""
        assert VariableType.STRING.value == "string"
        assert VariableType.NUMBER.value == "number"
        assert VariableType.BOOLEAN.value == "boolean"
        assert VariableType.SECRET.value == "secret"


class TestTemplateVariable:
    """Test TemplateVariable model."""

    def test_basic_variable(self) -> None:
        """Test basic variable creation."""
        var = TemplateVariable(name="test_var")
        assert var.name == "test_var"
        assert var.type == VariableType.STRING
        assert var.required is True
        assert var.default is None

    def test_variable_with_defaults(self) -> None:
        """Test variable with provider defaults."""
        var = TemplateVariable(
            name="instance_type",
            provider_defaults={
                "aws": "t3.micro",
                "gcp": "e2-micro",
            },
        )
        assert var.get_default_for_provider("aws") == "t3.micro"
        assert var.get_default_for_provider("gcp") == "e2-micro"
        assert var.get_default_for_provider("azure") is None


class TestTemplate:
    """Test Template model."""

    @pytest.fixture
    def template(self) -> Template:
        """Create a test template."""
        return Template(
            name="test-template",
            version="1.0.0",
            category=TemplateCategory.COMPUTE,
            providers=["aws", "gcp"],
            backends=[
                TemplateBackendConfig(
                    backend=IaCBackend.TERRAFORM,
                    entry_point="main.tf",
                )
            ],
            variables=[
                TemplateVariable(name="vm_name", required=True),
                TemplateVariable(name="size", required=False, default="small"),
            ],
            outputs=[
                TemplateOutput(name="instance_id"),
            ],
        )

    def test_get_variable(self, template: Template) -> None:
        """Test getting variable by name."""
        var = template.get_variable("vm_name")
        assert var is not None
        assert var.name == "vm_name"

        assert template.get_variable("nonexistent") is None

    def test_get_required_variables(self, template: Template) -> None:
        """Test getting required variables."""
        required = template.get_required_variables()
        assert len(required) == 1
        assert required[0].name == "vm_name"

    def test_supports_provider(self, template: Template) -> None:
        """Test provider support check."""
        assert template.supports_provider("aws") is True
        assert template.supports_provider("gcp") is True
        assert template.supports_provider("azure") is False

    def test_supports_backend(self, template: Template) -> None:
        """Test backend support check."""
        assert template.supports_backend(IaCBackend.TERRAFORM) is True
        assert template.supports_backend(IaCBackend.PULUMI) is False

    def test_get_backend_config(self, template: Template) -> None:
        """Test getting backend config."""
        config = template.get_backend_config(IaCBackend.TERRAFORM)
        assert config is not None
        assert config.entry_point == "main.tf"

        assert template.get_backend_config(IaCBackend.PULUMI) is None


class TestTemplateInstance:
    """Test TemplateInstance model."""

    @pytest.fixture
    def template(self) -> Template:
        """Create a test template."""
        return Template(
            name="test",
            variables=[
                TemplateVariable(name="required_var", required=True),
                TemplateVariable(
                    name="optional_var",
                    required=False,
                    default="default_value",
                ),
                TemplateVariable(
                    name="number_var",
                    type=VariableType.NUMBER,
                    required=False,
                    min_value=1,
                    max_value=100,
                ),
                TemplateVariable(
                    name="choice_var",
                    required=False,
                    allowed_values=["a", "b", "c"],
                ),
            ],
        )

    def test_get_variable(self, template: Template) -> None:
        """Test getting variable values."""
        instance = TemplateInstance(
            template=template,
            variables={"required_var": "test_value"},
            provider="aws",
        )

        assert instance.get_variable("required_var") == "test_value"
        assert instance.get_variable("optional_var") == "default_value"

    def test_validate_missing_required(self, template: Template) -> None:
        """Test validation of missing required variable."""
        instance = TemplateInstance(
            template=template,
            variables={},
            provider="aws",
        )

        errors = instance.validate_variables()
        assert len(errors) == 1
        assert "required_var" in errors[0]

    def test_validate_number_range(self, template: Template) -> None:
        """Test validation of number range."""
        instance = TemplateInstance(
            template=template,
            variables={"required_var": "x", "number_var": 200},
            provider="aws",
        )

        errors = instance.validate_variables()
        assert any("number_var" in e and "100" in e for e in errors)

    def test_validate_allowed_values(self, template: Template) -> None:
        """Test validation of allowed values."""
        instance = TemplateInstance(
            template=template,
            variables={"required_var": "x", "choice_var": "invalid"},
            provider="aws",
        )

        errors = instance.validate_variables()
        assert any("choice_var" in e for e in errors)

    def test_validate_success(self, template: Template) -> None:
        """Test successful validation."""
        instance = TemplateInstance(
            template=template,
            variables={
                "required_var": "value",
                "number_var": 50,
                "choice_var": "a",
            },
            provider="aws",
        )

        errors = instance.validate_variables()
        assert len(errors) == 0
