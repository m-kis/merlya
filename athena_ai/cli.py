#!/usr/bin/env python3
"""
Athena CLI - Main entry point for the Athena infrastructure orchestration tool.

This module provides:
- Configuration validation and auto-fix
- Environment setup
- REPL launch
"""
import os
import sys
from pathlib import Path

import click
from rich.console import Console

from athena_ai import __version__

console = Console()


def init_interactive():
    """Interactive configuration initialization wizard.

    Separates concerns:
    - .env file: API keys only (secrets)
    - config.json: Provider, models, settings (configuration)
    """
    from rich.prompt import Prompt

    from athena_ai.llm.model_config import ModelConfig

    config_dir = Path.home() / ".athena"
    env_file = config_dir / ".env"

    config_dir.mkdir(parents=True, exist_ok=True)

    console.print("\n[bold]Configure AI Provider[/bold]\n")
    console.print("Available providers:")
    console.print("  1. OpenRouter (recommended - multiple models)")
    console.print("  2. Anthropic (direct)")
    console.print("  3. OpenAI (GPT models)")
    console.print("  4. Ollama (local models)")

    choice = Prompt.ask("Select provider", choices=["1", "2", "3", "4"], default="1")

    # ✅ NEW: Separate env_content (secrets) and config (settings)
    env_content = []  # Only API keys
    provider = None
    model = None

    if choice == "1":
        api_key = Prompt.ask("Enter OpenRouter API key")
        model = Prompt.ask("Model", default="anthropic/claude-3.5-sonnet")
        # ✅ Only API key in .env
        env_content.append(f"OPENROUTER_API_KEY={api_key}")
        provider = "openrouter"

    elif choice == "2":
        api_key = Prompt.ask("Enter Anthropic API key")
        # ✅ Only API key in .env
        env_content.append(f"ANTHROPIC_API_KEY={api_key}")
        provider = "anthropic"
        model = "claude-3-5-sonnet-20241022"  # Default

    elif choice == "3":
        api_key = Prompt.ask("Enter OpenAI API key")
        # ✅ Only API key in .env
        env_content.append(f"OPENAI_API_KEY={api_key}")
        provider = "openai"
        model = "gpt-4o"  # Default

    elif choice == "4":
        model = Prompt.ask("Ollama model", default="llama3.2")
        provider = "ollama"
        # No API key needed for Ollama

    # ✅ Write .env file (API keys ONLY)
    with open(env_file, "w") as f:
        f.write("\n".join(env_content) + "\n")

    console.print(f"\n[green]✅ API keys saved to {env_file}[/green]")

    # ✅ Write config.json (provider + model)
    model_config = ModelConfig()
    model_config.set_provider(provider)
    if model:
        model_config.set_model(provider, model)

    console.print(f"[green]✅ Configuration saved to {model_config.config_file}[/green]")

    # Reload environment (API keys only)
    for line in env_content:
        if "=" in line:
            key, value = line.split("=", 1)
            os.environ[key] = value


def validate_and_fix_config() -> bool:
    """Validate configuration and fix issues if needed."""
    try:
        from athena_ai.utils.config_validator import ConfigValidator
        validator = ConfigValidator()

        if not validator.check_all():
            console.print("\n[yellow]System is not fully configured.[/yellow]")
            console.print("Starting auto-fix wizard...\n")

            if validator.fix_issues():
                console.print("\n[green]Configuration fixed![/green]")
                return True
            else:
                console.print("\n[red]Setup cancelled or failed.[/red]")
                return False
        return True

    except ImportError as e:
        console.print("[red]Critical Error: Could not import Athena components.[/red]")
        console.print(f"Error: {e}")
        console.print("Ensure you are running this from the project root.")
        return False


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="athena")
@click.option('--env', '-e', default=None, help='Environment (dev/staging/prod)')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
@click.option('--debug', '-d', is_flag=True, help='Enable debug output')
@click.pass_context
def cli(ctx, env, verbose, debug):
    """
    Athena - AI-Powered Infrastructure Orchestration.

    Run without arguments to start the interactive REPL.
    """
    ctx.ensure_object(dict)
    ctx.obj['env'] = env or os.getenv("ATHENA_ENV", "dev")
    ctx.obj['verbose'] = verbose
    ctx.obj['debug'] = debug

    # Configure logging - must be called early to prevent console spam
    # Generate a session ID for log deduplication in multi-instance scenarios
    import datetime
    session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]  # Include milliseconds
    from athena_ai.utils.logger import setup_logger
    setup_logger(verbose=debug or verbose, session_id=session_id)

    # Set verbosity level for UI components
    if debug or verbose:
        from athena_ai.utils.verbosity import VerbosityLevel, get_verbosity
        v = get_verbosity()
        if debug:
            v.set_level(VerbosityLevel.DEBUG)
        elif verbose:
            v.set_level(VerbosityLevel.VERBOSE)

    # If no subcommand, launch REPL
    if ctx.invoked_subcommand is None:
        _launch_repl(ctx.obj['env'])


def _launch_repl(env: str):
    """Launch the interactive REPL."""
    console.print(f"\n[bold cyan]Athena[/bold cyan] [dim]v{__version__}[/dim]")
    console.print("[dim]Type /help for commands, /exit to quit[/dim]\n")

    # Validate configuration
    if not validate_and_fix_config():
        sys.exit(1)

    # Readiness Check: FalkorDB
    try:
        from athena_ai.knowledge.falkordb_client import get_falkordb_client
        kg = get_falkordb_client()
        # Attempt to connect - the client doesn't auto-connect on creation
        if not kg.connect():
            console.print("[yellow]⚠️  Warning: FalkorDB is not reachable.[/yellow]")
            console.print("[dim]   Knowledge graph features will be disabled.[/dim]")
            console.print("[dim]   Ensure FalkorDB is running: docker run -p 6379:6379 -it --rm falkordb/falkordb[/dim]\n")
        else:
            console.print("[green]✅ FalkorDB connected[/green]")
    except ImportError:
        # falkordb package not installed - skip silently
        pass
    except Exception as e:
        # Log the error but don't crash
        console.print(f"[yellow]⚠️  Warning: FalkorDB check failed: {e}[/yellow]")

    # Launch REPL
    try:
        from athena_ai.repl import start_repl
        start_repl(env=env)

    except KeyboardInterrupt:
        console.print("\n[yellow]Goodbye![/yellow]")
    except Exception as e:
        console.print(f"\n[red]Fatal Error: {e}[/red]")
        if os.getenv("ATHENA_DEBUG"):
            import traceback
            traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.argument('query', nargs=-1)
@click.option('--target', '-t', help='Target host(s)')
@click.option('--dry-run', is_flag=True, help='Preview without executing')
@click.pass_context
def run(ctx, query, target, dry_run):
    """
    Run a single command/query without entering the REPL.

    Example: athena run "check nginx status on webserver"
    """
    if not query:
        console.print("[red]Error: Please provide a query[/red]")
        sys.exit(1)

    query_str = " ".join(query)

    # Validate configuration first
    if not validate_and_fix_config():
        sys.exit(1)

    # Run the query
    try:
        from athena_ai.repl import AthenaREPL

        repl = AthenaREPL(env=ctx.obj['env'])

        import asyncio
        result = asyncio.run(repl.process_single_query(
            query_str,
            target=target,
            dry_run=dry_run
        ))

        if result:
            console.print(result)

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.pass_context
def status(ctx):
    """Show system status and configuration."""
    console.print("\n[bold]Athena Status[/bold]\n")

    # Environment
    console.print(f"  Environment: [cyan]{ctx.obj['env']}[/cyan]")

    # Configuration
    try:
        from athena_ai.utils.config_validator import ConfigValidator
        validator = ConfigValidator()

        checks = validator.get_status()
        for name, ok in checks.items():
            status = "[green]OK[/green]" if ok else "[red]Missing[/red]"
            console.print(f"  {name}: {status}")

    except Exception as e:
        console.print(f"  [red]Error checking status: {e}[/red]")

    # Host registry
    try:
        from athena_ai.context import get_host_registry
        registry = get_host_registry()
        host_count = len(registry.list_hosts())
        console.print(f"  Registered hosts: [cyan]{host_count}[/cyan]")
    except Exception:
        console.print("  Registered hosts: [yellow]Unknown[/yellow]")

    console.print()


@cli.command()
def version():
    """Show version information."""
    console.print(f"Athena v{__version__}")


@cli.command()
@click.pass_context
def setup(ctx):
    """Run the configuration setup wizard."""
    console.print("\n[bold]Athena Setup Wizard[/bold]\n")

    try:
        from athena_ai.utils.config_validator import ConfigValidator
        validator = ConfigValidator()
        validator.fix_issues()

    except Exception as e:
        console.print(f"[red]Setup error: {e}[/red]")
        sys.exit(1)


def main():
    """Entry point for the athena CLI."""
    cli()


if __name__ == "__main__":
    main()
