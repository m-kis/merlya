# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.6.3] - 2025-12-10

### Added
- **MCP (Model Context Protocol) integration** for external tool servers
  - `/mcp add|remove|list|show|test|tools|examples` commands
  - Stdio server support with environment variable templating
  - Secret resolution via Merlya's keyring: `${GITHUB_TOKEN}` syntax
  - Default value syntax: `${VAR:-default}` for optional env vars
  - Tool discovery and invocation across multiple servers
  - Warning suppression for optional MCP capabilities (prompts/resources)
- **Mistral and Groq provider configuration**
  - Full `/model provider mistral` support
  - Full `/model provider groq` support
  - API key handling via keyring (`MISTRAL_API_KEY`, `GROQ_API_KEY`)
  - Router fallback configuration for both providers
- **PydanticAI agent improvements**
  - History processors for context window management
  - Tool call/return pairing validation
  - `@agent.system_prompt` for dynamic router context injection
  - `@agent.output_validator` for response coherence validation
  - `UsageLimits` for request/tool call limits
- **Centralized agent constants** in `config/constants.py`

### Changed
- **Dynamic tool call limits** based on task mode from router
  - Diagnostic: 100 calls (SSH investigation, log analysis)
  - Remediation: 50 calls (fixing, configuring)
  - Query: 30 calls (information gathering)
  - Chat: 20 calls (simple conversations)
- Improved error keyword detection with word boundaries (regex)
- Persistence failure logs elevated to `warning` level
- Hard fallback limit (100 messages) prevents unbounded history growth

### Fixed
- Missing `Implementation` type import in MCP manager
- Type annotations for history processor (`HistoryProcessor` alias)
- **Tool retry limit** increased to 3 (was 1) for elevation/credential flows
- Clearer system prompt guidance for privilege elevation workflow

## [0.6.2] - 2025-12-10

### Added
- **Slash command support in `merlya run`** - Execute internal commands directly without AI processing
  - Command classification: blocked, interactive, allowed
  - Blocked: `/exit`, `/quit`, `/new`, `/conv` (session control)
  - Interactive: `/hosts add`, `/ssh config`, `/secret set` (require user input)
  - Allowed: `/scan`, `/hosts list`, `/health`, `/model show`, etc.
- **English README** (`README_EN.md`) with link from French README
- **Documentation section** in CONTRIBUTING.md explaining merlya-docs workflow

## [0.6.1] - 2025-12-09

### Fixed
- API key loading from keyring in `merlya run` mode
- Harmonized CLI and REPL initialization for consistent context setup

## [0.6.0] - 2025-12-09

### Added
- **Non-interactive mode** (`merlya run`) for automation and CI/CD
  - Single command execution: `merlya run "Check disk space"`
  - Task file support (YAML/text): `merlya run --file tasks.yml`
  - JSON output format: `merlya run --format json`
  - Auto-confirmation: `merlya run --yes`
- **File transfer tools** for SSH operations
- **TOML import** for hosts with jump_host/bastion support
- CODE_OF_CONDUCT, CODEOWNERS, GitHub templates (issues/PR)

### Changed
- README rewritten for public release
- CI hardened on GitHub runners (lint + format + mypy + tests + Bandit + pip-audit + build)
- Release workflow migrated from self-hosted runners

## [0.5.6] - 2025-12-08

### Added

- **Multi-provider LLM support** via PydanticAI framework
  - OpenRouter, Anthropic, OpenAI, Ollama, LiteLLM, Groq providers
  - Seamless provider switching with `/model` command
- **Local intent classification** with ONNX models
  - Automatic tier detection based on available RAM
  - LLM fallback for edge cases
- **SSH connection pooling** with asyncssh
  - MFA/2FA support (TOTP, keyboard-interactive)
  - Jump host / bastion support
  - 10-minute connection reuse
- **Rich CLI interface** with markdown rendering
  - Autocompletion for commands and hosts
  - Syntax highlighting for code blocks
- **Host management** with `/hosts` command
  - Import from SSH config, /etc/hosts, Ansible inventories
  - Tag-based organization
  - Automatic enrichment on connection
- **Health checks** at startup
  - RAM, disk space, SSH, keyring, web search verification
  - Graceful degradation with warnings
- **i18n support** for English and French
- **Security features**
  - Credential storage in system keyring
  - Input validation with Pydantic
  - Permission management for elevated commands

### Infrastructure

- CI/CD with GitHub Actions
- Security scanning with Bandit and pip-audit
- Type checking with mypy (strict mode)
- Test coverage target: 80%+
- Trusted publishing to PyPI via OIDC

### Documentation

- Complete README with installation and usage examples
- CONTRIBUTING guidelines with SOLID principles
- SECURITY policy with vulnerability reporting process
- Architecture Decision Records (ADR)

[0.5.6]: https://github.com/m-kis/merlya/releases/tag/v0.5.6
