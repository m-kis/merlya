# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Persistent Secure Secret Storage** (`/secret` command)
  - Secure secrets stored using system keyring (macOS Keychain, Windows Credential Locker, Linux SecretService)
  - Fallback to encrypted file storage when keyring unavailable
  - Secrets persist across sessions and survive restarts
  - Commands: `/secret set`, `/secret get`, `/secret list`, `/secret delete`
  - Use `@secret_name` in queries to reference secrets
- **Embedding Model Persistence**
  - Embedding model choice saved to `~/.merlya/config.json`
  - Survives restarts without requiring environment variables
  - Priority: env var > config file > default
  - Supports custom HuggingFace models
- **Task-Specific Model Routing**
  - Configure different models for different task types
  - `correction`: Quick fixes (use fast/cheap model like haiku)
  - `planning`: Complex reasoning (use powerful model like opus)
  - `synthesis`: General tasks (use balanced model like sonnet)
  - Commands: `/model task set <task> <model>`
- Interactive inventory setup wizard (`/inventory setup`)
  - Guides first-time users through host and SSH key configuration
  - Auto-detects existing SSH keys and prompts for passphrase
- Quick-add command for hosts (`/inventory quick-add`)
  - Minimal prompts for fast host addition
  - Supports comma-separated batch additions
- Fallback responses for empty agent outputs
  - Provides actionable guidance when no hosts configured
  - Context-aware messages based on query type

### Fixed

- **Report Display Issue**: Web search and analysis reports now display content
  - `save_report` returns actual content instead of just success message
  - Report content captured and displayed in response synthesis
  - Large reports (>500 chars) returned directly without re-synthesis
- **Application Exit Hanging**: Fixed ThreadPoolExecutor not shutting down
  - Added `shutdown_persistence_executor()` with `atexit` handler
  - Proper cleanup on REPL exit prevents hanging threads
- **CRITICAL**: Agent TERMINATE without response issue
  - Agents now provide meaningful summaries before terminating
  - Improved response extraction handles edge cases
  - Empty responses trigger helpful fallback messages
- SSH passphrase detection code duplication
  - Consolidated `_key_needs_passphrase()` into canonical `check_key_needs_passphrase()`
  - Removed duplicate implementation from inventory manager
  - Added `skip_validation` parameter for pre-validated paths
- SSH scanner credential resolution
  - Uses unified `resolve_ssh_for_host()` for consistent behavior
  - Better error messages for passphrase requirements
  - Checks passphrase availability before connection attempt

### Improved

- SSH scanner error messages with actionable guidance
- Inventory command help restructured for better UX
- Engineer prompt with clearer termination rules

- Optional services status display at CLI startup
  - Shows availability of FalkorDB, Web Search (DDGS), Smart Triage (Embeddings)
  - Provides installation hints for missing optional dependencies
- Added `beautifulsoup4` as explicit dependency for web content parsing
- Comprehensive test suite for SessionCommandHandler (22 tests)
  - Conversation ID validation tests (path traversal, special chars, length)
  - Edge case tests (empty list, exceptions, cancellation handling)
  - Security tests for /check, /load, /delete commands
- Comprehensive test suite for inventory system (82 tests)
  - LLM sanitizer tests: prompt injection protection, PII redaction
  - Relation heuristics tests: cluster, replica, group, service detection
  - E2E integration tests: complete workflows (parse, import, export, search)
  - Performance tests: 10k host bulk import, N+1 query validation
- Thread-safe singleton pattern for inventory parser
- Graceful LLM fallback with interactive user prompts on parse failures
- Pagination support for inventory queries (LIMIT/OFFSET)
- Credential audit trail hooks (repository level)
- Session credential TTL (15 minutes auto-expiration)
- Plaintext credential detection with security warnings
- Audit logging for secret variable access
- Database indices for groups, aliases, and status fields

### Fixed

- FalkorDB readiness check now actually connects instead of only checking flag
  - `get_falkordb_client()` was returning a client without calling `connect()`
  - Added `auto_connect` parameter to `get_falkordb_client()` for lazy initialization
  - Added `reset_falkordb_client()` helper for testing
- SessionCommandHandler security and robustness improvements
  - Conversation ID validation to prevent path traversal attacks
  - Global exception handling in /conversations command
  - Safe string conversion for timestamp fields
  - Improved error recovery in /compact command
- Thread safety race condition in InventoryParser singleton
- LLM parser blocking on failure (now offers fallback options)
- Memory exhaustion on large inventories (added pagination)
- N+1 query problem in batch relation inserts (now uses single batched query)

### Security

- Comprehensive security audit of credential management system (Grade A-)
- In-memory only credential storage (never persisted)
- Type separation for HOST, CONFIG, SECRET credentials
- LLM leak prevention via resolve_secrets flag
- Automatic credential expiration (CREDENTIAL_TTL = 900s)
- Plaintext credential detection (7 patterns: password, api_key, token, etc.)
- Secret access audit logs for compliance tracking

### Documentation

- Deep analysis document (INVENTORY_DEEP_ANALYSIS.md)
- UX refactor proposal (INVENTORY_UX_REFACTOR_PROPOSAL.md)
- Security audit report (SECURITY_AUDIT_CREDENTIALS.md)
- Execution summary (EXECUTION_SUMMARY.md)
