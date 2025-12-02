"""
Tools Base - Context injection and validation utilities.

Replaces global variables with dependency injection (DIP principle).
"""
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Optional

from merlya.context.host_registry import HostRegistry, get_host_registry
from merlya.core.hooks import HookEvent, get_hook_manager
from merlya.utils.logger import logger


class StatusManager:
    """
    Manages Rich Status/spinner with contextual updates and interruption support.

    Features:
    - Dynamic message updates showing current operation
    - Pause/resume for user input
    - Activity logging for debugging
    - Keyboard interrupt handling
    """

    def __init__(self, console=None):
        self._console = console
        self._status = None
        self._message = ""
        self._is_active = False
        self._operation_stack: list[str] = []  # Track nested operations
        self._interrupted = False

    def set_console(self, console):
        """Set the Rich console to use."""
        self._console = console

    def start(self, message: str = "[cyan]🧠 Processing...[/cyan]"):
        """Start the status spinner with initial message."""
        if self._console and not self._is_active:
            self._message = message
            self._interrupted = False
            self._operation_stack = []
            try:
                self._status = self._console.status(message, spinner="dots")
                self._status.start()
                self._is_active = True
            except Exception:
                # If status initialization fails, ensure clean state
                self._status = None
                self._is_active = False

    def update(self, message: str, operation: Optional[str] = None):
        """
        Update the spinner message with contextual information.

        Args:
            message: New message to display
            operation: Optional operation name for tracking (e.g., 'scan_host', 'execute_command')
        """
        if not self._is_active or not self._status:
            return

        self._message = message
        if operation:
            self._operation_stack.append(operation)

        try:
            self._status.update(message)
        except Exception:
            pass  # Silently ignore update failures

    def update_host_operation(self, operation: str, hostname: str, details: str = ""):
        """
        Update spinner with host-specific operation context.

        Args:
            operation: Operation type (e.g., 'scanning', 'executing', 'connecting')
            hostname: Target hostname
            details: Optional additional details
        """
        if not self._is_active or not self._status:
            # Don't try to update if no spinner is active
            return

        emoji_map = {
            'scanning': '🔍',
            'executing': '⚡',
            'connecting': '🔌',
            'reading': '📖',
            'writing': '✍️',
            'checking': '🔒',
            'elevating': '🔐',
        }
        emoji = emoji_map.get(operation.lower(), '🔄')
        detail_str = f": {details}" if details else ""
        # Use a clean message format - no prefix concatenation
        message = f"[cyan]{emoji} {operation.capitalize()} [bold]{hostname}[/bold]{detail_str}[/cyan]"
        self.update(message, operation=f"{operation}:{hostname}")

    def stop(self):
        """Stop the status spinner."""
        if self._status and self._is_active:
            self._status.stop()
            self._is_active = False
            self._status = None  # Explicit cleanup to prevent resource leak
            self._operation_stack = []

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

    def mark_interrupted(self):
        """Mark that an interruption was requested."""
        self._interrupted = True

    @property
    def was_interrupted(self) -> bool:
        """Check if an interruption was requested."""
        return self._interrupted

    @property
    def current_operation(self) -> Optional[str]:
        """Get the current operation being performed."""
        return self._operation_stack[-1] if self._operation_stack else None

    @contextmanager
    def pause_for_input(self):
        """Context manager to pause spinner during user input."""
        was_active = self._is_active
        if was_active:
            self.stop()
        try:
            yield
        finally:
            if was_active and not self._interrupted:
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
            # Step 1: Import the repository module
            try:
                from merlya.memory.persistence.inventory_repository import get_inventory_repository
            except (ImportError, ModuleNotFoundError) as e:
                logger.warning(f"Failed to import inventory repository module: {type(e).__name__}: {e}")
                get_inventory_repository = None

            # Step 2: Initialize the repository if import succeeded
            if get_inventory_repository is not None:
                try:
                    self.inventory_repo = get_inventory_repository()
                except (ValueError, RuntimeError, OSError, sqlite3.Error) as e:
                    # Known initialization errors:
                    # - ValueError/RuntimeError: invalid config or runtime issues
                    # - OSError: filesystem errors (can't create .merlya directory)
                    # - sqlite3.Error: database connection or schema errors
                    logger.warning(f"Failed to initialize inventory repository: {type(e).__name__}: {e}")
                except Exception as e:
                    # Unexpected errors - log at error level but continue since inventory is optional
                    logger.error(f"Unexpected error initializing inventory repository: {type(e).__name__}: {e}")

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

    if _ctx.host_registry:
        logger.debug(f"Tools initialized with {len(_ctx.host_registry.hostnames)} hosts")
    else:
        logger.debug("Tools initialized without host registry")
    return _ctx


def sanitize_hostname(hostname: str) -> tuple[str, bool]:
    """
    Sanitize hostname by removing LLM parsing artifacts.

    LLMs sometimes produce malformed hostnames with XML/HTML tags embedded,
    such as: "MYSQL8CLUSTER4-1</parameter name="path">/etc/mysql/conf.d/*"

    Args:
        hostname: Raw hostname from LLM output

    Returns:
        (sanitized_hostname, was_modified)
    """
    import ipaddress
    import re

    if not hostname:
        return hostname, False

    # Skip sanitization for valid IP addresses (IPv4 or IPv6)
    try:
        ipaddress.ip_address(hostname)
        return hostname, False  # Valid IP, don't sanitize
    except ValueError:
        pass  # Not an IP, continue sanitization

    original = hostname

    # Remove XML/HTML tags like </parameter...>, <param...>, etc.
    # Pattern matches: < followed by optional /, word chars, optional attributes, and >
    hostname = re.sub(r'</?[a-zA-Z][^>]*>', '', hostname)

    # Remove anything after path separator (/) - handles "HOSTNAME/etc/..."
    # But NOT colon, to preserve port numbers like host:22 for now
    if '/' in hostname:
        hostname = hostname.split('/')[0]

    # Remove port suffix if present (host:22 -> host)
    if ':' in hostname and not hostname.startswith('['):  # Not IPv6 [addr]:port
        hostname = hostname.split(':')[0]

    # Remove any remaining special chars that aren't valid in hostnames
    # Valid hostname chars: ASCII alphanumeric, hyphen, dot (for FQDN)
    # Use ASCII flag to exclude unicode characters (security)
    hostname = re.sub(r'[^a-zA-Z0-9\-.]', '', hostname)

    # Remove leading/trailing dots and hyphens
    hostname = hostname.strip('.-')

    return hostname, hostname != original


def validate_host(hostname: str, context: Optional[str] = None) -> tuple[bool, str]:
    """
    Validate hostname against registry and inventory with disambiguation.

    Uses intelligent host resolution to:
    1. Sanitize hostname (remove LLM parsing artifacts)
    2. Find exact matches
    3. Resolve partial matches with confidence scoring
    4. Provide disambiguation when multiple hosts match

    Args:
        hostname: Hostname to validate
        context: Optional context for disambiguation (e.g., "ansible", "prod")

    Returns:
        (is_valid, message)
    """
    from merlya.context.host_resolver import get_host_resolver

    ctx = get_tool_context()

    # Sanitize hostname first (LLM sometimes produces malformed hostnames)
    sanitized, was_modified = sanitize_hostname(hostname)
    if was_modified:
        logger.warning(f"🔧 Hostname sanitized: '{hostname}' -> '{sanitized}'")
        hostname = sanitized

    if not hostname:
        return False, "❌ Empty hostname after sanitization"

    # Allow local execution
    if hostname in ["local", "localhost", "127.0.0.1"]:
        return True, "Local execution allowed"

    # Check new inventory repository first (exact match)
    if ctx.inventory_repo:
        try:
            host = ctx.inventory_repo.get_host_by_name(hostname)
            if host is not None:
                return True, f"Host '{hostname}' found in inventory"
        except (AttributeError, TypeError, ValueError) as e:
            # Expected errors from malformed data or missing attributes
            logger.debug(f"Inventory lookup error for '{hostname}': {e}")
        except Exception as e:
            # Unexpected errors - log at warning level for visibility
            logger.warning(f"Inventory lookup failed for '{hostname}': {type(e).__name__}: {e}")

    # Use intelligent host resolver for disambiguation
    resolver = get_host_resolver(ctx.host_registry)
    result = resolver.resolve(hostname, context)

    if result.exact_match and result.host:
        return True, f"Host '{result.host.hostname}' validated (exact match)"

    if result.host and not result.disambiguation_needed:
        # Good match with high confidence
        confidence_pct = int(result.confidence * 100)
        return True, f"Host '{result.host.hostname}' validated ({confidence_pct}% match)"

    if result.disambiguation_needed:
        # Multiple hosts match - need user to clarify
        disambiguation_msg = resolver.format_disambiguation(result, hostname)
        return False, f"❌ Ambiguous hostname: '{hostname}'\n\n{disambiguation_msg}"

    # No match found - fall back to legacy registry for suggestions
    if not ctx.host_registry:
        ctx.host_registry = get_host_registry()
    if ctx.host_registry.is_empty():
        ctx.host_registry.load_all_sources()

    validation = ctx.host_registry.validate(hostname)

    if validation.is_valid and validation.host:
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
