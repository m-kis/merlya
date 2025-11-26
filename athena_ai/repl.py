"""
Interactive REPL for Athena - AI-Powered Infrastructure Orchestration.
"""
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
# Using Ag2 Multi-Agent Orchestrator
from athena_ai.agents.ag2_orchestrator import Ag2Orchestrator as Orchestrator
# Using SQLite-based ConversationManager for unified storage
from athena_ai.memory.conversation_manager_sqlite import ConversationManager
# Triage system for automatic priority classification
from athena_ai.triage import classify_priority, get_behavior, describe_behavior
from athena_ai.context.manager import ContextManager
from athena_ai.security.credentials import CredentialManager
from athena_ai.memory.session import SessionManager
from athena_ai.mcp.manager import MCPManager
from athena_ai.commands import get_command_loader
from athena_ai.utils.logger import logger
from athena_ai.utils.config import ConfigManager
import sys
import json
import os
import asyncio

console = Console()

# UI translations
MESSAGES = {
    'en': {
        'welcome_title': 'Welcome',
        'welcome_header': '🚀 Athena Ag2 Interactive Mode',
        'welcome_env': 'Environment',
        'welcome_session': 'Session',
        'welcome_intro': 'Type your questions naturally or use slash commands:',
        'welcome_help': 'Show commands',
        'welcome_scan': 'Scan infrastructure',
        'welcome_exit': 'Exit',
        'welcome_start': 'Start by asking me anything about your infrastructure!',
        'processing': 'Processing',
        'error': 'Error',
    },
    'fr': {
        'welcome_title': 'Bienvenue',
        'welcome_header': '🚀 Athena Ag2 Mode Interactif',
        'welcome_env': 'Environnement',
        'welcome_session': 'Session',
        'welcome_intro': 'Posez vos questions naturellement ou utilisez les commandes slash :',
        'welcome_help': 'Afficher les commandes',
        'welcome_scan': 'Scanner l\'infrastructure',
        'welcome_exit': 'Quitter',
        'welcome_start': 'Commencez par me poser n\'importe quelle question sur votre infrastructure !',
        'processing': 'Traitement en cours',
        'error': 'Erreur',
    }
}

SLASH_COMMANDS = {
    '/help': 'Show available slash commands',
    '/scan': 'Scan infrastructure (--full for SSH scan)',
    '/refresh': 'Force refresh all context',
    '/cache-stats': 'Show cache statistics',
    '/ssh-info': 'Show SSH configuration',
    '/permissions': 'Show permission capabilities [hostname]',
    '/session': 'Session management (list, show, export)',
    '/context': 'Show current context',
    '/model': 'Model management (list, set, show)',
    '/variables': 'Manage variables (hosts, credentials, etc.)',
    '/credentials': 'Alias for /variables (backward compatibility)',
    '/mcp': 'Manage MCP servers (add, list, delete, show)',
    '/language': 'Change language (en/fr)',
    '/triage': 'Test priority classification for a query',
    '/conversations': 'List all conversations',
    '/new': 'Start new conversation [title]',
    '/load': 'Load conversation <id>',
    '/compact': 'Compact current conversation',
    '/delete': 'Delete conversation <id>',
    '/reset': 'Reset Ag2 agents memory',
    '/exit': 'Exit Athena',
    '/quit': 'Exit Athena',
}


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

        # Setup prompt session
        history_file = Path.home() / ".athena" / "history"
        history_file.parent.mkdir(parents=True, exist_ok=True)

        # Completer for slash commands
        completer = WordCompleter(
            list(SLASH_COMMANDS.keys()),
            ignore_case=True,
            sentence=True
        )

        self.session = PromptSession(
            history=FileHistory(str(history_file)),
            auto_suggest=AutoSuggestFromHistory(),
            completer=completer
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

    def show_welcome(self):
        """Show welcome message."""
        lang = self.config.language or 'en'
        msg = MESSAGES[lang]

        # Get conversation info
        conv = self.conversation_manager.current_conversation
        conv_info = ""
        if conv:
            token_usage = self.conversation_manager.get_token_usage_percent()
            conv_info = f"""
**Conversation**: {conv.id} ({len(conv.messages)} messages, {conv.token_count:,} tokens)
**Token usage**: {token_usage:.1f}% of limit
"""

        welcome = f"""
# {msg['welcome_header']}

**{msg['welcome_env']}**: {self.env}
**{msg['welcome_session']}**: {self.session_manager.current_session_id}
{conv_info}
{msg['welcome_intro']}
- `/help` - {msg['welcome_help']}
- `/conversations` - List all conversations
- `/new [title]` - Start new conversation
- `/scan` - {msg['welcome_scan']}
- `/exit` - {msg['welcome_exit']}

{msg['welcome_start']}
"""
        console.print(Panel(Markdown(welcome), title=msg['welcome_title'], border_style="cyan"))

    def show_help(self):
        """Show help message."""
        help_text = "## Available Slash Commands\n\n"
        for cmd, desc in SLASH_COMMANDS.items():
            help_text += f"**{cmd}**: {desc}\n"

        help_text += "\n## Smart Context System\n\n"
        help_text += "Athena uses intelligent caching that auto-detects changes:\n"
        help_text += "- **Inventory** (/etc/hosts): Auto-refreshes when file changes (1h TTL)\n"
        help_text += "- **Local info**: Cached for 5 minutes\n"
        help_text += "- **Remote hosts**: Cached for 30 minutes\n"
        help_text += "- Use `/cache-stats` to see cache state\n"
        help_text += "- Use `/refresh` to force update everything\n"

        help_text += "\n## Model Configuration\n\n"
        help_text += "Athena supports multiple LLM providers and models:\n"
        help_text += "- `/model show` - Show current model configuration\n"
        help_text += "- `/model list` - List available models for current provider\n"
        help_text += "- `/model set <provider> <model>` - Set model for provider\n"
        help_text += "- `/model provider <provider>` - Switch provider (openrouter, anthropic, openai, ollama)\n"
        help_text += "- Task-specific models: Fast model for corrections, best model for complex planning\n"

        help_text += "\n## Variables System (@variables)\n\n"
        help_text += "Define reusable variables for hosts, credentials, and more:\n\n"
        help_text += "**Host Aliases:**\n"
        help_text += "- `/variables set preproddb db-qarc-1` - Define host alias\n"
        help_text += "- `/variables set prodmongo mongo-preprod-1` - Another host\n"
        help_text += "- Use: `check mysql on @preproddb`\n\n"
        help_text += "**Credentials:**\n"
        help_text += "- `/variables set mongo-user admin` - Username (visible)\n"
        help_text += "- `/variables set-secret mongo-pass` - Password (secure input, hidden)\n"
        help_text += "- Use: `check mongo on @preproddb using @mongo-user @mongo-pass`\n\n"
        help_text += "**Other Variables:**\n"
        help_text += "- `/variables set myenv production` - Context variables\n"
        help_text += "- `/variables set region eu-west-1` - Any value you need\n\n"
        help_text += "**Management:**\n"
        help_text += "- `/variables list` - Show all variables (secrets masked)\n"
        help_text += "- `/variables delete <key>` - Delete a variable\n"
        help_text += "- `/variables clear` - Clear all variables\n"
        help_text += "- Note: `/credentials` is an alias for `/variables`\n"

        help_text += "\n## Examples\n\n"
        help_text += "- `list mongo preprod IPs`\n"
        help_text += "- `check if nginx is running on web-prod-001`\n"
        help_text += "- `what services are running on mongo-preprod-1`\n"
        help_text += "- `/scan --full` (scan all hosts via SSH)\n"
        help_text += "- `/cache-stats` (check cache status)\n"
        help_text += "- `/refresh` (force refresh after infrastructure changes)\n"
        help_text += "- `/model list openrouter` (list OpenRouter models)\n"
        help_text += "- `/model set openrouter anthropic/claude-3-opus` (switch to Opus)\n"

        help_text += "\n## MCP (Model Context Protocol)\n\n"
        help_text += "MCP extends Athena with standardized external tools.\n\n"
        help_text += "**Commands:**\n"
        help_text += "- `/mcp list` - List configured servers\n"
        help_text += "- `/mcp add` - Add a server (interactive)\n"
        help_text += "- `/mcp delete <name>` - Remove a server\n"
        help_text += "- `/mcp examples` - Show example configurations\n\n"
        help_text += "**Popular MCP Servers:**\n"
        help_text += "- `@modelcontextprotocol/server-filesystem` - File operations\n"
        help_text += "- `@modelcontextprotocol/server-git` - Git operations\n"
        help_text += "- `@modelcontextprotocol/server-postgres` - PostgreSQL queries\n"
        help_text += "- `@modelcontextprotocol/server-brave-search` - Web search\n\n"
        help_text += "**Usage:** MCP tools are auto-available to agents once configured.\n"
        help_text += "Example: After adding filesystem server, say 'list files in /tmp'\n"

        # Custom commands section
        custom_commands = self.command_loader.list_commands()
        if custom_commands:
            help_text += "\n## Custom Commands\n\n"
            help_text += "Extensible commands loaded from markdown files:\n\n"
            for name, desc in custom_commands.items():
                help_text += f"- `/{name}`: {desc}\n"
            help_text += "\n*Add your own in `~/.athena/commands/*.md`*\n"

        console.print(Markdown(help_text))

    def handle_slash_command(self, command: str) -> bool:
        """
        Handle slash commands.
        Returns True if command was handled, False otherwise.
        """
        parts = command.split()
        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        if cmd in ['/exit', '/quit']:
            return 'exit'

        # Check for extensible custom commands first
        cmd_name = cmd[1:]  # Remove leading /
        custom_cmd = self.command_loader.get(cmd_name)
        if custom_cmd:
            # Expand template with args and execute
            prompt = self.command_loader.expand(custom_cmd, args)
            console.print(f"[cyan]Running /{custom_cmd.name}...[/cyan]\n")

            # Add to conversation and process
            self.conversation_manager.add_user_message(prompt)

            with console.status("[cyan]Agents working...[/cyan]", spinner="dots"):
                response = asyncio.run(
                    self.orchestrator.process_request(user_query=prompt)
                )

            self.conversation_manager.add_assistant_message(response)
            console.print(Markdown(response))
            return True

        elif cmd == '/help':
            self.show_help()
            return True

        elif cmd == '/scan':
            full = '--full' in args
            console.print("[cyan]Scanning infrastructure...[/cyan]")
            context = self.context_manager.discover_environment(scan_remote=full)

            local = context.get('local', {})
            inventory = context.get('inventory', {})
            remote_hosts = context.get('remote_hosts', {})

            console.print(f"\n[green]✓ Scan complete[/green]")
            console.print(f"  Local: {local.get('hostname')}")
            console.print(f"  Inventory: {len(inventory)} hosts")

            if remote_hosts:
                accessible = sum(1 for h in remote_hosts.values() if h.get('accessible'))
                console.print(f"  Remote: {accessible}/{len(remote_hosts)} accessible")

            return True

        elif cmd == '/refresh':
            console.print("[cyan]Force refreshing all context...[/cyan]")
            self.context_manager.discover_environment(scan_remote=False, force=True)
            console.print("[green]✓ Context force refreshed (cache cleared)[/green]")
            return True

        elif cmd == '/cache-stats':
            stats = self.context_manager.get_cache_stats()
            from rich.table import Table

            table = Table(title="Cache Statistics")
            table.add_column("Component", style="cyan")
            table.add_column("Age", style="yellow")
            table.add_column("TTL", style="blue")
            table.add_column("Status", style="green")
            table.add_column("Fingerprint", style="magenta")

            for key, info in stats.items():
                status = "✓ Valid" if info['valid'] else "✗ Expired"
                status_style = "green" if info['valid'] else "red"
                fingerprint = "Yes" if info.get('has_fingerprint') else "No"

                table.add_row(
                    key,
                    f"{info['age_seconds']}s",
                    f"{info['ttl_seconds']}s",
                    f"[{status_style}]{status}[/{status_style}]",
                    fingerprint
                )

            console.print(table)
            console.print("\n[dim]Valid = Cache is fresh, Expired = Will auto-refresh on next access[/dim]")
            return True

        elif cmd == '/ssh-info':
            console.print("\n[bold]SSH Configuration[/bold]\n")

            if self.credentials.supports_agent():
                agent_keys = self.credentials.get_agent_keys()
                if agent_keys:
                    console.print(f"[green]✓ ssh-agent: {len(agent_keys)} keys loaded[/green]")
                else:
                    console.print(f"[yellow]⚠ ssh-agent detected but no keys[/yellow]")
            else:
                console.print(f"[red]✗ ssh-agent not available[/red]")

            keys = self.credentials.get_ssh_keys()
            console.print(f"\nSSH Keys: {len(keys)} available")

            default_key = self.credentials.get_default_key()
            if default_key:
                console.print(f"Default: {default_key}\n")

            return True

        elif cmd.startswith('/permissions'):
            # /permissions [hostname] - Show permission capabilities
            args = cmd.split()[1:] if ' ' in cmd else []

            if not args:
                # Show cached permission info for all hosts
                if not self.orchestrator.permissions.capabilities_cache:
                    console.print("[yellow]No permission data cached yet.[/yellow]")
                    console.print("[dim]Run commands on hosts to detect permissions automatically.[/dim]")
                else:
                    console.print("\n[bold]Permission Capabilities (Cached)[/bold]\n")
                    for target, caps in self.orchestrator.permissions.capabilities_cache.items():
                        console.print(f"[cyan]{target}[/cyan]:")
                        console.print(self.orchestrator.permissions.format_capabilities_summary(target))
                        console.print()
            else:
                # Show permissions for specific host
                target = args[0]
                console.print(f"\n[bold]Detecting permissions on {target}...[/bold]\n")
                try:
                    caps = self.orchestrator.permissions.detect_capabilities(target)
                    console.print(self.orchestrator.permissions.format_capabilities_summary(target))
                except Exception as e:
                    console.print(f"[red]Error: {e}[/red]")

            return True

        elif cmd == '/context':
            context = self.context_manager.get_context()
            local = context.get('local', {})
            inventory = context.get('inventory', {})
            remote_hosts = context.get('remote_hosts', {})

            console.print(f"\n[bold]Current Context[/bold]")
            console.print(f"  Local: {local.get('hostname')} ({local.get('os')})")
            console.print(f"  Inventory: {len(inventory)} hosts")

            if remote_hosts:
                accessible = sum(1 for h in remote_hosts.values() if h.get('accessible'))
                console.print(f"  Remote: {accessible}/{len(remote_hosts)} accessible\n")

            return True

        elif cmd == '/session':
            if 'list' in args:
                sessions = self.session_manager.list_sessions(limit=5)
                from rich.table import Table
                table = Table(title="Recent Sessions")
                table.add_column("Session ID", style="cyan")
                table.add_column("Started", style="green")
                table.add_column("Queries", style="magenta")

                for s in sessions:
                    table.add_row(s['id'], s['started_at'], str(s['total_queries']))

                console.print(table)
            else:
                console.print(f"Current session: {self.session_manager.current_session_id}")
                console.print("Use: /session list")

            return True

        elif cmd == '/model':
            return self._handle_model_command(args)

        elif cmd in ['/variables', '/credentials']:
            # /credentials is now an alias for /variables
            return self._handle_variables_command(args)

        elif cmd == '/mcp':
            return self._handle_mcp_command(args)

        elif cmd == '/language':
            return self._handle_language_command(args)

        elif cmd == '/triage':
            return self._handle_triage_command(args)

        elif cmd == '/conversations':
            return self._handle_conversations_command(args)

        elif cmd == '/new':
            return self._handle_new_conversation_command(args)

        elif cmd == '/load':
            return self._handle_load_conversation_command(args)

        elif cmd == '/compact':
            return self._handle_compact_conversation_command(args)

        elif cmd == '/delete' and args:  # Only handle if args exist (to avoid conflict with /variables delete)
            return self._handle_delete_conversation_command(args)

        return False

    def _handle_variables_command(self, args: list) -> bool:
        """
        Handle /variables command for managing all types of variables.

        Supports:
        - Host aliases: /variables set preproddb db-qarc-1
        - User variables: /variables set myuser cedric
        - Credentials: /variables set mongo-user admin
        - Secrets: /variables set-secret mongo-pass (secure input)
        """

        # /variables set <key> <value>
        if args and args[0] == 'set':
            if len(args) >= 3:
                key = args[1]
                value = ' '.join(args[2:])  # Support values with spaces
                self.credentials.set_variable(key, value)
                console.print(f"[green]✓ Variable '{key}' = '{value}'[/green]")
                console.print(f"[dim]Use @{key} in your queries[/dim]")
            else:
                console.print("[red]Error: Missing key or value[/red]")
                console.print("[yellow]Usage: /variables set <key> <value>[/yellow]")
                console.print("[dim]Examples:[/dim]")
                console.print("[dim]  /variables set preproddb db-qarc-1  (host alias)[/dim]")
                console.print("[dim]  /variables set mongo-user admin        (credential)[/dim]")
                console.print("[dim]  /variables set myenv production        (context)[/dim]")
            return True

        # /variables set-secret <key> - Secure input with getpass
        elif args and args[0] in ['set-secret', 'secret']:
            if len(args) >= 2:
                key = args[1]
                if self.credentials.set_variable_secure(key):
                    console.print(f"[green]✓ Secret variable '{key}' set securely[/green]")
                    console.print(f"[dim]Use @{key} in your queries[/dim]")
                else:
                    console.print(f"[yellow]Secret variable not saved[/yellow]")
            else:
                console.print("[red]Error: Missing key[/red]")
                console.print("[yellow]Usage: /variables set-secret <key>[/yellow]")
                console.print("[dim]Examples:[/dim]")
                console.print("[dim]  /variables set-secret mongo-pass    (password)[/dim]")
                console.print("[dim]  /variables set-secret api-key       (API key)[/dim]")
                console.print("[dim]  /variables set-secret ssh-key       (SSH private key)[/dim]")
            return True

        # /credentials list
        elif args and args[0] == 'list':
            variables = self.credentials.list_variables()
            if not variables:
                console.print("[yellow]No credential variables defined[/yellow]")
            else:
                from rich.table import Table
                table = Table(title="Credential Variables")
                table.add_column("Variable", style="cyan")
                table.add_column("Value", style="green")

                for key, value in sorted(variables.items()):
                    # Mask sensitive values (passwords, tokens, API keys, secrets)
                    display_value = value
                    key_lower = key.lower()

                    # Check if key name suggests it's sensitive
                    sensitive_keywords = ['pass', 'pwd', 'password', 'secret', 'token',
                                        'key', 'api', 'auth', 'credential', 'jwt', 'cert',
                                        'private', 'signature', 'encryption']
                    is_sensitive = any(kw in key_lower for kw in sensitive_keywords)

                    # Also mask long values that look like tokens/keys (>20 chars, no spaces)
                    looks_like_secret = len(value) > 20 and ' ' not in value

                    if is_sensitive or looks_like_secret:
                        # Show first 4 and last 4 chars for identification
                        if len(value) > 12:
                            display_value = value[:4] + '*' * 12 + value[-4:]
                        else:
                            display_value = '*' * len(value)

                    table.add_row(f"@{key}", display_value)

                console.print(table)
                console.print("\n[dim]Use @variable in your queries to reference them[/dim]")
            return True

        # /credentials delete <key>
        elif args and args[0] in ['delete', 'del', 'remove']:
            if len(args) >= 2:
                key = args[1]
                if self.credentials.delete_variable(key):
                    console.print(f"[green]✓ Variable '{key}' deleted[/green]")
                else:
                    console.print(f"[yellow]Variable '{key}' not found[/yellow]")
            else:
                console.print("[red]Error: Missing variable name[/red]")
                console.print("[yellow]Usage: /credentials delete <key>[/yellow]")
            return True

        # /credentials clear
        elif args and args[0] == 'clear':
            self.credentials.clear_session_credentials()
            self.credentials.clear_variables()
            console.print("[green]✓ All credentials and variables cleared[/green]")
            return True

        # Show usage
        else:
            console.print("[yellow]Usage:[/yellow]")
            console.print("  /credentials set <key> <value>     - Set a credential variable (plain text)")
            console.print("  /credentials set-secret <key>      - Set a secret securely (hidden input)")
            console.print("  /credentials list                  - List all variables")
            console.print("  /credentials delete <key>          - Delete a variable")
            console.print("  /credentials clear                 - Clear all credentials and variables")
            console.print("\n[dim]Examples:[/dim]")
            console.print("[dim]  /credentials set mongo-user admin           # Non-sensitive (username)[/dim]")
            console.print("[dim]  /credentials set-secret mongo-pass          # Secure input for password[/dim]")
            console.print("[dim]  /credentials set-secret api-key             # Secure input for API key[/dim]")
            console.print("[dim]  /credentials set-secret ssh-private-key     # Secure input for SSH key[/dim]")
            console.print("[dim]  Then use: 'check mongo with @mongo-user @mongo-pass'[/dim]")
            return True

    def _handle_model_command(self, args: list) -> bool:
        """Handle /model command for model configuration."""
        model_config = self.orchestrator.llm_router.model_config

        # /model show - Show current config
        if not args or args[0] == 'show':
            config = model_config.get_current_config()
            from rich.table import Table

            console.print(f"\n[bold]Current Model Configuration[/bold]\n")
            console.print(f"  Provider: [cyan]{config['provider']}[/cyan]")
            console.print(f"  Model: [green]{config['model']}[/green]")

            # Show task-specific models
            console.print(f"\n[bold]Task Models:[/bold]")
            for task, model_alias in config['task_models'].items():
                console.print(f"  {task}: [yellow]{model_alias}[/yellow]")

            console.print()
            return True

        # /model list [provider] - List available models
        elif args[0] == 'list':
            provider = args[1] if len(args) > 1 else None
            models = model_config.list_models(provider)
            provider_name = provider or model_config.get_provider()

            from rich.table import Table
            table = Table(title=f"Available Models - {provider_name}")
            table.add_column("Model", style="cyan")

            for model in models:
                table.add_row(model)

            console.print(table)
            console.print(f"\n[dim]Use: /model set {provider_name} <model>[/dim]")
            return True

        # /model set <model> OR /model set <provider> <model>
        elif args[0] == 'set':
            if len(args) == 2:
                # Short syntax: /model set <model> (uses current provider)
                provider = model_config.get_provider()
                model = args[1]
            elif len(args) >= 3:
                # Full syntax: /model set <provider> <model>
                provider = args[1]
                model = args[2]
            else:
                console.print("[red]Error: Missing model name[/red]")
                console.print("[yellow]Usage:[/yellow]")
                console.print("  /model set <model> - Set model for current provider")
                console.print("  /model set <provider> <model> - Set model for specific provider")
                return True

            try:
                model_config.set_model(provider, model)
                console.print(f"[green]✓ Model for {provider} set to: {model}[/green]")
            except ValueError as e:
                console.print(f"[red]Error: {e}[/red]")

            return True

        # /model provider <provider> - Set current provider
        elif args[0] == 'provider' and len(args) >= 2:
            provider = args[1]

            try:
                # Switch provider using LiteLLMRouter's switch_provider method
                self.orchestrator.llm_router.switch_provider(provider)
                console.print(f"[green]✓ Provider set to: {provider}[/green]")
            except ValueError as e:
                console.print(f"[red]Error: {e}[/red]")

            return True

        # /model task - Task model management
        elif args[0] == 'task':
            if len(args) == 1 or (len(args) == 2 and args[1] == 'show'):
                # /model task show - Show task models
                task_models = model_config.get_task_models()
                from rich.table import Table

                table = Table(title="Task Models Configuration")
                table.add_column("Task", style="cyan")
                table.add_column("Model Alias", style="yellow")
                table.add_column("Description", style="dim")

                descriptions = {
                    "correction": "Fast corrections (uses quick model)",
                    "planning": "Complex planning (uses intelligent model)",
                    "synthesis": "Data synthesis (uses balanced model)"
                }

                for task, alias in task_models.items():
                    desc = descriptions.get(task, "")
                    table.add_row(task, alias, desc)

                console.print(table)
                console.print("\n[dim]💡 You can use:[/dim]")
                console.print("[dim]   - Aliases (haiku, sonnet, opus) for Claude models[/dim]")
                console.print("[dim]   - Full model paths (qwen/..., meta-llama/..., etc.) for ANY model[/dim]")
                console.print("[dim]   - Mix and match! Use different models for different tasks[/dim]")
                return True

            elif len(args) >= 4 and args[1] == 'set':
                # /model task set <task> <alias>
                task = args[2]
                alias = args[3]

                try:
                    model_config.set_task_model(task, alias)
                    console.print(f"[green]✓ Task model for '{task}' set to: {alias}[/green]")
                except ValueError as e:
                    console.print(f"[red]Error: {e}[/red]")

                return True

            else:
                console.print("[yellow]Usage:[/yellow]")
                console.print("  /model task show - Show task model configuration")
                console.print("  /model task set <task> <model> - Set task-specific model")
                console.print("\n[dim]Tasks:[/dim] correction, planning, synthesis")
                console.print("[dim]Model can be:[/dim]")
                console.print("  [dim]- Alias: haiku, sonnet, opus (for Claude)[/dim]")
                console.print("  [dim]- Full path: qwen/qwen-2.5-coder-7b-instruct (ANY model!)[/dim]")
                console.print("\n[dim]Examples:[/dim]")
                console.print("[dim]  /model task set correction haiku                          # Claude alias[/dim]")
                console.print("[dim]  /model task set planning qwen/qwen3-coder-30b-a3b-instruct  # Qwen[/dim]")
                console.print("[dim]  /model task set synthesis meta-llama/llama-3.1-70b-instruct # Llama[/dim]")
                return True

        else:
            console.print("[yellow]Usage:[/yellow]")
            console.print("  /model show - Show current configuration")
            console.print("  /model list [provider] - List available models")
            console.print("  /model set <model> - Set model for current provider")
            console.print("  /model set <provider> <model> - Set model for specific provider")
            console.print("  /model provider <provider> - Switch provider")
            console.print("  /model task show - Show task model configuration")
            console.print("  /model task set <task> <alias> - Set task-specific model")
            console.print("\n[dim]Providers: openrouter, anthropic, openai, ollama[/dim]")
            console.print("\n[dim]Examples:[/dim]")
            console.print("[dim]  /model set z-ai/glm-4.5-air:free[/dim]")
            console.print("[dim]  /model set openrouter anthropic/claude-3.5-sonnet[/dim]")
            console.print("[dim]  /model task set planning opus[/dim]")
            return True

    def _handle_mcp_command(self, args: list) -> bool:
        """
        Handle /mcp command for managing MCP servers.

        Commands:
        - /mcp list - List all configured MCP servers
        - /mcp add - Add a new MCP server (prompts for JSON config)
        - /mcp delete <name> - Delete an MCP server
        - /mcp show <name> - Show configuration of an MCP server
        - /mcp examples - Show example configurations
        """

        # /mcp list - List all servers
        if not args or args[0] == 'list':
            servers = self.mcp_manager.list_servers()
            if not servers:
                console.print("[yellow]No MCP servers configured[/yellow]")
                console.print("[dim]Use /mcp add to add a server, or /mcp examples for examples[/dim]")
            else:
                from rich.table import Table
                table = Table(title="MCP Servers")
                table.add_column("Name", style="cyan")
                table.add_column("Type", style="green")
                table.add_column("Command", style="yellow")

                for name, config in sorted(servers.items()):
                    server_type = config.get('type', 'unknown')
                    command = config.get('command', 'N/A')
                    table.add_row(name, server_type, command)

                console.print(table)
                console.print("\n[dim]Use @mcp <server-name> in your queries to use the server[/dim]")
            return True

        # /mcp add - Add a new server
        elif args[0] == 'add':
            console.print("\n[bold]Add MCP Server[/bold]\n")
            console.print("[dim]Enter server name (e.g., filesystem, git, github):[/dim]")

            # Prompt for server name
            try:
                name = input("Server name: ").strip()
                if not name:
                    console.print("[red]Error: Server name cannot be empty[/red]")
                    return True

                console.print("\n[dim]Enter JSON configuration (multi-line, press Ctrl+D when done):[/dim]")
                console.print("[dim]Example:[/dim]")
                console.print('[dim]{"type": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"]}[/dim]\n')

                # Read multi-line JSON input
                lines = []
                try:
                    while True:
                        line = input()
                        lines.append(line)
                except EOFError:
                    pass

                json_str = '\n'.join(lines)

                # Parse JSON
                try:
                    config = json.loads(json_str)
                except json.JSONDecodeError as e:
                    console.print(f"[red]Error: Invalid JSON - {e}[/red]")
                    return True

                # Add server
                if self.mcp_manager.add_server(name, config):
                    console.print(f"\n[green]✓ MCP server '{name}' added successfully[/green]")
                    console.print(f"[dim]Use @mcp {name} in your queries to activate this server[/dim]")
                else:
                    console.print(f"[red]Failed to add MCP server '{name}'[/red]")

            except KeyboardInterrupt:
                console.print("\n[yellow]Cancelled[/yellow]")

            return True

        # /mcp delete <name> - Delete a server
        elif args[0] in ['delete', 'del', 'remove']:
            if len(args) < 2:
                console.print("[red]Error: Missing server name[/red]")
                console.print("[yellow]Usage: /mcp delete <server-name>[/yellow]")
                return True

            name = args[1]
            if self.mcp_manager.delete_server(name):
                console.print(f"[green]✓ MCP server '{name}' deleted[/green]")
            else:
                console.print(f"[yellow]MCP server '{name}' not found[/yellow]")

            return True

        # /mcp show <name> - Show server config
        elif args[0] == 'show':
            if len(args) < 2:
                console.print("[red]Error: Missing server name[/red]")
                console.print("[yellow]Usage: /mcp show <server-name>[/yellow]")
                return True

            name = args[1]
            config = self.mcp_manager.get_server(name)

            if config:
                console.print(f"\n[bold]MCP Server: {name}[/bold]\n")
                console.print(json.dumps(config, indent=2))
            else:
                console.print(f"[yellow]MCP server '{name}' not found[/yellow]")

            return True

        # /mcp examples - Show example configurations
        elif args[0] == 'examples':
            examples = self.mcp_manager.get_example_configs()

            console.print("\n[bold]Example MCP Server Configurations[/bold]\n")

            for name, config in examples.items():
                console.print(f"[cyan]{name}[/cyan]:")
                console.print(json.dumps(config, indent=2))
                console.print()

            console.print("[dim]To add a server, use: /mcp add[/dim]")
            return True

        # Show usage
        else:
            console.print("[yellow]Usage:[/yellow]")
            console.print("  /mcp list - List all configured MCP servers")
            console.print("  /mcp add - Add a new MCP server (interactive)")
            console.print("  /mcp delete <name> - Delete an MCP server")
            console.print("  /mcp show <name> - Show server configuration")
            console.print("  /mcp examples - Show example configurations")
            console.print("\n[dim]Usage in queries:[/dim]")
            console.print("[dim]  @mcp filesystem list files in /tmp[/dim]")
            console.print("[dim]  @mcp git show recent commits[/dim]")
            return True

    def _handle_language_command(self, args: list) -> bool:
        """
        Handle /language command to change language preference.

        Commands:
        - /language - Show current language
        - /language en - Set language to English
        - /language fr - Set language to French
        """
        if not args:
            # Show current language
            current = self.config.language or 'en'
            lang_name = 'English' if current == 'en' else 'Français'
            console.print(f"\n[bold]Current Language / Langue actuelle:[/bold] {lang_name} ({current})\n")
            console.print("[dim]Usage: /language <en|fr>[/dim]")
            return True

        lang = args[0].lower()
        if lang not in ['en', 'fr']:
            console.print("[red]Error: Language must be 'en' or 'fr'[/red]")
            console.print("[dim]Usage: /language <en|fr>[/dim]")
            return True

        # Update language
        self.config.language = lang

        # Recreate orchestrator with new language
        self.orchestrator = Orchestrator(env=self.env, language=lang)

        if lang == 'en':
            console.print("[green]✓ Language set to English[/green]")
            console.print("[dim]All responses will now be in English[/dim]")
        else:
            console.print("[green]✓ Langue définie sur Français[/green]")
            console.print("[dim]Toutes les réponses seront maintenant en français[/dim]")

        return True

    def _handle_triage_command(self, args: list) -> bool:
        """
        Handle /triage command to test priority classification.

        Usage:
        - /triage <query> - Classify a query without executing
        - /triage - Show triage help
        """
        if not args:
            console.print("\n[bold]🎯 Triage System[/bold]\n")
            console.print("Automatic priority classification (P0-P3) based on query analysis.\n")
            console.print("[yellow]Usage:[/yellow]")
            console.print("  /triage <query> - Test classification for a query\n")
            console.print("[dim]Examples:[/dim]")
            console.print("  /triage MongoDB is down on prod-db-01")
            console.print("  /triage High latency on staging API")
            console.print("  /triage Check nginx config")
            console.print("\n[bold]Priority Levels:[/bold]")
            console.print("  [bold red]P0[/bold red] - CRITICAL: Production down, data loss, security breach")
            console.print("  [bold #FFA500]P1[/bold #FFA500] - URGENT: Service degraded, vulnerability, imminent failure")
            console.print("  [bold yellow]P2[/bold yellow] - IMPORTANT: Performance issues, non-critical failures")
            console.print("  [bold blue]P3[/bold blue] - NORMAL: Standard requests, maintenance tasks")
            return True

        # Classify the query
        query = " ".join(args)
        result = classify_priority(query)
        behavior = get_behavior(result.priority)

        # Build display
        priority = result.priority
        color = priority.color

        console.print(f"\n[bold]🎯 Triage Result[/bold]\n")

        # Priority with color
        console.print(Panel(
            f"[bold {color}]{priority.name}[/bold {color}] - {priority.label}\n\n"
            f"[dim]Confidence: {result.confidence:.0%}[/dim]",
            title="Priority",
            border_style=color,
        ))

        # Signals detected
        if result.signals:
            console.print(f"\n[bold]Signals detected:[/bold]")
            for signal in result.signals:
                console.print(f"  • {signal}")

        # Context detected
        context_parts = []
        if result.environment_detected:
            context_parts.append(f"Environment: {result.environment_detected}")
        if result.service_detected:
            context_parts.append(f"Service: {result.service_detected}")
        if result.host_detected:
            context_parts.append(f"Host: {result.host_detected}")

        if context_parts:
            console.print(f"\n[bold]Context:[/bold]")
            for part in context_parts:
                console.print(f"  • {part}")

        # Reasoning
        console.print(f"\n[bold]Reasoning:[/bold]")
        console.print(f"  {result.reasoning}")

        # Behavior profile
        console.print(f"\n[bold]Behavior Profile:[/bold]")
        console.print(f"  Mode: {describe_behavior(priority)}")
        console.print(f"  Auto-confirm reads: {'Yes' if behavior.auto_confirm_reads else 'No'}")
        console.print(f"  Auto-confirm writes: {'Yes' if behavior.auto_confirm_writes else 'No'}")
        console.print(f"  Response format: {behavior.response_format}")

        # Escalation warning
        if result.escalation_required:
            console.print(f"\n[bold red]⚠️  ESCALATION REQUIRED[/bold red]")
            console.print(f"[dim]This issue requires immediate attention![/dim]")

        console.print()
        return True

    def _handle_conversations_command(self, args: list) -> bool:
        """Handle /conversations command to list all conversations."""
        conversations = self.conversation_manager.list_conversations(limit=20)

        if not conversations:
            console.print("[yellow]No conversations found[/yellow]")
            return True

        from rich.table import Table
        table = Table(title="📚 Conversations Available")
        table.add_column("ID", style="cyan")
        table.add_column("Title", style="green")
        table.add_column("Messages", style="magenta")
        table.add_column("Tokens", style="yellow")
        table.add_column("Status", style="blue")

        for conv in conversations:
            status = "Current" if conv.get("current") else "Archived"
            table.add_row(
                conv["id"],
                conv["title"][:40],  # Truncate long titles
                str(conv["message_count"]),
                f"{conv['token_count']:,}",
                status
            )

        console.print(table)
        console.print("\n[dim]Use /load <id> to load a conversation[/dim]")
        console.print("[dim]Use /new to start a new conversation[/dim]")
        return True

    def _handle_new_conversation_command(self, args: list) -> bool:
        """Handle /new command to start a new conversation."""
        title = " ".join(args) if args else None

        conv_id = self.conversation_manager.start_new_conversation(title=title)

        console.print(f"\n[green]✅ Started new conversation: {conv_id}[/green]")
        if title:
            console.print(f"[dim]Title: {title}[/dim]")

        # Show token usage
        usage = self.conversation_manager.get_token_usage_percent()
        console.print(f"[dim]Token usage: {usage:.1f}% of limit[/dim]\n")

        return True

    def _handle_load_conversation_command(self, args: list) -> bool:
        """Handle /load command to load a conversation."""
        if not args:
            console.print("[red]Error: Missing conversation ID[/red]")
            console.print("[yellow]Usage: /load <conversation_id>[/yellow]")
            console.print("[dim]Tip: Use /conversations to list all conversations[/dim]")
            return True

        conv_id = args[0]

        if self.conversation_manager.switch_to_conversation(conv_id):
            conv = self.conversation_manager.current_conversation
            console.print(f"\n[green]✅ Loaded conversation: {conv.title}[/green]")
            console.print(f"[dim]Messages: {len(conv.messages)}[/dim]")
            console.print(f"[dim]Tokens: {conv.token_count:,}[/dim]")

            # Show token usage
            usage = self.conversation_manager.get_token_usage_percent()
            console.print(f"[dim]Token usage: {usage:.1f}% of limit[/dim]\n")
        else:
            console.print(f"[red]❌ Failed to load conversation: {conv_id}[/red]")
            console.print("[dim]Use /conversations to see available conversations[/dim]")

        return True

    def _handle_compact_conversation_command(self, args: list) -> bool:
        """Handle /compact command to compact current conversation."""
        if not self.conversation_manager.current_conversation:
            console.print("[yellow]No current conversation to compact[/yellow]")
            return True

        old_tokens = self.conversation_manager.get_current_tokens()

        console.print("\n[cyan]🔄 Compacting conversation...[/cyan]")

        if self.conversation_manager.compact_conversation():
            new_tokens = self.conversation_manager.get_current_tokens()

            console.print(f"[green]✅ Conversation compacted[/green]")
            console.print(f"[dim]Reduced from {old_tokens:,} tokens to {new_tokens:,} tokens[/dim]")
            console.print(f"[dim]💡 Started new conversation with summary[/dim]\n")
        else:
            console.print("[red]❌ Failed to compact conversation[/red]")

        return True

    def _handle_delete_conversation_command(self, args: list) -> bool:
        """Handle /delete command to delete a conversation."""
        if not args:
            console.print("[red]Error: Missing conversation ID[/red]")
            console.print("[yellow]Usage: /delete <conversation_id>[/yellow]")
            return True

        conv_id = args[0]

        # Load conversation to show info
        conv = self.conversation_manager.load_conversation(conv_id)
        if not conv:
            console.print(f"[yellow]Conversation '{conv_id}' not found[/yellow]")
            return True

        # Confirm deletion
        console.print(f"\n[yellow]⚠️  Delete conversation '{conv.title}'?[/yellow]")
        console.print(f"[dim]  Messages: {len(conv.messages)}[/dim]")
        console.print(f"[dim]  Tokens: {conv.token_count:,}[/dim]")

        try:
            confirm = input("Confirm [y/N]: ").strip().lower()
            if confirm == 'y':
                if self.conversation_manager.delete_conversation(conv_id):
                    console.print(f"[green]✅ Conversation deleted[/green]")
                else:
                    console.print(f"[red]❌ Failed to delete conversation[/red]")
            else:
                console.print("[dim]Cancelled[/dim]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Cancelled[/dim]")

        return True

    def _handle_reset_command(self, args: list) -> bool:
        """Handle /reset command to reset Ag2 agents."""
        self.orchestrator.reset_session()
        # Also clear conversation history in manager to stay in sync
        self.conversation_manager.start_new_conversation(title="New Session (Reset)")
        console.print("[green]✅ Ag2 Agents and Conversation History Reset[/green]")
        return True

    def run(self):
        """Run the interactive REPL."""
        self.show_welcome()

        while True:
            try:
                # Get user input
                user_input = self.session.prompt('\n🦉 athena> ', multiline=False)

                if not user_input.strip():
                    continue

                # Handle slash commands
                if user_input.startswith('/'):
                    result = self.handle_slash_command(user_input)
                    if result == 'exit':
                        console.print("\n[yellow]Ending session...[/yellow]")
                        self.session_manager.end_session()
                        console.print("[green]Goodbye! 👋[/green]\n")
                        break
                    continue

                # Regular query - send to orchestrator
                console.print()  # New line

                # Add user message to conversation
                self.conversation_manager.add_user_message(user_input)

                # Check if we should compact
                if self.conversation_manager.should_compact():
                    usage = self.conversation_manager.get_token_usage_percent()
                    console.print(f"[yellow]⚠️  WARNING: Conversation approaching token limit ({usage:.1f}% used)[/yellow]")
                    console.print("[dim]💡 Tip: Use /compact to summarize and start fresh, or /new to start a new conversation[/dim]\n")

                # Auto-compact if at limit
                if self.conversation_manager.must_compact():
                    console.print("[cyan]🔄 AUTO-COMPACTING: Token limit reached[/cyan]")
                    self.conversation_manager.compact_conversation()
                    console.print("[green]✅ Conversation compacted automatically[/green]")
                    console.print("[dim]📊 Summary created, new conversation started[/dim]\n")

                # Process request with Ag2Orchestrator (async)
                # Uses process_request which includes triage classification
                # Note: Streaming callbacks in orchestrator display agent activity in real-time
                with console.status("[cyan]🤖 Agents working...[/cyan]", spinner="dots"):
                    response = asyncio.run(
                        self.orchestrator.process_request(user_query=user_input)
                    )

                # Add assistant response to conversation
                self.conversation_manager.add_assistant_message(response)

                # Display response - Ag2 returns markdown, render it properly
                console.print()
                console.print(Markdown(response))

            except KeyboardInterrupt:
                console.print("\n[yellow]Use /exit or Ctrl+D to quit[/yellow]")
                continue

            except EOFError:
                console.print("\n[yellow]Ending session...[/yellow]")
                self.session_manager.end_session()
                console.print("[green]Goodbye! 👋[/green]\n")
                break

            except Exception as e:
                console.print(f"\n[red]Error: {e}[/red]")
                logger.error(f"REPL error: {e}")


def start_repl(env: str = "dev"):
    """Start the interactive REPL."""
    repl = AthenaREPL(env=env)
    repl.run()
