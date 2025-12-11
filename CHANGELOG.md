# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.7.0] - 2025-12-11

### Added

#### Advanced Architecture (Sprints 1-8)

- **Parser Service** (`merlya/parser/`)
  - Tier-based backend selection (lightweight/balanced/performance)
  - HeuristicBackend: regex-based entity extraction (ReDoS protected)
  - ONNXParserBackend: NER model-based extraction
  - Parse incidents, logs, host queries, and commands
  - Pre-compiled patterns at module level for performance

- **Log Store** (`merlya/tools/logs/`)
  - `store_raw_log()`: Store command outputs with TTL
  - `get_raw_log()`: Retrieve complete log by ID
  - `get_raw_log_slice()`: Extract specific line ranges
  - `cleanup_expired_logs()`: Remove expired entries

- **Context Tools** (`merlya/tools/context/`)
  - `list_hosts_summary()`: Compact inventory overview
  - `get_host_details()`: Detailed info for single host
  - `list_groups()`: Tag-based host groupings
  - `get_infrastructure_context()`: Combined context for LLM

- **Session Manager** (`merlya/session/`)
  - `TokenEstimator`: Accurate token counting per model
  - `ContextTierPredictor`: ONNX-based complexity classification
  - `SessionSummarizer`: Hybrid ONNX + LLM summarization
  - `SessionManager`: Context window management

- **Policy System** (`merlya/config/policies.py`)
  - `PolicyConfig`: Configurable limits and safeguards
  - `PolicyManager`: Runtime policy enforcement
  - Auto context tier detection
  - Host count and token validation

- **Skills System** (`merlya/skills/`)
  - YAML-based skill definitions
  - `SkillRegistry`: Singleton for skill management
  - `SkillLoader`: Load from files and directories
  - `SkillExecutor`: Parallel execution with timeout
  - `SkillWizard`: Interactive skill creation (`/skill create`)
  - Built-in skills: incident_triage, disk_audit, log_analysis, fleet_check

- **Subagents** (`merlya/subagents/`)
  - `SubagentFactory`: Create ephemeral PydanticAI agents
  - `SubagentOrchestrator`: Parallel execution via asyncio.gather
  - Per-host result aggregation
  - Semaphore-based concurrency control

- **Fast Path Routing** (`merlya/router/handler.py`)
  - Direct database queries without LLM for simple intents
  - Fast path intents: host.list, host.details, group.list, skill.list, var.*
  - Skill-based routing with confidence threshold (0.6)
  - Automatic fallback to LLM agent

- **Audit Logging** (`merlya/audit/`)
  - `AuditLogger`: SQLite persistence + loguru output
  - Event types: command, skill, tool, destructive ops
  - Sensitive data sanitization (passwords, secrets)
  - TTL-based log retrieval

### Changed

- Database schema version bumped to v2 (automatic migration)
- `raw_logs` table: ON DELETE SET NULL for host_id
- `sessions` table: ON DELETE CASCADE for conversation_id
- SkillExecutor integrates with AuditLogger when enabled

### Fixed

- MCP test mock missing `show_server` method
- Parser backend import name (ONNXParserBackend)

### Security

- **Password cache TTL**: Elevation passwords expire after 30 minutes
- **Race condition protection**: Per-host asyncio.Lock in capability detection
- **Router identifier validation**: Blocks path traversal, empty, and overly long names
- **Input validation**: MAX_INPUT_SIZE limits for ReDoS protection
- **Pre-compiled regex patterns**: All patterns compiled at module level

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
- **Smart elevation without upfront password prompt**:
  - Try `su`/`sudo` without password first
  - Only prompt for password if elevation fails with authentication error
  - Consent cached per host (say "N" once, never asked again for that host)
  - Password cached in memory for session (never persisted to disk)

### Fixed
- Missing `Implementation` type import in MCP manager
- Type annotations for history processor (`HistoryProcessor` alias)
- **Context loss on long conversations**: increased history limits (50 default, 200 hard max)
- **Secret names not persisting**: `/secret list` now shows secrets after restart
  - Secret names are stored in `~/.merlya/secrets.json`
  - Keyring doesn't provide enumeration, so names must be tracked separately
- **Random exploration behavior**: added "Task Focus" instructions to system prompt
  - Clear DO/DON'T guidelines to prevent aimless directory exploration
  - Explicit "continue" behavior: resume from last step, don't restart
  - Examples of good vs bad behavior patterns
- **Timeout during user interaction**: removed global 120s timeout that killed `ask_user`
  - User interaction tools now wait indefinitely for user input
  - LLM providers use their own request timeouts
  - SSH commands use per-command timeout parameter
- **Secret resolution not working in commands**: `@secret-name` was not resolved
  - Fixed `SecretStore` singleton pattern (`_instance` was a dataclass field, not `ClassVar`)
  - Different parts of the app were getting different instances
  - Now properly uses `ClassVar` for true singleton behavior
- **Secret autocompletion**: Typing `@` now suggests secrets (in addition to hosts/variables)
- **Persistent SSH elevation capabilities**: Detected sudo/su/doas capabilities now persist
  - Stored in host metadata with 24h TTL
  - Avoids re-detection on every connection
  - Three-layer caching: in-memory → database → SSH probes
- **Better SSH error explanations**: Connection errors now include:
  - Human-readable symptom (e.g., "Connection timeout to 164.132.77.97")
  - Explanation of the cause
  - Suggested solutions (e.g., "Check VPN, try ping...")

### Security
- **CRITICAL: Secret leak to LLM fixed** - `@secret-name` references were resolved
  before sending to LLM, exposing passwords in plaintext
  - Secrets are now resolved only at execution time in `ssh_execute`
  - Logs show `@secret-name`, never actual values
  - LLM never sees secret values, only references
- **Secret resolution in commands** - `@secret-name` syntax in SSH commands
  - Automatically resolved from keyring at execution time
  - Safe logging with masked values
- **Auto-elevation on permission errors** - Merlya handles elevation automatically
  - Detects "Permission denied" errors and retries with elevation
  - Uses correct method per host (su/sudo/doas)
  - User confirmation before elevation
  - Removed `ModelRetry` dependency for elevation (more reliable)
- **Thread-safe SecretStore singleton** - Fixed race condition in multi-threaded scenarios
  - Double-checked locking pattern prevents duplicate instances
  - Atomic file writes for `~/.merlya/secrets.json` prevent data corruption
- **Tighter secret pattern regex** - Now excludes emails and URLs
  - `user@github.com` no longer matches as a secret reference
  - Only matches `@secret-name` at start of string or after whitespace/operators
- **Timezone-aware cache TTL** - Elevation capabilities cache uses UTC
  - Prevents 1-hour errors during DST transitions
  - Handles legacy naive timestamps gracefully

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
