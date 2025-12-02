# Merlya Roadmap

## Current Version: 0.3.0

### Legend

- :white_check_mark: Done
- :construction: In Progress
- :hourglass: Planned
- :bulb: Idea/Future

---

## Phase 1: Core Foundation :white_check_mark:

**Goal:** Working CLI with basic infrastructure management

| Feature | Status | Version |
|---------|--------|---------|
| Interactive REPL with 48 slash commands | :white_check_mark: | 0.1.0 |
| Multi-LLM support (OpenRouter, Anthropic, OpenAI, Ollama) | :white_check_mark: | 0.1.0 |
| SSH execution with connection pooling | :white_check_mark: | 0.1.0 |
| Host discovery (SSH config, /etc/hosts) | :white_check_mark: | 0.1.0 |
| Host validation (anti-hallucination) | :white_check_mark: | 0.1.0 |
| Risk assessment for commands | :white_check_mark: | 0.1.0 |
| AutoGen 0.7+ multi-agent orchestration | :white_check_mark: | 0.1.0 |
| FalkorDB knowledge graph (optional) | :white_check_mark: | 0.1.0 |

---

## Phase 2: Production Polish :white_check_mark:

**Goal:** Production-ready UI and installation

| Feature | Status | Version | Issue |
|---------|--------|---------|-------|
| Spinners for long operations | :white_check_mark: | 0.2.0 | |
| Progress bars (multi-host scan) | :white_check_mark: | 0.2.0 | |
| Verbosity levels (`/log level`) | :white_check_mark: | 0.3.0 | |
| Log management (`/log show`, `/log tail`) | :white_check_mark: | 0.3.0 | |
| `merlya --version` | :white_check_mark: | 0.1.1 | |
| PyPI publication | :white_check_mark: | 0.3.0 | [#16](https://github.com/m-kis/merlya/issues/16) |
| Docker image | :hourglass: | 0.4.0 | [#17](https://github.com/m-kis/merlya/issues/17) |

---

## Phase 3: Secrets & Configuration :white_check_mark:

**Goal:** Secure credential and configuration management

| Feature | Status | Version |
|---------|--------|---------|
| Persistent secrets (`/secret`) | :white_check_mark: | 0.3.0 |
| System keyring integration (macOS/Windows/Linux) | :white_check_mark: | 0.3.0 |
| Encrypted file fallback | :white_check_mark: | 0.3.0 |
| Session secrets with TTL (`/variables set-secret`) | :white_check_mark: | 0.2.0 |
| Embedding model persistence | :white_check_mark: | 0.3.0 |
| Task-specific model routing | :white_check_mark: | 0.3.0 |

---

## Phase 4: Infrastructure Scanning :white_check_mark:

**Goal:** Comprehensive infrastructure visibility

| Feature | Status | Version |
|---------|--------|---------|
| Local machine scanner (12h TTL, SQLite) | :white_check_mark: | 0.2.0 |
| JIT on-demand remote scanning | :white_check_mark: | 0.2.0 |
| Smart cache with fingerprint validation | :white_check_mark: | 0.2.0 |
| Host registry with metadata | :white_check_mark: | 0.2.0 |
| Permission detection and caching | :white_check_mark: | 0.2.0 |

---

## Phase 5: Agent System :white_check_mark:

**Goal:** Multi-agent AI orchestration

| Feature | Status | Version |
|---------|--------|---------|
| BaseAgent with dependency injection | :white_check_mark: | 0.1.0 |
| SentinelAgent (security monitoring) | :white_check_mark: | 0.2.0 |
| DiagnosticAgent (root cause analysis) | :white_check_mark: | 0.2.0 |
| RemediationAgent (action execution) | :white_check_mark: | 0.2.0 |
| ProvisioningAgent (infrastructure) | :white_check_mark: | 0.2.0 |
| MonitoringAgent (health checks) | :white_check_mark: | 0.2.0 |
| CoordinatorAgent (multi-agent teams) | :white_check_mark: | 0.2.0 |
| ChainOfThoughtAgent (reasoning) | :white_check_mark: | 0.2.0 |

---

## Phase 6: Executors :white_check_mark:

**Goal:** Multiple execution backends

| Feature | Status | Version |
|---------|--------|---------|
| SSH executor with pooling | :white_check_mark: | 0.1.0 |
| Ansible playbook executor | :white_check_mark: | 0.2.0 |
| Terraform executor (plan/apply/destroy) | :white_check_mark: | 0.2.0 |
| Kubernetes executor (kubectl) | :white_check_mark: | 0.2.0 |
| AWS executor | :white_check_mark: | 0.2.0 |
| Docker executor | :white_check_mark: | 0.2.0 |
| Auto-corrector (error suggestions) | :white_check_mark: | 0.2.0 |

---

## Phase 7: Triage & Classification :white_check_mark:

**Goal:** Intelligent request handling

| Feature | Status | Version |
|---------|--------|---------|
| AI-based triage (LLM) | :white_check_mark: | 0.2.0 |
| Embedding-based triage (sentence-transformers) | :white_check_mark: | 0.2.0 |
| Keyword-based fallback | :white_check_mark: | 0.1.0 |
| Priority levels (P0-P3) | :white_check_mark: | 0.1.0 |
| Intent classification (QUERY/ACTION/ANALYSIS) | :white_check_mark: | 0.2.0 |
| Feedback system (`/feedback`) | :white_check_mark: | 0.2.0 |

---

## Phase 8: CI/CD Integration :white_check_mark:

**Goal:** DevOps workflow integration

| Feature | Status | Version |
|---------|--------|---------|
| GitHub Actions adapter | :white_check_mark: | 0.2.0 |
| Workflow management (`/cicd`) | :white_check_mark: | 0.2.0 |
| Failure analysis with embeddings | :white_check_mark: | 0.2.0 |
| Learning engine (pattern recognition) | :white_check_mark: | 0.2.0 |
| Debug workflow (`/debug-workflow`) | :white_check_mark: | 0.2.0 |
| Extensible platform registry | :white_check_mark: | 0.2.0 |

---

## Phase 9: Knowledge & Learning :construction:

**Goal:** Learning from operations

| Feature | Status | Target | Issue |
|---------|--------|--------|-------|
| FalkorDB incident memory | :white_check_mark: | 0.2.0 | |
| Pattern learning from incidents | :white_check_mark: | 0.2.0 | |
| CVE vulnerability tracking | :white_check_mark: | 0.2.0 | |
| Web search integration | :white_check_mark: | 0.2.0 | |
| Enhanced incident pattern learning | :hourglass: | 0.5.0 | [#23](https://github.com/m-kis/merlya/issues/23) |
| Automatic runbook generation | :hourglass: | 0.5.0 | [#24](https://github.com/m-kis/merlya/issues/24) |
| Anomaly detection | :bulb: | 0.6.0 | [#25](https://github.com/m-kis/merlya/issues/25) |
| Predictive alerts | :bulb: | 0.6.0 | [#26](https://github.com/m-kis/merlya/issues/26) |

---

## Phase 10: Enhanced UX :hourglass:

**Goal:** Improved user experience

| Feature | Status | Target | Issue |
|---------|--------|--------|-------|
| Session export/import | :hourglass: | 0.4.0 | [#21](https://github.com/m-kis/merlya/issues/21) |
| Inline variable/secret setting | :hourglass: | 0.4.0 | [#40](https://github.com/m-kis/merlya/issues/40) |
| Bulk variable import from file | :hourglass: | 0.4.0 | [#41](https://github.com/m-kis/merlya/issues/41) |

---

## Phase 11: Cloud & Provisioning :hourglass:

**Goal:** Cloud infrastructure management

| Feature | Status | Target | Issue |
|---------|--------|--------|-------|
| Cloud providers (AWS, GCP, Azure) | :hourglass: | 0.5.0 | [#22](https://github.com/m-kis/merlya/issues/22) |
| Cloud provisioning APIs | :bulb: | 0.5.0 | [#39](https://github.com/m-kis/merlya/issues/39) |

---

## Phase 12: Enterprise :bulb:

**Goal:** Team and enterprise features

| Feature | Status | Target | Issue |
|---------|--------|--------|-------|
| Multi-user support | :bulb: | 1.0.0 | [#27](https://github.com/m-kis/merlya/issues/27) |
| RBAC (role-based access) | :bulb: | 1.0.0 | [#28](https://github.com/m-kis/merlya/issues/28) |
| Audit logging (compliance) | :bulb: | 1.0.0 | [#29](https://github.com/m-kis/merlya/issues/29) |
| SSO integration (SAML/OIDC) | :bulb: | 1.0.0 | [#30](https://github.com/m-kis/merlya/issues/30) |
| API server mode (REST/GraphQL) | :bulb: | 1.0.0 | [#31](https://github.com/m-kis/merlya/issues/31) |

---

## Current Implementation Summary

### Fully Implemented (v0.3.0)

| Category | Count | Details |
|----------|-------|---------|
| Slash Commands | 48 | Full REPL command system |
| Agents | 15 | Multi-agent orchestration |
| Executors | 10 | SSH, Ansible, Terraform, K8s, AWS, Docker |
| Scanners | 14 | Local and remote scanning |
| Tools | 34+ | System, file, infra, security, CI/CD, web |
| Domain Services | 14 | Analysis, planning, synthesis, codegen |

### Code Statistics

- **Python Files**: 296
- **Lines of Code**: ~50,000+
- **Test Coverage**: Active CI with pytest

---

## Version History

| Version | Date | Highlights |
|---------|------|------------|
| 0.3.0 | 2025-12-02 | Persistent secrets, logging system, PyPI release, task-specific model routing |
| 0.2.0 | 2025-11-28 | Production polish, agents, executors, triage, CI/CD |
| 0.1.0 | 2025-11-26 | Initial release |

---

## Quick Links

- [Open Issues](https://github.com/m-kis/merlya/issues)
- [PyPI Package](https://pypi.org/project/merlya/)
- [Changelog](CHANGELOG.md)

---

## How to Contribute

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Priority Areas

1. **Docker image** - Containerized deployment ([#17](https://github.com/m-kis/merlya/issues/17))
2. **Session export/import** - Backup and restore ([#21](https://github.com/m-kis/merlya/issues/21))
3. **Knowledge system** - Pattern learning, runbook generation ([#23](https://github.com/m-kis/merlya/issues/23), [#24](https://github.com/m-kis/merlya/issues/24))
4. **Cloud integrations** - AWS, GCP, Azure connectors ([#22](https://github.com/m-kis/merlya/issues/22))

### Feature Requests

Open an issue with the `enhancement` label:
<https://github.com/m-kis/merlya/issues/new>
