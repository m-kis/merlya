"""
Tools Base - Context injection and validation utilities.

Replaces global variables with dependency injection (DIP principle).
"""
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Optional

from athena_ai.context.host_registry import HostRegistry, get_host_registry
from athena_ai.core.hooks import HookEvent, get_hook_manager
from athena_ai.utils.logger import logger


class StatusManager:
    """
    Manages Rich Status/spinner that can be paused for user input.

    This solves the issue where console.status() blocks input() calls.
    """

    def __init__(self, console=None):
        self._console = console
        self._status = None
        self._message = ""
        self._is_active = False

    def set_console(self, console):
        """Set the Rich console to use."""
        self._console = console

    def start(self, message: str = "[cyan]Processing...[/cyan]"):
        """Start the status spinner."""
        if self._console and not self._is_active:
            self._message = message
            try:
                self._status = self._console.status(message, spinner="dots")
                self._status.start()
                self._is_active = True
            except Exception:
                # If status initialization fails, ensure clean state
                self._status = None
                self._is_active = False

    def stop(self):
        """Stop the status spinner."""
        if self._status and self._is_active:
            self._status.stop()
            self._is_active = False
            self._status = None  # Explicit cleanup to prevent resource leak

    def resume(self):
        """Resume the status spinner with the previous message."""
        if self._console and not self._is_active and self._message:
            try:
                self._status = self._console.status(self._message, spinner="dots")
                self._status.start()
                self._is_active = True
            except Exception:
                # If status initialization fails, ensure clean state
                self._status = None
                self._is_active = False

    @contextmanager
    def pause_for_input(self):
        """Context manager to pause spinner during user input."""
        was_active = self._is_active
        if was_active:
            self.stop()
        try:
            yield
        finally:
            if was_active:
                self.resume()

    @property
    def is_active(self) -> bool:
        return self._is_active


# Global status manager singleton
_status_manager: Optional[StatusManager] = None


def get_status_manager() -> StatusManager:
    """Get or create the global status manager."""
    global _status_manager
    if _status_manager is None:
        _status_manager = StatusManager()
    return _status_manager


@dataclass
class ToolContext:
    """
    Dependency injection container for tools.

    Replaces global variables with explicit dependencies (DIP).
    """
    executor: Any = None
    context_manager: Any = None
    permissions: Any = None
    context_memory: Any = None
    error_correction: Any = None
    credentials: Any = None
    host_registry: Optional[HostRegistry] = None
    inventory_repo: Any = None  # New inventory repository
    hooks: Any = None
    console: Any = None  # Rich console for user interaction
    input_callback: Any = None  # Callback for user input (to handle spinner pause)

    def __post_init__(self):
        """Initialize optional dependencies."""
        if not self.host_registry:
            self.host_registry = get_host_registry()
        if not self.hooks:
            self.hooks = get_hook_manager()
        if not self.console:
            from rich.console import Console
            self.console = Console()
        # Initialize inventory repository
        if not self.inventory_repo:
            try:
                from athena_ai.memory.persistence.inventory_repository import get_inventory_repository
                self.inventory_repo = get_inventory_repository()
            except Exception as e:
                logger.warning(f"Failed to initialize inventory repository: {e}")

    def get_user_input(self, prompt: str = "> ") -> str:
        """
        Get user input, pausing the status spinner if active.

        This ensures the spinner doesn't block or interfere with input().

        Raises:
            KeyboardInterrupt: If user presses Ctrl+C
            EOFError: If input stream is closed
        """
        status_manager = get_status_manager()
        # Ensure StatusManager has console for proper integration
        if self.console and not status_manager._console:
            status_manager.set_console(self.console)

        with status_manager.pause_for_input():
            if self.input_callback:
                return self.input_callback(prompt)
            return input(prompt)


# Global context (for backward compatibility with AutoGen registration)
_ctx: Optional[ToolContext] = None


def get_tool_context() -> ToolContext:
    """Get the global tool context."""
    global _ctx
    if not _ctx:
        _ctx = ToolContext()
    return _ctx


def initialize_tools(
    executor,
    context_manager,
    permissions,
    context_memory=None,
    error_correction=None,
    credentials=None,
) -> ToolContext:
    """
    Initialize tool dependencies.

    Called by Orchestrator at startup.
    """
    global _ctx

    _ctx = ToolContext(
        executor=executor,
        context_manager=context_manager,
        permissions=permissions,
        context_memory=context_memory,
        error_correction=error_correction,
        credentials=credentials,
    )

    # Load host registry
    if _ctx.host_registry and _ctx.host_registry.is_empty():
        _ctx.host_registry.load_all_sources()

    logger.debug(f"Tools initialized with {len(_ctx.host_registry.hostnames)} hosts")
    return _ctx


def validate_host(hostname: str) -> tuple[bool, str]:
    """
    Validate hostname against registry and inventory.

    Checks both the legacy host registry and the new inventory repository.

    Returns:
        (is_valid, message)
    """
    ctx = get_tool_context()

    # Allow local execution
    if hostname in ["local", "localhost", "127.0.0.1"]:
        return True, "Local execution allowed"

    # Check new inventory repository first
    if ctx.inventory_repo:
        try:
            host = ctx.inventory_repo.get_host_by_name(hostname)
            if host:
                return True, f"Host '{hostname}' found in inventory"
        except Exception as e:
            logger.debug(f"Inventory lookup failed for '{hostname}': {e}")

    # Fall back to legacy host registry
    if not ctx.host_registry:
        ctx.host_registry = get_host_registry()
    if ctx.host_registry.is_empty():
        ctx.host_registry.load_all_sources()

    validation = ctx.host_registry.validate(hostname)

    if validation.is_valid:
        return True, f"Host '{validation.host.hostname}' validated"

    return False, validation.get_suggestion_text()


def emit_hook(event: HookEvent, data: dict, source: str = "tools") -> Any:
    """
    Emit hook event if hooks are initialized.

    Returns context for cancellation checking, or None if unavailable.
    """
    ctx = get_tool_context()
    if not ctx.hooks:
        return None
    try:
        return ctx.hooks.emit(event, data, source)
    except Exception as e:
        logger.warning(f"Hook emission failed: {e}")
        return None
