# Merlya

**AI-powered infrastructure orchestration CLI** - A natural language interface for managing your infrastructure.

## Features

- Natural language queries for infrastructure management
- Multi-LLM support (OpenRouter, Anthropic, OpenAI, Ollama)
- SSH execution with your existing credentials (`~/.ssh/config`, `ssh-agent`)
- Interactive REPL with conversation memory
- Extensible slash commands and hooks system
- Host validation to prevent hallucinated commands
- Risk assessment for dangerous operations

## Installation

```bash
# Basic installation (core features only)
poetry install

# With knowledge graph support (DuckDuckGo search, FalkorDB)
poetry install -E knowledge

# With smart error triage (ML-based error classification)
poetry install -E smart-triage

# Full installation (all features)
poetry install -E all
```

### Installation Extras

| Extra | Dependencies | Features |
|-------|-------------|----------|
| `knowledge` | `duckduckgo-search`, `falkordb` | Web search, knowledge graph storage |
| `smart-triage` | `sentence-transformers`, `falkordb` | ML-based error classification, semantic tool selection |
| `all` | All of the above | Full feature set |

### With pip

```bash
pip install .                    # Basic
pip install ".[knowledge]"       # With knowledge graph
pip install ".[smart-triage]"    # With ML error triage
pip install ".[all]"             # Everything
```

## Quick Start

```bash
# Configure your LLM provider
export OPENROUTER_API_KEY="sk-or-..."
# or ANTHROPIC_API_KEY, OPENAI_API_KEY, OLLAMA_HOST

# Launch interactive REPL (default)
merlya

# Or run a single query
merlya ask "list all mongo hosts"
```

## Usage

### Interactive Mode (REPL)

```bash
$ merlya

Merlya REPL - Type /help for commands

> list mongo preprod IPs
MongoDB Preprod hosts:
  - mongo-preprod-1: 203.0.113.10
  - mongo-preprod-2: 198.51.100.20

> check if mongodb is running on mongo-preprod-1
Checking mongodb status...
[SSH] systemctl status mongod
mongod.service - MongoDB Database Server
   Active: active (running)

> /scan --full
Scanning all hosts...

> /help
```

### Single Query Mode

```bash
# Simple query
merlya ask "what services are running on web-prod-1"

# Dry-run (see plan without executing)
merlya ask "restart nginx on lb-prod-1" --dry-run

# Auto-confirm critical actions
merlya ask "restart mongodb" --confirm
```

### Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/scan` | Scan infrastructure |
| `/scan --full` | Full SSH scan of all hosts |
| `/hosts` | List known hosts |
| `/variables set <key> <value>` | Set a variable |
| `/variables set-secret <key>` | Set a secret (hidden input) |
| `/model list` | List available models |
| `/model set <provider> <model>` | Switch LLM model |
| `/clear` | Clear conversation |
| `/exit` | Exit REPL |

### Custom Commands

Create markdown files in `~/.merlya/commands/` or `.merlya/commands/`:

```markdown
---
name: healthcheck
description: Run health check on a host
aliases: [hc, health]
---

Perform health check on {{$1}}:
- Check CPU, memory, disk
- List running services
- Check for errors in logs
```

Then use: `/healthcheck web-prod-1`

## Configuration

### LLM Providers

```bash
# OpenRouter (recommended - multiple models)
export OPENROUTER_API_KEY="sk-or-..."
export OPENROUTER_MODEL="anthropic/claude-sonnet-4"

# Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."

# OpenAI
export OPENAI_API_KEY="sk-..."

# Ollama (local/offline)
export OLLAMA_HOST="http://localhost:11434"
export OLLAMA_MODEL="llama3"
```

### SSH Configuration

Merlya uses your existing SSH setup:

```ssh
# ~/.ssh/config
Host mongo-*
    User mongodb-admin
    IdentityFile ~/.ssh/id_mongo

Host *.prod
    User ops
    IdentityFile ~/.ssh/id_prod
```

### Inventory Sources

Merlya discovers hosts from:
- `/etc/hosts`
- `~/.ssh/config`
- SSH scanning
- Custom inventory files (`~/.merlya/inventory.yaml`)

## Architecture

```
User Query
    |
    v
+-------------------+
|   REPL / CLI      |
+-------------------+
    |
    v
+-------------------+
|   Orchestrator    |  <- AutoGen/AG2 multi-agent
+-------------------+
    |
    v
+-------------------+
|   LLM Router      |  <- OpenRouter, Anthropic, OpenAI, Ollama
+-------------------+
    |
    v
+-------------------+
|  Context Manager  |  <- Host registry, SSH scan results
+-------------------+
    |
    v
+-------------------+
|  SSH Executor     |  <- Connection pooling, error correction
+-------------------+
```

## Security

### Risk Assessment

Commands are evaluated before execution:
- **Low**: read-only (ps, cat, df) - auto-execute
- **Moderate**: config changes (chmod) - prompt confirmation
- **Critical**: destructive (rm, reboot, stop) - requires `--confirm`

### Host Validation

All commands are validated against the host registry. Operations on unknown/hallucinated hostnames are blocked.

### Credential Management

When authentication errors occur (MongoDB, MySQL, PostgreSQL, SSH), Merlya:

1. **Detects the error** - Classifies it as a credential issue with confidence score
2. **Prompts the user** - Asks for username/password via secure input (getpass)
3. **Caches credentials** - Stores in-memory with 15-minute TTL
4. **Retries automatically** - Re-executes the command with new credentials

```bash
# Example flow
> check mongodb status on db-prod-01

🔐 Authentication required for:
   Service: MongoDB
   Target: db-prod-01
   Error: Authentication failed

Would you like to provide credentials? (yes/no)
> yes
   Username: admin
   Password: ****

✅ Credentials stored successfully! (TTL: 15 minutes)
```

Credentials are:

- Never persisted to disk
- Never logged (even in debug mode)
- Validated against injection attacks
- Available as `@mongodb-user` / `@mongodb-pass` variables

### Audit Trail

All actions logged to `~/.merlya/merlya.log`

## Optional Features

### Knowledge Graph (FalkorDB)

```bash
# Install with knowledge support
pip install ".[knowledge]"

# Start FalkorDB
docker run -p 6379:6379 falkordb/falkordb

# Enable in Merlya
export FALKORDB_HOST="localhost"
```

### Hooks

Create `~/.merlya/hooks.yaml` to intercept tool executions:

```yaml
hooks:
  tool_execute_start:
    - name: audit
      action: log
      config:
        file: /var/log/merlya-audit.log
```

## Development

```bash
# Install dev dependencies
poetry install

# Run tests
pytest

# Type checking
mypy merlya
```

## License

**MIT License with Commons Clause** - See [LICENSE](LICENSE)

This software is free to use for personal, educational, and community purposes.

**Commercial use, sale, for-profit redistribution, or integration into a paid product/service is strictly prohibited without written permission from the author, Cédric Merlin and M-KIS.**

For commercial licensing inquiries, please contact the author.
