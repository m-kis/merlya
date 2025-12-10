"""
Merlya Parser - Abstract base class for parser backends.

Defines the interface that all parser backends must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from merlya.parser.models import (
        CommandParsingResult,
        HostQueryParsingResult,
        IncidentParsingResult,
        LogParsingResult,
    )


class ParserBackend(ABC):
    """
    Abstract base class for parser backends.

    All parsing backends must implement this interface.
    The backend selection is tier-based (like IntentClassifier):
    - lightweight: HeuristicBackend
    - balanced: ONNXBackend with distilbert-NER
    - performance: ONNXBackend with bert-base-NER
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the backend name (e.g., 'heuristic', 'onnx')."""
        ...

    @property
    @abstractmethod
    def is_loaded(self) -> bool:
        """Return True if the backend is ready to use."""
        ...

    @abstractmethod
    async def load(self) -> bool:
        """
        Load any required models or resources.

        Returns:
            True if loading succeeded, False otherwise.
        """
        ...

    @abstractmethod
    async def parse_incident(self, text: str) -> IncidentParsingResult:
        """
        Parse text as an incident description.

        Args:
            text: Raw incident description text.

        Returns:
            Structured incident parsing result.
        """
        ...

    @abstractmethod
    async def parse_log(self, text: str) -> LogParsingResult:
        """
        Parse text as log output.

        Args:
            text: Raw log text.

        Returns:
            Structured log parsing result.
        """
        ...

    @abstractmethod
    async def parse_host_query(self, text: str) -> HostQueryParsingResult:
        """
        Parse text as a host query.

        Args:
            text: Raw host query text.

        Returns:
            Structured host query parsing result.
        """
        ...

    @abstractmethod
    async def parse_command(self, text: str) -> CommandParsingResult:
        """
        Parse text as a command.

        Args:
            text: Raw command text.

        Returns:
            Structured command parsing result.
        """
        ...

    @abstractmethod
    async def extract_entities(self, text: str) -> dict[str, list[str]]:
        """
        Extract named entities from text.

        Args:
            text: Input text.

        Returns:
            Dictionary mapping entity types to lists of values.
            Common types: hosts, services, paths, errors, timestamps.
        """
        ...
