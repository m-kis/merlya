"""
Core REPL logic for Athena.
"""
import asyncio
import os
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.history import FileHistory

# Using unified Multi-Agent Orchestrator
from athena_ai.agents import Orchestrator
from athena_ai.commands import get_command_loader
from athena_ai.mcp.manager import MCPManager

# Using unified ConversationManager
from athena_ai.memory.conversation import ConversationManager
from athena_ai.memory.session import SessionManager
from athena_ai.repl.commands import CommandHandler
from athena_ai.repl.completer import create_completer
from athena_ai.repl.ui import console, print_error, print_markdown, print_success, print_warning, show_welcome
from athena_ai.utils.config import ConfigManager
from athena_ai.utils.logger import logger


class AthenaREPL:
    """Interactive REPL for Athena."""

    def __init__(self, env: str = "dev"):
        self.env = env

        # Load .env file to set API keys in environment (like CLI does)
        self._load_env_file()

        # Configuration manager
        self.config = ConfigManager()

        # Ask for language on first run
        if self.config.language is None:
            self._prompt_language_selection()

        # Initialize orchestrator with language preference
        self.orchestrator = Orchestrator(env=env, language=self.config.language or 'en')

        # Use the same context manager as the orchestrator
        self.context_manager = self.orchestrator.context_manager
        self.session_manager = SessionManager(env=env)
        # IMPORTANT: Use the orchestrator's credential manager so variables are shared
        self.credentials = self.orchestrator.credentials
        # MCP server manager
        self.mcp_manager = MCPManager()
        # Conversation manager for context management
        self.conversation_manager = ConversationManager(env=env)
        # Extensible command loader
        self.command_loader = get_command_loader()

        # Command Handler
        self.command_handler = CommandHandler(self)

        # Setup prompt session
        history_file = Path.home() / ".athena" / "history"
        history_file.parent.mkdir(parents=True, exist_ok=True)

        # Smart completer for commands, hosts, and variables
        self.completer = create_completer(
            context_manager=self.context_manager,
            credentials_manager=self.credentials
        )

        self.session = PromptSession(
            history=FileHistory(str(history_file)),
            auto_suggest=AutoSuggestFromHistory(),
            completer=self.completer
        )

        # Start session
        self.session_manager.start_session(metadata={"env": env, "mode": "repl"})

    def _load_env_file(self):
        """Load .env file to set API keys and config in environment (same as CLI)."""
        config_path = Path.home() / ".athena" / ".env"
        if config_path.exists():
            logger.debug(f"Loading config from {config_path}")
            try:
                with open(config_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)
                            os.environ[key] = value
                            logger.debug(f"Set env var: {key}")
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
                    console.print("[green]✓ Language set to English[/green]\n")
                    break
                elif choice == '2':
                    self.config.language = 'fr'
                    console.print("[green]✓ Langue définie sur Français[/green]\n")
                    break
                else:
                    console.print("[red]Invalid choice. Please enter 1 or 2.[/red]")
            except (KeyboardInterrupt, EOFError):
                # Default to English on interrupt
                self.config.language = 'en'
                console.print("\n[yellow]Defaulting to English[/yellow]\n")
                break

    def start(self):
        """Start the REPL loop."""
        # Show welcome message
        conv = self.conversation_manager.current_conversation
        conv_info = ""
        if conv:
            token_usage = self.conversation_manager.get_token_usage_percent()
            conv_info = f"""
**Conversation**: {conv.id} ({len(conv.messages)} messages, {conv.token_count:,} tokens)
**Token usage**: {token_usage:.1f}% of limit
"""
        show_welcome(self.env, self.session_manager.current_session_id, self.config.language, conv_info)

        while True:
            try:
                # Get user input
                user_input = self.session.prompt("\nAthena> ").strip()

                if not user_input:
                    continue

                # Handle slash commands
                if user_input.startswith('/'):
                    result = self.command_handler.handle_command(user_input)
                    if result == 'exit':
                        break
                    if result:
                        continue

                # Process natural language query
                self.conversation_manager.add_user_message(user_input)

                # Resolve @variables before sending to LLM
                # (user sees original query, LLM gets resolved values)
                resolved_query = user_input
                if self.credentials.has_variables(user_input):
                    resolved_query = self.credentials.resolve_variables(user_input)

                with console.status("[cyan]Processing...[/cyan]", spinner="dots"):
                    response = asyncio.run(
                        self.orchestrator.process_request(user_query=resolved_query)
                    )

                self.conversation_manager.add_assistant_message(response)
                # Display response with markdown formatting
                if response:
                    console.print()  # Add spacing
                    print_markdown(response)

            except KeyboardInterrupt:
                continue
            except EOFError:
                break
            except Exception as e:
                logger.error(f"REPL Error: {e}")
                print_error(f"{e}")

        print_success("Goodbye!")
        self.session_manager.end_session()

    # Command implementations called from CommandHandler

    def _handle_mcp_command(self, args):
        """Handle /mcp command for MCP server management."""
        from rich.table import Table

        if not args:
            console.print("[yellow]Usage:[/yellow]")
            console.print("  /mcp list - List configured servers")
            console.print("  /mcp add - Add a new server (interactive)")
            console.print("  /mcp delete <name> - Remove a server")
            console.print("  /mcp show <name> - Show server details")
            console.print("  /mcp examples - Show example configurations")
            return True

        cmd = args[0]

        if cmd == 'list':
            servers = self.mcp_manager.list_servers()
            if not servers:
                print_warning("No MCP servers configured")
                console.print("[dim]Use /mcp add to configure a server[/dim]")
            else:
                table = Table(title="MCP Servers")
                table.add_column("Name", style="cyan")
                table.add_column("Command", style="green")
                table.add_column("Status", style="yellow")

                for name, config in servers.items():
                    cmd_str = config.get('command', 'N/A')
                    status = "[green]✓[/green]" if config.get('enabled', True) else "[red]✗[/red]"
                    table.add_row(name, cmd_str[:50], status)
                console.print(table)

        elif cmd == 'add':
            console.print("\n[bold cyan]Add MCP Server[/bold cyan]\n")
            try:
                name = input("Server name: ").strip()
                command = input("Command (e.g., npx @modelcontextprotocol/server-git): ").strip()
                args_str = input("Arguments (space-separated, or empty): ").strip()

                if name and command:
                    server_args = args_str.split() if args_str else []
                    self.mcp_manager.add_server(name, command, server_args)
                    print_success(f"MCP server '{name}' added")
                else:
                    print_error("Name and command are required")
            except (KeyboardInterrupt, EOFError):
                print_warning("Cancelled")

        elif cmd == 'delete' and len(args) > 1:
            name = args[1]
            if self.mcp_manager.remove_server(name):
                print_success(f"Server '{name}' removed")
            else:
                print_error(f"Server '{name}' not found")

        elif cmd == 'show' and len(args) > 1:
            name = args[1]
            servers = self.mcp_manager.list_servers()
            if name in servers:
                config = servers[name]
                console.print(f"\n[bold]{name}[/bold]")
                console.print(f"  Command: {config.get('command')}")
                console.print(f"  Args: {config.get('args', [])}")
                console.print(f"  Env: {config.get('env', {})}")
            else:
                print_error(f"Server '{name}' not found")

        elif cmd == 'examples':
            console.print("\n[bold]Example MCP Servers:[/bold]\n")
            console.print("  [cyan]Filesystem:[/cyan]")
            console.print("    npx @modelcontextprotocol/server-filesystem /path/to/dir\n")
            console.print("  [cyan]Git:[/cyan]")
            console.print("    npx @modelcontextprotocol/server-git --repository /path/to/repo\n")
            console.print("  [cyan]PostgreSQL:[/cyan]")
            console.print("    npx @modelcontextprotocol/server-postgres postgresql://...\n")

        return True

    def _handle_language_command(self, args):
        """Handle /language command to change language preference."""
        if not args:
            current = self.config.language or 'en'
            console.print(f"Current language: [cyan]{current}[/cyan]")
            console.print("Usage: /language <en|fr>")
            return True

        lang = args[0].lower()
        if lang in ['en', 'english']:
            self.config.language = 'en'
            print_success("Language set to English")
        elif lang in ['fr', 'french', 'français']:
            self.config.language = 'fr'
            print_success("Langue définie sur Français")
        else:
            print_error("Supported languages: en, fr")

        return True

    def _handle_triage_command(self, args):
        """Handle /triage command to test priority classification."""
        from athena_ai.triage import classify_priority, describe_behavior

        if not args:
            console.print("[yellow]Usage:[/yellow] /triage <query>")
            console.print("Example: /triage production database is down")
            return True

        query = ' '.join(args)
        result = classify_priority(query)

        console.print("\n[bold]Triage Analysis[/bold]")
        console.print(f"  Query: [dim]{query}[/dim]")
        console.print(f"  Priority: [{result.priority.color}]{result.priority.label}[/{result.priority.color}]")
        console.print(f"  Environment: {result.environment or 'unknown'}")
        console.print(f"  Impact: {result.impact or 'unknown'}")
        console.print(f"  Service: {result.service or 'unknown'}")
        console.print("\n[bold]Behavior Profile:[/bold]")
        console.print(describe_behavior(result.priority))

        return True

    def _handle_conversations_command(self, args):
        """Handle /conversations command to list all conversations."""
        from rich.table import Table

        conversations = self.conversation_manager.list_conversations(limit=20)
        if not conversations:
            print_warning("No conversations found")
            console.print("[dim]Start chatting to create a conversation[/dim]")
            return True

        table = Table(title="Conversations")
        table.add_column("ID", style="cyan")
        table.add_column("Title", style="green")
        table.add_column("Messages", style="yellow")
        table.add_column("Tokens", style="magenta")
        table.add_column("Updated", style="dim")

        current_id = self.conversation_manager.current_conversation.id if self.conversation_manager.current_conversation else None

        for conv in conversations:
            conv_id = conv.get('id', conv.get('conversation_id', 'N/A'))
            title = conv.get('title', 'Untitled')[:30]
            msg_count = str(conv.get('message_count', 0))
            tokens = str(conv.get('token_count', 0))
            updated = conv.get('updated_at', '')[:16]

            # Mark current conversation
            if conv_id == current_id:
                conv_id = f"[bold]{conv_id}[/bold] *"

            table.add_row(conv_id, title, msg_count, tokens, updated)

        console.print(table)
        console.print("[dim]* = current conversation[/dim]")
        return True

    def _handle_new_conversation_command(self, args):
        """Handle /new command to start a new conversation."""
        title = ' '.join(args) if args else None
        conv = self.conversation_manager.create_conversation(title=title)
        print_success(f"New conversation started: {conv.id}")
        if title:
            console.print(f"  Title: {title}")
        return True

    def _handle_load_conversation_command(self, args):
        """Handle /load command to load a conversation."""
        if not args:
            print_error("Usage: /load <conversation_id>")
            return True

        conv_id = args[0]
        if self.conversation_manager.load_conversation(conv_id):
            conv = self.conversation_manager.current_conversation
            print_success(f"Loaded conversation: {conv_id}")
            console.print(f"  Messages: {len(conv.messages)}")
            console.print(f"  Tokens: {conv.token_count}")
        else:
            print_error(f"Conversation not found: {conv_id}")

        return True

    def _handle_compact_conversation_command(self, args):
        """Handle /compact command to compact current conversation."""
        conv = self.conversation_manager.current_conversation
        if not conv:
            print_error("No active conversation")
            return True

        before_tokens = conv.token_count
        before_messages = len(conv.messages)

        # Compact by summarizing old messages
        with console.status("[cyan]Compacting conversation...[/cyan]", spinner="dots"):
            self.conversation_manager.compact_conversation()

        after_tokens = conv.token_count
        after_messages = len(conv.messages)

        print_success("Conversation compacted")
        console.print(f"  Messages: {before_messages} → {after_messages}")
        console.print(f"  Tokens: {before_tokens} → {after_tokens}")
        console.print(f"  Saved: {before_tokens - after_tokens} tokens")

        return True

    def _handle_delete_conversation_command(self, args):
        """Handle /delete command to delete a conversation."""
        if not args:
            print_error("Usage: /delete <conversation_id>")
            return True

        conv_id = args[0]

        # Confirmation
        try:
            confirm = input(f"Delete conversation {conv_id}? (y/N): ").strip().lower()
            if confirm != 'y':
                print_warning("Cancelled")
                return True
        except (KeyboardInterrupt, EOFError):
            print_warning("Cancelled")
            return True

        if self.conversation_manager.delete_conversation(conv_id):
            print_success(f"Conversation deleted: {conv_id}")
        else:
            print_error(f"Failed to delete conversation: {conv_id}")

        return True

    def process_single_query(self, query: str) -> str:
        """
        Process a single query without entering the interactive REPL.
        Used for CLI one-shot mode.
        """
        self.conversation_manager.add_user_message(query)

        # Resolve @variables before sending to LLM
        resolved_query = query
        if self.credentials.has_variables(query):
            resolved_query = self.credentials.resolve_variables(query)

        response = asyncio.run(self.orchestrator.process_request(user_query=resolved_query))
        self.conversation_manager.add_assistant_message(response)
        return response


def start_repl(env: str = "dev") -> None:
    """
    Entry point to start the Athena REPL.
    Called from cli.py.
    """
    repl = AthenaREPL(env=env)
    repl.start()
