"""
Model configuration command handlers.

Handles: /model
"""

from rich.table import Table

from athena_ai.repl.ui import console, print_error, print_success


class ModelCommandHandler:
    """Handles model-related slash commands."""

    def __init__(self, repl):
        """Initialize with reference to the main REPL instance."""
        self.repl = repl

    def handle(self, args: list) -> bool:
        """Handle /model command for model configuration."""
        if not args:
            self._show_help()
            return True

        cmd = args[0]

        # Handle embedding subcommand separately (no LLM config needed)
        if cmd == 'embedding':
            self._handle_embedding(args[1:])
            return True

        try:
            if (not hasattr(self.repl, 'orchestrator') or
                not hasattr(self.repl.orchestrator, 'llm_router') or
                not hasattr(self.repl.orchestrator.llm_router, 'model_config')):
                print_error("Model configuration not available")
                return True
            model_config = self.repl.orchestrator.llm_router.model_config
            if cmd == 'show':
                self._show_config(model_config)
            elif cmd == 'local':
                self._handle_local(args[1:], model_config)
            elif cmd == 'list':
                self._list_models(args[1:], model_config)
            elif cmd == 'set':
                self._set_model(args[1:], model_config)
            elif cmd == 'provider' and len(args) >= 2:
                self._set_provider(args[1])
            else:
                self._show_help()

        except ValueError as e:
            print_error(f"Invalid value: {e}")
        except Exception as e:
            print_error(f"Model command failed: {e}")

        return True

    def _show_config(self, model_config):
        """Show current model configuration."""
        config = model_config.get_current_config()
        provider = config['provider']
        model = config['model']

        console.print("\n[bold]🤖 Current Model Configuration[/bold]\n")

        # Provider & Model
        is_local = provider == "ollama"
        provider_display = f"[green]{provider}[/green]" if is_local else f"[cyan]{provider}[/cyan]"
        console.print(f"  Provider: {provider_display}")
        console.print(f"  Model: [green]{model}[/green]")

        # Show task-specific models if configured
        if config.get('task_models'):
            console.print("\n[bold]⚙️ Task Models:[/bold]")
            for task, model_alias in config['task_models'].items():
                console.print(f"  {task}: [yellow]{model_alias}[/yellow]")
        console.print()

    def _handle_local(self, args: list, model_config):
        """Handle /model local subcommand."""
        if not args:
            print_error("Usage: /model local <on|off|set> [model_name]")
            return

        subcmd = args[0].lower()
        if subcmd in ['on', 'true', 'enable']:
            # Switch to Ollama provider using proper encapsulated method
            llm_router = self.repl.orchestrator.llm_router
            if not llm_router.switch_provider("ollama", verify=True):
                print_error("Failed to switch to Ollama - server may not be available")
                return
            if len(args) > 1:
                model_config.set_model("ollama", args[1])
            current_model = model_config.get_model("ollama")
            print_success(f"Switched to Ollama (Model: {current_model})")
            self.repl.orchestrator.reload_agents()

        elif subcmd in ['off', 'false', 'disable']:
            # Switch back to default cloud provider from config
            llm_router = self.repl.orchestrator.llm_router
            default_provider = model_config.config.get("provider", "openrouter")
            # If default is ollama, fall back to openrouter
            if default_provider == "ollama":
                default_provider = "openrouter"
            if not llm_router.switch_provider(default_provider, verify=False):
                print_error(f"Failed to switch to {default_provider}")
                return
            current_model = model_config.get_model(default_provider)
            print_success(f"Switched to {default_provider.title()} (Model: {current_model})")
            self.repl.orchestrator.reload_agents()

        elif subcmd == 'set':
            if len(args) > 1:
                model_config.set_model("ollama", args[1])
                print_success(f"Ollama model set to: {args[1]}")
                self.repl.orchestrator.reload_agents()
            else:
                print_error("Missing model name. Usage: /model local set <model>")
        else:
            print_error(f"Invalid local subcommand: {subcmd}. Use: on, off, set <model>")

    def _list_models(self, args: list, model_config):
        """List available models."""
        provider = args[0] if args else None
        models = model_config.list_models(provider)
        provider_name = provider or model_config.get_provider()

        table = Table(title=f"Available Models - {provider_name}")
        table.add_column("Model", style="cyan")
        for model in models:
            table.add_row(model)
        console.print(table)

    def _set_model(self, args: list, model_config):
        """Set model for provider."""
        if len(args) == 1:
            provider = model_config.get_provider()
            model = args[0]
        elif len(args) >= 2:
            provider = args[0]
            model = args[1]
        else:
            print_error("Usage: /model set <model> OR /model set <provider> <model>")
            return

        model_config.set_model(provider, model)
        print_success(f"Model for {provider} set to: {model}")
        # Reload agents to apply the new model
        self.repl.orchestrator.reload_agents()

    def _set_provider(self, provider: str):
        """Switch provider with validation."""
        llm_router = self.repl.orchestrator.llm_router
        model_config = llm_router.model_config

        # Validate provider against known providers
        valid_providers = list(model_config.AVAILABLE_MODELS.keys())
        if provider not in valid_providers:
            print_error(f"Invalid provider: {provider}. Must be one of: {', '.join(valid_providers)}")
            return

        # Use encapsulated switch_provider method
        # Skip verification for cloud providers (they don't need it)
        verify = (provider == "ollama")
        if not llm_router.switch_provider(provider, verify=verify):
            print_error(f"Failed to switch to {provider}")
            return

        print_success(f"Provider set to: {provider}")
        # Reload agents to apply the new provider
        self.repl.orchestrator.reload_agents()

    def _handle_embedding(self, args: list):
        """Handle /model embedding subcommand for AI features configuration."""
        from athena_ai.triage.embedding_config import (
            AVAILABLE_MODELS,
            get_embedding_config,
        )

        config = get_embedding_config()

        if not args:
            # Show current embedding config
            self._show_embedding_config(config)
            return

        subcmd = args[0].lower()

        if subcmd == 'list':
            # List available embedding models
            table = Table(title="🧠 Available Embedding Models", show_lines=False)
            table.add_column("Model", style="cyan", no_wrap=True, min_width=28)
            table.add_column("Size", style="yellow", justify="right", width=6)
            table.add_column("Dims", style="green", justify="right", width=5)
            table.add_column("Speed", style="blue", width=7)
            table.add_column("Quality", style="magenta", width=7)
            table.add_column("Description", style="dim", overflow="fold")

            for name, info in AVAILABLE_MODELS.items():
                is_current = "→ " if name == config.current_model else "  "
                table.add_row(
                    f"{is_current}{name}",
                    f"{info.size_mb}MB",
                    str(info.dimensions),
                    info.speed,
                    info.quality,
                    info.description,
                )
            console.print(table)

        elif subcmd == 'set' and len(args) > 1:
            # Set embedding model
            model_name = args[1]
            if config.set_model(model_name):
                print_success(f"Embedding model changed to: {model_name}")
                console.print("[dim]ℹ️ Model will be loaded on next AI feature use[/dim]")
            else:
                print_error(f"Unknown model: {model_name}")
                console.print("[dim]Use '/model embedding list' to see available models[/dim]")

        elif subcmd == 'show':
            self._show_embedding_config(config)

        else:
            console.print("[yellow]Embedding Usage:[/yellow]")
            console.print("  /model embedding - Show current embedding model")
            console.print("  /model embedding list - List available models")
            console.print("  /model embedding set <model> - Set embedding model")

    def _show_embedding_config(self, config):
        """Show current embedding model configuration."""
        info = config.model_info

        console.print("\n[bold]🧠 Embedding Model Configuration[/bold]\n")
        console.print(f"  Current Model: [cyan]{config.current_model}[/cyan]")
        console.print(f"  Size: [yellow]{info.size_mb}MB[/yellow]")
        console.print(f"  Dimensions: [green]{info.dimensions}[/green]")
        console.print(f"  Speed: [blue]{info.speed}[/blue]")
        console.print(f"  Quality: [magenta]{info.quality}[/magenta]")
        console.print(f"  Description: [dim]{info.description}[/dim]")
        console.print()
        console.print("[dim]ℹ️ Used for: Triage classification, Tool selection, Error analysis[/dim]")
        console.print("[dim]📝 Tip: Set via ATHENA_EMBEDDING_MODEL env var for persistence[/dim]")
        console.print()

    def _show_help(self):
        """Show help for /model command."""
        console.print("[yellow]Usage:[/yellow]")
        console.print("  /model show - Show current LLM configuration")
        console.print("  /model local <on|off|set> [model] - Enable/Disable/Configure local LLM (Ollama)")
        console.print("  /model list [provider] - List available LLM models")
        console.print("  /model set [provider] <model> - Set LLM model for provider")
        console.print("  /model provider <provider> - Switch cloud provider")
        console.print()
        console.print("[yellow]Embedding Models (AI features):[/yellow]")
        console.print("  /model embedding - Show current embedding model")
        console.print("  /model embedding list - List available embedding models")
        console.print("  /model embedding set <model> - Set embedding model")
