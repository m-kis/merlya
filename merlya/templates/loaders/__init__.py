"""
Merlya Templates - Loaders.

Template loaders from various sources.

v0.9.0: Initial implementation.
"""

from merlya.templates.loaders.base import AbstractTemplateLoader
from merlya.templates.loaders.embedded import EmbeddedTemplateLoader
from merlya.templates.loaders.filesystem import FilesystemTemplateLoader

__all__ = [
    "AbstractTemplateLoader",
    "EmbeddedTemplateLoader",
    "FilesystemTemplateLoader",
]
