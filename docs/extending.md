# Extending Merlya

This guide explains how to add custom tools, commands, and functionality.

## Adding New Tools

Tools are functions the agent can call during execution.

### Step 1: Create Tool Function

Create your tool in `merlya/tools/<category>/`:

```python
# merlya/tools/mytools/backup.py

from merlya.tools.core.base import ToolResult

async def create_backup(
    ctx: "SharedContext",
    host: str,
    path: str,
    destination: str,
) -> ToolResult:
    """
    Create a backup of a file or directory.

    Args:
        ctx: Shared context.
        host: Target host.
        path: Path to backup.
        destination: Backup destination.

    Returns:
        ToolResult with backup info.
    """
    try:
        # Use existing SSH tool
        from merlya.tools.core import ssh_execute

        command = f"tar -czf {destination} {path}"
        result = await ssh_execute(ctx, host, command)

        if result.success:
            return ToolResult(
                success=True,
                data={"backup_path": destination, "source": path}
            )
        return ToolResult(success=False, error=result.error)

    except Exception as e:
        return ToolResult(success=False, error=str(e))
```

### Step 2: Register with Agent

Add the tool to `merlya/agent/tools.py`:

```python
def _register_backup_tools(agent: Agent) -> None:
    """Register backup tools."""

    @agent.tool
    async def create_backup(
        ctx: RunContext[AgentDependencies],
        host: str,
        path: str,
        destination: str,
    ) -> dict[str, Any]:
        """
        Create a backup of a file or directory.

        Args:
            ctx: Run context.
            host: Target host name.
            path: Path to backup.
            destination: Backup destination path.

        Returns:
            Backup information.
        """
        from merlya.tools.mytools.backup import create_backup as _create_backup

        result = await _create_backup(
            ctx.deps.context, host, path, destination
        )

        if result.success:
            return result.data
        raise ModelRetry(f"Backup failed: {result.error}")

# Add to register_all_tools()
def register_all_tools(agent: Agent) -> None:
    _register_core_tools(agent)
    _register_system_tools(agent)
    _register_file_tools(agent)
    _register_backup_tools(agent)  # Add this
    # ...
```

### Step 3: Update Router (Optional)

Add keywords to activate your tool in `merlya/router/intent_classifier.py`:

```python
TOOL_KEYWORDS = {
    # ...
    "backup": ["backup", "archive", "snapshot", "tar", "zip"],
}
```

## Adding New Commands

Commands are slash commands like `/help`, `/hosts`.

### Step 1: Create Command Handler

Create handler in `merlya/commands/handlers/`:

```python
# merlya/commands/handlers/backup.py

from merlya.commands.registry import CommandResult

async def handle_backup(ctx: "SharedContext", args: list[str]) -> CommandResult:
    """
    Handle /backup command.

    Usage: /backup <host> <path> [destination]
    """
    if len(args) < 2:
        return CommandResult(
            success=False,
            message="Usage: /backup <host> <path> [destination]"
        )

    host = args[0].lstrip("@")
    path = args[1]
    destination = args[2] if len(args) > 2 else f"{path}.backup.tar.gz"

    try:
        from merlya.tools.mytools.backup import create_backup

        result = await create_backup(ctx, host, path, destination)

        if result.success:
            return CommandResult(
                success=True,
                message=f"Backup created: {result.data['backup_path']}"
            )
        return CommandResult(success=False, message=result.error)

    except Exception as e:
        return CommandResult(success=False, message=str(e))
```

### Step 2: Register Command

Add to `merlya/commands/handlers/__init__.py`:

```python
from merlya.commands.handlers.backup import handle_backup

def init_commands() -> None:
    registry = get_registry()

    # ... existing commands ...

    registry.register(
        name="backup",
        description="Create a backup of a remote file or directory",
        usage="/backup <host> <path> [destination]",
        handler=handle_backup,
        aliases=["bak"],
    )
```

## Adding Translations

### Step 1: Add Translation Keys

Add to `merlya/i18n/locales/en.json`:

```json
{
  "commands": {
    "backup": {
      "created": "Backup created: {path}",
      "failed": "Backup failed: {error}"
    }
  },
  "commands_meta": {
    "backup": {
      "description": "Create a backup of a remote file",
      "usage": "/backup <host> <path> [destination]"
    }
  }
}
```

Add to `merlya/i18n/locales/fr.json`:

```json
{
  "commands": {
    "backup": {
      "created": "Sauvegarde créée : {path}",
      "failed": "Échec de la sauvegarde : {error}"
    }
  },
  "commands_meta": {
    "backup": {
      "description": "Créer une sauvegarde d'un fichier distant",
      "usage": "/backup <hôte> <chemin> [destination]"
    }
  }
}
```

### Step 2: Use Translations

```python
from merlya.i18n import get_i18n

i18n = get_i18n()
message = i18n.t("commands.backup.created", path=destination)
```

## Adding Database Tables

### Step 1: Define Model

Add to `merlya/persistence/models.py`:

```python
@dataclass
class Backup:
    """Backup record."""
    id: str
    host: str
    source_path: str
    backup_path: str
    created_at: datetime
    size_bytes: int | None = None
```

### Step 2: Create Repository

Add to `merlya/persistence/repositories.py`:

```python
class BackupRepository:
    """Repository for backup records."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(self, backup: Backup) -> Backup:
        await self.db.execute(
            """
            INSERT INTO backups (id, host, source_path, backup_path, created_at, size_bytes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (backup.id, backup.host, backup.source_path,
             backup.backup_path, backup.created_at, backup.size_bytes)
        )
        return backup

    async def get_by_host(self, host: str) -> list[Backup]:
        rows = await self.db.fetchall(
            "SELECT * FROM backups WHERE host = ? ORDER BY created_at DESC",
            (host,)
        )
        return [Backup(**row) for row in rows]
```

### Step 3: Add Schema

Add to `merlya/persistence/database.py`:

```python
SCHEMA = """
-- ... existing tables ...

CREATE TABLE IF NOT EXISTS backups (
    id TEXT PRIMARY KEY,
    host TEXT NOT NULL,
    source_path TEXT NOT NULL,
    backup_path TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    size_bytes INTEGER,
    FOREIGN KEY (host) REFERENCES hosts(name)
);
"""
```

## Testing Extensions

### Unit Tests

```python
# tests/test_backup.py

import pytest
from merlya.tools.mytools.backup import create_backup

@pytest.mark.asyncio
async def test_create_backup(mock_context):
    result = await create_backup(
        mock_context,
        host="testhost",
        path="/var/log/app.log",
        destination="/backups/app.log.tar.gz"
    )

    assert result.success
    assert result.data["backup_path"] == "/backups/app.log.tar.gz"
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_backup_command(ctx):
    from merlya.commands import get_registry

    registry = get_registry()
    result = await registry.execute(ctx, "/backup web01 /var/log")

    assert result.success
```

## Using MCP Servers

MCP (Model Context Protocol) lets Merlya bridge external services like GitHub, Slack, or custom APIs. Unlike custom commands which are built into the codebase, MCP servers are external processes that expose tools dynamically.

### Step 1: Add Server to Configuration

Define the MCP server in `config.yaml`:

```yaml
mcp:
  servers:
    github:
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_TOKEN: "${GITHUB_TOKEN}"
    slack:
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-slack"]
      env:
        SLACK_BOT_TOKEN: "${SLACK_BOT_TOKEN}"
```

### Step 2: Test the Connection

Use the `/mcp` command to verify the server is working:

```bash
/mcp list              # List configured servers
/mcp test github       # Test connection to GitHub server
/mcp tools github      # List available tools from server
```

### Step 3: Use MCP Tools in Agent

MCP tools are automatically exposed to the agent as `server.tool` (e.g., `github.create_issue`). The agent can call them via the `call_mcp_tool` function:

```python
# Agent can call MCP tools directly
result = await call_mcp_tool(
    ctx,
    server="github",
    tool="create_issue",
    arguments={"repo": "org/repo", "title": "Bug report"}
)
```

For programmatic access in custom code:

```python
from merlya.mcp.manager import MCPManager

# Get or create the singleton (async-safe)
manager = await MCPManager.create(config, secrets)

# Or get existing instance (may be None)
manager = MCPManager.get_instance()

# Call a tool (must include server prefix)
result = await manager.call_tool("github.create_issue", {
    "repo": "org/repo",
    "title": "Bug report",
    "body": "Description here"
})
```

**Important:** Tool names must include the server prefix (e.g., `github.create_issue`, not just `create_issue`).

### Environment Variable Handling

MCP servers can reference environment variables:

```yaml
mcp:
  servers:
    github:
      env:
        GITHUB_TOKEN: "${GITHUB_TOKEN}"        # Required - raises error if missing
        CACHE_DIR: "${CACHE_DIR:-/tmp/cache}"  # Optional with default
```

Missing required variables will raise a clear error message listing all missing variables.

## Best Practices

### Tool Design

1. **Single responsibility** - One tool, one purpose
2. **Return ToolResult** - Consistent success/error handling
3. **Document parameters** - Clear docstrings for LLM
4. **Handle errors** - Catch exceptions, return meaningful errors
5. **Use existing tools** - Compose with `ssh_execute`, etc.

### Command Design

1. **Clear usage** - Show syntax in help
2. **Validate args** - Check required parameters
3. **Use translations** - Support i18n
4. **Return CommandResult** - Consistent responses

### Security

1. **Validate inputs** - Sanitize paths, hostnames
2. **Check permissions** - Use elevation when needed
3. **Audit actions** - Log sensitive operations
4. **No secrets in code** - Use keyring/environment
