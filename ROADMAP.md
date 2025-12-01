# Merlya Roadmap

## Current Version: 0.1.0

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

---

## Phase 2: Production Polish :construction:

**Goal:** Production-ready UI and installation

| Feature | Status | Target |
|---------|--------|--------|
| Spinners for long operations | :construction: | 0.2.0 |
| Progress bars (multi-host scan) | :hourglass: | 0.2.0 |
| Clean debug output (verbosity levels) | :hourglass: | 0.2.0 |
| `merlya --version` | :white_check_mark: | 0.1.1 |
| PyPI publication | :hourglass: | 0.2.0 |
| Docker image | :hourglass: | 0.2.0 |

---

## Phase 3: Enhanced Features :hourglass:

**Goal:** Advanced infrastructure management

| Feature | Status | Target |
|---------|--------|--------|
| Session export/import | :hourglass: | 0.3.0 |
| Ansible playbook execution | :hourglass: | 0.3.0 |
| Terraform integration | :hourglass: | 0.3.0 |
| Kubernetes support (kubectl) | :hourglass: | 0.3.0 |
| Cloud providers (AWS, GCP, Azure) | :hourglass: | 0.3.0 |
| Persistent memory (cross-session) | :hourglass: | 0.3.0 |

---

## Phase 4: Knowledge & Learning :bulb:

**Goal:** Learning from operations

| Feature | Status | Target |
|---------|--------|--------|
| FalkorDB knowledge graph | :white_check_mark: | 0.1.0 |
| Incident pattern learning | :hourglass: | 0.4.0 |
| Runbook generation | :bulb: | 0.4.0 |
| Anomaly detection | :bulb: | 0.5.0 |
| Predictive alerts | :bulb: | 0.5.0 |

---

## Phase 5: Enterprise :bulb:

**Goal:** Team and enterprise features

| Feature | Status | Target |
|---------|--------|--------|
| Multi-user support | :bulb: | 1.0.0 |
| RBAC (role-based access) | :bulb: | 1.0.0 |
| Audit logging (compliance) | :bulb: | 1.0.0 |
| SSO integration | :bulb: | 1.0.0 |
| API server mode | :bulb: | 1.0.0 |

---

## Version History

| Version | Date | Highlights |
|---------|------|------------|
| 0.1.0 | 2025-11-26 | Initial release |

---

## How to Contribute

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Priority Areas

1. **UI/UX improvements** - Spinners, progress bars, cleaner output
2. **Documentation** - User guides, API docs, examples
3. **Testing** - Unit tests, integration tests
4. **Cloud integrations** - AWS, GCP, Azure connectors

### Feature Requests

Open an issue with the `enhancement` label:
https://github.com/m-kis/merlya/issues/new
