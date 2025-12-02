# Merlya REPL Commands

Complete reference for all slash commands available in the Merlya interactive REPL.

## Quick Reference

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/help <topic>` | Detailed help (model, variables, inventory, ssh, cicd, mcp, context, session, triage) |
| `/scan` | Scan local or specific host |
| `/refresh` | Force refresh context |
| `/cache-stats` | Show cache statistics |
| `/ssh` | SSH management (keys, agent, passphrase, test) |
| `/permissions` | Show permission capabilities |
| `/context` | Show current context |
| `/model` | Model configuration |
| `/variables` | Manage variables |
| `/secret` | Manage persistent secrets |
| `/inventory` | Manage hosts |
| `/cicd` | CI/CD management |
| `/mcp` | MCP server management |
| `/triage` | Test priority classification |
| `/feedback` | Correct triage classification |
| `/triage-stats` | Show learned patterns |
| `/conversations` | List conversations |
| `/new` | Start new conversation |
| `/load` | Load conversation |
| `/compact` | Compact conversation |
| `/delete` | Delete conversation |
| `/reset` | Reset agents memory |
| `/language` | Change language |
| `/reload-commands` | Reload custom commands |
| `/exit`, `/quit` | Exit Merlya |

---

## Infrastructure Commands

### `/scan [hostname]`

Scan local machine or a specific remote host.

```bash
# Scan local machine only
/scan

# Scan a specific remote host
/scan web-01
/scan 192.168.1.10
```

**Scanning Philosophy (JIT):**
- Local machine: Comprehensive scan, cached for 12h in SQLite
- Remote hosts: Scanned Just-In-Time when first connecting
- No bulk scanning: Individual hosts scanned on demand

---

### `/refresh [hostname]`

Force refresh the cached context.

```bash
# Refresh local context cache
/refresh

# Refresh cache for a specific host
/refresh web-01
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
Local Info: Cached (TTL: 12h)
Remote Hosts: 3 cached (TTL: 30m)
```

---

### `/ssh`

Centralized SSH key and connection management.

```bash
# Show SSH overview (agent, keys, global config)
/ssh

# Show available SSH keys
/ssh keys

# Show ssh-agent status
/ssh agent

# Global key management
/ssh key set ~/.ssh/id_ed25519
/ssh key show
/ssh key clear

# Per-host key management
/ssh host web-prod-01 show
/ssh host web-prod-01 set
/ssh host web-prod-01 clear

# Passphrase management
/ssh passphrase global
/ssh passphrase id_ed25519

# Connection testing
/ssh test web-prod-01
```

**Key Resolution Priority:**

1. Host-specific key (from inventory metadata)
2. Global key (`/ssh key set`)
3. `~/.ssh/config` IdentityFile
4. Default keys (id_ed25519, id_rsa, etc.)

Passphrases are cached in memory only and expire on exit.

---

### `/permissions [hostname]`

Check permission capabilities on a host.

```bash
# Check permissions on specific host
/permissions web-01

# Check local permissions
/permissions local
```

---

### `/context`

Show current infrastructure context.

```bash
/context
```

---

## Model Configuration

### `/model show`

Display current LLM configuration.

```bash
/model show
```

---

### `/model list [provider]`

List available models for current or specified provider.

```bash
/model list
/model list openrouter
```

---

### `/model set <model>` or `/model set <provider> <model>`

Set model for a specific provider.

```bash
# Set model for current provider
/model set claude-3-opus-20240229

# Set model for specific provider
/model set anthropic claude-3-opus-20240229
/model set openrouter anthropic/claude-3-sonnet
```

---

### `/model provider <name>`

Switch LLM provider.

```bash
/model provider ollama
/model provider openrouter
/model provider anthropic
/model provider openai
```

---

### `/model local`

Manage local Ollama models.

```bash
# Switch to Ollama (auto-downloads model)
/model local on [model]

# Switch back to cloud provider
/model local off

# Set specific Ollama model
/model local set llama3.2
```

---

### `/model task`

Configure task-specific model routing for cost/performance optimization.

```bash
# Show task configuration
/model task

# List valid tasks and aliases
/model task list

# Set model for specific task
/model task set correction haiku
/model task set planning opus
/model task set synthesis sonnet

# Reset to defaults
/model task reset
```

**Task Types:**

| Task | Purpose | Recommended |
|------|---------|-------------|
| `correction` | Quick fixes, typos, simple edits | haiku (fast, cheap) |
| `planning` | Complex reasoning, architecture | opus (powerful) |
| `synthesis` | General tasks, summaries | sonnet (balanced) |

---

### `/model embedding`

Manage local embedding models for semantic understanding.

```bash
# Show current embedding model
/model embedding

# List available models
/model embedding list

# Set model (any HuggingFace model)
/model embedding set all-MiniLM-L6-v2
```

**Embeddings are used for:**

- Triage classification (query priority P0-P3)
- Intent detection (action/analysis/question)
- Tool selection
- Error pattern matching
- Similar query lookup

---

## Variables System

### `/variables list`

List all defined variables.

```bash
/variables list
```

---

### `/variables set <name> <value>`

Define a config variable (persisted).

```bash
/variables set region eu-west-1
/variables set CONFIG {"env":"prod"}
```

---

### `/variables set-host <name> <hostname>`

Define a host alias (persisted).

```bash
/variables set-host proddb db-prod-001.example.com
```

**Usage in queries:**
```
check mongodb status on @proddb
```

---

### `/variables set-secret <name>` or `/variables secret <name>`

Define a secret (memory-only, NOT persisted). Uses secure hidden input.

```bash
/variables set-secret dbpass
/variables secret token
```

---

### `/variables delete <name>`

Delete a variable. Aliases: `del`, `remove`

```bash
/variables delete proddb
```

---

### `/variables clear`

Clear all variables.

```bash
/variables clear
```

---

### `/variables clear-secrets`

Clear only secrets (memory-only variables).

```bash
/variables clear-secrets
```

---

### `/credentials`

Alias for `/variables` (backward compatibility).

---

## Persistent Secrets

Persistent secrets are stored securely using the system keyring (macOS Keychain, Windows Credential Locker, Linux SecretService). Unlike `/variables secret` which stores in memory only, `/secret` persists across sessions.

### `/secret`

Show help for secret management.

```bash
/secret
/secret help
```

---

### `/secret set <name> [value]`

Store a persistent secret. If value is not provided, prompts for secure hidden input.

```bash
# Prompt for value (recommended - hidden input)
/secret set db-password

# Set directly (visible in terminal history - use with caution)
/secret set api-key sk-xxx123
```

---

### `/secret get <name>`

Retrieve a secret value (displays masked by default).

```bash
/secret get db-password
```

---

### `/secret list`

List all stored secrets (values are masked).

```bash
/secret list
```

**Output:**
```
Persistent Secrets
==================
🔐 db-password     : ********
🔐 api-key         : ********
🔐 ssh-passphrase  : ********

Total: 3 secrets stored in system keyring
```

---

### `/secret delete <name>`

Delete a persistent secret.

```bash
/secret delete old-api-key
```

---

### `/secret clear`

Delete ALL persistent secrets (with confirmation).

```bash
/secret clear
```

---

### `/secret export [file]`

Export secrets to encrypted file (for backup/migration).

```bash
/secret export ~/merlya-secrets.enc
```

---

### `/secret import <file>`

Import secrets from encrypted file.

```bash
/secret import ~/merlya-secrets.enc
```

---

### Using Secrets in Queries

Reference persistent secrets with `@name` syntax:

```bash
# Store credentials
/secret set mongo-user
/secret set mongo-pass

# Use in query
check mongodb status with user @mongo-user password @mongo-pass
```

---

### Storage Backend Priority

1. **System Keyring** (preferred): macOS Keychain, Windows Credential Locker, Linux SecretService
2. **Encrypted File** (fallback): `~/.merlya/secrets.enc` with Fernet encryption
3. **Memory Only** (last resort): If all else fails, secrets are session-only

---

## Inventory System

### `/inventory list`

List inventory sources. Alias: `ls`

```bash
/inventory list
```

---

### `/inventory show [source] [--limit N]`

Show hosts from all or specific source.

```bash
/inventory show
/inventory show /etc/hosts
/inventory show --limit 50
```

---

### `/inventory search <pattern> [--limit N]`

Search hosts by hostname, IP, or groups. Alias: `find`

```bash
/inventory search prod
/inventory search 192.168
/inventory search web --limit 20
```

---

### `/inventory add <file>`

Import hosts from file. Alias: `import`

Supported formats: CSV, JSON, YAML, INI (Ansible), /etc/hosts, ~/.ssh/config

```bash
/inventory add /etc/hosts
/inventory add ~/.ssh/config
/inventory add hosts.csv
/inventory add inventory.json
```

---

### `/inventory add-host [hostname]`

Add single host interactively.

```bash
/inventory add-host
/inventory add-host web-prod-01
```

---

### `/inventory remove <source>`

Remove a source and its hosts. Aliases: `delete`, `rm`

```bash
/inventory remove hosts.csv
```

---

### `/inventory export <file>`

Export inventory to file (json/csv/yaml).

```bash
/inventory export inventory.json
/inventory export hosts.csv
```

---

### `/inventory snapshot [name]`

Create a point-in-time snapshot.

```bash
/inventory snapshot
/inventory snapshot before-cleanup
```

---

### `/inventory stats`

Show inventory statistics.

```bash
/inventory stats
```

---

### `/inventory relations`

Manage host relationships.

```bash
# Get AI-suggested relations
/inventory relations
/inventory relations suggest

# List validated relations
/inventory relations list
```

---

## CI/CD Commands

### `/cicd`

Overview and detected CI/CD platforms.

```bash
/cicd
```

---

### `/cicd status`

Recent run status summary.

```bash
/cicd status
```

---

### `/cicd workflows`

List available workflows.

```bash
/cicd workflows
```

---

### `/cicd runs [N]`

List last N runs (default: 10).

```bash
/cicd runs
/cicd runs 20
```

---

### `/cicd trigger <workflow> [--ref <branch>]`

Trigger a workflow.

```bash
/cicd trigger deploy
/cicd trigger deploy --ref main
```

---

### `/cicd cancel <run_id>`

Cancel a running workflow.

```bash
/cicd cancel 12345678
```

---

### `/cicd retry <run_id> [--full]`

Retry a failed run.

```bash
/cicd retry 12345678
/cicd retry 12345678 --full
```

---

### `/cicd analyze <run_id>`

Analyze a specific run.

```bash
/cicd analyze 12345678
```

---

### `/cicd permissions`

Check CI/CD permissions.

```bash
/cicd permissions
```

---

### `/debug-workflow [run_id]`

Debug a CI/CD workflow failure.

```bash
# Debug most recent failure
/debug-workflow

# Debug specific run
/debug-workflow 12345678
```

---

## MCP Server Management

### `/mcp list`

List configured MCP servers.

```bash
/mcp list
```

---

### `/mcp add`

Add an MCP server (interactive).

```bash
/mcp add
```

---

### `/mcp show <name>`

Show MCP server configuration details.

```bash
/mcp show github
```

---

### `/mcp delete <name>`

Remove an MCP server configuration.

```bash
/mcp delete filesystem
```

---

### `/mcp examples`

Show example MCP server configurations.

```bash
/mcp examples
```

---

## Triage Commands

### `/triage <query>`

Test priority classification for a query.

```bash
/triage production database is slow
```

**Output:**

```text
Triage Classification
=====================
Priority: P1 (High)
Intent: ANALYSIS
Confidence: 0.92
Environment: production
```

---

### `/feedback <intent> <priority> <query>`

Correct a triage classification.

```bash
# Correct specific query
/feedback action P0 restart nginx on prod

# Correct last query
/feedback --last action P0
```

**Intents:** `query`, `action`, `analysis`
**Priorities:** `P0` (critical), `P1` (urgent), `P2` (important), `P3` (normal)

---

### `/triage-stats`

Show learned triage patterns statistics.

```bash
/triage-stats
```

---

## Conversation Management

### `/conversations`

List all saved conversations.

```bash
/conversations
```

---

### `/new [title]`

Start a new conversation.

```bash
/new
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

---

### `/delete <id>`

Delete a conversation.

```bash
/delete 3
```

---

## Session Management

### `/session`

Show current session info.

```bash
/session
```

---

### `/session list`

List recent sessions.

```bash
/session list
```

---

## Other Commands

### `/language <code>`

Change response language.

```bash
/language fr
/language en
```

---

### `/reload-commands`

Reload custom slash commands from `~/.merlya/commands/`.

```bash
/reload-commands
```

---

### `/reset`

Reset agent memory (clear conversation context from agents).

```bash
/reset
```

---

### `/exit` or `/quit`

Exit the Merlya REPL.

```bash
/exit
```

---

## Custom Commands

Merlya supports custom slash commands defined in markdown files.

### Location

```text
~/.merlya/commands/
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
```

### Usage

```bash
/deploy myapp prod
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `MERLYA_ENV` | Default environment (dev/staging/prod) |
| `MERLYA_LANGUAGE` | Default language (en/fr) |
| `MERLYA_MODEL` | Default LLM model |
| `MERLYA_PROVIDER` | Default LLM provider |
| `MERLYA_EMBEDDING_MODEL` | Local embedding model |
| `MERLYA_ENABLE_LLM_FALLBACK` | Enable LLM-based inventory parsing (default: false) |
| `MERLYA_LLM_COMPLIANCE_ACKNOWLEDGED` | Confirm LLM data handling compliance |

---

## See Also

- [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- [INVENTORY.md](INVENTORY.md) - Inventory system details
- [VARIABLES.md](VARIABLES.md) - Variable system
- [TOOLS.md](TOOLS.md) - Available tools
- [TRIAGE.md](TRIAGE.md) - Triage system
- [CREDENTIALS.md](CREDENTIALS.md) - Credential management
