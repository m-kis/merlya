"""
Non-interactive batch execution for Merlya.

Handles `merlya run` command for automated tasks.
Supports both natural language commands (via AI agent) and slash commands.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from loguru import logger
from pydantic import BaseModel

if TYPE_CHECKING:
    from merlya.core.context import SharedContext

# Commands that should never run in batch mode
BLOCKED_COMMANDS = frozenset(
    {
        "exit",
        "quit",
        "q",  # Session control
        "new",  # Conversation management
        "conv",
        "conversation",  # No context in batch
    }
)

# Commands requiring interactive input (blocked without workaround)
INTERACTIVE_COMMANDS = frozenset(
    {
        "hosts add",  # Prompts for hostname, port, user
        "ssh config",  # Prompts for SSH configuration
        "secret set",  # Secure input prompt required
    }
)


@dataclass
class TaskResult:
    """Result of a task execution."""

    task: str
    success: bool
    message: str
    actions: list[str]
    data: Any = None  # Structured data for JSON output
    task_type: str = "agent"  # "agent" or "command"

    def to_dict(self) -> dict[str, Any]:
        """Convert task result to JSON-serializable dictionary."""
        return {
            "task": self.task,
            "success": self.success,
            "message": self.message,
            "actions": list(self.actions),
            "data": _to_json_safe(self.data),
            "task_type": self.task_type,
        }


@dataclass
class BatchResult:
    """Result of batch execution."""

    success: bool
    tasks: list[TaskResult]
    total: int
    passed: int
    failed: int

    def to_dict(self) -> dict[str, Any]:
        """Convert batch result to JSON-serializable dictionary."""
        return {
            "success": self.success,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "tasks": [task.to_dict() for task in self.tasks],
        }


def _to_json_safe(value: Any, _seen: set[int] | None = None) -> Any:
    """Convert common Merlya objects to JSON-serializable structures."""
    if _seen is None:
        _seen = set()

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    obj_id = id(value)
    if obj_id in _seen:
        return str(value)  # or raise an error, or return a sentinel

    # Mark as seen for containers
    if isinstance(value, (dict, list, tuple, set)) or is_dataclass(value):
        _seen = _seen | {obj_id}

    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _to_json_safe(to_dict(), _seen | {obj_id})
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _to_json_safe(v, _seen) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: _to_json_safe(v, _seen) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_json_safe(v, _seen) for v in value]
    return str(value)


def _parse_slash_command(cmd: str) -> tuple[str, str, list[str]]:
    """
    Parse a slash command into its components.

    Args:
        cmd: Command string starting with "/".

    Returns:
        Tuple of (base_command, full_command_path, args).
        Example: "/hosts list --tag=web" -> ("hosts", "hosts list", ["--tag=web"])
    """
    parts = cmd[1:].split()  # Remove leading "/" and split
    if not parts:
        return "", "", []

    base_cmd = parts[0].lower()

    # Check for subcommand
    if len(parts) > 1 and not parts[1].startswith("-"):
        full_cmd = f"{base_cmd} {parts[1].lower()}"
        args = parts[2:]
    else:
        full_cmd = base_cmd
        args = parts[1:]

    return base_cmd, full_cmd, args


def _check_command_allowed(cmd: str) -> tuple[bool, str | None]:
    """
    Check if a slash command is allowed in batch mode.

    Args:
        cmd: Command string starting with "/".

    Returns:
        Tuple of (is_allowed, error_message).
    """
    base_cmd, full_cmd, _ = _parse_slash_command(cmd)

    # Check blocked commands
    if base_cmd in BLOCKED_COMMANDS:
        return False, f"Command '/{base_cmd}' is not available in batch mode"

    # Check interactive commands
    if full_cmd in INTERACTIVE_COMMANDS:
        return (
            False,
            f"Command '/{full_cmd}' requires interactive input and cannot run in batch mode",
        )

    return True, None


async def _execute_slash_command(
    ctx: SharedContext,
    cmd: str,
) -> TaskResult:
    """
    Execute a slash command and return a TaskResult.

    Args:
        ctx: Shared context.
        cmd: Command string starting with "/".

    Returns:
        TaskResult with command execution result.
    """
    from merlya.commands import get_registry

    registry = get_registry()

    # Check if command is allowed
    allowed, error_msg = _check_command_allowed(cmd)
    if not allowed:
        return TaskResult(
            task=cmd,
            success=False,
            message=error_msg or "Command not allowed",
            actions=[],
            task_type="command",
        )

    # Execute the command
    result = await registry.execute(ctx, cmd)

    if result is None:
        return TaskResult(
            task=cmd,
            success=False,
            message="Command not found or returned no result",
            actions=[],
            task_type="command",
        )

    # Build TaskResult from CommandResult
    return TaskResult(
        task=cmd,
        success=result.success,
        message=result.message,
        actions=["command_execute"],
        data=result.data,
        task_type="command",
    )


async def run_batch(
    commands: list[str],
    *,
    auto_confirm: bool = False,
    quiet: bool = False,
    output_format: str = "text",
    verbose: bool = False,
) -> BatchResult:
    """
    Execute commands in non-interactive batch mode.

    Args:
        commands: List of commands to execute.
        auto_confirm: Skip confirmation prompts.
        quiet: Minimal output.
        output_format: Output format (text/json).
        verbose: Enable verbose logging.

    Returns:
        BatchResult with execution results.
    """
    from merlya.agent import MerlyaAgent
    from merlya.commands import init_commands
    from merlya.core.context import SharedContext
    from merlya.health import run_startup_checks
    from merlya.secrets import load_api_keys_from_keyring

    # Initialize commands
    init_commands()

    # Create context with non-interactive flags
    ctx = await SharedContext.create()
    ctx.auto_confirm = auto_confirm
    ctx.quiet = quiet
    ctx.output_format = output_format

    # Load API keys from keyring into environment
    load_api_keys_from_keyring(ctx.config, ctx.secrets)

    # Configure logging level
    if verbose:
        logger.enable("merlya")
    elif quiet:
        logger.disable("merlya")

    # Load skills BEFORE health checks (required for skill matching)
    try:
        from merlya.skills import SkillLoader

        loader = SkillLoader()
        loader.load_all()
        logger.debug("Skills loaded for batch mode")
    except Exception as e:
        logger.debug(f"Skills loading skipped: {e}")

    # Run health checks (only show in debug mode)
    is_debug = ctx.config.logging.console_level == "debug"

    if not quiet and is_debug:
        ctx.ui.info("Running health checks...")

    health = await run_startup_checks()
    ctx.health = health

    if not health.can_start:
        if output_format == "json":
            print(json.dumps({"success": False, "error": "Health checks failed"}))
        else:
            ctx.ui.error("Cannot start: critical checks failed")
        return BatchResult(success=False, tasks=[], total=0, passed=0, failed=0)

    # Initialize router
    await ctx.init_router(health.model_tier)

    # Create agent
    model = f"{ctx.config.model.provider}:{ctx.config.model.model}"
    agent = MerlyaAgent(ctx, model=model)

    results: list[TaskResult] = []
    passed = 0
    failed = 0

    try:
        for cmd in commands:
            if not quiet and output_format == "text":
                ctx.ui.info(f"Executing: {cmd}")

            try:
                # Check if this is a slash command
                if cmd.startswith("/"):
                    # Execute slash command directly
                    task_result = await _execute_slash_command(ctx, cmd)
                else:
                    # Route and execute via agent
                    if not ctx.router:
                        raise RuntimeError("Router not initialized")
                    route_result = await ctx.router.route(cmd)

                    response = await agent.run(cmd, route_result)

                    task_result = TaskResult(
                        task=cmd,
                        success=True,
                        message=response.message,
                        actions=response.actions_taken or [],
                        task_type="agent",
                    )

                # Track results
                results.append(task_result)
                if task_result.success:
                    passed += 1
                else:
                    failed += 1

                # Display output
                if output_format == "text" and not quiet:
                    if task_result.success:
                        ctx.ui.markdown(task_result.message)
                    else:
                        ctx.ui.error(task_result.message)
                    ctx.ui.newline()

            except Exception as e:
                logger.error(f"Task failed: {cmd} - {e}")
                task_result = TaskResult(
                    task=cmd,
                    success=False,
                    message=str(e),
                    actions=[],
                )
                results.append(task_result)
                failed += 1

                if output_format == "text":
                    ctx.ui.error(f"Failed: {e}")
    finally:
        # Cleanup - always runs even if exception occurs
        await ctx.close()

    batch_result = BatchResult(
        success=failed == 0,
        tasks=results,
        total=len(commands),
        passed=passed,
        failed=failed,
    )

    # Output final result
    if output_format == "json":
        print(json.dumps(batch_result.to_dict(), indent=2))
    elif not quiet:
        ctx.ui.newline()
        status = "success" if batch_result.success else "error"
        ctx.ui.print(f"[{status}]Completed: {passed}/{len(commands)} tasks passed[/{status}]")

    return batch_result


def load_tasks_from_file(file_path: str) -> list[str]:
    """
    Load tasks from a YAML or text file.

    YAML format:
        tasks:
          - description: "Check disk space"
            prompt: "Check disk space on all web servers"
          - prompt: "List running services"

    Text format (one command per line):
        Check disk space on all web servers
        List running services

    Args:
        file_path: Path to the task file.

    Returns:
        List of command strings.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Task file not found: {file_path}")

    content = path.read_text()

    # Try YAML first
    if path.suffix in (".yml", ".yaml"):
        data = yaml.safe_load(content)
        # Handle None/empty YAML files
        if data is None:
            return []
        if isinstance(data, dict) and "tasks" in data:
            tasks = []
            for task in data["tasks"]:
                if isinstance(task, str):
                    tasks.append(task)
                elif isinstance(task, dict):
                    prompt = task.get("prompt") or task.get("description") or ""
                    tasks.append(str(prompt))
                # Skip invalid task entries (numbers, None, etc.)
            return [t for t in tasks if t]
        elif isinstance(data, list):
            return [str(item) for item in data if item]

    # Fall back to text (one command per line)
    commands: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        commands.append(stripped)
    return commands


async def run_single(
    command: str,
    *,
    auto_confirm: bool = False,
    quiet: bool = False,
    output_format: str = "text",
    verbose: bool = False,
) -> int:
    """
    Execute a single command and return exit code.

    Args:
        command: The command to execute.
        auto_confirm: Skip confirmation prompts.
        quiet: Minimal output.
        output_format: Output format (text/json).
        verbose: Enable verbose logging.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    result = await run_batch(
        [command],
        auto_confirm=auto_confirm,
        quiet=quiet,
        output_format=output_format,
        verbose=verbose,
    )
    return 0 if result.success else 1


async def run_from_file(
    file_path: str,
    *,
    auto_confirm: bool = False,
    quiet: bool = False,
    output_format: str = "text",
    verbose: bool = False,
) -> int:
    """
    Execute tasks from a file and return exit code.

    Args:
        file_path: Path to the task file.
        auto_confirm: Skip confirmation prompts.
        quiet: Minimal output.
        output_format: Output format (text/json).
        verbose: Enable verbose logging.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    try:
        tasks = load_tasks_from_file(file_path)
    except FileNotFoundError as e:
        if output_format == "json":
            print(json.dumps({"success": False, "error": str(e)}))
        else:
            print(f"Error: {e}", file=sys.stderr)
        return 1

    if not tasks:
        if output_format == "json":
            print(json.dumps({"success": False, "error": "No tasks found in file"}))
        else:
            print("Error: No tasks found in file", file=sys.stderr)
        return 1

    result = await run_batch(
        tasks,
        auto_confirm=auto_confirm,
        quiet=quiet,
        output_format=output_format,
        verbose=verbose,
    )
    return 0 if result.success else 1
