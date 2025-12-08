# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- CODE_OF_CONDUCT, CODEOWNERS, templates GitHub (issues/PR) pour cadrer les contributions

### Changed
- README réécrit pour préparer l’ouverture publique (installation, qualité, CI/CD, sécurité)
- CI durcie sur runners GitHub (lint + format check + mypy + tests + Bandit + pip-audit + build) et workflow de release migré hors self-hosted

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
