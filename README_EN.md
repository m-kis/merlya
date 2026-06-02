> ## ⚠️ Project archived — no longer maintained
>
> **Merlya is no longer actively developed** (last release: `v0.8.5`, February 2026).
>
> **Why?** The rapid rise of general-purpose CLI agents — **Claude Code**, Codex CLI, Gemini CLI and others — has largely absorbed Merlya's value proposition. Backed by the major AI labs, these tools now cover most of the "natural-language CLI assistant" experience with resources far beyond those of an independent project. Maintaining a competitor on that ground no longer makes sense **for now**.
>
> The code remains browsable, reusable and installable (`pip install merlya`) under the MIT + Commons Clause license, **for archival purposes only**: no new features, bug fixes or security updates are planned. Since the tool handles SSH, secrets and privilege elevation, assess that risk before any production use.
>
> Thanks to everyone who tried and supported the project. 🙏

<p align="center">
  <img src="https://merlya.m-kis.fr/assets/logo.png" alt="Merlya Logo" width="120">
</p>

<h1 align="center">Merlya</h1>

<p align="center">
  <strong>AI-powered infrastructure assistant for DevOps & SysAdmins</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/merlya/"><img src="https://img.shields.io/pypi/v/merlya?color=%2340C4E0" alt="PyPI"></a>
  <a href="https://pypi.org/project/merlya/"><img src="https://img.shields.io/pypi/pyversions/merlya" alt="Python"></a>
  <a href="https://pypi.org/project/merlya/"><img src="https://img.shields.io/pypi/dm/merlya" alt="Downloads"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT%20%2B%20Commons%20Clause-blue" alt="License"></a>
  <a href="https://merlya.m-kis.fr/"><img src="https://img.shields.io/badge/docs-merlya.m--kis.fr-40C4E0" alt="Documentation"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/status-archived-lightgrey" alt="Status: Archived">
  <img src="https://img.shields.io/badge/maintenance-no%20longer%20maintained-red" alt="Unmaintained">
  <img src="https://img.shields.io/badge/code%20style-ruff-000000" alt="Ruff">
  <img src="https://img.shields.io/badge/type%20checked-mypy-blue" alt="mypy">
</p>

<p align="center">
  <a href="https://github.com/m-kis/merlya/blob/main/README.md">Lire en Français</a>
</p>

---

## Overview

Merlya is an autonomous CLI assistant that understands your infrastructure context, plans intelligent actions, and executes them safely. It combines a **SmartExtractor** (LLM + regex hybrid) to extract hosts from natural language, a secure SSH pool, and simplified inventory management. A single `MerlyaAgent` delegates work to focused specialist agents based on the nature of the request.

### Key Features

- **Natural language commands** to diagnose and remediate your environments
- **Specialist agent architecture**: `MerlyaAgent` delegates to specialists (diagnostic, execution, security, query)
- **Async SSH pool** with MFA/2FA, jump hosts, and SFTP
- **`/hosts` inventory** with smart import (SSH config, /etc/hosts, Ansible, TOML, CSV)
- **Brain/fast models**: brain for complex reasoning, fast for quick decisions
- **IaC Pipelines**: Ansible, Terraform, Kubernetes, Bash with mandatory HITL
- **Explicit elevation**: sudo/doas/su configured per host (no auto-detection)
- **Security by design**: secrets in keyring, Pydantic validation, loop detection
- **Observability**: in-memory metrics + circuit breaker / retry (`/metrics`)
- **i18n**: English and French
- **MCP integration** to consume external tools (GitHub, Slack, custom) via `/mcp`

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER INPUT                                      │
│                    "Check disk on web-01 via bastion"                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SMART EXTRACTOR                                      │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                      │
│  │ Fast Model  │───▶│   Regex     │───▶│   Hosts     │                      │
│  │ (semantic)  │    │  Patterns   │    │  Inventory  │                      │
│  └─────────────┘    └─────────────┘    └─────────────┘                      │
│  Output: hosts=[web-01], via=bastion, context injected                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          MERLYA AGENT                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  System prompt guides delegation decision (no separate classifier)  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│        │                    │                    │                    │      │
│        ▼                    ▼                    ▼                    ▼      │
│  ┌──────────┐        ┌──────────┐        ┌──────────┐        ┌──────────┐   │
│  │Diagnostic│        │Execution │        │Security  │        │ Query    │   │
│  │Specialist│        │Specialist│        │Specialist│        │Specialist│   │
│  │read-only │        │HITL+pipes│        │sec audits│        │inventory │   │
│  └──────────┘        └──────────┘        └──────────┘        └──────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SECURITY LAYER                                     │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                      │
│  │  Keyring    │    │  Elevation  │    │    Loop     │                      │
│  │  Secrets    │    │  Explicit   │    │  Detection  │                      │
│  │ @secret-ref │    │ (per-host)  │    │ (5+ repeat) │                      │
│  └─────────────┘    └─────────────┘    └─────────────┘                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            SSH POOL                                          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                      │
│  │ Connection  │    │  Jump Host  │    │    MFA      │                      │
│  │   Reuse     │    │   Support   │    │   Support   │                      │
│  └─────────────┘    └─────────────┘    └─────────────┘                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          PERSISTENCE                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │  Hosts   │  │ Sessions │  │  Audit   │  │ Raw Logs │  │ Messages │       │
│  │ Inventory│  │ Context  │  │   Logs   │  │  (TTL)   │  │ History  │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
│                         SQLite + Keyring                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Installation (End Users)

```bash
pip install merlya
merlya
```

### Docker Installation

```bash
# Copy and configure environment variables
cp .env.example .env
# Edit .env with your API keys

# Start the container
docker compose up -d

# Development mode (source code mounted)
docker compose --profile dev up -d
```

**SSH Configuration for Docker:**

The container mounts your local SSH directory. By default, it uses `$HOME/.ssh`.

In CI/CD environments where `$HOME` may be unset, you must explicitly set `SSH_DIR`:

```bash
# Via environment variable
SSH_DIR=/root/.ssh docker compose up -d

# Or in your .env file
SSH_DIR=/home/jenkins/.ssh
```

**Required permissions:**
- SSH directory: `700` (owner rwx only)
- Private keys: `600` (owner rw only)

See `.env.example` for complete variable documentation.

### First Launch

1. Language selection (fr/en)
2. LLM provider configuration (key stored in keyring)
3. Local scan and host import (SSH config, /etc/hosts, Ansible inventories)
4. Health checks (RAM, disk, LLM, SSH, keyring, web search)

## Quick Examples

```bash
> Check disk usage on web-prod-01
> /hosts list
> /ssh exec db-01 "uptime"
> /model show
> /metrics
> /variable set region eu-west-1
> /mcp list
```

> **Note**: Host names are written **without the `@` prefix**. The `@` prefix is reserved for secret references (e.g., `@db-password`).

## Security

### Secrets and @secret references

Secrets (passwords, tokens, API keys) are stored in the system keyring (macOS Keychain, Linux Secret Service) and referenced by `@secret-name` in commands:

```bash
> Connect to MongoDB with @db-password
# Merlya resolves @db-password from keyring before execution
# Logs show @db-password, never the actual value
```

### Privilege Elevation

Merlya automatically detects elevation capabilities (sudo, doas, su) and handles passwords securely:

1. **sudo NOPASSWD** - Best choice, no password needed
2. **doas** - Often passwordless on BSD
3. **sudo with password** - Standard fallback
4. **su** - Last resort, requires root password

Elevation passwords are stored in keyring and referenced by `@elevation:hostname:password`.

### Loop Detection

The agent detects repetitive patterns (same tool called 3+ times, A-B-A-B alternation) and injects a message to redirect to a different approach.

## Configuration

- User file: `~/.merlya/config.yaml` (language, model, SSH timeouts, UI).
- API keys: stored in keyring. Memory fallback with warning.
- Useful environment variables:

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | OpenRouter key (default provider) |
| `ANTHROPIC_API_KEY` | Anthropic key |
| `OPENAI_API_KEY` | OpenAI key |
| `MISTRAL_API_KEY` | Mistral key |
| `GROQ_API_KEY` | Groq key |
| `MERLYA_ROUTER_FALLBACK` | LLM fallback model |

## Installation for Contributors

```bash
git clone https://github.com/m-kis/merlya.git
cd merlya
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"    # Dev dependencies

merlya --version
pytest tests/ -v
```

## Quality and Scripts

| Check | Command |
|-------|---------|
| Lint | `ruff check merlya/` |
| Format (check) | `ruff format --check merlya/` |
| Type check | `mypy merlya/` |
| Tests + coverage | `pytest tests/ --cov=merlya --cov-report=term-missing` |
| Security (code) | `bandit -r merlya/ -c pyproject.toml` |
| Security (deps) | `pip-audit -r <(pip freeze)` |

Key principles: DRY/KISS/YAGNI, SOLID, SoC, LoD, no files > ~600 lines, coverage >= 80%, conventional commits (see [CONTRIBUTING.md](CONTRIBUTING.md)).

## CI/CD

- `.github/workflows/ci.yml`: lint + format check + mypy + tests + security (Bandit + pip-audit) on GitHub runners for each PR/push.
- `.github/workflows/release.yml`: build + GitHub release + PyPI publication via trusted publishing, triggered on `v*` tag or `workflow_dispatch` by a maintainer (no secrets on external PRs).
- `main` branch protected: merge via PR, CI required, >= 1 review, squash merge recommended.

## Documentation

📚 **Full documentation**: [https://merlya.m-kis.fr/](https://merlya.m-kis.fr/)

Local files:
- [docs/architecture.md](docs/architecture.md): architecture and decisions
- [docs/commands.md](docs/commands.md): slash commands
- [docs/configuration.md](docs/configuration.md): complete configuration
- [docs/tools.md](docs/tools.md): tools and agents
- [docs/ssh.md](docs/ssh.md): SSH, bastions, MFA
- [docs/extending.md](docs/extending.md): extensions/agents

## Contributing

- Read [CONTRIBUTING.md](CONTRIBUTING.md) for conventions (commits, branches, file/function size limits).
- Follow the [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- Issue and PR templates are available in `.github/`.

## Security

See [SECURITY.md](SECURITY.md). Do not publish vulnerabilities in public issues: write to `security@merlya.fr`.

## License

[MIT with Commons Clause](LICENSE). The Commons Clause prohibits selling the software as a hosted service while allowing use, modification, and redistribution.

---

<p align="center">
  Made by <a href="https://github.com/m-kis">M-KIS</a>
</p>
