"""
Merlya Centers - Registry.

Singleton registry for managing center instances.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from merlya.centers.base import AbstractCenter, CenterMode

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


class CenterRegistry:
    """
    Registry for operational centers.

    Manages center instances and provides lookup by mode.
    Follows the singleton pattern with reset_instance() for tests.
    """

    _instance: CenterRegistry | None = None

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._centers: dict[CenterMode, type[AbstractCenter]] = {}
        self._instances: dict[CenterMode, AbstractCenter] = {}
        self._ctx: SharedContext | None = None

    @classmethod
    def get_instance(cls) -> CenterRegistry:
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton for tests."""
        cls._instance = None

    def set_context(self, ctx: SharedContext) -> None:
        """
        Set the shared context for center instantiation.

        Args:
            ctx: Shared context to use for centers.
        """
        self._ctx = ctx
        # Clear existing instances when context changes
        self._instances.clear()
        logger.debug("⚙️ CenterRegistry context updated")

    def register(
        self,
        mode: CenterMode,
        center_class: type[AbstractCenter],
    ) -> None:
        """
        Register a center class for a mode.

        Args:
            mode: The operational mode.
            center_class: The center class to register.
        """
        self._centers[mode] = center_class
        logger.debug(f"⚙️ Registered center for mode {mode.value}: {center_class.__name__}")

    def get(self, mode: CenterMode) -> AbstractCenter:
        """
        Get center instance for a mode.

        Args:
            mode: The operational mode.

        Returns:
            Center instance for the mode.

        Raises:
            ValueError: If no center registered for mode.
            RuntimeError: If context not set.
        """
        if mode not in self._centers:
            raise ValueError(f"No center registered for mode: {mode.value}")

        if self._ctx is None:
            raise RuntimeError("Context not set. Call set_context() first.")

        # Lazy instantiation
        if mode not in self._instances:
            center_class = self._centers[mode]
            self._instances[mode] = center_class(self._ctx)
            logger.debug(f"⚡ Instantiated center for mode {mode.value}")

        return self._instances[mode]

    def get_by_name(self, name: str) -> AbstractCenter:
        """
        Get center by mode name.

        Args:
            name: Mode name (e.g., "diagnostic", "change").

        Returns:
            Center instance.
        """
        try:
            mode = CenterMode(name.lower())
            return self.get(mode)
        except ValueError as e:
            raise ValueError(f"Unknown center mode: {name}") from e

    def is_registered(self, mode: CenterMode) -> bool:
        """Check if a center is registered for a mode."""
        return mode in self._centers

    @property
    def registered_modes(self) -> list[CenterMode]:
        """Get list of registered modes."""
        return list(self._centers.keys())
