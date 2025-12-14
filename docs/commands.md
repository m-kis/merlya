# Slash Commands

Merlya supports slash commands for quick actions.

## General Commands

### `/help [command]`
Show help for all commands or a specific command.

```bash
/help           # List all commands
/help hosts     # Help for /hosts command
```

### `/exit`
Exit Merlya.

### `/new [title]`
Start a new conversation.

```bash
/new
/new "Server maintenance"
```

### `/language <en|fr>`
Change interface language.

```bash
/language fr    # Switch to French
/language en    # Switch to English
```

## Host Management

### `/hosts list [--tag TAG]`
List all hosts in inventory.

```bash
/hosts list
/hosts list --tag production
```

### `/hosts show <name>`
Show details for a specific host.

```bash
/hosts show web01
```

### `/hosts add <name> <hostname> [options]`
Add a new host to inventory.

```bash
/hosts add web01 10.0.1.5
/hosts add web01 10.0.1.5 --user admin --port 2222
/hosts add web01 10.0.1.5 --jump bastion
```

### `/hosts delete <name>`
Remove a host from inventory.

```bash
/hosts delete web01
```

### `/hosts tag <name> <tag>`
Add a tag to a host.

```bash
/hosts tag web01 production
```

### `/hosts untag <name> <tag>`
Remove a tag from a host.

```bash
/hosts untag web01 staging
```

### `/hosts import <file>`
Import hosts from a file.

Supported formats:

- **JSON** - Array of host objects
- **YAML** - List of hosts
- **TOML** - Host definitions with `[hosts.name]` sections
- **CSV** - Columns: name, hostname, port, username, tags
- **SSH config** - `~/.ssh/config` format

```bash
/hosts import hosts.toml
/hosts import ~/.ssh/config
/hosts import inventory.yaml
```

**TOML Example:**

```toml
[hosts.internal-db]
hostname = "10.0.1.50"
user = "dbadmin"
jump_host = "bastion.example.com"
port = 22
tags = ["database", "production"]

[hosts.bastion]
hostname = "bastion.example.com"
user = "admin"
```

### `/hosts export <file>`
Export hosts to a file.

```bash
/hosts export hosts.json
/hosts export backup.yaml
```

## Scanning

### `/scan <host> [options]`
Scan a host for system information and security.

```bash
/scan web01
/scan @web01 --full       # Full scan
/scan web01 --security    # Security-focused scan
/scan web01 --system      # System info only
```

## Variables

### `/variable list`
List all variables.

### `/variable set <name> <value>`
Set a variable.

```bash
/variable set deploy_env production
/variable set api_url https://api.example.com
```

### `/variable get <name>`
Get a variable value.

### `/variable delete <name>`
Delete a variable.

## Secrets

Secrets are stored securely in the system keyring.

### `/secret list`
List all secrets (values hidden).

### `/secret set <name>`
Set a secret (prompts for value).

```bash
/secret set DB_PASSWORD
# Prompts: Enter value for DB_PASSWORD: ****
```

### `/secret delete <name>`
Delete a secret.

## Conversations

### `/conversations list [--limit N]`
List saved conversations.

```bash
/conversations list
/conversations list --limit 10
```

### `/conversations load <id>`
Load a previous conversation.

```bash
/conversations load abc123
```

### `/conversations search <query>`
Search conversations.

```bash
/conversations search "disk usage"
```

## Model Management

### `/model`
Show current LLM configuration.

### `/model set <provider:model>`
Change the LLM model.

## MCP (Model Context Protocol)

Extend Merlya with external MCP servers (e.g., Context7, GitHub, Slack, custom).

### `/mcp list`
List configured MCP servers.

```bash
/mcp list
```

### `/mcp add <name> <command> [args...] [--env=KEY=VALUE] [--cwd=/path] [--no-test]`
Add a server and automatically test the connection.

**Environment Variable Syntax:**
- `${secret-name}` - Required variable (from env or `/secret set`)
- `${VAR:-default}` - Variable with default value

**Flags:**
- `--env=KEY=VALUE` - Set environment variable (can use multiple times)
- `--cwd=/path` - Set working directory for the server
- `--no-test` - Skip automatic connection test

**Examples:**

```bash
# Context7 - Code documentation context
/secret set context7-token <your-api-key>
/mcp add context7 npx -y @upstash/context7-mcp --env=CONTEXT7_API_KEY=${context7-token}

# GitHub - Repository management
/secret set github-token ghp_xxxxx
/mcp add github npx -y @modelcontextprotocol/server-github --env=GITHUB_TOKEN=${github-token}

# Slack - Team communication
/secret set slack-bot-token xoxb-your-bot-token
/mcp add slack npx -y @modelcontextprotocol/server-slack --env=SLACK_BOT_TOKEN=${slack-bot-token}

# Filesystem - Local file access
/mcp add fs npx -y @modelcontextprotocol/server-filesystem /home/user/projects

# With optional env default
/mcp add custom python server.py --env=PORT=${MCP_PORT:-8080}

# Skip auto-test (useful for offline setup)
/mcp add slow-server npx -y @slow/mcp --no-test
```

**Important:**
- After adding, Merlya automatically tests the connection
- If the test fails, the config is saved but you'll see a warning
- Use `/mcp test <name>` to retry the connection test

### `/mcp remove <name>`
Remove a server from configuration.

```bash
/mcp remove github
```

### `/mcp show <name>`
Show server configuration.

```bash
/mcp show github
```

### `/mcp test <name>`
Start/connect and list exposed tools.

```bash
/mcp test github
```

### `/mcp tools [name]`
List available MCP tools (optionally filter by server).

```bash
/mcp tools
/mcp tools github
```

### `/mcp examples`
Show sample configuration snippets with common MCP servers.

```bash
/mcp examples
```

```bash
/model set openrouter:anthropic/claude-3.5-sonnet
/model set ollama:llama3.2
```

### `/model test`
Test LLM connectivity.

## SSH Management

### `/ssh connect <host>`
Test SSH connection to a host.

```bash
/ssh connect web01
```

### `/ssh key add <name> <path>`
Add an SSH key.

### `/ssh key list`
List configured SSH keys.

## System

### `/health`
Show system health status.

```bash
/health
# Shows: RAM, Disk, LLM, SSH, Keyring, Web Search status
```

### `/log level <level>`
Set log level.

```bash
/log level debug
/log level info
```

### `/log dir`
Show log directory location.

### `/log clear`
Clear old log files.

## Skills

### `/skill list`
List all available skills (builtin and user-defined).

```bash
/skill list
```

### `/skill show <name>`
Show details of a specific skill.

```bash
/skill show incident_triage
```

### `/skill reload`
Reload skills from disk.

```bash
/skill reload
```

### `/skill create`
Interactive wizard to create a new skill.

```bash
/skill create
# Prompts for:
# - Skill name
# - Description
# - Intent patterns
# - Tools allowed
# - Max hosts, timeout
# - System prompt
```

## Audit

### `/audit list [--limit N] [--host HOST]`
List recent command executions.

```bash
/audit list
/audit list --limit 50
/audit list --host web01
```

### `/audit show <id>`
Show details of a specific audit entry.

```bash
/audit show abc123
```

## Using @ Mentions

### Host Mentions
Reference hosts from inventory with `@`:

```bash
Check disk on @web01
Connect to @database-primary via @bastion
```

### Variable Mentions
Reference variables with `@`:

```bash
Deploy to @deploy_env environment
```

Variables are expanded before processing.

## Command Aliases

Some commands have shorter aliases:

| Command | Alias |
|---------|-------|
| `/help` | `/h` |
| `/exit` | `/quit`, `/q` |
| `/hosts list` | `/hl` |
| `/conversations` | `/conv` |
