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
| Interactive REPL | :white_check_mark: | 0.1.0 |
| Multi-LLM support (OpenRouter, Anthropic, OpenAI, Ollama) | :white_check_mark: | 0.1.0 |
| SSH execution with connection pooling | :white_check_mark: | 0.1.0 |
| Host discovery (SSH config, /etc/hosts) | :white_check_mark: | 0.1.0 |
| Slash commands system | :white_check_mark: | 0.1.0 |
| Host validation (anti-hallucination) | :white_check_mark: | 0.1.0 |
| Risk assessment for commands | :white_check_mark: | 0.1.0 |
| AutoGen multi-agent orchestration | :white_check_mark: | 0.1.0 |
| FalkorDB knowledge graph | :white_check_mark: | 0.1.0 |

---

## Phase 2: Production Polish :white_check_mark:

**Goal:** Production-ready UI and installation

| Feature | Status | Version | Issue |
|---------|--------|---------|-------|
| Spinners for long operations | :white_check_mark: | 0.2.0 | |
| Progress bars (multi-host scan) | :white_check_mark: | 0.2.0 | |
| Verbosity levels (`/log level`) | :white_check_mark: | 0.3.0 | |
| `merlya --version` | :white_check_mark: | 0.1.1 | |
| PyPI publication | :white_check_mark: | 0.3.0 | [#16](https://github.com/m-kis/merlya/issues/16) |
| Docker image | :hourglass: | 0.4.0 | [#17](https://github.com/m-kis/merlya/issues/17) |

---

## Phase 3: Secrets & Configuration :white_check_mark:

**Goal:** Secure credential and configuration management

| Feature | Status | Version |
|---------|--------|---------|
| Persistent secrets (`/secret`) | :white_check_mark: | 0.3.0 |
| System keyring integration | :white_check_mark: | 0.3.0 |
| Encrypted file fallback | :white_check_mark: | 0.3.0 |
| Embedding model persistence | :white_check_mark: | 0.3.0 |
| Task-specific model routing | :white_check_mark: | 0.3.0 |
| Comprehensive logging system | :white_check_mark: | 0.3.0 |

---

## Phase 4: Enhanced Execution :construction:

**Goal:** Advanced infrastructure management and IaC integration

| Feature | Status | Target | Issue |
|---------|--------|--------|-------|
| Session export/import | :hourglass: | 0.4.0 | [#21](https://github.com/m-kis/merlya/issues/21) |
| Ansible playbook execution | :hourglass: | 0.4.0 | [#18](https://github.com/m-kis/merlya/issues/18) |
| Terraform integration | :hourglass: | 0.4.0 | [#19](https://github.com/m-kis/merlya/issues/19) |
| Kubernetes support (kubectl) | :hourglass: | 0.4.0 | [#20](https://github.com/m-kis/merlya/issues/20) |
| Cloud providers (AWS, GCP, Azure) | :hourglass: | 0.5.0 | [#22](https://github.com/m-kis/merlya/issues/22) |
| Cloud provisioning APIs | :bulb: | 0.5.0 | [#39](https://github.com/m-kis/merlya/issues/39) |

---

## Phase 5: Variables & UX Improvements :hourglass:

**Goal:** Enhanced variable system and user experience

| Feature | Status | Target | Issue |
|---------|--------|--------|-------|
| Inline variable/secret setting in prompts | :hourglass: | 0.4.0 | [#40](https://github.com/m-kis/merlya/issues/40) |
| Bulk variable import from file | :hourglass: | 0.4.0 | [#41](https://github.com/m-kis/merlya/issues/41) |

---

## Phase 6: Knowledge & Learning :hourglass:

**Goal:** Learning from operations

| Feature | Status | Target | Issue |
|---------|--------|--------|-------|
| Incident pattern learning | :hourglass: | 0.5.0 | [#23](https://github.com/m-kis/merlya/issues/23) |
| Runbook generation | :hourglass: | 0.5.0 | [#24](https://github.com/m-kis/merlya/issues/24) |
| Anomaly detection | :bulb: | 0.6.0 | [#25](https://github.com/m-kis/merlya/issues/25) |
| Predictive alerts | :bulb: | 0.6.0 | [#26](https://github.com/m-kis/merlya/issues/26) |

---

## Phase 7: Enterprise :bulb:

**Goal:** Team and enterprise features

| Feature | Status | Target | Issue |
|---------|--------|--------|-------|
| Multi-user support | :bulb: | 1.0.0 | [#27](https://github.com/m-kis/merlya/issues/27) |
| RBAC (role-based access) | :bulb: | 1.0.0 | [#28](https://github.com/m-kis/merlya/issues/28) |
| Audit logging (compliance) | :bulb: | 1.0.0 | [#29](https://github.com/m-kis/merlya/issues/29) |
| SSO integration (SAML/OIDC) | :bulb: | 1.0.0 | [#30](https://github.com/m-kis/merlya/issues/30) |
| API server mode (REST/GraphQL) | :bulb: | 1.0.0 | [#31](https://github.com/m-kis/merlya/issues/31) |

---

## Version History

| Version | Date | Highlights |
|---------|------|------------|
| 0.3.0 | 2025-12-02 | Persistent secrets, logging system, PyPI release, task-specific model routing |
| 0.2.0 | 2025-11-28 | Production polish, spinners, smart triage |
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

1. **Executor integrations** - Ansible, Terraform, Kubernetes ([#18](https://github.com/m-kis/merlya/issues/18), [#19](https://github.com/m-kis/merlya/issues/19), [#20](https://github.com/m-kis/merlya/issues/20))
2. **Knowledge system** - Pattern learning, runbook generation ([#23](https://github.com/m-kis/merlya/issues/23), [#24](https://github.com/m-kis/merlya/issues/24))
3. **Docker image** - Containerized deployment ([#17](https://github.com/m-kis/merlya/issues/17))
4. **Cloud integrations** - AWS, GCP, Azure connectors ([#22](https://github.com/m-kis/merlya/issues/22))

### Feature Requests

Open an issue with the `enhancement` label:
https://github.com/m-kis/merlya/issues/new
