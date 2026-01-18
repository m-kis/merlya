"""
Merlya Templates - Embedded Loader.

Load built-in templates bundled with Merlya.

v0.9.0: Initial implementation.
"""

from __future__ import annotations

from pathlib import Path

from merlya.templates.loaders.filesystem import FilesystemTemplateLoader


class EmbeddedTemplateLoader(FilesystemTemplateLoader):
    """Load built-in templates from the merlya package."""

    def __init__(self) -> None:
        """Initialize with the builtin templates directory."""
        builtin_path = Path(__file__).parent.parent / "builtin"
        super().__init__(builtin_path)
