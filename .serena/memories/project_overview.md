# Merlya - Project Overview

## Purpose
AI-powered infrastructure assistant CLI for DevOps/SysAdmins. Manages servers via SSH through natural language commands.

## Tech Stack
- Python 3.13, PydanticAI, asyncssh, prompt_toolkit, loguru, SQLite (aiosqlite), keyring
- LLM providers: OpenRouter (default), Anthropic, OpenAI, Mistral, Groq, Ollama
- Tools: ruff (lint/format), mypy, pytest, bandit, pip-audit

## Key Commands
- Run: `merlya` or `python -m merlya.cli.run`
- Lint: `ruff check merlya/`
- Format check: `ruff format --check merlya/`
- Type check: `mypy merlya/`
- Tests: `pytest tests/ --cov=merlya --cov-report=term-missing`

## Architecture
- REPL (repl/loop.py) → Router (router/) → MerlyaAgent (agent/main.py) → PydanticAI tools
- SSH Pool (ssh/pool.py) with CircuitBreaker (ssh/circuit_breaker.py)
- SQLite persistence (persistence/), keyring secrets (secrets/)
- Dual mode: DIAGNOSTIC (read-only) / CHANGE (mutations via IaC pipelines)
- i18n: fr/en (i18n/)

## Important Notes
- Two parallel agent systems: MerlyaAgent (active) and Orchestrator (vestigial)
- Centers (centers/) are defined but not in main execution path
- Multiple overlapping loop-prevention mechanisms (see architecture_issues.md)
