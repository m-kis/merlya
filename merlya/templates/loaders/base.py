"""
Merlya Templates - Base Loader.

Abstract base class for template loaders.

v0.9.0: Initial implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from merlya.templates.models import (
    IaCBackend,
    Template,
    TemplateBackendConfig,
    TemplateCategory,
    TemplateOutput,
    TemplateVariable,
    VariableType,
)


class AbstractTemplateLoader(ABC):
    """Abstract base class for template loaders."""

    @abstractmethod
    def load_all(self) -> list[Template]:
        """
        Load all templates from this source.

        Returns:
            List of loaded templates.
        """
        ...

    @abstractmethod
    def load(self, name: str) -> Template | None:
        """
        Load a specific template by name.

        Args:
            name: Template name.

        Returns:
            The template or None if not found.
        """
        ...

    def _parse_template_yaml(self, content: str, source_path: Path | None = None) -> Template:
        """
        Parse a template YAML file.

        Args:
            content: YAML content.
            source_path: Path to the template directory.

        Returns:
            Parsed Template object.
        """
        data = yaml.safe_load(content)
        return self._dict_to_template(data, source_path)

    def _dict_to_template(self, data: dict[str, Any], source_path: Path | None = None) -> Template:
        """
        Convert a dictionary to a Template object.

        Args:
            data: Dictionary from YAML.
            source_path: Path to the template directory.

        Returns:
            Template object.
        """
        # Parse variables
        variables = []
        for var_data in data.get("variables", []):
            var_type = var_data.get("type", "string")
            try:
                var_type_enum = VariableType(var_type)
            except ValueError:
                logger.warning(f"Unknown variable type: {var_type}, using string")
                var_type_enum = VariableType.STRING

            variables.append(
                TemplateVariable(
                    name=var_data["name"],
                    type=var_type_enum,
                    description=var_data.get("description", ""),
                    required=var_data.get("required", True),
                    default=var_data.get("default"),
                    validation_regex=var_data.get("validation_regex"),
                    min_value=var_data.get("min_value"),
                    max_value=var_data.get("max_value"),
                    allowed_values=var_data.get("allowed_values"),
                    provider_defaults=var_data.get("provider_defaults", {}),
                )
            )

        # Parse outputs
        outputs = []
        for out_data in data.get("outputs", []):
            outputs.append(
                TemplateOutput(
                    name=out_data["name"],
                    description=out_data.get("description", ""),
                    value_path=out_data.get("value_path", ""),
                    sensitive=out_data.get("sensitive", False),
                )
            )

        # Parse backends
        backends = []
        for backend_data in data.get("backends", []):
            backend_type = backend_data.get("backend", "terraform")
            try:
                backend_enum = IaCBackend(backend_type)
            except ValueError:
                logger.warning(f"Unknown backend: {backend_type}, skipping")
                continue

            backends.append(
                TemplateBackendConfig(
                    backend=backend_enum,
                    entry_point=backend_data.get("entry_point", "main.tf"),
                    files=backend_data.get("files", []),
                )
            )

        # Parse category
        category_str = data.get("category", "other")
        try:
            category = TemplateCategory(category_str)
        except ValueError:
            logger.warning(f"Unknown category: {category_str}, using 'other'")
            category = TemplateCategory.OTHER

        return Template(
            name=data["name"],
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            category=category,
            providers=data.get("providers", []),
            backends=backends,
            variables=variables,
            outputs=outputs,
            tags=data.get("tags", []),
            author=data.get("author", ""),
            source_path=source_path,
        )
