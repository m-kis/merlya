"""
Hook System for Athena.

Provides a pub/sub event system for tool execution, agent messages, and REPL commands.
Inspired by Claude Code's hooks system but adapted for infrastructure automation.

Features:
- Singleton HookManager for global event handling
- Pre/post execution hooks with cancellation support
- YAML configuration for external hooks
- Python API for programmatic hooks
"""

import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

from athena_ai.utils.logger import logger


class HookEvent(str, Enum):
    """Events that can trigger hooks."""

    # Tool execution events
    TOOL_EXECUTE_START = "tool.execute.start"
    TOOL_EXECUTE_END = "tool.execute.end"
    TOOL_EXECUTE_ERROR = "tool.execute.error"

    # Agent events
    AGENT_MESSAGE = "agent.message"
    AGENT_TOOL_CALL = "agent.tool_call"

    # REPL events
    COMMAND_INPUT = "command.input"
    COMMAND_OUTPUT = "command.output"

    # Session events
    SESSION_START = "session.start"
    SESSION_END = "session.end"


@dataclass
class HookContext:
    """
    Context passed to hook handlers.

    Attributes:
        event: The event that triggered the hook
        data: Event-specific data (tool name, target, command, etc.)
        source: Source of the event (tool name, agent name, etc.)
        cancelled: If True, the operation will be blocked
        cancel_reason: Reason for cancellation
    """
    event: HookEvent
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = ""
    cancelled: bool = False
    cancel_reason: str = ""

    def cancel(self, reason: str = "Blocked by hook"):
        """Cancel the operation."""
        self.cancelled = True
        self.cancel_reason = reason


@dataclass
class HookDefinition:
    """
    Definition of a hook from YAML config.

    Attributes:
        name: Hook identifier
        event: Event to listen for
        action: Action type (log, shell, block, notify)
        command: Shell command for 'shell' action
        format: Log format string for 'log' action
        match: Regex pattern to match against data
        block_message: Message shown when blocking
    """
    name: str
    event: HookEvent
    action: str  # log, shell, block, notify
    command: str = ""
    format: str = ""
    match: str = ""
    block_message: str = ""


class HookManager:
    """
    Singleton pub/sub manager for hook events.

    Usage:
        hooks = get_hook_manager()

        # Subscribe to events
        def my_handler(ctx: HookContext):
            print(f"Tool {ctx.data['tool']} executed on {ctx.data['target']}")

        unsubscribe = hooks.subscribe(HookEvent.TOOL_EXECUTE_START, my_handler)

        # Emit events
        ctx = hooks.emit(HookEvent.TOOL_EXECUTE_START, {
            "tool": "execute_command",
            "target": "web-01",
            "command": "systemctl restart nginx"
        })

        if ctx.cancelled:
            print(f"Blocked: {ctx.cancel_reason}")

        # Unsubscribe when done
        unsubscribe()
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._handlers: Dict[HookEvent, List[Callable]] = {}
            cls._instance._yaml_hooks: List[HookDefinition] = []
            cls._instance._initialized = False
        return cls._instance

    def initialize(self):
        """Initialize hooks from YAML config files."""
        if self._initialized:
            return

        # Load hooks from config locations
        config_paths = [
            Path.home() / ".athena" / "hooks.yaml",
            Path.cwd() / ".athena" / "hooks.yaml",
        ]

        for path in config_paths:
            if path.exists():
                self._load_yaml_hooks(path)

        self._initialized = True
        logger.debug(f"HookManager initialized with {len(self._yaml_hooks)} YAML hooks")

    def _load_yaml_hooks(self, path: Path):
        """Load hooks from YAML file."""
        try:
            with open(path) as f:
                config = yaml.safe_load(f)

            if not config or "hooks" not in config:
                return

            for event_name, hooks_list in config["hooks"].items():
                try:
                    event = HookEvent(event_name)
                except ValueError:
                    logger.warning(f"Unknown hook event: {event_name}")
                    continue

                for hook_config in hooks_list:
                    hook = HookDefinition(
                        name=hook_config.get("name", "unnamed"),
                        event=event,
                        action=hook_config.get("action", "log"),
                        command=hook_config.get("command", ""),
                        format=hook_config.get("format", ""),
                        match=hook_config.get("match", ""),
                        block_message=hook_config.get("block_message", ""),
                    )
                    self._yaml_hooks.append(hook)
                    logger.debug(f"Loaded hook: {hook.name} for {event_name}")

        except Exception as e:
            logger.warning(f"Failed to load hooks from {path}: {e}")

    def subscribe(
        self,
        event: HookEvent,
        handler: Callable[[HookContext], None]
    ) -> Callable[[], None]:
        """
        Subscribe to an event.

        Args:
            event: Event to listen for
            handler: Function called when event is emitted

        Returns:
            Unsubscribe function
        """
        if event not in self._handlers:
            self._handlers[event] = []

        self._handlers[event].append(handler)
        logger.debug(f"Handler subscribed to {event.value}")

        # Return unsubscribe function
        def unsubscribe():
            if handler in self._handlers.get(event, []):
                self._handlers[event].remove(handler)
                logger.debug(f"Handler unsubscribed from {event.value}")

        return unsubscribe

    def emit(
        self,
        event: HookEvent,
        data: Optional[Dict[str, Any]] = None,
        source: str = ""
    ) -> HookContext:
        """
        Emit an event and run all handlers.

        Args:
            event: Event to emit
            data: Event data
            source: Event source identifier

        Returns:
            HookContext with potential cancellation info
        """
        ctx = HookContext(event=event, data=data or {}, source=source)

        # Run programmatic handlers
        for handler in self._handlers.get(event, []):
            try:
                handler(ctx)
                if ctx.cancelled:
                    logger.info(f"Event {event.value} cancelled by handler: {ctx.cancel_reason}")
                    return ctx
            except Exception as e:
                logger.warning(f"Hook handler error for {event.value}: {e}")

        # Run YAML hooks
        for hook in self._yaml_hooks:
            if hook.event != event:
                continue

            # Check match pattern
            if hook.match:
                match_found = False
                for _key, value in ctx.data.items():
                    if isinstance(value, str) and re.search(hook.match, value):
                        match_found = True
                        break
                if not match_found:
                    continue

            # Execute hook action
            try:
                self._execute_yaml_hook(hook, ctx)
                if ctx.cancelled:
                    return ctx
            except Exception as e:
                logger.warning(f"YAML hook '{hook.name}' error: {e}")

        return ctx

    def _execute_yaml_hook(self, hook: HookDefinition, ctx: HookContext):
        """Execute a YAML-defined hook."""

        if hook.action == "log":
            # Format and log message
            message = self._format_string(hook.format, ctx.data)
            logger.info(f"[HOOK:{hook.name}] {message}")

        elif hook.action == "shell":
            # Execute shell command
            command = self._format_string(hook.command, ctx.data)
            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode != 0:
                    logger.warning(f"Hook shell command failed: {result.stderr}")
            except subprocess.TimeoutExpired:
                logger.warning(f"Hook shell command timed out: {command}")
            except Exception as e:
                logger.warning(f"Hook shell command error: {e}")

        elif hook.action == "block":
            # Block the operation
            message = self._format_string(
                hook.block_message or "Blocked by hook: {name}",
                {**ctx.data, "name": hook.name}
            )
            ctx.cancel(message)

        elif hook.action == "notify":
            # Notification (could be Slack, email, etc.)
            message = self._format_string(hook.format, ctx.data)
            logger.info(f"[NOTIFY:{hook.name}] {message}")
            # Future: Add actual notification integrations

    def _format_string(self, template: str, data: Dict[str, Any]) -> str:
        """Format a string template with data."""
        result = template
        for key, value in data.items():
            result = result.replace(f"{{{key}}}", str(value))
        return result

    def list_hooks(self) -> Dict[str, List[str]]:
        """List all registered hooks."""
        result = {}

        # Programmatic handlers
        for event, handlers in self._handlers.items():
            result[event.value] = [
                f"[python] {h.__name__}" for h in handlers
            ]

        # YAML hooks
        for hook in self._yaml_hooks:
            if hook.event.value not in result:
                result[hook.event.value] = []
            result[hook.event.value].append(f"[yaml] {hook.name} ({hook.action})")

        return result

    def clear(self):
        """Clear all hooks (for testing)."""
        self._handlers.clear()
        self._yaml_hooks.clear()
        self._initialized = False

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing)."""
        cls._instance = None


# Singleton accessor
_hook_manager: Optional[HookManager] = None


def get_hook_manager() -> HookManager:
    """Get the global HookManager instance."""
    global _hook_manager
    if _hook_manager is None:
        _hook_manager = HookManager()
        _hook_manager.initialize()
    return _hook_manager


def reset_hook_manager() -> None:
    """Reset the global HookManager (for testing)."""
    global _hook_manager
    HookManager.reset_instance()
    _hook_manager = None
