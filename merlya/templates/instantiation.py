"""
Merlya Templates - Instantiation.

Template rendering with Jinja2.

v0.9.0: Initial implementation.
v0.9.1: Context manager protocol, improved backend handling.
"""

from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from loguru import logger

from merlya.templates.models import (
    IaCBackend,
    Template,
    TemplateInstance,
    TemplateRenderError,
    TemplateValidationError,
)

if TYPE_CHECKING:
    from types import TracebackType


class TemplateInstantiator:
    """
    Render templates with variable substitution.

    Can be used as a context manager for automatic cleanup:

        with TemplateInstantiator() as instantiator:
            instance = instantiator.instantiate(template, variables, provider)
            # Use instance...
        # Temporary directories are automatically cleaned up
    """

    def __init__(self) -> None:
        """Initialize the instantiator."""
        self._temp_dirs: list[Path] = []

    def __enter__(self) -> TemplateInstantiator:
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit with automatic cleanup."""
        self.cleanup()

    def __del__(self) -> None:
        """Clean up on deletion (safety net)."""
        with contextlib.suppress(Exception):
            self.cleanup()

    def instantiate(
        self,
        template: Template,
        variables: dict[str, Any],
        provider: str,
        backend: IaCBackend = IaCBackend.TERRAFORM,
        output_path: Path | None = None,
    ) -> TemplateInstance:
        """
        Instantiate a template with variables.

        Args:
            template: The template to instantiate.
            variables: Variable values.
            provider: Target cloud provider.
            backend: IaC backend to use.
            output_path: Output directory (created if None).

        Returns:
            TemplateInstance with rendered files.

        Raises:
            TemplateValidationError: If variables are invalid.
            TemplateRenderError: If rendering fails.
        """
        # Create instance
        instance = TemplateInstance(
            template=template,
            variables=variables,
            provider=provider,
            backend=backend,
        )

        # Validate variables
        errors = instance.validate_variables()
        if errors:
            raise TemplateValidationError(
                f"Variable validation failed for template '{template.name}'",
                errors=errors,
            )

        # Check provider support
        if not template.supports_provider(provider):
            raise TemplateValidationError(
                f"Template '{template.name}' does not support provider '{provider}'"
            )

        # Check backend support
        if not template.supports_backend(backend):
            raise TemplateValidationError(
                f"Template '{template.name}' does not support backend '{backend.value}'"
            )

        # Get backend config
        backend_config = template.get_backend_config(backend)
        if not backend_config:
            raise TemplateValidationError(
                f"No backend config for '{backend.value}' in template '{template.name}'"
            )

        # Create output directory
        if output_path is None:
            output_path = Path(tempfile.mkdtemp(prefix=f"merlya_{template.name}_"))
            self._temp_dirs.append(output_path)

        instance.output_path = output_path

        # Render templates
        try:
            rendered_files = self._render_template_files(
                template=template,
                backend_config=backend_config,
                backend=backend,
                variables=self._build_render_context(instance),
                output_path=output_path,
            )
            instance.rendered_files = rendered_files
        except Exception as e:
            raise TemplateRenderError(f"Failed to render template: {e}") from e

        logger.info(f"Instantiated template '{template.name}' at {output_path}")
        return instance

    def _build_render_context(self, instance: TemplateInstance) -> dict[str, Any]:
        """Build the Jinja2 render context."""
        context: dict[str, Any] = {
            "provider": instance.provider,
            "backend": instance.backend.value,
            "template_name": instance.template.name,
            "template_version": instance.template.version,
        }

        # Add all variables with defaults (include None so templates can check with {% if var %})
        for var in instance.template.variables:
            value = instance.get_variable(var.name)
            context[var.name] = value

        # Add explicit variables (may override defaults)
        context.update(instance.variables)

        return context

    def _render_template_files(
        self,
        template: Template,
        backend_config: Any,
        backend: IaCBackend,
        variables: dict[str, Any],
        output_path: Path,
    ) -> dict[str, str]:
        """Render all template files."""
        rendered: dict[str, str] = {}

        if not template.source_path:
            logger.warning(f"Template '{template.name}' has no source path")
            return rendered

        # Set up Jinja2 environment
        template_dir = template.source_path
        if backend == IaCBackend.TERRAFORM:
            template_dir = template.source_path / "terraform"

        if not template_dir.exists():
            template_dir = template.source_path

        # Note: autoescape is disabled intentionally for IaC templates.
        # Terraform/Pulumi/Ansible configs are not HTML and don't need HTML escaping.
        # Escaping would break valid HCL/YAML syntax in generated infrastructure code.
        env = Environment(  # nosec B701 - IaC templates require raw output, not HTML escaping
            loader=FileSystemLoader(str(template_dir)),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
            autoescape=False,
        )

        # Get files to render
        files_to_render = backend_config.files or []

        # If no files specified, find all .j2 files
        if not files_to_render and template_dir.exists():
            files_to_render = [str(f.relative_to(template_dir)) for f in template_dir.rglob("*.j2")]

        # Also include entry point if it's a .j2 file
        if (
            backend_config.entry_point.endswith(".j2")
            and backend_config.entry_point not in files_to_render
        ):
            files_to_render.append(backend_config.entry_point)

        # Render each file
        for file_path in files_to_render:
            try:
                jinja_template = env.get_template(file_path)
                rendered_content = jinja_template.render(**variables)

                # Output file name (remove .j2 extension)
                output_name = file_path[:-3] if file_path.endswith(".j2") else file_path
                output_file = output_path / output_name

                # Create parent directories
                output_file.parent.mkdir(parents=True, exist_ok=True)

                # Write rendered content
                output_file.write_text(rendered_content)
                rendered[output_name] = rendered_content

                logger.debug(f"Rendered {file_path} -> {output_file}")

            except Exception as e:
                logger.error(f"Failed to render {file_path}: {e}")
                raise

        return rendered

    def cleanup(self) -> None:
        """Clean up temporary directories."""
        import shutil

        for temp_dir in self._temp_dirs:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
        self._temp_dirs.clear()
