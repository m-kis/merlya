"""
Merlya CLI - Command line interface.

Main entry point for the Merlya application.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
import sys

from loguru import logger

from merlya import __version__ as MERLYA_VERSION
from merlya.tools.core.bash import kill_all_subprocesses

# Disable tokenizers parallelism warnings in forked processes
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def _setup_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    """Setup signal handlers for graceful shutdown.

    We use signal.signal for immediate signal handling that bypasses the asyncio
    event loop. This ensures synchronous signal processing even when prompt_toolkit
    or Rich spinners are active, but does not integrate with async operations.
    The handler kills subprocesses immediately and schedules task cancellation
    on the event loop via call_soon_threadsafe.
    """
    _cancel_flag: list[bool] = [False]

    def handle_signal_sync(signum: int, _frame: object) -> None:
        """Synchronous signal handler - runs immediately when signal received."""
        if _cancel_flag[0]:
            # Second signal: force exit
            logger.warning("Forced shutdown (second signal)")
            # Force kill all subprocesses before exit
            with contextlib.suppress(Exception):
                kill_all_subprocesses()
            os._exit(1)  # Use os._exit for immediate termination

        _cancel_flag[0] = True
        logger.debug(f"Received signal {signum}, killing subprocesses...")

        # CRITICAL: Kill subprocesses IMMEDIATELY (synchronous)
        # This ensures blocked I/O operations are interrupted right away
        try:
            killed = kill_all_subprocesses()
            if killed:
                logger.debug(f"Killed {killed} subprocess(es)")
        except Exception as e:
            logger.debug(f"Error killing subprocesses: {e}")

        # Schedule task cancellation on the event loop
        # This is thread-safe and will be processed when the loop next iterates
        loop.call_soon_threadsafe(_cancel_all_tasks, loop)

    def _cancel_all_tasks(loop: asyncio.AbstractEventLoop) -> None:
        """Cancel all running tasks."""
        for task in asyncio.all_tasks(loop):
            if not task.done():
                task.cancel()

    # Setup signal handlers
    if sys.platform != "win32":
        # Use signal.signal for immediate handling (bypasses event loop)
        signal.signal(signal.SIGINT, handle_signal_sync)
        signal.signal(signal.SIGTERM, handle_signal_sync)


def create_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="merlya",
        description="AI-powered infrastructure management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  merlya                                    Interactive REPL mode
  merlya run "Check disk space"             Execute single command
  merlya run --file tasks.yml               Execute from file
  merlya run --yes "Restart nginx"          Skip confirmations
  merlya config set model.provider openai   Set LLM provider
  merlya config set model.model gpt-4o      Set LLM model
  merlya config show                        Show all settings

LLM Providers: openrouter (default), anthropic, openai, mistral, groq, ollama
Documentation: https://merlya.m-kis.fr/
        """,
    )

    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {MERLYA_VERSION}",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--debug-http",
        action="store_true",
        help="Enable HTTP request/response debugging (useful for API issues)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run subcommand
    run_parser = subparsers.add_parser(
        "run",
        help="Execute commands in non-interactive mode",
        description="Execute infrastructure tasks without interactive prompts",
    )
    run_parser.add_argument(
        "task",
        nargs="?",
        help="Task/command to execute",
    )
    run_parser.add_argument(
        "-f",
        "--file",
        metavar="FILE",
        help="Load tasks from YAML or text file",
    )
    run_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompts (auto-confirm)",
    )
    run_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    run_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Show only results, minimal output",
    )

    # config subcommand
    config_parser = subparsers.add_parser(
        "config",
        help="Manage configuration",
        description="View or modify Merlya configuration",
    )
    config_subparsers = config_parser.add_subparsers(dest="config_action")

    # config set
    config_set_parser = config_subparsers.add_parser(
        "set",
        help="Set a configuration value",
    )
    config_set_parser.add_argument(
        "key",
        help="Configuration key (e.g., llm.provider, logging.level)",
    )
    config_set_parser.add_argument(
        "value",
        help="Value to set",
    )

    # config get
    config_get_parser = config_subparsers.add_parser(
        "get",
        help="Get a configuration value",
    )
    config_get_parser.add_argument(
        "key",
        help="Configuration key to retrieve",
    )

    # config show
    config_subparsers.add_parser(
        "show",
        help="Show all configuration",
    )

    return parser


def run_repl_mode(verbose: bool = False, debug_http: bool = False) -> None:
    """Run interactive REPL mode."""
    from merlya.core.logging import configure_logging, enable_http_debug
    from merlya.repl import run_repl

    configure_logging(console_level="DEBUG" if verbose else "INFO")

    if debug_http:
        enable_http_debug()

    async def _run_with_cleanup() -> None:
        """Run REPL with proper cleanup on interruption."""
        try:
            await run_repl()
        except asyncio.CancelledError:
            logger.debug("REPL cancelled, cleaning up...")
        finally:
            # Ensure cleanup happens
            from merlya.core.context import SharedContext

            try:
                ctx = SharedContext.get_instance()
                if ctx:
                    await ctx.close()
            except RuntimeError:
                # Context already closed or never initialized
                pass
            except Exception as e:
                logger.debug(f"Cleanup error: {e}")

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _setup_signal_handlers(loop)

        try:
            loop.run_until_complete(_run_with_cleanup())
        finally:
            # Cancel any remaining tasks
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()

            # Wait for tasks to complete cancellation
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))

            loop.close()

    except KeyboardInterrupt:
        # This catches interrupts that happen before signal handlers are set
        pass

    logger.info("Goodbye!")
    sys.exit(0)


def run_batch_mode(args: argparse.Namespace) -> None:
    """Run non-interactive batch mode."""
    from merlya.cli.run import run_from_file, run_single
    from merlya.core.logging import configure_logging

    verbose = getattr(args, "verbose", False)
    configure_logging(console_level="DEBUG" if verbose else "INFO")

    if args.file:
        exit_code = asyncio.run(
            run_from_file(
                args.file,
                auto_confirm=args.yes,
                quiet=args.quiet,
                output_format=args.format,
                verbose=verbose,
            )
        )
    elif args.task:
        exit_code = asyncio.run(
            run_single(
                args.task,
                auto_confirm=args.yes,
                quiet=args.quiet,
                output_format=args.format,
                verbose=verbose,
            )
        )
    else:
        print("Error: Either a task or --file is required", file=sys.stderr)
        sys.exit(1)

    sys.exit(exit_code)


def run_config_command(args: argparse.Namespace) -> None:
    """Handle config subcommand."""
    from merlya.config import get_config

    config = get_config()

    if args.config_action == "set":
        _config_set(config, args.key, args.value)
    elif args.config_action == "get":
        _config_get(config, args.key)
    elif args.config_action == "show":
        _config_show(config)
    else:
        print("Usage: merlya config {set,get,show}", file=sys.stderr)
        sys.exit(1)


def _config_set(config: object, key: str, value: str) -> None:
    """Set a configuration value."""
    from merlya.config import Config

    if not isinstance(config, Config):
        print("Error: Invalid config", file=sys.stderr)
        sys.exit(1)

    parts = key.split(".")
    if len(parts) != 2:
        print(f"Error: Invalid key format '{key}'. Use section.key", file=sys.stderr)
        sys.exit(1)

    section, attr = parts

    # Map section names to config attributes
    section_map = {
        "llm": "model",
        "model": "model",
        "logging": "logging",
        "general": "general",
        "ssh": "ssh",
        "router": "router",
    }

    section_name = section_map.get(section)
    if not section_name or not hasattr(config, section_name):
        print(f"Error: Unknown section '{section}'", file=sys.stderr)
        sys.exit(1)

    section_obj = getattr(config, section_name)

    # Handle special keys and aliases
    attr_map = {
        "provider": "provider",
        "api_key": "api_key_env",
        "api_key_env": "api_key_env",
        "model": "model",
        "base_url": "base_url",
        "level": "console_level",  # logging.level -> logging.console_level
        "console_level": "console_level",
        "file_level": "file_level",
        "log_level": "log_level",  # general.log_level (legacy)
        "language": "language",
    }

    attr_name = attr_map.get(attr, attr)

    if not hasattr(section_obj, attr_name):
        print(f"Error: Unknown key '{attr}' in section '{section}'", file=sys.stderr)
        sys.exit(1)

    # Normalize log level values to lowercase
    if attr_name in ("console_level", "file_level", "log_level"):
        value = value.lower()

    setattr(section_obj, attr_name, value)
    config.save()
    print(f"Set {key} = {value}")


def _config_get(config: object, key: str) -> None:
    """Get a configuration value."""
    from merlya.config import Config

    if not isinstance(config, Config):
        print("Error: Invalid config", file=sys.stderr)
        sys.exit(1)

    parts = key.split(".")
    if len(parts) != 2:
        print(f"Error: Invalid key format '{key}'. Use section.key", file=sys.stderr)
        sys.exit(1)

    section, attr = parts
    section_map = {
        "llm": "model",
        "model": "model",
        "logging": "logging",
        "general": "general",
        "ssh": "ssh",
        "router": "router",
    }

    section_name = section_map.get(section)
    if not section_name or not hasattr(config, section_name):
        print(f"Error: Unknown section '{section}'", file=sys.stderr)
        sys.exit(1)

    section_obj = getattr(config, section_name)

    attr_map = {
        "provider": "provider",
        "api_key": "api_key_env",
        "api_key_env": "api_key_env",
        "model": "model",
        "base_url": "base_url",
        "level": "console_level",  # logging.level -> logging.console_level
        "console_level": "console_level",
        "file_level": "file_level",
        "log_level": "log_level",  # general.log_level (legacy)
        "language": "language",
    }

    attr_name = attr_map.get(attr, attr)

    if not hasattr(section_obj, attr_name):
        print(f"Error: Unknown key '{attr}'", file=sys.stderr)
        sys.exit(1)

    value = getattr(section_obj, attr_name)
    print(value)


def _config_show(config: object) -> None:
    """Show all configuration."""
    import yaml

    from merlya.config import Config

    if not isinstance(config, Config):
        print("Error: Invalid config", file=sys.stderr)
        sys.exit(1)

    # Convert to dict for display
    config_dict = {
        "general": {
            "language": config.general.language,
        },
        "model": {
            "provider": config.model.provider,
            "model": config.model.model,
            "api_key_env": config.model.api_key_env,
            "base_url": getattr(config.model, "base_url", None),
        },
        "router": {
            "type": config.router.type,
            "model": config.router.model,
        },
        "ssh": {
            "connect_timeout": config.ssh.connect_timeout,
            "pool_timeout": config.ssh.pool_timeout,
        },
        "logging": {
            "console_level": config.logging.console_level,
            "file_level": config.logging.file_level,
        },
    }

    print(yaml.dump(config_dict, default_flow_style=False))


def main() -> None:
    """Main entry point for merlya CLI."""
    parser = create_parser()
    args = parser.parse_args()

    try:
        if args.command == "run":
            run_batch_mode(args)
        elif args.command == "config":
            run_config_command(args)
        else:
            # Default: interactive REPL mode
            run_repl_mode(
                verbose=getattr(args, "verbose", False),
                debug_http=getattr(args, "debug_http", False),
            )

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
