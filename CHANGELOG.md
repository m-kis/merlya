# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
