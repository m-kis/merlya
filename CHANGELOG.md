# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.2] - 2025-02-19

### Added

- SSH circuit breaker surfaced to the agent with retry messaging to avoid command storms.
- System health/startup checks now cover MCP servers, skills registry, ONNX readiness, and tier-aware parser initialization.
- CLI `/hosts check` now records host health status and captures OS info on success.

### Changed

- Refactored agent tool registration into dedicated modules (system, files, MCP) to keep modules under 600 LOC.
- System tools package reorganized into submodules with backward-compatible proxies for `ssh_execute` patching in tests.
- Router target clarification prompts ensure ambiguous execution requests pick local vs inventory hosts before using tools.
- Permissions heuristics expanded (journalctl/dmesg, more log paths) with hardened sudo/doas prefix stripping.

### Fixed

- `ssh_execute` now auto-elevates when permission errors are returned in stdout or when privileged commands fail silently.
- Cron schedule validation tightened to reject injection attempts and malformed specs.
- Fast-path detection avoids treating PID queries as host lookups; JSON serialization handles objects exposing `to_dict()`.
- MCP command testing reports `TimeoutError` correctly; `doas` elevation no longer embeds passwords in the command string.

## [0.7.1] - 2025-12-12

### Added

- **Proactive Agent Mode** (`merlya/agent/main.py`)
  - Agent never blocks because of missing inventory/config
  - Discovers resources dynamically and proposes alternatives
  - Inventory is now optional - agent works without pre-configured hosts
  - New `unresolved_hosts` field in RouterResult for proactive discovery

- **Bash Tool** (`merlya/tools/core/tools.py`)
  - New `bash` tool for local command execution
  - Universal fallback for CLI tools (kubectl, aws, docker, gcloud, etc.)
  - Dangerous command blocklist for safety
  - Proper timeout and secret handling

- **Mistral and Groq in Setup Wizard** (`merlya/setup/wizard.py`)
  - Added Mistral (mistral-large-latest) as option 4
  - Added Groq (llama-3.3-70b-versatile) as option 5
  - Ollama moved to option 6

### Fixed

- **Ctrl+C handling in prompts** (`merlya/ui/console.py`)
  - KeyboardInterrupt now properly converted to CancelledError
  - Fixes "Task exception was never retrieved" error on Ctrl+C
  - All async prompt methods (prompt, prompt_secret, prompt_confirm, prompt_choice) updated

- **SSH execute permissive mode**
  - Hosts not in inventory can now be connected directly
  - Agent tries direct connection instead of failing immediately

### Changed

- **System prompt** completely rewritten with proactive philosophy
  - "NEVER SAY I can't because X is not configured"
  - Clear guidelines for bash vs ssh_execute usage
  - Zero-config mode documentation

## [0.7.2] - 2025-12-13

### Added

- **New System Tools** (`merlya/tools/system/`)
  - Network: `check_network`, `check_port`, `dns_lookup`, `ping`, `traceroute`
  - Services: `list_services`, `manage_service` (systemd/init support)
  - Health: `health_summary` for quick host health check
  - Logs: `grep_logs`, `tail_logs` with journalctl support
  - Cron: `list_cron`, `add_cron`, `remove_cron`

- **MCP Tool Schema Exposure** (`merlya/mcp/manager.py`, `merlya/agent/tools.py`)
  - LLM now sees full parameter schemas for MCP tools
  - `list_mcp_tools` returns required/optional parameters
  - Improved `call_mcp_tool` docstring with Context7 usage pattern

- **Enhanced `/scan` Command** (`merlya/commands/handlers/system.py`)
  - `--services`: Include running services list
  - `--network`: Include network diagnostics
  - `health_summary` added to default system scan

- **SSH Verification Hints** (`merlya/tools/core/verification.py`)
  - State-changing commands return verification suggestions
  - Agent can confirm actions succeeded (e.g., service restart)

### Fixed

- **MCP Deadlock** (`merlya/mcp/manager.py`)
  - Fix deadlock in `_ensure_connected` by calling `_ensure_group` before acquiring lock
  - `asyncio.Lock()` is not reentrant, caused hang on MCP tool calls

- **MCP Environment Variables** (`merlya/mcp/manager.py`)
  - Custom env vars now merged with `get_default_environment()` instead of replacing
  - Fixes missing PATH causing `npx` and other executables not found

- **MCP Auto-Test** (`merlya/commands/handlers/mcp.py`)
  - `/mcp add` now automatically tests connection after adding
  - `--no-test` flag to skip auto-test
  - Better error messages for timeout, missing env vars

### Changed

- **SSH Module Refactoring** (`merlya/tools/core/`)
  - Split `ssh.py` into focused modules: connection, elevation, patterns, errors
  - Better separation of concerns
  - Improved error handling and password security

## [Unreleased]

### Fixed

- **SSH key passphrase retry** (`merlya/ssh/auth.py`)
  - Wrong passphrase no longer stored in keyring
  - User gets 3 attempts before failing
  - Better detection of "wrong passphrase" vs "invalid key format" errors
  - Wrong cached passphrase is cleared on failure

### Added

- **@hostname Resolution** (`merlya/tools/core/tools.py`)
  - `@pine64` in commands now resolved to actual hostname/IP
  - Resolution order: inventory → DNS → user prompt
  - Follows sysadmin logic for unknown hosts
  - Works in both `ssh_execute` and `bash` tools

- **Session Message Persistence**
  - Messages now persisted to SQLite for session resumption
  - Full conversation history restored on `/session load`
  - Automatic trimming to MAX_MESSAGES_IN_MEMORY on load

- **Loop Detection** (`merlya/agent/history.py`)
  - Detects repetitive tool call patterns
  - Three detection modes: same call repeated, consecutive identical calls, alternating patterns
  - Injects "loop breaker" system message to redirect agent
  - Configurable thresholds: LOOP_DETECTION_WINDOW=10, LOOP_THRESHOLD_SAME_CALL=3

- **Secret References in Commands**
  - Commands can contain `@secret-name` references (e.g., `@db-password`)
  - Secrets auto-resolved from keyring at execution time
  - Safe logging: actual values never appear in logs
  - New SECRET_PATTERN for structured keys like `@service:host:field`

- **Observability Status API** (`merlya/audit/`)
  - `get_observability_status()` returns Logfire/SQLite backend status
  - Used in `/audit stats` for cleaner status display

- **Host Metadata Update** (`merlya/persistence/repositories.py`)
  - `update_metadata()` for efficient partial host updates
  - Used by elevation system to persist capabilities

### Changed

- **Elevation System Refactoring** (`merlya/security/permissions.py`)
  - Priority-based method selection: sudo NOPASSWD > doas > sudo_with_password > su
  - Passwords stored in system keyring (macOS Keychain, Linux Secret Service)
  - Returns `@elevation:host:password` references instead of raw values
  - Detection already determines if password needed; no retry logic
  - Added `store_password()`, `clear_cache()` methods

- **Agent System Prompt** (`merlya/agent/main.py`)
  - BE DIRECT: Try most obvious path first
  - TRUST USER HINTS: Use location hints immediately
  - ONE COMMAND IS BETTER: Prefer direct commands over exploration
  - Auto-elevation documented: no manual `request_elevation` needed
  - Security: Forbidden plaintext password patterns documented

- **Tool Call Limits** (`merlya/config/constants.py`)
  - Raised limits as failsafes only (loop detection handles safety)
  - TOOL_CALLS_LIMIT_DIAGNOSTIC: 200
  - REQUEST_LIMIT_DIAGNOSTIC: 300

### Fixed

- **Thread-Safety** (`merlya/mcp/manager.py`, `merlya/ssh/pool.py`)
  - SSHPool: Changed from asyncio.Lock to threading.Lock for singleton
  - MCPManager: Added threading.Lock guard for lazy asyncio.Lock creation
  - suppress_mcp_capability_warnings() now only suppresses MCP-related loggers

- **Parser Improvements** (`merlya/parser/`)
  - IPv4 validation: reject octets > 255
  - Better incident detection with minimum confidence threshold
  - Check initialize() return value before proceeding

- **Security Improvements**
  - Path canonicalization in SSH key audit (prevent traversal)
  - Variables import: reject symlinks, world-writable files
  - Removed /tmp from allowed import directories
  - Case-insensitive health_status comparison

- **PydanticAI Tool Docstrings**
  - Removed `ctx: Run context.` from all tool docstrings
  - Improves tool description extraction for LLM

### Security

- **Plaintext Password Detection**: `detect_unsafe_password()` warns about embedded passwords
- **Credential References**: `request_credentials()` returns `@service:host:field` references
- **Elevation Password Security**: Never stored in memory, always in keyring with `@` references

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

[Unreleased]: https://github.com/m-kis/merlya/compare/v0.7.2...HEAD
[0.7.2]: https://github.com/m-kis/merlya/compare/v0.7.1...v0.7.2
[0.7.1]: https://github.com/m-kis/merlya/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/m-kis/merlya/releases/tag/v0.7.0
[0.6.3]: https://github.com/m-kis/merlya/releases/tag/v0.6.3
[0.6.2]: https://github.com/m-kis/merlya/releases/tag/v0.6.2
[0.6.1]: https://github.com/m-kis/merlya/releases/tag/v0.6.1
[0.6.0]: https://github.com/m-kis/merlya/releases/tag/v0.6.0
[0.5.6]: https://github.com/m-kis/merlya/releases/tag/v0.5.6
