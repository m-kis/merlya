"""
Merlya Templates - Filesystem Loader.

Load templates from local filesystem directories.

v0.9.0: Initial implementation.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from merlya.templates.loaders.base import AbstractTemplateLoader

if TYPE_CHECKING:
    from merlya.templates.models import Template


class FilesystemTemplateLoader(AbstractTemplateLoader):
    """Load templates from a filesystem directory."""

    TEMPLATE_FILE = "template.yaml"

    def __init__(self, base_path: Path | str) -> None:
        """
        Initialize the filesystem loader.

        Args:
            base_path: Base directory containing template subdirectories.
        """
        self._base_path = Path(base_path)

    def load_all(self) -> list[Template]:
        """Load all templates from the base directory."""
        templates: list[Template] = []

        if not self._base_path.exists():
            logger.warning(f"Template directory does not exist: {self._base_path}")
            return templates

        # Each subdirectory is a template
        for template_dir in self._base_path.iterdir():
            if not template_dir.is_dir():
                continue

            template = self._load_from_dir(template_dir)
            if template:
                templates.append(template)

        return templates

    def load(self, name: str) -> Template | None:
        """Load a specific template by name."""
        base_path_resolved = self._base_path.resolve()
        template_dir_resolved = (self._base_path / name).resolve()

        # Prevent path traversal (including absolute paths and symlinks escaping base_path).
        if not template_dir_resolved.is_relative_to(base_path_resolved):
            logger.warning(f"Invalid template name (path traversal attempt): {name}")
            return None

        return self._load_from_dir(template_dir_resolved)

    def _load_from_dir(self, template_dir: Path) -> Template | None:
        """Load a template from a directory."""
        template_file = template_dir / self.TEMPLATE_FILE

        if not template_file.exists():
            logger.debug(f"No template.yaml in {template_dir}")
            return None

        try:
            content = template_file.read_text(encoding="utf-8")
            template = self._parse_template_yaml(content, source_path=template_dir)
            logger.debug(f"Loaded template: {template.name} from {template_dir}")
            return template
        except Exception as e:
            logger.warning(f"Failed to load template from {template_dir}: {e}")
            return None
