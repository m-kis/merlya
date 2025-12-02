# Merlya

**AI-powered infrastructure orchestration CLI** - A natural language interface for managing your infrastructure.

[![PyPI version](https://badge.fury.io/py/merlya.svg)](https://pypi.org/project/merlya/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT%20Commons%20Clause-yellow.svg)](LICENSE)

## Features

- Natural language queries for infrastructure management
- Multi-LLM support (OpenRouter, Anthropic, OpenAI, Ollama)
- SSH execution with your existing credentials (`~/.ssh/config`, `ssh-agent`)
- Interactive REPL with conversation memory
- Persistent secrets with system keyring (macOS Keychain, Windows Credential Locker, Linux SecretService)
- Task-specific model routing (fast models for fixes, powerful models for planning)
- Comprehensive logging system with runtime configuration
- Extensible slash commands and hooks system
- Host validation to prevent hallucinated commands
- Risk assessment for dangerous operations

## Installation

### From PyPI (Recommended)

```bash
# Basic installation
pip install merlya

# With knowledge graph support (DuckDuckGo search, FalkorDB)
pip install "merlya[knowledge]"

# With smart error triage (ML-based error classification)
pip install "merlya[smart-triage]"

# Full installation (all features)
pip install "merlya[all]"
```

### From Source

```bash
# Clone the repository
git clone https://github.com/m-kis/merlya.git
cd merlya

# Install with Poetry
poetry install

# Or with extras
poetry install -E all
```

### Installation Extras

| Extra | Dependencies | Features |
|-------|-------------|----------|
| `knowledge` | `duckduckgo-search`, `falkordb` | Web search, knowledge graph storage |
| `smart-triage` | `sentence-transformers`, `falkordb` | ML-based error classification, semantic tool selection |
| `all` | All of the above | Full feature set |

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
| `/secret set <name>` | Store a persistent secret |
| `/secret list` | List stored secrets |
| `/variables set <key> <value>` | Set a variable |
| `/variables set-secret <key>` | Set a session secret (hidden input) |
| `/model list` | List available models |
| `/model set <provider> <model>` | Switch LLM model |
| `/model task set <task> <model>` | Set task-specific model |
| `/log level <level>` | Change log verbosity |
| `/log show` | Display recent logs |
| `/inventory list` | List inventory sources |
| `/clear` | Clear conversation |
| `/exit` | Exit REPL |

### Persistent Secrets

Store secrets securely using your system's keyring:

```bash
# Store a secret (prompts for hidden input)
/secret set db-password

# List stored secrets
/secret list

# Use secrets in queries with @name syntax
check mongodb status with password @db-password

# Delete a secret
/secret delete db-password
```

Secrets are stored in:

1. **System Keyring** (preferred): macOS Keychain, Windows Credential Locker, Linux SecretService
2. **Encrypted File** (fallback): `~/.merlya/secrets.enc`

### Task-Specific Model Routing

Configure different models for different task types:

```bash
# Use fast model for quick fixes
/model task set correction claude-3-5-haiku-latest

# Use powerful model for complex planning
/model task set planning claude-sonnet-4

# Use balanced model for general tasks
/model task set synthesis claude-sonnet-4
```

### Logging

Control log verbosity at runtime:

```bash
# Set log level
/log level debug    # Show all logs
/log level info     # Normal verbosity
/log level warning  # Only warnings and errors
/log level error    # Only errors

# View recent logs
/log show
/log show 50        # Show last 50 entries
```

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
|   LLM Router      |  <- Task-specific model selection
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

Authentication required for:
   Service: MongoDB
   Target: db-prod-01
   Error: Authentication failed

Would you like to provide credentials? (yes/no)
> yes
   Username: admin
   Password: ****

Credentials stored successfully! (TTL: 15 minutes)
```

Credentials are:

- Never persisted to disk (use `/secret` for persistent storage)
- Never logged (even in debug mode)
- Validated against injection attacks
- Available as `@mongodb-user` / `@mongodb-pass` variables

### Audit Trail

All actions logged to `~/.merlya/logs/`

## Optional Features

### Knowledge Graph (FalkorDB)

```bash
# Install with knowledge support
pip install "merlya[knowledge]"

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

# Linting
ruff check merlya/
```

## Roadmap

See [ROADMAP.md](ROADMAP.md) for planned features.

**Coming in v0.4.0:**

- Ansible playbook execution
- Terraform integration
- Kubernetes support (kubectl)
- Session export/import
- Docker image

## License

**MIT License with Commons Clause** - See [LICENSE](LICENSE)

This software is free to use for personal, educational, and community purposes.

**Commercial use, sale, for-profit redistribution, or integration into a paid product/service is strictly prohibited without written permission from the author, Cedric Merlin and M-KIS.**

For commercial licensing inquiries, please contact the author.
