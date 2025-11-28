"""
Help command handler.

Handles: /help
"""

from rich.markdown import Markdown

from athena_ai.repl.ui import console


SLASH_COMMANDS = {
    '/help': 'Show available slash commands',
    '/scan': 'Scan infrastructure (--full for SSH scan)',
    '/refresh': 'Force refresh context (--full for SSH scan)',
    '/cache-stats': 'Show cache statistics',
    '/ssh-info': 'Show SSH configuration',
    '/permissions': 'Show permission capabilities [hostname]',
    '/session': 'Session management (list, show, export)',
    '/context': 'Show current context',
    '/model': 'Model management (list, set, show)',
    '/variables': 'Manage variables (hosts, credentials, etc.)',
    '/credentials': 'Alias for /variables (backward compatibility)',
    '/inventory': 'Manage host inventory (add, list, show, remove, export, relations)',
    '/mcp': 'Manage MCP servers (add, list, delete, show)',
    '/language': 'Change language (en/fr)',
    '/triage': 'Test priority classification for a query',
    '/feedback': 'Correct triage classification (intent/priority)',
    '/triage-stats': 'Show learned triage patterns statistics',
    '/conversations': 'List all conversations',
    '/new': 'Start new conversation [title]',
    '/load': 'Load conversation <id>',
    '/compact': 'Compact current conversation',
    '/delete': 'Delete conversation <id>',
    '/reset': 'Reset Ag2 agents memory',
    '/exit': 'Exit Athena',
    '/quit': 'Exit Athena',
}


class HelpCommandHandler:
    """Handles help-related slash commands."""

    def __init__(self, repl):
        """Initialize with reference to the main REPL instance."""
        self.repl = repl

    def show_help(self) -> bool:
        """Show help message."""
        help_text = self._build_help_text()
        console.print(Markdown(help_text))
        return True

    def _build_help_text(self) -> str:
        """Build the help text."""
        help_text = "## Available Slash Commands\n\n"
        for cmd, desc in SLASH_COMMANDS.items():
            help_text += f"**{cmd}**: {desc}\n"

        help_text += self._smart_context_section()
        help_text += self._model_config_section()
        help_text += self._variables_section()
        help_text += self._inventory_section()
        help_text += self._examples_section()
        help_text += self._mcp_section()
        help_text += self._custom_commands_section()

        return help_text

    def _smart_context_section(self) -> str:
        return """
## Smart Context System

Athena uses intelligent caching that auto-detects changes:
- **Inventory** (/etc/hosts): Auto-refreshes when file changes (1h TTL)
- **Local info**: Cached for 5 minutes
- **Remote hosts**: Cached for 30 minutes
- Use `/cache-stats` to see cache state
- Use `/refresh` to force update (add `--full` to include SSH scan)
"""

    def _model_config_section(self) -> str:
        return """
## Model Configuration

**LLM Models (for chat and planning):**
- `/model show` - Show current model configuration
- `/model list` - List available models for current provider
- `/model set <provider> <model>` - Set model for provider
- `/model provider <provider>` - Switch provider (openrouter, anthropic, openai, ollama)
- Task-specific models: Fast model for corrections, best model for complex planning

**Embedding Models (for AI features):**
- `/model embedding` - Show current embedding model
- `/model embedding list` - List all available embedding models
- `/model embedding set <model>` - Change embedding model
- Models: BGE, E5, GTE, MiniLM families (sizes: 17-420MB)
- Used for: Triage classification, tool selection, error analysis
- Persist with: `ATHENA_EMBEDDING_MODEL` environment variable
"""

    def _variables_section(self) -> str:
        return """
## Variables System (@variables)

Define reusable variables for hosts, credentials, and more:

**Host Aliases:**
- `/variables set preproddb db-qarc-1` - Define host alias
- `/variables set prodmongo mongo-preprod-1` - Another host
- Use: `check mysql on @preproddb`

**Credentials:**
- `/variables set mongo-user admin` - Username (visible)
- `/variables set-secret mongo-pass` - Password (secure input, hidden)
- Use: `check mongo on @preproddb using @mongo-user @mongo-pass`

**Other Variables:**
- `/variables set myenv production` - Context variables
- `/variables set region eu-west-1` - Any value you need

**Management:**
- `/variables list` - Show all variables (secrets masked)
- `/variables delete <key>` - Delete a variable
- `/variables clear` - Clear all variables
- Note: `/credentials` is an alias for `/variables`
"""

    def _inventory_section(self) -> str:
        return """
## Inventory System

Manage your infrastructure hosts with `/inventory`:

**Commands:**
- `/inventory list` - List all hosts in inventory
- `/inventory add <file>` - Import hosts from file (CSV, JSON, YAML, INI, /etc/hosts, ~/.ssh/config)
- `/inventory add-host [name]` - Add a single host interactively
- `/inventory show <hostname>` - Show host details
- `/inventory search <query>` - Search hosts by name, group, or IP
- `/inventory remove <hostname>` - Remove a host
- `/inventory export [format]` - Export inventory (json, csv, yaml)
- `/inventory relations [suggest]` - Show/suggest host relations
- `/inventory snapshot [name]` - Create/list inventory snapshots
- `/inventory stats` - Show inventory statistics

**SSH Key Management:**
- `/inventory ssh-key <host>` - Show SSH key config for host
- `/inventory ssh-key <host> set` - Set SSH key path (interactive)
- `/inventory ssh-key <host> clear` - Remove SSH key config
- Passphrases are stored as secrets (in-memory only, never persisted)

**Host References (@hostname):**
Reference any inventory host in your prompts using `@hostname`:
- `check nginx on @web-prod-01` - Target specific host
- `compare disk usage @db-master vs @db-replica`
- `restart service on @backend-01 @backend-02`

Auto-completion is available for inventory hosts.
"""

    def _examples_section(self) -> str:
        return """
## Examples

- `list mongo preprod IPs`
- `check if nginx is running on web-prod-001`
- `what services are running on mongo-preprod-1`
- `check redis on @cache-prod-01` (using inventory host)
- `/scan --full` (scan all hosts via SSH)
- `/cache-stats` (check cache status)
- `/refresh` (force refresh local context)
- `/refresh --full` (force refresh + SSH scan)
- `/model list openrouter` (list OpenRouter models)
- `/model set openrouter anthropic/claude-3-opus` (switch to Opus)
"""

    def _mcp_section(self) -> str:
        return """
## MCP (Model Context Protocol)

MCP extends Athena with standardized external tools.

**Commands:**
- `/mcp list` - List configured servers
- `/mcp add` - Add a server (interactive)
- `/mcp delete <name>` - Remove a server
- `/mcp examples` - Show example configurations

**Popular MCP Servers:**
- `@modelcontextprotocol/server-filesystem` - File operations
- `@modelcontextprotocol/server-git` - Git operations
- `@modelcontextprotocol/server-postgres` - PostgreSQL queries
- `@modelcontextprotocol/server-brave-search` - Web search

**Usage:** MCP tools are auto-available to agents once configured.
Example: After adding filesystem server, say 'list files in /tmp'
"""

    def _custom_commands_section(self) -> str:
        """Build custom commands section if any exist."""
        try:
            custom_commands = self.repl.command_loader.list_commands()
        except Exception as e:
            # command_loader may be uninitialized or fail
            if hasattr(self.repl, 'logger') and self.repl.logger:
                self.repl.logger.error(f"Failed to load custom commands: {e}")
            return f"\n## Custom Commands\n\nError loading commands: {e}\n"
        custom_commands = {}

        if not custom_commands:
            return ""

        section = "\n## Custom Commands\n\n"
        section += "Extensible commands loaded from markdown files:\n\n"
        for name, desc in custom_commands.items():
            section += f"- `/{name}`: {desc}\n"
        section += "\n*Add your own in `~/.athena/commands/*.md`*\n"
        return section
