<p align="center">
  <img src="https://merlya.fr/static/media/logo.41177386c9cd7ecf8aaa.png" alt="Merlya Logo" width="120">
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
</p>

<p align="center">
  <a href="https://m-kis.github.io/merlya-docs/"><img src="https://img.shields.io/badge/docs-online-brightgreen" alt="Documentation"></a>
  <img src="https://img.shields.io/badge/code%20style-ruff-000000" alt="Ruff">
  <img src="https://img.shields.io/badge/type%20checked-mypy-blue" alt="mypy">
</p>

<p align="center">
  <a href="https://m-kis.github.io/merlya-docs/">Documentation</a> •
  <a href="#installation">Installation</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#contributing">Contributing</a>
</p>

---

## Overview

Merlya is an autonomous CLI assistant that understands your infrastructure context, plans intelligent actions, and executes them securely. It combines a local intent router (ONNX) with LLM fallback via PydanticAI, a secure SSH pool, and simplified inventory management.

### Key Features

- Natural language commands to diagnose and remediate your environments
- Async SSH pool with MFA/2FA, jump hosts, and SFTP support
- `/hosts` inventory with smart import (SSH config, /etc/hosts, Ansible)
- Local-first router (gte/EmbeddingGemma/e5) with configurable LLM fallback
- Security by design: secrets in keyring, Pydantic validation, consistent logging
- Extensible (modular Docker/K8s/CI-CD agents) and i18n (fr/en)

## Installation

```bash
pip install merlya          # Standard installation
pip install merlya[router]  # With local ONNX router
pip install merlya[all]     # All extras

# Launch the assistant
merlya
```

> ONNX doesn't have Python 3.14 wheels yet: use Python ≤ 3.13 for `[router]`.

### First Run

The setup wizard guides you through:

1. Language selection (fr/en)
2. LLM provider configuration (key stored in keyring)
3. Local scan and host import (SSH config, /etc/hosts, Ansible inventories)
4. Health checks (RAM, disk, LLM, SSH, keyring, web search)

## Quick Start

```bash
> Check disk usage on @web-prod-01
> /hosts list
> /ssh exec @db-01 "uptime"
> /model router show
> /variable set region eu-west-1
```

## Configuration

- User config file: `~/.merlya/config.yaml` (language, model, SSH timeouts, UI)
- API keys: stored in system keyring. In-memory fallback with warning.
- Useful environment variables:

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `MERLYA_ROUTER_FALLBACK` | LLM fallback model |
| `MERLYA_LOG_LEVEL` | Log level (debug, info, warning, error) |

## Documentation

Full documentation is available at **[m-kis.github.io/merlya-docs](https://m-kis.github.io/merlya-docs/)** with an AI-powered chat assistant to help you find answers quickly.

Topics covered:
- [Installation Guide](https://m-kis.github.io/merlya-docs/getting-started/installation/)
- [Quick Start](https://m-kis.github.io/merlya-docs/getting-started/quickstart/)
- [REPL Mode](https://m-kis.github.io/merlya-docs/guides/repl-mode/)
- [SSH Management](https://m-kis.github.io/merlya-docs/guides/ssh-management/)
- [LLM Providers](https://m-kis.github.io/merlya-docs/guides/llm-providers/)
- [CLI Reference](https://m-kis.github.io/merlya-docs/reference/cli/)

## Development

### Installation for Contributors

```bash
git clone https://github.com/m-kis/merlya.git
cd merlya
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"    # Dev dependencies

merlya --version
pytest tests/ -v
```

### Quality Checks

| Check | Command |
|-------|---------|
| Lint | `ruff check merlya/` |
| Format (check) | `ruff format --check merlya/` |
| Type check | `mypy merlya/` |
| Tests + coverage | `pytest tests/ --cov=merlya --cov-report=term-missing` |
| Security (code) | `bandit -r merlya/ -c pyproject.toml` |
| Security (deps) | `pip-audit -r <(pip freeze)` |

Key principles: DRY/KISS/YAGNI, SOLID, SoC, LoD, no files > ~600 lines, coverage ≥ 80%, conventional commits (see [CONTRIBUTING.md](CONTRIBUTING.md)).

## CI/CD

- `.github/workflows/ci.yml`: lint + format check + mypy + tests + security (Bandit + pip-audit) on GitHub runners for each PR/push.
- `.github/workflows/release.yml`: build + GitHub release + PyPI publish via trusted publishing, triggered on `v*` tag or `workflow_dispatch` by a maintainer.
- `main` branch protected: merge via PR, CI required, ≥1 review, squash merge recommended.

## Contributing

- Read [CONTRIBUTING.md](CONTRIBUTING.md) for conventions (commits, branches, file/function size limits).
- Follow the [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- Issue and PR templates are available in `.github/`.

## Security

See [SECURITY.md](SECURITY.md). Do not publish vulnerabilities in public issues: email `security@merlya.fr`.

## License

[MIT with Commons Clause](LICENSE). The Commons Clause prohibits selling the software as a hosted service while allowing use, modification, and redistribution.

---

<p align="center">
  Made with ❤️ by <a href="https://github.com/m-kis">M-KIS</a>
</p>
