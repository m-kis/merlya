"""
Merlya Templates - Data models.

Models for template definitions, variables, and instances.

v0.9.0: Initial implementation.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path  # noqa: TC003 - Required at runtime for Pydantic
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field


class TemplateCategory(str, Enum):
    """Categories for organizing templates."""

    COMPUTE = "compute"
    NETWORK = "network"
    STORAGE = "storage"
    DATABASE = "database"
    SECURITY = "security"
    CONTAINER = "container"
    SERVERLESS = "serverless"
    OTHER = "other"


class VariableType(str, Enum):
    """Types for template variables."""

    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    LIST = "list"
    MAP = "map"
    SECRET = "secret"


class IaCBackend(str, Enum):
    """Supported IaC backends for templates."""

    TERRAFORM = "terraform"
    PULUMI = "pulumi"
    ANSIBLE = "ansible"
    CLOUDFORMATION = "cloudformation"


class TemplateVariable(BaseModel):
    """Definition of a template variable."""

    name: str
    type: VariableType = VariableType.STRING
    description: str = ""
    required: bool = True
    default: Any = None
    validation_regex: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    allowed_values: list[Any] | None = None
    provider_defaults: dict[str, Any] = Field(default_factory=dict)

    def get_default_for_provider(self, provider: str) -> Any:
        """Get default value for a specific provider."""
        return self.provider_defaults.get(provider, self.default)


class TemplateOutput(BaseModel):
    """Definition of a template output."""

    name: str
    description: str = ""
    value_path: str = ""
    sensitive: bool = False


class TemplateBackendConfig(BaseModel):
    """Configuration for a specific IaC backend."""

    backend: IaCBackend
    entry_point: str
    files: list[str] = Field(default_factory=list)


class Template(BaseModel):
    """Template definition."""

    name: str
    version: str = "1.0.0"
    description: str = ""
    category: TemplateCategory = TemplateCategory.OTHER
    providers: list[str] = Field(default_factory=list)
    backends: list[TemplateBackendConfig] = Field(default_factory=list)
    variables: list[TemplateVariable] = Field(default_factory=list)
    outputs: list[TemplateOutput] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    author: str = ""
    source_path: Path | None = None

    def get_variable(self, name: str) -> TemplateVariable | None:
        """Get variable by name."""
        for var in self.variables:
            if var.name == name:
                return var
        return None

    def get_required_variables(self) -> list[TemplateVariable]:
        """Get all required variables without defaults."""
        return [v for v in self.variables if v.required and v.default is None]

    def supports_provider(self, provider: str) -> bool:
        """Check if template supports a provider."""
        return not self.providers or provider.lower() in [p.lower() for p in self.providers]

    def supports_backend(self, backend: IaCBackend) -> bool:
        """Check if template supports a backend."""
        return any(b.backend == backend for b in self.backends)

    def get_backend_config(self, backend: IaCBackend) -> TemplateBackendConfig | None:
        """Get configuration for a specific backend."""
        for b in self.backends:
            if b.backend == backend:
                return b
        return None


class TemplateInstance(BaseModel):
    """An instantiated template with resolved variables."""

    template: Template
    variables: dict[str, Any] = Field(default_factory=dict)
    provider: str = ""
    backend: IaCBackend = IaCBackend.TERRAFORM
    output_path: Path | None = None
    rendered_files: dict[str, str] = Field(default_factory=dict)

    def get_variable(self, name: str) -> Any:
        """Get resolved variable value."""
        if name in self.variables:
            return self.variables[name]
        var = self.template.get_variable(name)
        if var:
            return var.get_default_for_provider(self.provider)
        return None

    def validate_variables(self) -> list[str]:
        """Validate all variables are set correctly.

        Returns:
            List of validation errors (empty if valid).
        """
        errors = []
        for var in self.template.variables:
            value = self.get_variable(var.name)

            # Check required
            if var.required and value is None:
                errors.append(f"Required variable '{var.name}' is not set")
                continue

            if value is None:
                continue

            # Type validation
            if var.type == VariableType.NUMBER:
                if not isinstance(value, int | float):
                    errors.append(f"Variable '{var.name}' must be a number")
                elif var.min_value is not None and value < var.min_value:
                    errors.append(f"Variable '{var.name}' must be >= {var.min_value}")
                elif var.max_value is not None and value > var.max_value:
                    errors.append(f"Variable '{var.name}' must be <= {var.max_value}")

            elif var.type == VariableType.BOOLEAN:
                if not isinstance(value, bool):
                    errors.append(f"Variable '{var.name}' must be a boolean")

            elif var.type == VariableType.LIST:
                if not isinstance(value, list):
                    errors.append(f"Variable '{var.name}' must be a list")

            elif var.type == VariableType.MAP and not isinstance(value, dict):
                errors.append(f"Variable '{var.name}' must be a map/dict")

            # Allowed values check
            if var.allowed_values and value not in var.allowed_values:
                errors.append(f"Variable '{var.name}' must be one of: {var.allowed_values}")

            # Regex validation for string variables
            if var.validation_regex and isinstance(value, str):
                try:
                    if not re.match(var.validation_regex, value):
                        errors.append(
                            f"Variable '{var.name}' does not match pattern: {var.validation_regex}"
                        )
                except re.error as e:
                    logger.warning(f"Invalid regex pattern for '{var.name}': {e}")
                    errors.append(f"Invalid regex pattern for variable '{var.name}': {e}")

        return errors


class TemplateError(Exception):
    """Base exception for template errors."""

    pass


class TemplateNotFoundError(TemplateError):
    """Template not found."""

    pass


class TemplateParseError(TemplateError):
    """Template parsing failed."""

    pass


class TemplateValidationError(TemplateError):
    """Template validation failed."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


class TemplateRenderError(TemplateError):
    """Template rendering failed."""

    pass
