"""
Merlya Parser Service - Main entry point for text parsing.

ONNX model-based parsing has been removed in v0.8.0.
Now uses HeuristicBackend (pattern-based) only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from merlya.parser.backends.heuristic import HeuristicBackend

if TYPE_CHECKING:
    from merlya.parser.backends.base import ParserBackend
    from merlya.parser.models import (
        CommandParsingResult,
        HostQueryParsingResult,
        IncidentParsingResult,
        LogParsingResult,
    )


class ParserService:
    """
    Main parser service - singleton for text parsing.

    Uses HeuristicBackend only (ONNX removed in v0.8.0).

    Usage:
        service = ParserService.get_instance()
        await service.initialize()
        result = await service.parse_incident("Production server is down...")
    """

    _instance: ParserService | None = None

    def __init__(
        self,
        tier: str = "lightweight",
        model_id: str | None = None,
    ) -> None:
        """
        Initialize the parser service.

        Args:
            tier: Ignored (kept for backward compatibility).
            model_id: Ignored (kept for backward compatibility).
        """
        # tier and model_id ignored - ONNX removed
        _ = tier, model_id
        self._tier = "lightweight"
        self._backend: ParserBackend | None = None
        self._initialized = False

        logger.debug("🔧 ParserService created (heuristic backend)")

    @classmethod
    def get_instance(
        cls,
        tier: str | None = None,
        model_id: str | None = None,
    ) -> ParserService:
        """
        Get or create the singleton instance.

        Args:
            tier: Backend tier (only used on first call).
            model_id: Optional model ID (only used on first call).

        Returns:
            ParserService singleton instance.
        """
        if cls._instance is None:
            cls._instance = cls(tier=tier or "lightweight", model_id=model_id)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (for tests)."""
        cls._instance = None

    async def initialize(self) -> bool:
        """
        Initialize the parser service and load backend.

        Returns:
            True if initialization succeeded.
        """
        if self._initialized:
            return True

        self._backend = HeuristicBackend()

        if await self._backend.load():
            self._initialized = True
            logger.debug(f"✅ ParserService initialized with backend: {self._backend.name}")
            return True

        logger.error("❌ HeuristicBackend failed to load")
        self._backend = None
        return False

    @property
    def backend_name(self) -> str:
        """Return the active backend name."""
        return self._backend.name if self._backend else "none"

    @property
    def is_initialized(self) -> bool:
        """Return True if the service is ready."""
        return self._initialized

    @property
    def tier(self) -> str:
        """Return the configured tier."""
        return self._tier

    async def parse_incident(self, text: str) -> IncidentParsingResult:
        """
        Parse text as an incident description.

        Args:
            text: Raw incident description text.

        Returns:
            Structured incident parsing result with:
            - incident: IncidentInput with extracted fields
            - confidence: How confident the parser is (0.0-1.0)
            - coverage_ratio: How much of the text was parsed
            - backend_used: Which backend performed the parsing
        """
        if not self._initialized and not await self.initialize():
            raise RuntimeError("Failed to initialize ParserService")

        assert self._backend is not None  # Guaranteed after initialization
        return await self._backend.parse_incident(text)

    async def parse_log(self, text: str) -> LogParsingResult:
        """
        Parse text as log output.

        Args:
            text: Raw log text.

        Returns:
            Structured log parsing result with:
            - parsed_log: ParsedLog with entries, counts, patterns
            - confidence: Parsing confidence
            - coverage_ratio: Text coverage
        """
        if not self._initialized and not await self.initialize():
            raise RuntimeError("Failed to initialize ParserService")

        assert self._backend is not None  # Guaranteed after initialization
        return await self._backend.parse_log(text)

    async def parse_host_query(self, text: str) -> HostQueryParsingResult:
        """
        Parse text as a host query.

        Args:
            text: Raw query text.

        Returns:
            Structured host query parsing result.
        """
        if not self._initialized and not await self.initialize():
            raise RuntimeError("Failed to initialize ParserService")

        assert self._backend is not None  # Guaranteed after initialization
        return await self._backend.parse_host_query(text)

    async def parse_command(self, text: str) -> CommandParsingResult:
        """
        Parse text as a command.

        Args:
            text: Raw command text.

        Returns:
            Structured command parsing result.
        """
        if not self._initialized and not await self.initialize():
            raise RuntimeError("Failed to initialize ParserService")

        assert self._backend is not None  # Guaranteed after initialization
        return await self._backend.parse_command(text)

    async def extract_entities(self, text: str) -> dict[str, list[str]]:
        """
        Extract named entities from text.

        Args:
            text: Input text.

        Returns:
            Dictionary mapping entity types to values.
        """
        if not self._initialized and not await self.initialize():
            raise RuntimeError("Failed to initialize ParserService")

        assert self._backend is not None  # Guaranteed after initialization
        return await self._backend.extract_entities(text)


# Convenience functions for direct usage
async def parse_incident(text: str) -> IncidentParsingResult:
    """Parse text as an incident (convenience function)."""
    service = ParserService.get_instance()
    return await service.parse_incident(text)


async def parse_log(text: str) -> LogParsingResult:
    """Parse text as log output (convenience function)."""
    service = ParserService.get_instance()
    return await service.parse_log(text)


async def parse_host_query(text: str) -> HostQueryParsingResult:
    """Parse text as a host query (convenience function)."""
    service = ParserService.get_instance()
    return await service.parse_host_query(text)


async def parse_command(text: str) -> CommandParsingResult:
    """Parse text as a command (convenience function)."""
    service = ParserService.get_instance()
    return await service.parse_command(text)
