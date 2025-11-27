# Athena REPL Commands

Complete reference for all slash commands available in the Athena interactive REPL.

## Quick Reference

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/scan` | Scan infrastructure |
| `/refresh` | Force refresh context |
| `/cache-stats` | Show cache statistics |
| `/ssh-info` | Show SSH configuration |
| `/permissions` | Show permission capabilities |
| `/session` | Session management |
| `/context` | Show current context |
| `/model` | Model configuration |
| `/variables` | Manage variables |
| `/mcp` | MCP server management |
| `/language` | Change language |
| `/triage` | Test priority classification |
| `/feedback` | Correct triage classification |
| `/triage-stats` | Show learned patterns |
| `/conversations` | List conversations |
| `/new` | Start new conversation |
| `/load` | Load conversation |
| `/compact` | Compact conversation |
| `/delete` | Delete conversation |
| `/reset` | Reset agents memory |
| `/exit`, `/quit` | Exit Athena |

---

## Infrastructure Commands

### `/scan [--full]`

Scan infrastructure and discover hosts.

```bash
# Quick scan (inventory only)
/scan

# Full scan (includes SSH connectivity test)
/scan --full
```

**Output:**
- Discovered hosts from SSH config
- Hosts from `/etc/hosts`
- Ansible inventory hosts (if configured)
- Connection status (with `--full`)

---

### `/refresh [--full]`

Force refresh the cached context.

```bash
# Refresh inventory caches
/refresh

# Full refresh including SSH scans
/refresh --full
```

---

### `/cache-stats`

Show cache statistics and TTL information.

```bash
/cache-stats
```

**Output:**
```
Cache Statistics
================
Inventory Cache: 45 hosts (TTL: 1h, updated: 5m ago)
Local Info: Cached (TTL: 5m)
Remote Hosts: 3 cached (TTL: 30m)
Smart Cache: Fingerprint-based (12 entries)
```

---

### `/ssh-info`

Show SSH configuration details.

```bash
/ssh-info
```

**Output:**
- SSH config file locations
- Configured hosts with aliases
- Jump hosts (ProxyJump)
- Identity files

---

### `/permissions [hostname]`

Check permission capabilities on a host.

```bash
# Check permissions on specific host
/permissions web-01

# Check local permissions
/permissions local
```

**Output:**
```
Permissions on web-01
=====================
User: deploy
Sudo: Yes (passwordless)
SSH Key: ~/.ssh/id_rsa
Writable: /tmp, /home/deploy
```

---

### `/context`

Show current infrastructure context.

```bash
/context
```

**Output:**
- Environment (dev/staging/prod)
- Known hosts count
- Current session info
- Active conversation

---

## Model Configuration

### `/model show`

Display current LLM configuration.

```bash
/model show
```

**Output:**
```
Current Model Configuration
===========================
Provider: anthropic
Model: claude-3-sonnet-20240229
Temperature: 0.1
Task Models:
  - triage: claude-3-haiku (fast)
  - planning: claude-3-opus (complex)
  - default: claude-3-sonnet
```

---

### `/model list`

List available models for current provider.

```bash
/model list
```

---

### `/model set <provider> <model>`

Set model for a specific provider.

```bash
# Set Anthropic model
/model set anthropic claude-3-opus-20240229

# Set OpenRouter model
/model set openrouter anthropic/claude-3-sonnet
```

---

### `/model provider <name>`

Switch LLM provider.

```bash
# Switch to Ollama (local)
/model provider ollama

# Switch to OpenRouter
/model provider openrouter
```

**Supported Providers:**
- `anthropic` - Anthropic API
- `openai` - OpenAI API
- `openrouter` - OpenRouter (multi-provider)
- `ollama` - Local Ollama

---

## Variables System

### `/variables list`

List all defined variables.

```bash
/variables list
```

**Output:**
```
Variables
=========
Host Aliases:
  @preproddb → db-qarc-1
  @webprod → web-prod-01

Credentials:
  @mongo-user → admin (encrypted)
  @mongo-pass → ******* (encrypted)
```

---

### `/variables set <name> <value>`

Define a new variable.

```bash
# Host alias
/variables set preproddb db-qarc-1

# Credential (stored encrypted)
/variables set mongo-pass SuperSecretPassword
```

**Usage in queries:**
```
check mongodb status on @preproddb with user @mongo-user
```

---

### `/variables delete <name>`

Delete a variable.

```bash
/variables delete preproddb
```

---

### `/credentials`

Alias for `/variables` (backward compatibility).

---

## MCP Server Management

### `/mcp list`

List configured MCP servers.

```bash
/mcp list
```

---

### `/mcp add <name> <command> [args...] [--env KEY=VALUE]`

Add an MCP server configuration.

```bash
# Filesystem server
/mcp add filesystem npx -y @modelcontextprotocol/server-filesystem

# GitHub server with token
/mcp add github npx -y @modelcontextprotocol/server-github --env GITHUB_TOKEN=ghp_xxx

# AWS EKS with multiple env vars
/mcp add eks uvx awslabs.eks-mcp-server --env AWS_PROFILE=prod --env AWS_REGION=eu-west-1
```

---

### `/mcp delete <name>`

Remove an MCP server configuration.

```bash
/mcp delete filesystem
```

---

### `/mcp show <name>`

Show MCP server configuration details.

```bash
/mcp show github
```

---

## Triage Commands

### `/triage <query>`

Test priority classification for a query.

```bash
/triage production database is slow
```

**Output:**
```
Triage Classification
=====================
Priority: P1 (High)
Intent: ANALYSIS
Confidence: 0.92
Signals: [P1:slow, env:prod, service:database]
Environment: production
Behavior: Investigate, explain, recommend
```

---

### `/feedback <intent|priority> <value>`

Correct the last triage classification.

```bash
# Correct intent
/feedback intent action

# Correct priority
/feedback priority P0
```

This helps the smart classifier learn from corrections.

---

### `/triage-stats`

Show learned triage patterns statistics.

```bash
/triage-stats
```

**Output:**
```
Triage Statistics
=================
Total patterns learned: 156
By intent:
  QUERY: 45
  ACTION: 78
  ANALYSIS: 33
Accuracy (last 100): 94%
Cache size: 234/500
```

---

## Conversation Management

### `/conversations`

List all saved conversations.

```bash
/conversations
```

**Output:**
```
Conversations
=============
[1] 2024-01-15 10:30 - "Debugging MongoDB issues" (12 messages)
[2] 2024-01-14 15:45 - "Deploy new nginx config" (8 messages)
[3] 2024-01-14 09:00 - "Security audit web-01" (15 messages)
```

---

### `/new [title]`

Start a new conversation.

```bash
# New conversation with auto-generated title
/new

# New conversation with custom title
/new Debugging Redis cluster
```

---

### `/load <id>`

Load a previous conversation.

```bash
/load 2
```

---

### `/compact`

Compact current conversation to reduce context size.

```bash
/compact
```

This summarizes older messages while preserving recent context.

---

### `/delete <id>`

Delete a conversation.

```bash
/delete 3
```

---

## Session Management

### `/session list`

List all sessions.

```bash
/session list
```

---

### `/session show`

Show current session details.

```bash
/session show
```

---

### `/session export [format]`

Export session to file.

```bash
# Export as JSON
/session export json

# Export as Markdown
/session export md
```

---

## Other Commands

### `/language <code>`

Change response language.

```bash
# French
/language fr

# English
/language en
```

---

### `/reset`

Reset agent memory (clear conversation context from agents).

```bash
/reset
```

---

### `/exit` or `/quit`

Exit the Athena REPL.

```bash
/exit
```

---

## Custom Commands

Athena supports custom slash commands defined in markdown files.

### Location

```
~/.athena/commands/
├── deploy.md
├── healthcheck.md
└── backup.md
```

### Format

```markdown
---
name: deploy
description: Deploy application to environment
args:
  - name: app
    required: true
  - name: env
    default: staging
---

Deploy {app} to the {env} environment.
Check the current version, pull latest changes, and restart services.
Verify health after deployment.
```

### Usage

```bash
/deploy myapp prod
```

---

## Smart Context System

Athena uses intelligent caching that auto-detects changes:

| Cache Type | TTL | Auto-Refresh |
|------------|-----|--------------|
| Inventory (`/etc/hosts`) | 1 hour | On file change |
| Local info | 5 minutes | Periodic |
| Remote hosts | 30 minutes | On demand |
| SSH scan | 1 hour | Manual (`--full`) |

Use `/cache-stats` to monitor cache state.

---

## Environment Variables

Some commands respect environment variables:

| Variable | Description |
|----------|-------------|
| `ATHENA_ENV` | Default environment (dev/staging/prod) |
| `ATHENA_LANGUAGE` | Default language (en/fr) |
| `ATHENA_MODEL` | Default LLM model |
| `ATHENA_PROVIDER` | Default LLM provider |
| `ATHENA_ENABLE_LLM_FALLBACK` | Enable LLM-based inventory parsing fallback. Set to `"true"` to enable (default: `"false"`). Only enable after reviewing privacy implications below. |
| `ATHENA_LLM_COMPLIANCE_ACKNOWLEDGED` | Set to `"true"` to confirm your LLM provider meets your organization's data protection requirements (e.g., GDPR, SOC2, HIPAA). Required when `ATHENA_ENABLE_LLM_FALLBACK=true`. |

**LLM Fallback Privacy Notice:** When enabled, inventory content is sent to your configured LLM provider for parsing. This may include hostnames, IP addresses, environment names, and metadata. Athena sanitizes content before sending (redacting IPs and sensitive patterns), but you should verify your LLM provider's data handling policies meet your compliance requirements. Both variables must be set to `"true"` together.

---

## See Also

- [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- [TOOLS.md](TOOLS.md) - Available tools
- [TRIAGE.md](TRIAGE.md) - Triage system
- [CREDENTIALS.md](CREDENTIALS.md) - Credential management
