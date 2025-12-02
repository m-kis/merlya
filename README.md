# Merlya

**AI-powered infrastructure orchestration CLI** - A natural language interface for managing your infrastructure.

[![PyPI version](https://badge.fury.io/py/merlya.svg)](https://pypi.org/project/merlya/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT%20Commons%20Clause-yellow.svg)](LICENSE)

## Features

### Core Capabilities

- **Natural Language Interface** - Query and manage infrastructure using plain English
- **Multi-LLM Support** - OpenRouter, Anthropic, OpenAI, Ollama (local/offline)
- **Multi-Agent Orchestration** - AutoGen 0.7+ powered agent teams
- **48 Slash Commands** - Comprehensive CLI command system
- **SSH Execution** - Connection pooling, key management, passphrase caching

### Security & Credentials

- **Persistent Secrets** - System keyring integration (macOS Keychain, Windows Credential Locker, Linux SecretService)
- **Session Secrets** - In-memory temporary credentials with TTL
- **SSH Key Management** - Per-host key configuration, agent forwarding
- **Permission Detection** - Automatic capability detection on hosts
- **Audit Logging** - Compliance-ready action logging

### Intelligence & Learning

- **Smart Triage** - AI/embedding/keyword-based request classification (P0-P3)
- **Knowledge Graph** - FalkorDB incident memory and pattern learning
- **CVE Monitoring** - Vulnerability tracking integration
- **Error Analysis** - Semantic error classification and auto-correction suggestions

### Infrastructure Management

- **Local Scanner** - Comprehensive local machine scanning (12h TTL, SQLite cache)
- **Remote Scanner** - JIT on-demand SSH-based scanning
- **Host Registry** - Metadata, relationships, versioning
- **Inventory System** - Multi-format import (CSV/JSON/YAML/INI/hosts/ssh-config)

### CI/CD Integration

- **GitHub Actions** - Full workflow management, failure analysis
- **Learning Engine** - Learn from CI failures for better suggestions
- **Extensible** - Plugin architecture for GitLab, Jenkins, CircleCI

### Executors

- **SSH** - Connection pooling, error correction
- **Ansible** - Playbook execution
- **Terraform** - Plan/apply/destroy operations
- **Kubernetes** - kubectl integration
- **AWS** - Cloud API operations
- **Docker** - Container management

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
git clone https://github.com/m-kis/merlya.git
cd merlya
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

# Launch interactive REPL
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
[SSH] systemctl status mongod
mongod.service - MongoDB Database Server
   Active: active (running)

> /help
```

### Command Reference

#### Context & Scanning

| Command | Description |
|---------|-------------|
| `/scan` | Scan local machine or specific host |
| `/scan --full` | Full SSH scan of all hosts |
| `/refresh` | Force refresh context cache |
| `/cache-stats` | Show cache validity, TTL, fingerprints |
| `/context` | Show current infrastructure context |
| `/permissions` | Show detected permission capabilities |

#### Secrets & Variables

| Command | Description |
|---------|-------------|
| `/secret set <name>` | Store persistent secret (keyring) |
| `/secret list` | List stored secrets |
| `/secret delete <name>` | Delete a secret |
| `/variables set <key> <value>` | Set a variable |
| `/variables set-secret <key>` | Set session secret (hidden input, TTL) |

#### SSH Management

| Command | Description |
|---------|-------------|
| `/ssh keys` | List available SSH keys |
| `/ssh host <host> set-key <key>` | Set SSH key for host |
| `/ssh passphrase <key>` | Cache SSH key passphrase |
| `/ssh test <host>` | Test SSH connectivity |

#### Inventory

| Command | Description |
|---------|-------------|
| `/inventory list` | List inventory sources |
| `/inventory show <source>` | Show hosts from source |
| `/inventory search <pattern>` | Search hosts |
| `/inventory add <file>` | Import from CSV/JSON/YAML/INI |
| `/inventory add-host` | Interactive host addition |
| `/inventory export <format>` | Export as JSON/CSV/YAML |
| `/inventory relations` | AI-suggested host relations |

#### CI/CD

| Command | Description |
|---------|-------------|
| `/cicd status` | Show recent CI run status |
| `/cicd workflows` | List available workflows |
| `/cicd runs` | List recent runs |
| `/cicd analyze <run_id>` | Deep analysis of failure |
| `/cicd trigger <workflow>` | Trigger workflow execution |
| `/debug-workflow` | Debug most recent failure |

#### Model & Configuration

| Command | Description |
|---------|-------------|
| `/model list` | List available models |
| `/model set <provider> <model>` | Switch LLM model |
| `/model task set <task> <model>` | Set task-specific model |
| `/log level <level>` | Change log verbosity |
| `/log show [n]` | Display recent logs |
| `/stats` | Show usage statistics |

#### Session Management

| Command | Description |
|---------|-------------|
| `/conversations` | List conversations |
| `/new [title]` | Start new conversation |
| `/load <id>` | Load conversation |
| `/compact` | Compress conversation (reduce tokens) |
| `/delete <id>` | Delete conversation |

#### Triage & Learning

| Command | Description |
|---------|-------------|
| `/triage <query>` | Test priority classification |
| `/feedback` | Correct triage classifications |
| `/triage-stats` | Show learned patterns |

### Persistent Secrets

Store secrets securely using your system's keyring:

```bash
# Store a secret (prompts for hidden input)
/secret set db-password

# Use secrets in queries with @name syntax
check mongodb status with password @db-password
```

Storage priority:

1. **System Keyring** (preferred): macOS Keychain, Windows Credential Locker, Linux SecretService
2. **Encrypted File** (fallback): `~/.merlya/secrets.enc`

### Task-Specific Model Routing

Configure different models for different task types:

```bash
# Use fast model for quick fixes (P0/P1 priority)
/model task set correction claude-3-5-haiku-latest

# Use powerful model for complex planning (P3)
/model task set planning claude-sonnet-4

# Use balanced model for general tasks (P2)
/model task set synthesis claude-sonnet-4
```

### Custom Commands

Create markdown files in `~/.merlya/commands/`:

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

```text
User Query
    │
    ▼
┌───────────────────┐
│   REPL / CLI      │  48 slash commands
└───────────────────┘
    │
    ▼
┌───────────────────┐
│   Orchestrator    │  AutoGen 0.7+ multi-agent
└───────────────────┘
    │
    ├──▶ SentinelAgent (security)
    ├──▶ DiagnosticAgent (analysis)
    ├──▶ RemediationAgent (actions)
    ├──▶ ProvisioningAgent (infra)
    └──▶ MonitoringAgent (health)
    │
    ▼
┌───────────────────┐
│   LLM Router      │  Task-specific model selection
└───────────────────┘
    │
    ▼
┌───────────────────┐
│  Context Manager  │  JIT scanning, smart cache
└───────────────────┘
    │
    ▼
┌───────────────────┐
│    Executors      │  SSH, Ansible, Terraform, K8s, AWS
└───────────────────┘
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

When authentication errors occur, Merlya:

1. **Detects the error** - Classifies with confidence score
2. **Prompts the user** - Secure input (getpass)
3. **Caches credentials** - In-memory with 15-minute TTL
4. **Retries automatically** - Re-executes with new credentials

Use `/secret` for persistent storage or `/variables set-secret` for session-only secrets.

### Audit Trail

All actions logged to `~/.merlya/logs/`

## Optional Features

### Knowledge Graph (FalkorDB)

```bash
pip install "merlya[knowledge]"

# Start FalkorDB
docker run -p 6379:6379 falkordb/falkordb

export FALKORDB_HOST="localhost"
```

Features:

- Incident memory with similarity matching
- Pattern learning from past incidents
- CVE vulnerability tracking
- Web search integration

### Smart Triage (Embeddings)

```bash
pip install "merlya[smart-triage]"
```

Uses sentence-transformers for semantic classification when LLM is unavailable.

## Development

```bash
poetry install
pytest
mypy merlya
ruff check merlya/
```

## Roadmap

See [ROADMAP.md](ROADMAP.md) for planned features.

**Coming in v0.4.0:**

- Docker image
- Session export/import
- Enhanced Ansible/Terraform/K8s integration
- Cloud provider APIs (AWS, GCP, Azure)

## License

**MIT License with Commons Clause** - See [LICENSE](LICENSE)

Free for personal, educational, and community use.

**Commercial use prohibited without written permission from Cedric Merlin and M-KIS.**
