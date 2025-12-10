# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
