# MCP (Model Context Protocol)

Athena supports MCP servers to extend its capabilities with external tools and data sources.

## Overview

MCP (Model Context Protocol) is an open standard that allows AI assistants to connect with external tools, data sources, and services. Athena can use MCP servers to:

- Access filesystem operations
- Query databases
- Interact with APIs
- Execute specialized tools

```
┌─────────────────────────────────────────────────────┐
│                     Athena                          │
│                       ↓                             │
│    ┌─────────────────────────────────────┐         │
│    │         MCP Manager                  │         │
│    │  ~/.athena/mcp_servers.json          │         │
│    └──────────────┬──────────────────────┘         │
│                   ↓                                 │
│    ┌─────────┬─────────┬─────────┬─────────┐       │
│    │ fs      │ git     │ postgres│ github  │       │
│    │ server  │ server  │ server  │ server  │       │
│    └─────────┴─────────┴─────────┴─────────┘       │
└─────────────────────────────────────────────────────┘
```

---

## Commands

### List Configured Servers

```bash
/mcp list

# Output:
┏━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ Name        ┃ Command              ┃ Status ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ filesystem  │ npx                  │ ✅     │
│ postgres    │ npx                  │ ✅     │
└─────────────┴──────────────────────┴────────┘
```

### Add a Server (Interactive)

```bash
/mcp add

> Server name: filesystem
> Command (e.g., npx, uvx): npx
> Arguments (space-separated): -y @modelcontextprotocol/server-filesystem /home/user
> Environment variables (KEY=VALUE, comma-separated):
✓ MCP server 'filesystem' added
```

### Show Server Details

```bash
/mcp show <name>
/mcp show filesystem

# Output:
filesystem
  Command: npx
  Args: ['-y', '@modelcontextprotocol/server-filesystem', '/home/user']
  Env: {}
```

### Delete a Server

```bash
/mcp delete <name>
/mcp delete filesystem
✓ Server 'filesystem' removed
```

### Show Examples

```bash
/mcp examples

# Output:
Example MCP Servers:

  Filesystem:
    npx @modelcontextprotocol/server-filesystem /path/to/dir

  Git:
    npx @modelcontextprotocol/server-git --repository /path/to/repo

  PostgreSQL:
    npx @modelcontextprotocol/server-postgres postgresql://...
```

---

## Configuration

MCP servers are stored in `~/.athena/mcp_servers.json`:

```json
{
  "filesystem": {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"],
    "env": {}
  },
  "postgres": {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-postgres"],
    "env": {
      "POSTGRES_URL": "postgresql://user:pass@localhost/mydb"
    }
  }
}
```

### Configuration Fields

| Field | Required | Description |
|-------|----------|-------------|
| `type` | Yes | Server type (`stdio` is the most common) |
| `command` | Yes | Command to start the server (`npx`, `uvx`, `node`, etc.) |
| `args` | No | Array of command arguments |
| `env` | No | Environment variables for the server |
| `enabled` | No | Enable/disable the server (default: true) |

---

## Available MCP Servers

### Official Servers (Model Context Protocol)

| Server | Package | Description |
|--------|---------|-------------|
| Filesystem | `@modelcontextprotocol/server-filesystem` | Read/write files, directory operations |
| Git | `@modelcontextprotocol/server-git` | Git operations, history, diffs |
| GitHub | `@modelcontextprotocol/server-github` | GitHub API (issues, PRs, repos) |
| PostgreSQL | `@modelcontextprotocol/server-postgres` | Database queries |
| Brave Search | `@modelcontextprotocol/server-brave-search` | Web search |
| Memory | `@modelcontextprotocol/server-memory` | Key-value storage |
| Fetch | `@modelcontextprotocol/server-fetch` | HTTP requests |

### Example Configurations

#### Filesystem Server

```json
{
  "filesystem": {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"],
    "env": {
      "ALLOWED_PATHS": "/home/user,/tmp"
    }
  }
}
```

#### Git Server

```json
{
  "git": {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-git"],
    "env": {}
  }
}
```

#### GitHub Server

```json
{
  "github": {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-github"],
    "env": {
      "GITHUB_TOKEN": "ghp_xxxxxxxxxxxx"
    }
  }
}
```

#### PostgreSQL Server

```json
{
  "postgres": {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-postgres"],
    "env": {
      "POSTGRES_URL": "postgresql://user:password@localhost:5432/database"
    }
  }
}
```

#### Brave Search Server

```json
{
  "brave-search": {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-brave-search"],
    "env": {
      "BRAVE_API_KEY": "your-api-key"
    }
  }
}
```

---

## Using MCP Servers

Once configured, MCP servers make their tools available to Athena agents.

### @mcp Reference (Planned)

Reference MCP servers in queries with `@mcp`:

```bash
# Use filesystem server
@mcp filesystem list files in /tmp

# Use git server
@mcp git show recent commits

# Use postgres server
@mcp postgres list tables in public schema
```

### Tool Integration

MCP tools are automatically integrated into the agent's tool selection system:

1. Agent receives user query
2. Tool selector evaluates available tools (including MCP)
3. Relevant MCP tools are included in agent's capabilities
4. Agent uses MCP tools as needed

---

## Security Considerations

### Credential Management

- **Never store secrets directly** in `mcp_servers.json`
- Use environment variables for sensitive data
- Reference secrets with `@` variables when possible

#### Recommended Approach

```bash
# Set secret via /variables
/variables set-secret pg-password

# Reference in MCP config (future)
# Or set environment variable before starting
export POSTGRES_PASSWORD=$(cat ~/.secrets/pg_pass)
```

### File Access

- Filesystem server respects `ALLOWED_PATHS`
- Only grant access to necessary directories
- Use minimal permissions

### API Keys

- Store API keys in environment variables
- Use secrets management for production
- Rotate keys regularly

---

## Troubleshooting

### Server Not Starting

```bash
# Check if command exists
which npx

# Test server manually
npx -y @modelcontextprotocol/server-filesystem /tmp

# Check logs
tail -f ~/.athena/athena.log | grep -i mcp
```

### Server Not Available

1. Verify server is in `/mcp list`
2. Check configuration with `/mcp show <name>`
3. Ensure `enabled` is not set to `false`

### Environment Variables Not Applied

- Check syntax in config (`env` must be an object)
- Restart REPL after changing config
- Verify with `/mcp show <name>`

---

## API Reference

### MCPManager

```python
from athena_ai.mcp.manager import MCPManager

manager = MCPManager()

# Add server
manager.add_server("filesystem", {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
})

# List servers
servers = manager.list_servers()

# Get server config
config = manager.get_server("filesystem")

# Delete server
manager.delete_server("filesystem")

# Parse @mcp reference
result = manager.parse_mcp_reference("@mcp filesystem list files")
# ("filesystem", "list files")
```

---

## See Also

- [Model Context Protocol](https://modelcontextprotocol.io/) - Official MCP documentation
- [TOOLS.md](TOOLS.md) - Athena's built-in tools
- [VARIABLES.md](VARIABLES.md) - Secrets and credentials management
