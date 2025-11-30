# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Comprehensive test suite for inventory system (79 tests)
  - LLM sanitizer tests: prompt injection protection, PII redaction
  - Relation heuristics tests: cluster, replica, group, service detection
  - E2E integration tests: complete workflows (parse, import, export, search)
  - Performance tests: 10k host bulk import validation
- Thread-safe singleton pattern for inventory parser
- Graceful LLM fallback with interactive user prompts on parse failures
- Pagination support for inventory queries (LIMIT/OFFSET)
- Credential audit trail hooks (repository level)

### Fixed

- Thread safety race condition in InventoryParser singleton
- LLM parser blocking on failure (now offers fallback options)
- Memory exhaustion on large inventories (added pagination)

### Security

- Comprehensive security audit of credential management system (Grade A-)
- In-memory only credential storage (never persisted)
- Type separation for HOST, CONFIG, SECRET credentials
- LLM leak prevention via resolve_secrets flag

### Documentation

- Deep analysis document (INVENTORY_DEEP_ANALYSIS.md)
- UX refactor proposal (INVENTORY_UX_REFACTOR_PROPOSAL.md)
- Security audit report (SECURITY_AUDIT_CREDENTIALS.md)
- Execution summary (EXECUTION_SUMMARY.md)
