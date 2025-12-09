"""
Non-interactive batch execution for Merlya.

Handles `merlya run` command for automated tasks.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml
from loguru import logger


@dataclass
class TaskResult:
    """Result of a task execution."""

    task: str
    success: bool
    message: str
    actions: list[str]


@dataclass
class BatchResult:
    """Result of batch execution."""

    success: bool
    tasks: list[TaskResult]
    total: int
    passed: int
    failed: int


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

    # Run health checks (minimal output in quiet mode)
    if not quiet:
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
                # Route the command
                if not ctx.router:
                    raise RuntimeError("Router not initialized")
                route_result = await ctx.router.route(cmd)

                # Execute via agent
                response = await agent.run(cmd, route_result)

                task_result = TaskResult(
                    task=cmd,
                    success=True,
                    message=response.message,
                    actions=response.actions_taken or [],
                )
                results.append(task_result)
                passed += 1

                if output_format == "text" and not quiet:
                    ctx.ui.markdown(response.message)
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
        output = {
            "success": batch_result.success,
            "total": batch_result.total,
            "passed": batch_result.passed,
            "failed": batch_result.failed,
            "tasks": [asdict(t) for t in batch_result.tasks],
        }
        print(json.dumps(output, indent=2))
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
    return [line.strip() for line in content.splitlines() if line.strip()]


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
