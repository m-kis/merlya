"""
Verbosity Management System for Athena.

Provides centralized control over:
- Console output verbosity (silent, normal, verbose, debug)
- Log file verbosity
- Component-specific verbosity (agents, tools, network, etc.)

Usage:
    from athena_ai.utils.verbosity import get_verbosity, VerbosityLevel

    v = get_verbosity()
    v.set_level(VerbosityLevel.VERBOSE)

    if v.is_verbose:
        print("Detailed info...")

    with v.silent():
        # No console output in this block
        do_something()
"""
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Dict, Optional, Set

from athena_ai.utils.logger import logger


class VerbosityLevel(IntEnum):
    """Verbosity levels from silent to debug."""
    SILENT = 0      # No console output (only critical errors)
    MINIMAL = 1     # Essential output only (results, confirmations)
    NORMAL = 2      # Standard output (status, progress)
    VERBOSE = 3     # Detailed output (reasoning, steps)
    DEBUG = 4       # Everything (internal state, API calls)


class ComponentVerbosity(IntEnum):
    """Per-component verbosity control."""
    INHERIT = -1    # Use global level
    SILENT = 0
    MINIMAL = 1
    NORMAL = 2
    VERBOSE = 3
    DEBUG = 4


@dataclass
class VerbosityConfig:
    """Configuration for verbosity system."""
    global_level: VerbosityLevel = VerbosityLevel.NORMAL
    components: Dict[str, ComponentVerbosity] = field(default_factory=dict)
    log_to_file: bool = True
    log_level: VerbosityLevel = VerbosityLevel.DEBUG  # Always log everything to file
    show_timestamps: bool = False
    show_component_names: bool = True
    muted_components: Set[str] = field(default_factory=set)


class VerbosityManager:
    """
    Centralized verbosity management.

    Features:
    - Global verbosity level
    - Per-component verbosity
    - Context managers for temporary changes
    - Thread-safe
    """

    # Component names
    COMPONENT_AGENTS = "agents"
    COMPONENT_TOOLS = "tools"
    COMPONENT_NETWORK = "network"
    COMPONENT_LLM = "llm"
    COMPONENT_PLANNING = "planning"
    COMPONENT_EXECUTION = "execution"
    COMPONENT_SECURITY = "security"
    COMPONENT_MEMORY = "memory"

    def __init__(self, config: Optional[VerbosityConfig] = None):
        self._config = config or VerbosityConfig()
        self._lock = threading.Lock()
        self._output_callback: Optional[Callable[[str, VerbosityLevel, str], None]] = None
        self._suppressed_levels: Set[VerbosityLevel] = set()
        self._context_stack: list = []

    @property
    def level(self) -> VerbosityLevel:
        """Get current global verbosity level."""
        return self._config.global_level

    @level.setter
    def level(self, value: VerbosityLevel) -> None:
        """Set global verbosity level."""
        with self._lock:
            self._config.global_level = value
            logger.debug(f"Verbosity level set to: {value.name}")

    @property
    def is_silent(self) -> bool:
        """Check if in silent mode."""
        return self._config.global_level == VerbosityLevel.SILENT

    @property
    def is_verbose(self) -> bool:
        """Check if verbose output is enabled."""
        return self._config.global_level >= VerbosityLevel.VERBOSE

    @property
    def is_debug(self) -> bool:
        """Check if debug output is enabled."""
        return self._config.global_level >= VerbosityLevel.DEBUG

    def set_level(self, level: VerbosityLevel) -> None:
        """Set global verbosity level."""
        self.level = level

    def set_component_level(self, component: str, level: ComponentVerbosity) -> None:
        """Set verbosity level for a specific component."""
        with self._lock:
            self._config.components[component] = level

    def get_component_level(self, component: str) -> VerbosityLevel:
        """Get effective verbosity level for a component."""
        component_level = self._config.components.get(component, ComponentVerbosity.INHERIT)
        if component_level == ComponentVerbosity.INHERIT:
            return self._config.global_level
        return VerbosityLevel(component_level)

    def mute_component(self, component: str) -> None:
        """Mute a specific component."""
        with self._lock:
            self._config.muted_components.add(component)

    def unmute_component(self, component: str) -> None:
        """Unmute a specific component."""
        with self._lock:
            self._config.muted_components.discard(component)

    def is_component_muted(self, component: str) -> bool:
        """Check if a component is muted."""
        return component in self._config.muted_components

    def should_output(self, level: VerbosityLevel, component: Optional[str] = None) -> bool:
        """
        Check if output should be shown for given level and component.

        Args:
            level: Required verbosity level for the output
            component: Optional component name

        Returns:
            True if output should be shown
        """
        # Check if level is suppressed
        if level in self._suppressed_levels:
            return False

        # Check if component is muted
        if component and self.is_component_muted(component):
            return False

        # Get effective level
        if component:
            effective_level = self.get_component_level(component)
        else:
            effective_level = self._config.global_level

        return effective_level >= level

    def output(
        self,
        message: str,
        level: VerbosityLevel = VerbosityLevel.NORMAL,
        component: Optional[str] = None,
    ) -> None:
        """
        Output a message if verbosity level allows.

        Args:
            message: Message to output
            level: Required level for this message
            component: Optional component name
        """
        if not self.should_output(level, component):
            return

        # Format message
        formatted = message
        if self._config.show_component_names and component:
            formatted = f"[{component}] {message}"

        # Use callback if set, otherwise print
        if self._output_callback:
            self._output_callback(formatted, level, component)
        else:
            print(formatted)

        # Also log to file if enabled
        if self._config.log_to_file:
            if level >= VerbosityLevel.DEBUG:
                logger.debug(formatted)
            elif level >= VerbosityLevel.VERBOSE:
                logger.info(formatted)

    def set_output_callback(
        self,
        callback: Callable[[str, VerbosityLevel, str], None]
    ) -> None:
        """
        Set custom output callback.

        The callback receives (message, level, component).
        Useful for integrating with Rich console or other UIs.
        """
        self._output_callback = callback

    @contextmanager
    def silent(self):
        """Context manager for silent operation."""
        with self._lock:
            old_level = self._config.global_level
            self._config.global_level = VerbosityLevel.SILENT
        try:
            yield
        finally:
            with self._lock:
                self._config.global_level = old_level

    @contextmanager
    def verbose(self):
        """Context manager for verbose operation."""
        with self._lock:
            old_level = self._config.global_level
            self._config.global_level = VerbosityLevel.VERBOSE
        try:
            yield
        finally:
            with self._lock:
                self._config.global_level = old_level

    @contextmanager
    def debug(self):
        """Context manager for debug operation."""
        with self._lock:
            old_level = self._config.global_level
            self._config.global_level = VerbosityLevel.DEBUG
        try:
            yield
        finally:
            with self._lock:
                self._config.global_level = old_level

    @contextmanager
    def level_context(self, level: VerbosityLevel):
        """Context manager for arbitrary level."""
        with self._lock:
            old_level = self._config.global_level
            self._config.global_level = level
        try:
            yield
        finally:
            with self._lock:
                self._config.global_level = old_level

    @contextmanager
    def suppress_level(self, level: VerbosityLevel):
        """Context manager to suppress a specific level."""
        with self._lock:
            self._suppressed_levels.add(level)
        try:
            yield
        finally:
            with self._lock:
                self._suppressed_levels.discard(level)

    def get_status(self) -> Dict:
        """Get current verbosity status."""
        return {
            'global_level': self._config.global_level.name,
            'is_verbose': self.is_verbose,
            'is_debug': self.is_debug,
            'is_silent': self.is_silent,
            'muted_components': list(self._config.muted_components),
            'component_levels': {
                k: v.name for k, v in self._config.components.items()
            },
        }


# Singleton instance
_verbosity: Optional[VerbosityManager] = None


def get_verbosity() -> VerbosityManager:
    """Get the global VerbosityManager instance."""
    global _verbosity
    if _verbosity is None:
        _verbosity = VerbosityManager()
    return _verbosity


def set_verbosity_level(level: VerbosityLevel) -> None:
    """Convenience function to set global verbosity level."""
    get_verbosity().set_level(level)


def is_verbose() -> bool:
    """Convenience function to check if verbose mode is on."""
    return get_verbosity().is_verbose


def is_debug() -> bool:
    """Convenience function to check if debug mode is on."""
    return get_verbosity().is_debug


# Convenience shortcuts for common operations
def silent():
    """Context manager for silent operation."""
    return get_verbosity().silent()


def verbose():
    """Context manager for verbose operation."""
    return get_verbosity().verbose()


def debug():
    """Context manager for debug operation."""
    return get_verbosity().debug()
