"""
Help command handler.

Handles: /help [topic]
"""
from typing import Any, List, Optional

from rich.markdown import Markdown
from rich.table import Table

from merlya.repl.ui import console

# Available help topics
HELP_TOPICS = [
    'model', 'variables', 'inventory', 'cicd', 'mcp', 'context', 'session', 'stats'
]

# Quick reference for main help
SLASH_COMMANDS = {
    # Context
    '/scan': 'Scan local or specific host [hostname]',
    '/refresh': 'Force refresh context [hostname]',
    '/cache-stats': 'Show cache statistics',
    '/context': 'Show current context',
    '/ssh-info': 'Show SSH configuration',
    '/permissions': 'Show permission capabilities [hostname]',
    # Model
    '/model': 'Model management (show, list, set, provider, local, task, embedding)',
    # Variables
    '/variables': 'Manage variables (set, set-host, set-secret, list, delete, clear)',
    # Inventory
    '/inventory': 'Manage hosts (add, list, show, search, remove, export, relations)',
    # CI/CD
    '/cicd': 'CI/CD management (status, workflows, runs, analyze, trigger)',
    '/debug-workflow': 'Debug a CI/CD workflow failure [run_id]',
    # MCP
    '/mcp': 'Manage MCP servers (list, add, delete, show, examples)',
    # Triage
    '/triage': 'Test priority classification for a query',
    '/feedback': 'Correct triage classification',
    '/triage-stats': 'Show learned patterns statistics',
    # Session
    '/conversations': 'List all conversations',
    '/new': 'Start new conversation [title]',
    '/load': 'Load conversation <id>',
    '/compact': 'Compact current conversation',
    '/delete': 'Delete conversation <id>',
    '/reset': 'Reset agents memory',
    # Statistics
    '/stats': 'Show app statistics (llm, queries, actions, embeddings, agents)',
    # Other
    '/language': 'Change language (en/fr)',
    '/reload-commands': 'Reload custom commands',
    '/exit': 'Exit Merlya',
}


class HelpCommandHandler:
    """Handles help-related slash commands."""

    def __init__(self, repl):
        """Initialize with reference to the main REPL instance."""
        self.repl = repl

    def show_help(self, args: Optional[List[Any]] = None) -> bool:
        """
        Show help message.

        Usage:
            /help           - Show quick reference
            /help <topic>   - Show detailed help for topic
            /help topics    - List available topics
        """
        if not args:
            self._show_quick_help()
            return True

        topic = args[0].lower()

        if topic == 'topics':
            self._show_topics()
        elif topic == 'model':
            self._show_model_help()
        elif topic in ('variables', 'vars', 'credentials'):
            self._show_variables_help()
        elif topic == 'inventory':
            self._show_inventory_help()
        elif topic == 'cicd':
            self._show_cicd_help()
        elif topic == 'mcp':
            self._show_mcp_help()
        elif topic == 'context':
            self._show_context_help()
        elif topic == 'session':
            self._show_session_help()
        elif topic == 'triage':
            self._show_triage_help()
        elif topic == 'examples':
            self._show_examples()
        else:
            console.print(f"[yellow]Unknown topic: {topic}[/yellow]")
            self._show_topics()

        return True

    def _show_quick_help(self) -> None:
        """Show compact quick reference."""
        table = Table(title="Merlya Commands", show_header=False, box=None, padding=(0, 2))
        table.add_column("Command", style="cyan", no_wrap=True)
        table.add_column("Description", style="white")

        for cmd, desc in SLASH_COMMANDS.items():
            table.add_row(cmd, desc)

        console.print(table)
        console.print()
        console.print("[dim]For detailed help: /help <topic>[/dim]")
        console.print(f"[dim]Topics: {', '.join(HELP_TOPICS)}[/dim]")

        # Show custom commands if any
        self._show_custom_commands_compact()

    def _show_topics(self) -> None:
        """Show available help topics."""
        console.print("\n[bold]Available Help Topics[/bold]\n")
        topics_info = {
            'model': 'LLM providers, local models, task routing, embeddings',
            'variables': 'Host aliases, config variables, secrets',
            'inventory': 'Host management, import/export, relations, SSH keys',
            'cicd': 'CI/CD pipelines, workflows, debugging',
            'mcp': 'Model Context Protocol servers',
            'context': 'Infrastructure scanning, caching',
            'session': 'Conversations, history management',
            'triage': 'Priority classification, feedback',
            'examples': 'Usage examples',
        }
        for topic, desc in topics_info.items():
            console.print(f"  [cyan]/help {topic}[/cyan] - {desc}")
        console.print()

    def _show_model_help(self) -> None:
        """Show detailed model help."""
        help_text = """
## Model Configuration

**Basic Commands:**
- `/model show` - Show current configuration
- `/model list [provider]` - List available models
- `/model set <model>` - Set model for current provider
- `/model set <provider> <model>` - Set model for specific provider
- `/model provider <name>` - Switch provider (openrouter, anthropic, openai, ollama)

**Local Models (Ollama):**
- `/model local on [model]` - Switch to Ollama (auto-downloads)
- `/model local off` - Switch back to cloud provider
- `/model local set <model>` - Set Ollama model

**Task-Specific Routing:**
Route different tasks to different models for cost/performance optimization.

- `/model task` - Show task configuration
- `/model task list` - List valid tasks and aliases
- `/model task set <task> <model>` - Set model for task
- `/model task reset` - Reset to defaults

| Task | Purpose | Recommended |
|------|---------|-------------|
| `correction` | Quick fixes, typos, simple edits | haiku (fast, cheap) |
| `planning` | Complex reasoning, architecture | opus (powerful) |
| `synthesis` | General tasks, summaries | sonnet (balanced) |

Aliases: `haiku` → Claude Haiku, `sonnet` → Claude Sonnet, `opus` → Claude Opus

**Embedding Models:**
Local AI models for semantic understanding (no API calls).

- `/model embedding` - Show current embedding model
- `/model embedding list` - List available models
- `/model embedding set <model>` - Set model (any HuggingFace model)

| Used For | Description |
|----------|-------------|
| Triage classification | Determine query priority (P0-P3) |
| Intent detection | Identify if query is action/analysis/question |
| Tool selection | Choose best tool for the task |
| Error pattern matching | Match errors to known solutions |
| Similar query lookup | Find related past queries |

Models: 17-420MB, runs locally. Env var: `MERLYA_EMBEDDING_MODEL`
"""
        console.print(Markdown(help_text))

    def _show_variables_help(self) -> None:
        """Show detailed variables help."""
        help_text = """
## Variables System

**Host Aliases (persisted):**
- `/variables set-host proddb db-prod-001`
- Usage: `check mysql on @proddb`

**Config Variables (persisted):**
- `/variables set region eu-west-1`
- `/variables set CONFIG {"env":"prod"}`
- Supports JSON, hashes, special characters

**Secrets (memory-only, NOT persisted):**
- `/variables set-secret dbpass` - Secure input (hidden)
- `/variables secret token` - Alias

**Management:**
- `/variables list` - Show all (secrets masked)
- `/variables delete <key>` - Delete (aliases: del, remove)
- `/variables clear` - Clear all
- `/variables clear-secrets` - Clear secrets only

**Variable Types:**
| Type | Example | Persisted |
|------|---------|-----------|
| host | @proddb → db-prod-001 | Yes |
| config | @region → eu-west-1 | Yes |
| secret | @dbpass → ******** | No |
"""
        console.print(Markdown(help_text))

    def _show_inventory_help(self) -> None:
        """Show detailed inventory help."""
        help_text = """
## Inventory System

**Listing & Viewing:**
- `/inventory list` (alias: ls) - List inventory sources
- `/inventory show [source] [--limit N]` - Show hosts
- `/inventory search <query> [--limit N]` (alias: find) - Search hosts
- `/inventory stats` - Show statistics

**Import & Export:**
- `/inventory add <file>` (alias: import) - Import from file
- `/inventory add-host [name]` - Add single host interactively
- `/inventory remove <source>` (aliases: delete, rm) - Remove source
- `/inventory export <file>` - Export (json/csv/yaml)
- `/inventory snapshot [name]` - Create snapshot

Supported formats: CSV, JSON, YAML, INI, /etc/hosts, ~/.ssh/config

**Relations:**
- `/inventory relations` - Get AI-suggested relations
- `/inventory relations suggest` - Same as above
- `/inventory relations list` - List validated relations

**SSH Key Management:**
- `/inventory ssh-key <host>` - Show SSH config
- `/inventory ssh-key <host> set` - Set SSH key (interactive)
- `/inventory ssh-key <host> clear` - Remove SSH config

Passphrases stored as secrets (memory-only).

**Host References:**
Use `@hostname` in prompts: `check nginx on @web-prod-01`
Tab completion available for inventory hosts.
"""
        console.print(Markdown(help_text))

    def _show_cicd_help(self) -> None:
        """Show detailed CI/CD help."""
        help_text = """
## CI/CD Integration

**Status & Listing:**
- `/cicd` - Overview and detected platforms
- `/cicd status` - Recent run status summary
- `/cicd workflows` - List workflows
- `/cicd runs [N]` - List last N runs (default: 10)
- `/cicd permissions` - Check permissions

**Actions:**
- `/cicd trigger <workflow> [--ref <branch>]` - Trigger workflow
- `/cicd cancel <run_id>` - Cancel running workflow
- `/cicd retry <run_id> [--full]` - Retry failed run

**Analysis & Debugging:**
- `/cicd analyze <run_id>` - Analyze specific run
- `/debug-workflow` - Debug most recent failure
- `/debug-workflow <run_id>` - Debug specific run

Auto-detects: GitHub Actions, GitLab CI, and more.
"""
        console.print(Markdown(help_text))

    def _show_mcp_help(self) -> None:
        """Show detailed MCP help."""
        help_text = """
## MCP (Model Context Protocol)

**Commands:**
- `/mcp list` - List configured servers
- `/mcp add` - Add server (interactive)
- `/mcp show <name>` - Show server details
- `/mcp delete <name>` - Remove server
- `/mcp examples` - Show example configurations

**Popular Servers:**
- `@modelcontextprotocol/server-filesystem` - File operations
- `@modelcontextprotocol/server-git` - Git operations
- `@modelcontextprotocol/server-postgres` - PostgreSQL
- `@modelcontextprotocol/server-brave-search` - Web search

MCP tools are auto-available to agents once configured.
Example: After adding filesystem server, say 'list files in /tmp'
"""
        console.print(Markdown(help_text))

    def _show_context_help(self) -> None:
        """Show detailed context help."""
        help_text = """
## Context & Scanning

**Commands:**
- `/scan` - Scan local machine only
- `/scan <hostname>` - Scan specific remote host (JIT)
- `/refresh` - Force refresh local context cache
- `/refresh <hostname>` - Force refresh cache for specific host
- `/cache-stats` - Show cache statistics
- `/context` - Show current context summary
- `/ssh-info` - Show SSH configuration and keys
- `/permissions [host]` - Show/detect permission capabilities

**Scanning Philosophy (JIT):**
- Local machine: Comprehensive scan, cached for 12h in SQLite
- Remote hosts: Scanned Just-In-Time when first connecting
- No bulk scanning: Individual hosts scanned on demand

**Smart Caching:**
- Inventory (/etc/hosts): 1h TTL, auto-refresh on file change
- Local machine: 12h TTL (SQLite)
- Remote hosts: 30 min TTL per host

Use `/cache-stats` to see cache state.
"""
        console.print(Markdown(help_text))

    def _show_session_help(self) -> None:
        """Show detailed session help."""
        help_text = """
## Session & Conversations

**Conversation Management:**
- `/conversations` - List all conversations
- `/new [title]` - Start new conversation
- `/load <id>` - Load conversation by ID
- `/compact` - Compact current conversation (reduce tokens)
- `/delete <id>` - Delete conversation (with confirmation)

**Session:**
- `/session` - Show current session info
- `/session list` - List recent sessions

**Agent Memory:**
- `/reset` - Reset agents memory (keeps conversation)
"""
        console.print(Markdown(help_text))

    def _show_triage_help(self) -> None:
        """Show detailed triage help."""
        help_text = """
## Triage & Priority Classification

**Commands:**
- `/triage <query>` - Test priority classification
- `/feedback <intent> <priority> <query>` - Correct classification
- `/feedback --last <intent> <priority>` - Correct last query
- `/triage-stats` - Show learned patterns statistics

**Intents:**
- `query` - Information request (list, show, what is)
- `action` - Execute/modify (restart, check, deploy)
- `analysis` - Investigation (diagnose, why, troubleshoot)

**Priorities:**
- `P0` - CRITICAL (production down, data loss)
- `P1` - URGENT (degraded, security issue)
- `P2` - IMPORTANT (performance, warnings)
- `P3` - NORMAL (maintenance, questions)

Example: `/feedback action P1 restart nginx on prod`
"""
        console.print(Markdown(help_text))

    def _show_examples(self) -> None:
        """Show usage examples."""
        help_text = """
## Usage Examples

**Natural Language Queries:**
- `list mongo preprod IPs`
- `check if nginx is running on web-prod-001`
- `what services are running on mongo-preprod-1`
- `check redis on @cache-prod-01`

**Scanning & Context:**
- `/scan` - Local machine scan
- `/scan web-prod-01` - Scan specific host
- `/cache-stats` - Check cache status
- `/refresh` - Refresh local context

**Model Management:**
- `/model list openrouter` - List models
- `/model set anthropic/claude-3-opus` - Switch model
- `/model local on llama3.2` - Use local model

**Variables:**
- `/variables set-host prod db-prod-001.example.com`
- `/variables set-secret dbpass`
- `check mysql on @prod using @dbpass`

**Inventory:**
- `/inventory add hosts.csv` - Import hosts
- `/inventory search prod` - Find hosts
- `/inventory relations suggest` - Get relation suggestions
"""
        console.print(Markdown(help_text))

    def _show_custom_commands_compact(self) -> None:
        """Show custom commands in compact format."""
        try:
            custom_commands = self.repl.command_loader.list_commands()
        except Exception:
            return

        if not custom_commands:
            return

        console.print()
        console.print("[bold]Custom Commands:[/bold]")
        for name, desc in custom_commands.items():
            console.print(f"  [cyan]/{name}[/cyan] - {desc}")
