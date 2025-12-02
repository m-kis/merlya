"""
Core REPL logic for Merlya.
"""
import asyncio
import contextlib
import os
import sys
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.history import FileHistory

# Using unified Multi-Agent Orchestrator
from merlya.agents import Orchestrator
from merlya.commands import get_command_loader
from merlya.mcp.manager import MCPManager

# Using unified ConversationManager
from merlya.memory.conversation import ConversationManager
from merlya.memory.session import SessionManager
from merlya.repl.commands import CommandHandler, CommandResult
from merlya.repl.completer import create_completer
from merlya.repl.ui import console, print_error, print_markdown, print_success, print_warning, show_welcome
from merlya.tools.base import get_status_manager
from merlya.utils.config import ConfigManager
from merlya.utils.logger import logger
from merlya.utils.stats_manager import get_stats_manager


@contextlib.contextmanager
def suppress_asyncio_errors():
    """
    Context manager to suppress noisy asyncio/AutoGen errors during interrupts.

    When user presses Ctrl+C during an async operation, AutoGen can print
    verbose error messages like "Error processing publish message" and
    "task_done() called too many times". This filters them out for a cleaner UX.

    Set MERLYA_DEBUG_ERRORS=1 to disable suppression and see all errors.
    """
    import logging
    import os

    # Debug mode: disable suppression entirely
    if os.getenv("MERLYA_DEBUG_ERRORS"):
        yield
        return

    # Suppress autogen_core logger during interrupt handling
    # This prevents "Error processing publish message" from being logged
    autogen_logger = logging.getLogger("autogen_core")
    autogen_agentchat_logger = logging.getLogger("autogen_agentchat")

    # Add a filter to suppress specific error messages
    class InterruptFilter(logging.Filter):
        """Filter out noisy errors during Ctrl+C interrupts."""

        SUPPRESSED_MESSAGES = [
            "Error processing publish message",
            "task_done() called too many times",
            "CancelledError",
            "Event loop is closed",
        ]

        def filter(self, record):
            msg = record.getMessage()
            return not any(pattern in msg for pattern in self.SUPPRESSED_MESSAGES)

    interrupt_filter = InterruptFilter()
    autogen_logger.addFilter(interrupt_filter)
    autogen_agentchat_logger.addFilter(interrupt_filter)

    old_stderr = sys.stderr

    # Create a filter that suppresses known noisy patterns
    class FilteredStderr:
        """Stderr wrapper that filters out known noisy error patterns."""

        # Buffer size limits
        MAX_TRACEBACK_LINES = 50  # Maximum lines to buffer before deciding
        MIN_COMPLETE_TRACEBACK = 3  # Minimum lines for a complete traceback

        # Patterns to suppress (common AutoGen/asyncio shutdown noise)
        # These are specific error messages that occur during normal Ctrl+C interrupts
        NOISE_PATTERNS = [
            # AutoGen internal errors during shutdown
            "Error processing publish message",
            "task_done() called too many times",
            "unhandled exception during asyncio.run() shutdown",
            # Asyncio cancellation (expected during interrupt)
            "asyncio.exceptions.CancelledError",
            "exception=CancelledError",
            "Task was destroyed but it is pending",
            "_GatheringFuture exception=",
            # AutoGen context errors
            "AgentInstantiationContext",
            # Chained exception headers (we only care about the root cause)
            "during handling of the above exception",
            "During handling of the above exception",
            # Event loop cleanup
            "Event loop is closed",
            "RuntimeError: Event loop is closed",
            # HTTP client shutdown errors
            "httpcore._async.connection",
            "anyio._backends._asyncio",
            # AutoGen module paths in tracebacks
            "autogen_core._single_threaded_agent_runtime",
            "autogen_core._routed_agent",
            "autogen_core._base_agent",
            "autogen_agentchat.base",
            # OpenAI/httpx client shutdown
            "openai/_base_client.py",
            "openai/resources/chat/completions",
            "httpx/_client.py",
            "httpx/_transports/default",
        ]

        def __init__(self, original):
            self._original = original
            self._buffer = []
            self._suppressing = False

        def write(self, text):
            # When we start seeing a traceback or known error, suppress until clean
            if "Traceback (most recent call last):" in text:
                self._suppressing = True
                self._buffer = [text]
                return

            if self._suppressing:
                self._buffer.append(text)
                # Check if this is the end of the traceback (empty line or new non-indented line)
                # or if buffer contains enough context to decide
                buffer_text = "".join(self._buffer)
                if any(pattern in buffer_text for pattern in self.NOISE_PATTERNS):
                    # Known noise pattern - discard the whole traceback
                    if text.endswith("\n") and not text.startswith(" ") and not text.startswith("\t"):
                        # End of traceback section - clear and continue suppressing
                        self._buffer = []
                    return
                elif len(self._buffer) > self.MAX_TRACEBACK_LINES or (text == "\n" and len(self._buffer) > self.MIN_COMPLETE_TRACEBACK):
                    # Unknown traceback that's grown large or ended - might be real error
                    # But check one more time for noise patterns
                    if not any(p in buffer_text for p in self.NOISE_PATTERNS):
                        # Actually output it - it's a real error
                        for line in self._buffer:
                            self._original.write(line)
                    self._buffer = []
                    self._suppressing = False
                return

            # Check for single-line noise patterns
            if any(pattern in text for pattern in self.NOISE_PATTERNS):
                return

            # Normal output
            self._original.write(text)

        def flush(self):
            # On flush, output any buffered non-noise content
            if self._buffer and not self._suppressing:
                buffer_text = "".join(self._buffer)
                if not any(p in buffer_text for p in self.NOISE_PATTERNS):
                    self._original.write(buffer_text)
                self._buffer = []
            self._original.flush()

        # Forward other attributes to original stderr
        def __getattr__(self, name):
            return getattr(self._original, name)

    sys.stderr = FilteredStderr(old_stderr)
    try:
        yield
    finally:
        sys.stderr = old_stderr
        # Remove the filters from autogen loggers
        autogen_logger.removeFilter(interrupt_filter)
        autogen_agentchat_logger.removeFilter(interrupt_filter)


class MerlyaREPL:
    """Interactive REPL for Merlya."""

    def __init__(self, env: str = "dev"):
        self.env = env

        # Load .env file to set API keys in environment (like CLI does)
        self._load_env_file()

        # Configuration manager
        self.config = ConfigManager()

        # Ask for language on first run
        if self.config.language is None:
            self._prompt_language_selection()

        # Initialize orchestrator with language preference and shared console
        self.orchestrator = Orchestrator(
            env=env,
            language=self.config.language or 'en',
            console=console
        )

        # Use the same context manager as the orchestrator
        self.context_manager = self.orchestrator.context_manager
        self.session_manager = SessionManager(env=env)
        # IMPORTANT: Use the orchestrator's credential manager so variables are shared
        self.credentials = self.orchestrator.credentials
        # Alias for backward compatibility (used by inventory/manager.py)
        self.credential_manager = self.credentials
        # MCP server manager
        self.mcp_manager = MCPManager()
        # Conversation manager for context management
        self.conversation_manager = ConversationManager(env=env)
        # Extensible command loader
        self.command_loader = get_command_loader()

        # Command Handler
        self.command_handler = CommandHandler(self)

        # Setup prompt session
        history_file = Path.home() / ".merlya" / "history"
        history_file.parent.mkdir(parents=True, exist_ok=True)

        # Smart completer for commands, hosts, and variables
        self.completer = create_completer(
            context_manager=self.context_manager,
            credentials_manager=self.credentials
        )

        self.session: PromptSession[str] = PromptSession(
            history=FileHistory(str(history_file)),
            auto_suggest=AutoSuggestFromHistory(),
            completer=self.completer
        )

        # Setup SSH credentials (passphrase) on first run if needed
        self._setup_ssh_credentials()

        # Stats manager for metrics collection
        self.stats_manager = get_stats_manager()

        # Start session
        self.session_manager.start_session(metadata={"env": env, "mode": "repl"})

        # Set session ID for metrics tracking
        self.stats_manager.set_session_id(self.session_manager.current_session_id)

    def _load_env_file(self):
        """Load .env file to set API keys in environment.

        Only loads API keys (*_API_KEY) from .env.
        Configuration (provider, models) is loaded from config.json via ModelConfig.

        This prevents .env from overriding user's model configuration.
        """
        config_path = Path.home() / ".merlya" / ".env"
        if config_path.exists():
            logger.debug(f"Loading secrets from {config_path}")
            try:
                # ✅ Variables to IGNORE (config, not secrets)
                IGNORED_VARS = {
                    "MERLYA_PROVIDER",      # Use config.json
                    "OPENROUTER_MODEL",     # Use config.json
                    "ANTHROPIC_MODEL",      # Use config.json
                    "OPENAI_MODEL",         # Use config.json
                    "OLLAMA_MODEL",         # Use config.json
                }

                with open(config_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)

                            # ✅ Skip config variables (only load secrets)
                            if key in IGNORED_VARS:
                                logger.debug(f"⏭️ Skipping config var: {key} (use /model commands instead)")
                                continue

                            os.environ[key] = value
                            logger.debug(f"🔑 Loaded secret: {key}")
            except Exception as e:
                logger.warning(f"Failed to load .env file: {e}")
        else:
            logger.debug(f".env file not found at {config_path}")

    def _prompt_language_selection(self):
        """Prompt user to select language preference."""
        console.print("\n[bold cyan]🌍 Language Selection / Sélection de la langue[/bold cyan]\n")
        console.print("Choose your preferred language / Choisissez votre langue préférée:")
        console.print("  [1] English")
        console.print("  [2] Français")

        while True:
            try:
                choice = input("\nEnter choice / Entrez votre choix (1-2): ").strip()
                if choice == '1':
                    self.config.language = 'en'
                    console.print("[green]✅ Language set to English[/green]\n")
                    break
                elif choice == '2':
                    self.config.language = 'fr'
                    console.print("[green]✅ Langue définie sur Français[/green]\n")
                    break
                else:
                    console.print("[red]❌ Invalid choice. Please enter 1 or 2.[/red]")
            except (KeyboardInterrupt, EOFError):
                # Default to English on interrupt
                self.config.language = 'en'
                console.print("\n[yellow]⚠️ Defaulting to English[/yellow]\n")
                break

    def _setup_ssh_credentials(self):
        """
        Setup SSH credentials on startup.

        Checks if the default SSH key requires a passphrase and prompts user
        to enter it once for the session. This avoids repeated prompts during scans.
        """
        import getpass

        from merlya.security.credentials import VariableType

        try:
            # Check if passphrase is already set for this session
            if self.credentials.get_variable("ssh-passphrase-global"):
                logger.debug("SSH passphrase already configured for session")
                return

            # Get default SSH key
            default_key = self.credentials.get_default_key()
            if not default_key:
                logger.debug("No default SSH key found")
                return

            # Check if key needs passphrase
            if not self.credentials._key_needs_passphrase(default_key):
                logger.debug("Default SSH key does not require passphrase")
                return

            # Key needs passphrase - prompt user
            key_name = Path(default_key).name
            console.print("\n[bold cyan]🔐 SSH Key Setup[/bold cyan]")
            console.print(f"Default SSH key [yellow]{key_name}[/yellow] requires a passphrase.")
            console.print("[dim]Setting it now will enable remote host scanning without repeated prompts.[/dim]\n")

            try:
                setup_now = input("Configure passphrase for this session? (Y/n): ").strip().lower()
                if setup_now == "n":
                    console.print("[dim]Skipped. Use /inventory ssh-key set to configure later.[/dim]\n")
                    return

                passphrase = getpass.getpass("Enter passphrase: ")
                if passphrase:
                    # Store as session secret
                    self.credentials.set_variable(
                        "ssh-passphrase-global",
                        passphrase,
                        VariableType.SECRET
                    )
                    console.print("[green]✅ SSH passphrase configured for this session[/green]\n")
                    logger.info("SSH passphrase configured during startup")
                else:
                    console.print("[yellow]⚠️ Empty passphrase, skipping[/yellow]\n")

            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]Skipped SSH setup[/dim]\n")

        except Exception as e:
            # Don't fail startup if SSH setup fails
            logger.debug(f"SSH credential setup skipped: {e}")

    def _check_provider_readiness(self) -> str:
        """
        Check if the configured LLM provider is ready.

        Returns:
            Status string to append to welcome message, or empty if all good.
        """
        from merlya.llm.readiness import check_provider_readiness, format_readiness_result

        try:
            result = check_provider_readiness()

            if result.ready and not result.warnings:
                # All good - just log it
                return f"**Provider**: ✅ {result.provider} ({result.model})\n"

            # Format result for display
            formatted = format_readiness_result(result)

            if result.errors:
                # Critical error - show prominently
                console.print("\n[bold red]⚠️ Provider Readiness Check Failed[/bold red]")
                console.print(formatted)
                console.print("[dim]Fix the issues above or change provider with /model provider <name>[/dim]\n")
                return f"**Provider**: ❌ {result.provider} (not ready)\n"

            elif result.warnings:
                # Warnings only - show but continue
                return f"**Provider**: ⚠️ {result.provider} ({result.model}) - {len(result.warnings)} warning(s)\n"

            return f"**Provider**: ✅ {result.provider} ({result.model})\n"

        except Exception as e:
            logger.warning(f"Provider readiness check failed: {e}")
            return "**Provider**: ⚠️ Check failed\n"

    def start(self):
        """Start the REPL loop."""
        # Check provider readiness before starting
        provider_status = self._check_provider_readiness()

        # Show welcome message
        conv = self.conversation_manager.current_conversation
        conv_info = ""
        if conv:
            token_usage = self.conversation_manager.get_token_usage_percent()
            conv_info = f"""
**Conversation**: {conv.id} ({len(conv.messages)} messages, {conv.token_count:,} tokens)
**Token usage**: {token_usage:.1f}% of limit
"""
        # Add provider status
        conv_info += provider_status

        # Add memory status
        memory_status = "✅ FalkorDB" if self.orchestrator.has_long_term_memory else "💾 SQLite only"
        conv_info += f"**Memory**: {memory_status}\n"

        show_welcome(self.env, self.session_manager.current_session_id, self.config.language, conv_info)

        while True:
            try:
                # Get user input
                user_input = self.session.prompt("\nMerlya> ").strip()

                if not user_input:
                    continue

                # Handle slash commands
                if user_input.startswith('/'):
                    # Check if there's additional text after the command (multi-line input)
                    # Split on newlines and process command first
                    lines = user_input.split('\n')
                    command_line = lines[0].strip()
                    remaining_text = '\n'.join(lines[1:]).strip() if len(lines) > 1 else ''

                    with suppress_asyncio_errors():
                        result = asyncio.run(self.command_handler.handle_command(command_line))
                    if result == CommandResult.EXIT:
                        break
                    if result in (CommandResult.HANDLED, CommandResult.FAILED):
                        # If there's remaining text, process it as a new query
                        if remaining_text:
                            user_input = remaining_text
                            # Fall through to natural language processing
                        else:
                            continue
                    else:
                        # Unexpected result - slash commands should not fall through to LLM
                        logger.warning(f"Unexpected command result: {result} for input: {user_input[:50]}")
                        continue

                # Process natural language query
                self.conversation_manager.add_user_message(user_input)

                # Resolve @variables before sending to LLM
                # (user sees original query, LLM gets resolved values)
                resolved_query = user_input
                try:
                    if self.credentials.has_variables(user_input):
                        # Resolve variables but KEEP SECRETS as @variable to prevent leaking to LLM
                        resolved_query = self.credentials.resolve_variables(user_input, resolve_secrets=False)
                        # Security: Log resolution without exposing secret values
                        logger.debug(f"Variables resolved (original: {len(user_input)}, resolved: {len(resolved_query)} chars)")
                except Exception as e:
                    logger.warning(f"Variable resolution failed: {e}")
                    print_warning(f"Variable resolution failed: {e}")
                    # Continue with original query

                # Get recent conversation history for context
                conversation_history = self._get_recent_history()

                # Use StatusManager so tools can pause spinner for user input
                status_manager = get_status_manager()
                query_timer = self.stats_manager.start_timer()
                query_success = True
                query_error = None
                try:
                    status_manager.set_console(console)
                    status_manager.start("[cyan]🧠 Processing...[/cyan]")
                    # Wrap asyncio.run with error suppression to hide noisy AutoGen
                    # shutdown messages when user presses Ctrl+C
                    with suppress_asyncio_errors():
                        response = asyncio.run(
                            self.orchestrator.process_request(
                                user_query=resolved_query,
                                conversation_history=conversation_history,
                                # Pass original query for triage (without resolved credentials)
                                original_query=user_input if resolved_query != user_input else None,
                            )
                        )
                except Exception as e:
                    query_success = False
                    query_error = str(e)
                    raise
                finally:
                    status_manager.stop()
                    # Record query metrics
                    query_timer.stop()
                    self.stats_manager.record_query(
                        query_length=len(user_input),
                        response_length=len(response) if 'response' in dir() else 0,
                        total_time_ms=query_timer.elapsed_ms(),
                        success=query_success,
                        error=query_error,
                    )

                self.conversation_manager.add_assistant_message(response)
                # Display response with markdown formatting
                if response:
                    console.print()  # Add spacing
                    print_markdown(response)

            except KeyboardInterrupt:
                # Clean interrupt - just print a newline and continue
                console.print("\n[yellow]⏹ Interrupted[/yellow]")
                continue
            except EOFError:
                break
            except asyncio.CancelledError:
                # Async operation was cancelled (e.g., by Ctrl+C during LLM call)
                console.print("\n[yellow]⏹ Cancelled[/yellow]")
                continue
            except Exception as e:
                # Filter out noisy AutoGen shutdown errors
                error_str = str(e)
                if "task_done() called too many times" in error_str:
                    console.print("\n[yellow]⏹ Interrupted[/yellow]")
                    continue
                if "CancelledError" in error_str or "cancelled" in error_str.lower():
                    console.print("\n[yellow]⏹ Cancelled[/yellow]")
                    continue
                logger.error(f"REPL Error: {e}")
                print_error(f"{e}")

        # Clean shutdown of orchestrator to prevent httpx "Event loop is closed" errors
        if hasattr(self, 'orchestrator') and self.orchestrator is not None:
            self.orchestrator.shutdown_sync()

        print_success("Goodbye!")
        self.session_manager.end_session()

    # Command implementations called from CommandHandler

    def handle_mcp_command(self, args):
        """Handle /mcp command for MCP server management."""
        from merlya.repl.commands.mcp import handle_mcp_command
        return handle_mcp_command(self, args)

    def handle_language_command(self, args):
        """Handle /language command to change language preference."""
        from merlya.repl.commands.language import handle_language_command
        return handle_language_command(self, args)

    def handle_triage_command(self, args):
        """Handle /triage command to test priority classification."""
        from merlya.repl.commands.triage import handle_triage_command
        return handle_triage_command(self, args)

    def handle_feedback_command(self, args):
        """Handle /feedback command to correct triage classification."""
        from merlya.repl.commands.triage import handle_feedback_command
        return handle_feedback_command(self, args)

    def handle_triage_stats_command(self, args):
        """Handle /triage-stats command to show learning statistics."""
        from rich.table import Table

        try:
            stats = self.orchestrator.intent_parser.get_learning_stats()

            if not stats.get('available', False):
                print_warning("Smart triage learning not available")
                reason = stats.get('reason', 'Unknown')
                console.print(f"[dim]{reason}[/dim]")
                return True

            console.print("\n[bold]📊 Triage Learning Statistics[/bold]\n")

            # Pattern store stats
            pattern_stats = stats.get('pattern_store', {})
            if pattern_stats.get('available'):
                total = pattern_stats.get('total_patterns', 0)
                console.print(f"  Total patterns learned: [cyan]{total}[/cyan]")

                by_intent = pattern_stats.get('by_intent', {})
                if by_intent:
                    table = Table(title="Patterns by Intent")
                    table.add_column("Intent", style="cyan")
                    table.add_column("Count", style="green")

                    for intent, count in by_intent.items():
                        table.add_row(intent, str(count))

                    console.print(table)
            else:
                console.print("  Pattern store: [yellow]Not connected[/yellow]")
                console.print("[dim]  Connect FalkorDB to enable pattern learning[/dim]")

            # Embedding status
            embeddings = stats.get('embeddings_available', False)
            if embeddings:
                console.print("\n  Embeddings: [green]✅ Available[/green]")
            else:
                console.print("\n  Embeddings: [yellow]⚠️ Not available[/yellow]")
                console.print("[dim]  Install sentence-transformers for semantic matching[/dim]")

        except Exception as e:
            print_error(f"Failed to get stats: {e}")

        return True

    def _get_recent_history(self, max_messages: int = 6) -> list:
        """
        Get recent conversation history for context injection.

        Returns list of {role, content} dicts for the last N messages,
        excluding the current user message (which was just added before calling this).
        This avoids sending the same message twice to the orchestrator.
        """
        conv = self.conversation_manager.current_conversation
        if not conv or not conv.messages:
            return []

        # Exclude the last message (current user input just added) to avoid duplication
        # The orchestrator receives the current query via user_query parameter
        if len(conv.messages) <= 1:
            return []
        recent = conv.messages[-(max_messages + 1):-1]
        return [{"role": msg.role, "content": msg.content} for msg in recent]

    def process_single_query(self, query: str) -> str:
        """
        Process a single query without entering the interactive REPL.
        Used for CLI one-shot mode.
        """
        self.conversation_manager.add_user_message(query)

        # Resolve @variables before sending to LLM
        # (consistent error handling with REPL loop)
        resolved_query = query
        try:
            if self.credentials.has_variables(query):
                # Resolve variables but KEEP SECRETS as @variable to prevent leaking to LLM
                resolved_query = self.credentials.resolve_variables(query, resolve_secrets=False)
                # Security: Log variable resolution (without exposing secret values)
                logger.debug(f"Variables resolved in query (original length: {len(query)}, resolved: {len(resolved_query)})")
        except Exception as e:
            logger.warning(f"Variable resolution failed: {e}")
            print_warning(f"Variable resolution failed: {e}")
            # Continue with original query if resolution fails

        # Get conversation history for context
        conversation_history = self._get_recent_history()

        with suppress_asyncio_errors():
            response = asyncio.run(
                self.orchestrator.process_request(
                    user_query=resolved_query,
                    conversation_history=conversation_history
                )
            )
        self.conversation_manager.add_assistant_message(response)
        return response


def start_repl(env: str = "dev") -> None:
    """
    Entry point to start the Merlya REPL.
    Called from cli.py.
    """
    repl = MerlyaREPL(env=env)
    repl.start()
