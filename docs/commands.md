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

### `/hosts list [--tag=<tag>]`
List all hosts in inventory.

```bash
/hosts list
/hosts list --tag=production
```

### `/hosts show <name>`
Show details for a specific host.

```bash
/hosts show web01
```

### `/hosts add <name> [--test]`
Add a new host to inventory (interactive prompts for hostname, port, username).

```bash
/hosts add web01
/hosts add web01 --test
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

### `/hosts edit <name>`
Edit a host interactively (hostname/port/user/tags).

```bash
/hosts edit web01
```

### `/hosts check [<name>|--tag=<tag>|--all]`
Check SSH connectivity to hosts (supports `--parallel`).

```bash
/hosts check
/hosts check web01
/hosts check --tag=production --parallel
```

### `/hosts import <file>`
Import hosts from a file.

Supported formats:

- **JSON** - Array of host objects
- **YAML** - List of hosts
- **TOML** - Host definitions with `[hosts.name]` sections
- **CSV** - Columns: name, hostname, port, username, elevation_method, elevation_user, tags
- **SSH config** - `~/.ssh/config` format
- **/etc/hosts** - `/etc/hosts` format

```bash
/hosts import hosts.toml
/hosts import ~/.ssh/config --format=ssh
/hosts import inventory.yaml
/hosts import /etc/hosts --format=etc_hosts
```

**TOML Example:**

```toml
[hosts.internal-db]
hostname = "10.0.1.50"
user = "dbadmin"
jump_host = "bastion.example.com"
port = 22
tags = ["database", "production"]
elevation_method = "sudo_password"  # sudo, sudo_password, doas, doas_password, su, none
elevation_user = "root"             # Target user for elevation (default: root)

[hosts.bastion]
hostname = "bastion.example.com"
user = "admin"
elevation_method = "sudo"           # NOPASSWD sudo configured
```

**Elevation Methods:**

| Method           | Description                |
| ---------------- | -------------------------- |
| `none`           | No elevation (default)     |
| `sudo`           | sudo with NOPASSWD         |
| `sudo_password`  | sudo requiring password    |
| `doas`           | doas with NOPASSWD (BSD)   |
| `doas_password`  | doas requiring password    |
| `su`             | su (requires root password)|

### `/hosts export <file>`
Export hosts to a file.

```bash
/hosts export hosts.json
/hosts export backup.yaml
```

## Scanning

### `/scan <host> [options]`
Scan a host for system information and security issues.

**Scan Types:**

```bash
/scan web01               # Full scan (default)
/scan web01 --full        # Complete system + security scan
/scan web01 --quick       # Fast check: CPU, memory, disk, ports
/scan web01 --security    # Security checks only
/scan web01 --system      # System info only
```

**Output Options:**

```bash
/scan web01 --json        # Output as JSON
/scan web01 --show-all    # Show all ports/users/services (no truncation)
```

**Skip Options:**

```bash
/scan web01 --no-docker   # Skip Docker checks
/scan web01 --no-updates  # Skip pending updates check
/scan web01 --no-network  # Skip network diagnostics
/scan web01 --no-services # Skip services list
/scan web01 --no-cron     # Skip cron jobs list
```

**Multi-Host Scanning:**

```bash
/scan web01 db01 --quick             # Scan multiple hosts
/scan --tag=production --parallel    # Scan all hosts with tag in parallel
/scan --all --quick                  # Scan entire inventory
```

**System Checks:** CPU, memory, disk, Docker, services, network, cron, processes, logs

**Security Checks:** Open ports, SSH config, users, SSH keys, sudo config, critical services, failed logins, pending updates

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

### `/variable import <file> [--merge|--replace] [--dry-run]`
Import variables (and optionally hosts) from YAML/JSON/`.env` style files.

```bash
/variable import vars.yml
/variable import vars.env --dry-run
```

### `/variable export <file> [--include-secrets]`
Export variables to a file (YAML/JSON/`.env`), optionally prompting for secrets.

```bash
/variable export vars.yml
```

### `/variable template <file>`
Generate a template file for variable import.

```bash
/variable template vars-template.yml
```

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

### `/secret clear-elevation [<host>|--all]`
Clear stored elevation (sudo/su) passwords.

```bash
/secret clear-elevation           # List stored elevation passwords
/secret clear-elevation web01     # Clear for specific host
/secret clear-elevation --all     # Clear all elevation passwords
```

## Conversations

Merlya stores conversation history and lets you resume or export it.

### `/conv list [--limit=<n>]`
List saved conversations.

```bash
/conv list
/conv list --limit=10
```

### `/conv show <id>`
Show conversation details.

```bash
/conv show abc123
```

### `/conv load <id>`
Load a previous conversation.

```bash
/conv load abc123
```

### `/conv delete <id>`
Delete a conversation.

```bash
/conv delete abc123
```

### `/conv rename <id> <title>`
Rename a conversation.

```bash
/conv rename abc123 "Server maintenance"
```

### `/conv search <query>`
Search conversations.

```bash
/conv search "disk usage"
```

### `/conv export <id> <file>`
Export a conversation to a file.

```bash
/conv export abc123 ./incident.md
```

## Model Management

### `/model` or `/model show`

Show current provider and model configuration (brain/fast models).

### `/model provider <name>`
Change LLM provider (prompts for API key if missing). Sets default brain/fast models for the provider.

Available providers: `anthropic`, `openai`, `openrouter`, `mistral`, `groq`, `ollama`

### `/model brain [name]`
Show or set the **brain model** (complex reasoning, planning, analysis).

```bash
/model brain                    # Show current brain model
/model brain claude-sonnet-4    # Set brain model
```

### `/model fast [name]`

Show or set the **fast model** (routing, fingerprinting, quick decisions).

```bash
/model fast                     # Show current fast model
/model fast claude-haiku        # Set fast model
```

### `/model test`

Test LLM connectivity with the current configuration.

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

## SSH Management

### `/ssh connect <host>`
Test SSH connection to a host.

```bash
/ssh connect web01
```

### `/ssh exec <host> <command>`
Execute a command over SSH.

```bash
/ssh exec web01 "uptime"
```

### `/ssh disconnect <host>`
Disconnect from a host.

```bash
/ssh disconnect web01
```

### `/ssh config <host>`
Interactive SSH configuration for a host.

### `/ssh test <host>`
Test SSH connectivity (diagnostics).

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

### `/log show`

Show recent log entries.

## Audit

### `/audit recent [limit]`
Show recent audit events.

```bash
/audit recent
/audit recent 50
```

### `/audit export [file] [--since <hours>] [--limit <n>]`
Export audit logs to JSON (SIEM-compatible format).

```bash
/audit export                           # Export to default file
/audit export ./audit.json              # Export to specific file
/audit export --since 24                # Last 24 hours only
/audit export --limit 1000              # Limit to 1000 events
/audit export audit.json --since 48 --limit 500
```

### `/audit filter <type>`
Filter audit events by type.

```bash
/audit filter ssh
```

### `/audit stats`
Show audit statistics.

```bash
/audit stats
```

## Host and Secret References

### Host Names

Reference hosts from inventory by their name (without `@`):

```bash
Check disk on web01
Connect to database-primary via bastion
```

### Secret References
Reference secrets stored in keyring with `@`:

```bash
Connect to MongoDB with @db-password
Deploy using token @deploy-token
```

The `@` prefix is **reserved for secrets only**. Secrets are resolved from the system keyring before execution and never appear in logs.

### Variable Mentions

Variables set via `/variable set` are expanded automatically:

```bash
/variable set deploy_env production
Deploy to $deploy_env environment
```

## Command Aliases

Some commands have shorter aliases:

| Command | Alias |
|---------|-------|
| `/help` | `/h` |
| `/exit` | `/quit`, `/q` |
| `/language` | `/lang` |
| `/variable` | `/var` |
| `/conv` | `/conversation` |
