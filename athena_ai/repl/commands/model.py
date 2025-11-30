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
            if not hasattr(self.repl, 'orchestrator'):
                print_error("Orchestrator not initialized")
                return True
            if not hasattr(self.repl.orchestrator, 'llm_router'):
                print_error("LLM router not initialized")
                return True
            if not hasattr(self.repl.orchestrator.llm_router, 'model_config'):
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
            elif cmd == 'task':
                self._handle_task(args[1:], model_config)
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
                model_name = args[1]
                # Check if model exists, offer to download if not
                if not self._handle_ollama_model_setup(model_name):
                    return  # User cancelled or download failed
                model_config.set_model("ollama", model_name)
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
                model_name = args[1]
                # Check if model exists, offer to download if not
                if self._handle_ollama_model_setup(model_name):
                    model_config.set_model("ollama", model_name)
                    print_success(f"Ollama model set to: {model_name}")
                    self.repl.orchestrator.reload_agents()
            else:
                print_error("Missing model name. Usage: /model local set <model>")
        else:
            print_error(f"Invalid local subcommand: {subcmd}. Use: on, off, set <model>")

    def _list_models(self, args: list, model_config):
        """List available models."""
        provider = args[0] if args else None

        # Special handling for Ollama: Query actual server for available models
        if provider == "ollama" or (not provider and model_config.get_provider() == "ollama"):
            from athena_ai.llm.ollama_client import get_ollama_client
            from athena_ai.repl.ui import print_error, print_warning
            ollama_client = get_ollama_client()

            if not ollama_client.is_available():
                print_error("Ollama server is not available")
                console.print(f"[dim]ℹ️ Make sure Ollama is running at {ollama_client.base_url}[/dim]")
                console.print("[dim]ℹ️ Install: https://ollama.ai[/dim]")
                return

            ollama_models = ollama_client.list_models(refresh=True)
            if not ollama_models:
                print_warning("No Ollama models found")
                console.print("[dim]ℹ️ Pull a model first: ollama pull llama3.2[/dim]")
                return

            table = Table(title="🦙 Available Ollama Models")
            table.add_column("Model", style="cyan", no_wrap=True)
            table.add_column("Size", style="yellow", justify="right")
            table.add_column("Modified", style="dim")

            for model in ollama_models:
                table.add_row(
                    model.name,
                    model.display_size,
                    model.modified_at[:10]  # Just the date
                )
            console.print(table)
            total_size = sum(m.size_gb for m in ollama_models)
            console.print(f"\n[dim]Total: {len(ollama_models)} models ({total_size:.1f} GB)[/dim]")
            return

        # Default behavior for cloud providers
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
            # Check if user meant "/model provider <name>" instead of "/model set provider <name>"
            if args[0] == "provider":
                valid_providers = list(model_config.AVAILABLE_MODELS.keys())
                if args[1] in valid_providers:
                    console.print(
                        f"[yellow]⚠️ Did you mean '/model provider {args[1]}'?[/yellow]\n"
                        f"   Use '/model provider <name>' to switch providers.\n"
                        f"   Use '/model set <model>' to change the model."
                    )
                    return
            provider = args[0]
            model = args[1]
        else:
            print_error("Usage: /model set <model> OR /model set <provider> <model>")
            return

        # Special handling for Ollama: check if model exists, offer to download if not
        if provider == "ollama":
            if not self._handle_ollama_model_setup(model):
                return  # User cancelled or download failed

        model_config.set_model(provider, model)
        print_success(f"Model for {provider} set to: {model}")
        # Reload agents to apply the new model
        self.repl.orchestrator.reload_agents()

    def _handle_ollama_model_setup(self, model_name: str) -> bool:
        """
        Handle Ollama model setup: check if model exists, offer to download if not.

        Args:
            model_name: Name of the Ollama model

        Returns:
            True if model is ready to use, False if user cancelled or download failed
        """
        from athena_ai.llm.ollama_client import get_ollama_client

        ollama_client = get_ollama_client()

        # Check if Ollama is available
        if not ollama_client.is_available():
            print_error("Ollama server is not available")
            console.print(f"[dim]ℹ️ Make sure Ollama is running at {ollama_client.base_url}[/dim]")
            console.print("[dim]ℹ️ Install: https://ollama.ai[/dim]")
            return False

        # Check if model is already downloaded
        if ollama_client.has_model(model_name):
            console.print(f"[dim]✅ Model '{model_name}' is already available[/dim]")
            return True

        # Model not found - offer to download
        console.print(f"[yellow]⚠️ Model '{model_name}' is not downloaded yet[/yellow]")
        console.print(f"[dim]Would you like to download it now?[/dim]")

        # Prompt user for confirmation
        try:
            from prompt_toolkit import prompt
            response = prompt("Download model? [Y/n]: ").strip().lower()
            if response in ['n', 'no']:
                console.print("[dim]Model not downloaded. You can download it manually with:[/dim]")
                console.print(f"[dim]  ollama pull {model_name}[/dim]")
                return False
        except (ImportError, EOFError, KeyboardInterrupt):
            # Fallback if prompt_toolkit not available or user interrupts
            console.print("[yellow]Skipping download. Download manually with:[/yellow]")
            console.print(f"[dim]  ollama pull {model_name}[/dim]")
            return False

        # Download the model
        console.print(f"[dim]⏳ Downloading model '{model_name}'...[/dim]")
        console.print("[dim]   This may take a few minutes depending on model size[/dim]")

        if ollama_client.pull_model(model_name):
            console.print(f"[dim]✅ Model '{model_name}' downloaded successfully![/dim]")
            return True
        else:
            print_error(f"Failed to download model '{model_name}'")
            console.print("[dim]You can try downloading manually with:[/dim]")
            console.print(f"[dim]  ollama pull {model_name}[/dim]")
            return False

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

    def _handle_task(self, args: list, model_config):
        """Handle /model task subcommand for task-specific routing."""
        if not args:
            # Show current task model configuration
            task_models = model_config.get_task_models()
            if not task_models:
                console.print("[yellow]No task-specific models configured[/yellow]")
                console.print("[dim]Use '/model task set <task> <model>' to configure[/dim]")
                return

            table = Table(title="⚙️ Task-Specific Model Configuration")
            table.add_column("Task", style="cyan", no_wrap=True)
            table.add_column("Model/Alias", style="yellow")
            table.add_column("Description", style="dim")

            task_descriptions = {
                "correction": "Fast corrections (simple, cheap)",
                "planning": "Complex planning (powerful, expensive)",
                "synthesis": "General synthesis (balanced)",
            }

            for task, model in task_models.items():
                desc = task_descriptions.get(task, "Custom task")
                table.add_row(task, model, desc)

            console.print(table)
            console.print("\n[dim]💡 Use aliases (haiku/sonnet/opus) or full model paths[/dim]")
            return

        subcmd = args[0].lower()

        if subcmd == 'set' and len(args) >= 3:
            task = args[1]
            model = args[2]
            try:
                model_config.set_task_model(task, model)
                print_success(f"Task '{task}' will now use: {model}")
                # Reload agents to apply changes
                self.repl.orchestrator.reload_agents()
            except ValueError as e:
                print_error(str(e))

        elif subcmd == 'list':
            # List valid tasks and their current configuration
            console.print("\n[bold]Valid Tasks:[/bold]")
            console.print("  • correction - Fast corrections (typos, simple fixes)")
            console.print("  • planning   - Complex reasoning (architecture, design)")
            console.print("  • synthesis  - General tasks (balanced workload)")
            console.print("\n[bold]Model Aliases:[/bold]")
            console.print("  • haiku  - Fastest, cheapest (Claude Haiku or GPT-4o-mini)")
            console.print("  • sonnet - Balanced (Claude Sonnet or GPT-4o)")
            console.print("  • opus   - Most capable (Claude Opus or GPT-4o-latest)")
            console.print("\n[dim]Or use full model path: meta-llama/llama-3.1-70b-instruct[/dim]")

        elif subcmd == 'reset':
            # Reset to defaults
            model_config.config["task_models"] = model_config.TASK_MODELS.copy()
            model_config.save_config()
            print_success("Task models reset to defaults")
            self.repl.orchestrator.reload_agents()

        else:
            console.print("[yellow]Task Model Usage:[/yellow]")
            console.print("  /model task - Show current task configuration")
            console.print("  /model task list - List valid tasks and aliases")
            console.print("  /model task set <task> <model> - Set model for task")
            console.print("  /model task reset - Reset to defaults")
            console.print("\n[yellow]Examples:[/yellow]")
            console.print("  /model task set correction haiku")
            console.print("  /model task set planning opus")
            console.print("  /model task set synthesis meta-llama/llama-3.1-70b-instruct")

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

            # Always succeeds now (allows custom models)
            config.set_model(model_name)

            # Check if it's a custom model (not in recommended list)
            from athena_ai.triage.embedding_config import AVAILABLE_MODELS
            if model_name not in AVAILABLE_MODELS:
                console.print(f"[yellow]⚠️ Using custom model:[/yellow] [cyan]{model_name}[/cyan]")
                console.print("[dim]   This model will be downloaded from HuggingFace.[/dim]")
                console.print("[dim]   Use '/model embedding list' to see recommended models.[/dim]")

            print_success(f"Embedding model changed to: {model_name}")

            # Download model immediately
            console.print("[dim]⏳ Downloading model...[/dim]")
            try:
                from athena_ai.triage.smart_classifier.embedding_cache import (
                    EmbeddingCache,
                    HAS_EMBEDDINGS,
                )

                if not HAS_EMBEDDINGS:
                    console.print("[yellow]⚠️ sentence-transformers not installed[/yellow]")
                    console.print("[dim]Install with: pip install sentence-transformers[/dim]")
                else:
                    # Force download by creating a cache and accessing the model
                    cache = EmbeddingCache(model_name=model_name)
                    _ = cache.model  # This triggers the download
                    console.print("[dim]✅ Model downloaded and ready to use[/dim]")
            except Exception as e:
                print_error(f"Failed to download model: {e}")
                console.print("[dim]ℹ️ Model will be loaded on next AI feature use[/dim]")
                console.print("[dim]💡 Make sure the model exists on HuggingFace Hub[/dim]")

        elif subcmd == 'show':
            self._show_embedding_config(config)

        else:
            console.print("[yellow]Embedding Usage:[/yellow]")
            console.print("  /model embedding - Show current embedding model")
            console.print("  /model embedding list - List available models")
            console.print("  /model embedding set <model> - Set embedding model")

    def _show_embedding_config(self, config):
        """Show current embedding model configuration."""
        from athena_ai.triage.embedding_config import AVAILABLE_MODELS

        console.print("\n[bold]🧠 Embedding Model Configuration[/bold]\n")
        console.print(f"  Current Model: [cyan]{config.current_model}[/cyan]")

        # Check if it's a custom model
        if config.current_model in AVAILABLE_MODELS:
            info = config.model_info
            console.print(f"  Size: [yellow]{info.size_mb}MB[/yellow]")
            console.print(f"  Dimensions: [green]{info.dimensions}[/green]")
            console.print(f"  Speed: [blue]{info.speed}[/blue]")
            console.print(f"  Quality: [magenta]{info.quality}[/magenta]")
            console.print(f"  Description: [dim]{info.description}[/dim]")
        else:
            console.print(f"  [yellow]Custom Model[/yellow] (from HuggingFace)")
            console.print(f"  [dim]Model specs will be determined on first load[/dim]")

        console.print()
        console.print("[dim]ℹ️ Used for: Triage classification, Tool selection, Error analysis[/dim]")
        console.print("[dim]📝 Tip: Set via ATHENA_EMBEDDING_MODEL env var for persistence[/dim]")
        console.print("[dim]💡 You can use any HuggingFace model compatible with sentence-transformers[/dim]")
        console.print()

    def _show_help(self):
        """Show help for /model command."""
        console.print("\n[bold cyan]🤖 Model Configuration Commands[/bold cyan]\n")

        console.print("[yellow]━━━ LLM Configuration ━━━[/yellow]")
        console.print("  [cyan]/model show[/cyan]")
        console.print("    Show current LLM provider and model")
        console.print()
        console.print("  [cyan]/model provider <provider>[/cyan]")
        console.print("    Switch between providers (openrouter, anthropic, openai, ollama)")
        console.print()
        console.print("  [cyan]/model set <model>[/cyan] or [cyan]/model set <provider> <model>[/cyan]")
        console.print("    Set model for current or specified provider")
        console.print()
        console.print("  [cyan]/model list [provider][/cyan]")
        console.print("    List available models for provider")
        console.print()

        console.print("[yellow]━━━ Local Models (Ollama) ━━━[/yellow]")
        console.print("  [cyan]/model local on [model][/cyan]")
        console.print("    Enable Ollama and optionally set model")
        console.print("    [dim]→ Auto-downloads model if not available[/dim]")
        console.print()
        console.print("  [cyan]/model local off[/cyan]")
        console.print("    Switch back to cloud provider")
        console.print()
        console.print("  [cyan]/model local set <model>[/cyan]")
        console.print("    Set Ollama model (auto-downloads if needed)")
        console.print()

        console.print("[yellow]━━━ Task-Specific Routing ━━━[/yellow]")
        console.print("  [cyan]/model task[/cyan]")
        console.print("    Show current task-specific model configuration")
        console.print()
        console.print("  [cyan]/model task list[/cyan]")
        console.print("    List valid tasks and model aliases")
        console.print()
        console.print("  [cyan]/model task set <task> <model>[/cyan]")
        console.print("    Set model for specific task (correction/planning/synthesis)")
        console.print("    [dim]→ Use aliases: haiku (fast), sonnet (balanced), opus (powerful)[/dim]")
        console.print()
        console.print("  [cyan]/model task reset[/cyan]")
        console.print("    Reset task models to defaults")
        console.print()

        console.print("[yellow]━━━ Embedding Models (AI Features) ━━━[/yellow]")
        console.print("  [cyan]/model embedding[/cyan] or [cyan]/model embedding show[/cyan]")
        console.print("    Show current embedding model configuration")
        console.print()
        console.print("  [cyan]/model embedding list[/cyan]")
        console.print("    List recommended embedding models")
        console.print()
        console.print("  [cyan]/model embedding set <model>[/cyan]")
        console.print("    Set embedding model (downloads immediately)")
        console.print("    [dim]→ Use recommended models OR any HuggingFace model[/dim]")
        console.print("    [dim]→ Examples: google/gemma-2b, Alibaba-NLP/gte-large-en-v1.5[/dim]")
        console.print()

        console.print("[dim]💡 Tips:[/dim]")
        console.print("[dim]  • Ollama models are auto-downloaded with user confirmation[/dim]")
        console.print("[dim]  • Embedding models download immediately from HuggingFace[/dim]")
        console.print("[dim]  • Custom models show warnings but are fully supported[/dim]")
        console.print()
