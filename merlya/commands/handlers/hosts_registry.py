"""
Merlya Commands - Host import/export registry.

Registry pattern for extensible import/export formats (OCP-compliant).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar

from loguru import logger

if TYPE_CHECKING:
    from pathlib import Path

    from merlya.core.context import SharedContext


class BaseImporter(ABC):
    """Base class for host importers."""

    # Format identifier (e.g., "json", "yaml", "csv")
    format_id: ClassVar[str]

    # File extensions this importer handles
    extensions: ClassVar[tuple[str, ...]]

    # Human-readable name
    display_name: ClassVar[str]

    @abstractmethod
    async def import_hosts(
        self,
        ctx: SharedContext,
        content: str,
        file_path: Path | None = None,
    ) -> tuple[int, list[str]]:
        """
        Import hosts from content.

        Args:
            ctx: Shared context.
            content: File content to import.
            file_path: Original file path (for formats that need it).

        Returns:
            Tuple of (imported_count, errors).
        """
        ...


class BaseExporter(ABC):
    """Base class for host exporters."""

    # Format identifier
    format_id: ClassVar[str]

    # File extensions this exporter handles
    extensions: ClassVar[tuple[str, ...]]

    # Human-readable name
    display_name: ClassVar[str]

    @abstractmethod
    def export_hosts(self, hosts: list[dict[str, Any]]) -> str:
        """
        Export hosts to string content.

        Args:
            hosts: List of host dictionaries to export.

        Returns:
            Serialized content string.
        """
        ...


class ImporterRegistry:
    """Registry for host importers."""

    _importers: ClassVar[dict[str, type[BaseImporter]]] = {}
    _extension_map: ClassVar[dict[str, str]] = {}

    @classmethod
    def register(cls, importer_class: type[BaseImporter]) -> type[BaseImporter]:
        """
        Register an importer class.

        Can be used as decorator:
            @ImporterRegistry.register
            class JsonImporter(BaseImporter):
                ...

        Args:
            importer_class: Importer class to register.

        Returns:
            The importer class (for decorator usage).
        """
        format_id = importer_class.format_id
        cls._importers[format_id] = importer_class

        # Map extensions to format
        for ext in importer_class.extensions:
            cls._extension_map[ext.lower()] = format_id

        logger.debug(f"📥 Registered importer: {format_id} ({importer_class.display_name})")
        return importer_class

    @classmethod
    def get(cls, format_id: str) -> type[BaseImporter] | None:
        """Get importer by format ID."""
        return cls._importers.get(format_id.lower())

    @classmethod
    def get_by_extension(cls, extension: str) -> type[BaseImporter] | None:
        """Get importer by file extension."""
        ext = extension.lower().lstrip(".")
        format_id = cls._extension_map.get(ext)
        if format_id:
            return cls._importers.get(format_id)
        return None

    @classmethod
    def detect_format(cls, file_path: Path, args: list[str]) -> str:
        """
        Detect format from args or file extension.

        Args:
            file_path: Path to the file.
            args: Command arguments (may contain --format=xxx).

        Returns:
            Format ID string.
        """
        # Check explicit format in args
        for arg in args[1:]:
            if arg.startswith("--format="):
                return arg[9:].lower()

        # Special case: /etc/hosts
        if file_path.name == "hosts" and str(file_path).startswith("/etc"):
            return "etc_hosts"

        # Special case: SSH config (~/.ssh/config)
        if file_path.name == "config" and ".ssh" in str(file_path):
            return "ssh"

        # Check extension (keep the leading dot since extensions are registered with it)
        ext = file_path.suffix.lower()
        if ext in cls._extension_map:
            return cls._extension_map[ext]

        # Default to JSON
        return "json"

    @classmethod
    def list_formats(cls) -> list[tuple[str, str, tuple[str, ...]]]:
        """
        List all registered formats.

        Returns:
            List of (format_id, display_name, extensions) tuples.
        """
        return [
            (imp.format_id, imp.display_name, imp.extensions) for imp in cls._importers.values()
        ]

    @classmethod
    def reset_instance(cls) -> None:
        """Reset registry for testing. Required by CONTRIBUTING.md singleton pattern."""
        cls._importers.clear()
        cls._extension_map.clear()


class ExporterRegistry:
    """Registry for host exporters."""

    _exporters: ClassVar[dict[str, type[BaseExporter]]] = {}
    _extension_map: ClassVar[dict[str, str]] = {}

    @classmethod
    def register(cls, exporter_class: type[BaseExporter]) -> type[BaseExporter]:
        """
        Register an exporter class.

        Can be used as decorator:
            @ExporterRegistry.register
            class JsonExporter(BaseExporter):
                ...
        """
        format_id = exporter_class.format_id
        cls._exporters[format_id] = exporter_class

        for ext in exporter_class.extensions:
            cls._extension_map[ext.lower()] = format_id

        logger.debug(f"📤 Registered exporter: {format_id} ({exporter_class.display_name})")
        return exporter_class

    @classmethod
    def get(cls, format_id: str) -> type[BaseExporter] | None:
        """Get exporter by format ID."""
        return cls._exporters.get(format_id.lower())

    @classmethod
    def get_by_extension(cls, extension: str) -> type[BaseExporter] | None:
        """Get exporter by file extension."""
        ext = extension.lower().lstrip(".")
        format_id = cls._extension_map.get(ext)
        if format_id:
            return cls._exporters.get(format_id)
        return None

    @classmethod
    def detect_format(cls, file_path: Path, args: list[str]) -> str:
        """
        Detect format from args or file extension.

        Args:
            file_path: Path to the file.
            args: Command arguments (may contain --format=xxx).

        Returns:
            Format ID string.
        """
        # Check explicit format in args
        for arg in args[1:]:
            if arg.startswith("--format="):
                return arg[9:].lower()

        # Check extension (keep the leading dot since extensions are registered with it)
        ext = file_path.suffix.lower()
        if ext in cls._extension_map:
            return cls._extension_map[ext]

        # Default to JSON
        return "json"

    @classmethod
    def list_formats(cls) -> list[tuple[str, str, tuple[str, ...]]]:
        """
        List all registered formats.

        Returns:
            List of (format_id, display_name, extensions) tuples.
        """
        return [
            (exp.format_id, exp.display_name, exp.extensions) for exp in cls._exporters.values()
        ]

    @classmethod
    def reset_instance(cls) -> None:
        """Reset registry for testing. Required by CONTRIBUTING.md singleton pattern."""
        cls._exporters.clear()
        cls._extension_map.clear()
