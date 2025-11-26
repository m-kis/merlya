"""
Tools Base - Context injection and validation utilities.

Replaces global variables with dependency injection (DIP principle).
"""
from dataclasses import dataclass
from typing import Any, Optional

from athena_ai.context.host_registry import HostRegistry, get_host_registry
from athena_ai.core.hooks import HookEvent, get_hook_manager
from athena_ai.utils.logger import logger


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
    hooks: Any = None
    console: Any = None  # Rich console for user interaction

    def __post_init__(self):
        """Initialize optional dependencies."""
        if not self.host_registry:
            self.host_registry = get_host_registry()
        if not self.hooks:
            self.hooks = get_hook_manager()
        if not self.console:
            from rich.console import Console
            self.console = Console()


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
    Validate hostname against registry.

    Returns:
        (is_valid, message)
    """
    ctx = get_tool_context()

    # Allow local execution
    if hostname in ["local", "localhost", "127.0.0.1"]:
        return True, "Local execution allowed"

    # Ensure registry is loaded
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
