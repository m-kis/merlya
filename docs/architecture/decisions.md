# Architecture Decisions

Key architectural decisions and their rationale.

## Overview

Merlya is built on a modular architecture designed for extensibility, security, and ease of use. Version 0.8.0 introduces the **DIAGNOSTIC/CHANGE center architecture** for intelligent routing between read-only investigation and controlled mutations.

```mermaid
graph TB
    subgraph "User Interface"
        CLI[CLI / REPL]
    end

    subgraph "Routing Layer"
        SmartExtractor[SmartExtractor<br/>Host Detection]
        CenterClassifier[CenterClassifier<br/>DIAGNOSTIC/CHANGE]
    end

    subgraph "Operational Centers"
        DiagCenter[DIAGNOSTIC Center<br/>Read-Only]
        ChangeCenter[CHANGE Center<br/>Mutations + HITL]
    end

    subgraph "Pipelines"
        Ansible[AnsiblePipeline]
        Terraform[TerraformPipeline]
        K8s[KubernetesPipeline]
        Bash[BashPipeline]
    end

    subgraph "Infrastructure"
        SSH[SSH Pool]
        Capabilities[Capability Detector]
    end

    subgraph "LLM Providers"
        Brain[Brain Model<br/>Reasoning]
        Fast[Fast Model<br/>Routing]
    end

    CLI --> SmartExtractor
    SmartExtractor --> CenterClassifier
    CenterClassifier -->|read-only| DiagCenter
    CenterClassifier -->|mutations| ChangeCenter
    DiagCenter --> SSH
    ChangeCenter --> Capabilities
    Capabilities --> Ansible
    Capabilities --> Terraform
    Capabilities --> K8s
    Capabilities --> Bash
    CenterClassifier --> Fast
    DiagCenter --> Brain
    ChangeCenter --> Brain
```

---

## ADR-001: PydanticAI for Agent Framework

**Status:** Accepted

**Context:** We needed a framework for building LLM-powered agents with tool calling capabilities.

**Decision:** Use PydanticAI as the agent framework.

**Rationale:**
- Type-safe with Pydantic models
- Native async support
- Clean tool definition API
- Multi-provider support
- Active development and community

**Consequences:**
- Dependency on PydanticAI
- Benefits from upstream improvements
- May need to adapt to API changes

---

## ADR-002: AsyncSSH for SSH Connections

**Status:** Accepted

**Context:** SSH connectivity is core to Merlya's functionality.

**Decision:** Use asyncssh for all SSH operations.

**Rationale:**
- Pure Python, no external dependencies
- Async-native for concurrent connections
- Full SSH2 protocol support
- Jump host support built-in
- Active maintenance

**Consequences:**
- Async-only API
- Connection pooling needed for performance
- Memory overhead for many connections

---

## ADR-003: Connection Pooling

**Status:** Accepted

**Context:** Frequent SSH connections are slow and resource-intensive.

**Decision:** Implement connection pooling with automatic cleanup.

**Rationale:**
- Avoid connection overhead for repeated commands
- Limit concurrent connections
- Automatic cleanup of idle connections
- Graceful shutdown handling

**Implementation:**
```python
class SSHPool:
    max_connections: int = 10
    idle_timeout: int = 300  # 5 minutes

    async def get_connection(host) -> SSHConnection
    async def release_connection(conn)
    async def cleanup_idle()
```

---

## ADR-004: Keyring for Credential Storage

**Status:** Accepted

**Context:** API keys and credentials need secure storage.

**Decision:** Use the system keyring (via `keyring` library).

**Rationale:**
- OS-level security (Keychain, Secret Service, Credential Manager)
- No plaintext secrets in config files
- Standard cross-platform solution
- Fallback to in-memory with warning

**Consequences:**
- Requires keyring backend on Linux
- May need user interaction for first-time setup
- Headless servers need alternative setup

---

## ADR-005: Local Intent Classification

**Status:** Superseded by ADR-013 (v0.8.0)

**Context:** Not all user inputs require LLM processing.

**Decision:** Use pattern-based local classifier for intent routing with LLM fallback.

**Note:** This ADR has been superseded by ADR-013 (DIAGNOSTIC/CHANGE Center Architecture) which provides a more sophisticated routing system with CenterClassifier.

---

## ADR-006: YAML Configuration with SQLite Storage

**Status:** Accepted

**Context:** Configuration needs to be human-readable and editable. Host inventory requires structured storage with querying capabilities.

**Decision:** Use YAML for configuration files and SQLite for host inventory.

**Rationale:**
- YAML: Human-friendly syntax, widely used in DevOps
- YAML: Native support for complex structures
- SQLite: Fast querying for host lookups
- SQLite: Supports tagging, filtering, and search
- SQLite: Single file, no server needed

**File Locations:**
- `~/.merlya/config.yaml` - Main configuration
- `~/.merlya/merlya.db` - Host inventory (SQLite)
- `~/.merlya/logs/` - Log files
- `~/.merlya/history` - Command history

**Configuration Example:**
```yaml
general:
  language: en
  log_level: info

model:
  provider: openrouter
  model: amazon/nova-2-lite-v1:free
```

---

## ADR-007: Plugin Architecture

**Status:** Proposed

**Context:** Users need to extend Merlya with custom tools.

**Decision:** Entry-point based plugin system.

**Rationale:**
- Standard Python packaging approach
- Easy distribution via PyPI
- Namespace isolation
- Lazy loading

**Proposed Interface:**
```python
# pyproject.toml
[project.entry-points."merlya.tools"]
my_tool = "my_package:MyTool"

# Implementation
class MyTool(MerlyaTool):
    name = "my_tool"
    description = "Does something useful"

    async def execute(self, params: dict) -> ToolResult:
        ...
```

---

## ADR-008: Loguru for Logging

**Status:** Accepted

**Context:** Debugging and monitoring require good logging with minimal configuration.

**Decision:** Use [loguru](https://github.com/Delgan/loguru) for logging.

**Rationale:**
- Zero-configuration out of the box
- Automatic rotation and retention
- Human-readable colored output for development
- Exception catching with full traceback
- Easy to use API (`logger.info()`, `logger.error()`)
- Async-safe

**Implementation:**
```python
from loguru import logger

logger.info("✅ Operation completed successfully")
logger.warning("⚠️ Connection retry required")
logger.error("❌ SSH connection failed: {error}", error=e)
```

**Log Levels:**
- DEBUG: Detailed execution flow
- INFO: Key operations and results
- WARNING: Recoverable issues
- ERROR: Failures requiring attention

**Emoji Convention:**
All log messages use emojis for visual clarity (see CONTRIBUTING.md).

---

## ADR-009: Multi-Provider LLM Support

**Status:** Accepted

**Context:** Users have different LLM provider preferences and cost constraints.

**Decision:** Abstract LLM provider interface with multiple implementations. OpenRouter as default for free tier access.

**Supported Providers:**
- OpenRouter (default) - 100+ models, free tier available
- OpenAI (GPT-4o, GPT-4o-mini)
- Anthropic (Claude 3.5 Sonnet, Haiku)
- Ollama (local models, no API key needed)

**Interface:**
```python
class LLMProvider(Protocol):
    async def generate(prompt: str) -> str
    async def generate_with_tools(prompt: str, tools: list) -> ToolCall
```

---

## ADR-010: Security Model

**Status:** Accepted

**Context:** Merlya executes commands on remote systems.

**Decision:** Implement defense-in-depth security model.

**Layers:**
1. **Credential Protection** - Keyring storage
2. **Command Review** - User confirmation for destructive commands
3. **Input Validation** - Pydantic models for all inputs
4. **Audit Logging** - All commands logged
5. **Principle of Least Privilege** - Minimal permissions

**Dangerous Command Detection:**
```python
DANGEROUS_PATTERNS = [
    r"rm\s+-rf",
    r"mkfs",
    r"dd\s+if=",
    r">\s*/dev/",
    r"chmod\s+777",
]
```

---

## ADR-011: Non-Interactive Mode Credential Handling

**Status:** Accepted (v0.7.8)

**Context:** When running in non-interactive mode (`merlya run --yes`), the agent cannot prompt users for credentials. Previously, this led to infinite retry loops when sudo/su commands required passwords.

**Decision:** Fail-fast with clear error messages when credentials are needed but cannot be obtained.

**Rationale:**

- Immediate failure prevents wasted API calls and timeouts
- Clear error messages guide users to proper solutions
- Three resolution paths documented: keyring, NOPASSWD, interactive mode
- `permanent_failure` flag tells agent to stop retrying

**Implementation:**
```python
# In request_credentials() and ssh_execute()
if ctx.auto_confirm and missing_credentials:
    return CommandResult(
        success=False,
        message="Cannot obtain credentials in non-interactive mode",
        data={
            "non_interactive": True,
            "permanent_failure": True,  # Signal: do not retry
        }
    )
```

**Solutions for users:**

1. Store credentials in keyring: `merlya secret set sudo:host:password`
2. Configure NOPASSWD sudo on target hosts
3. Run in interactive mode (without `--yes`)

**Consequences:**

- Clear failure instead of timeout loops
- Better CI/CD integration (fast failure)
- Requires pre-configuration for automated elevated commands

---

## ADR-012: ElevationMethod Enum for Host Configuration

**Status:** Accepted (v0.7.8)

**Context:** Elevation method was stored as strings with inconsistent validation, causing NULL values and validation errors.

**Decision:** Use `ElevationMethod` enum with explicit values and proper NULL handling.

**Enum Values:**
```python
class ElevationMethod(str, Enum):
    NONE = "none"              # No elevation
    SUDO = "sudo"              # sudo (NOPASSWD)
    SUDO_PASSWORD = "sudo_password"  # sudo with password
    DOAS = "doas"              # doas (NOPASSWD)
    DOAS_PASSWORD = "doas_password"  # doas with password
    SU = "su"                  # su with password
```

**Handling:**

- NULL in database → `ElevationMethod.NONE`
- Invalid strings → `ElevationMethod.NONE`
- `/hosts edit` uses enum mapping
- Import (TOML/CSV) maps strings to enum values

**Consequences:**

- Type-safe elevation configuration
- No more validation errors on NULL
- Consistent behavior across all code paths

---

## ADR-013: DIAGNOSTIC/CHANGE Center Architecture

**Status:** Accepted (v0.8.0)

**Context:** Merlya needed a clear separation between read-only investigation and state-changing operations to improve safety and provide appropriate guardrails for each type of operation.

**Decision:** Implement two operational centers with different security models:

| Center | Purpose | Risk Level | HITL Required |
|--------|---------|------------|---------------|
| **DIAGNOSTIC** | Read-only investigation | LOW | No |
| **CHANGE** | Controlled mutations | HIGH | Yes |

**DIAGNOSTIC Center:**
```python
class DiagnosticCenter(AbstractCenter):
    """Read-only investigation center."""

    allowed_tools = [
        "ssh_execute",  # With read-only validation
        "kubectl_get", "kubectl_describe", "kubectl_logs",
        "read_file", "list_directory",
        "check_disk_usage", "check_memory",
        "analyze_logs", "tail_log",
    ]

    blocked_commands = [
        "rm ", "mv ", "chmod", "chown",
        "systemctl start/stop/restart",
        "kill", "reboot", "shutdown",
    ]
```

**CHANGE Center:**
```python
class ChangeCenter(AbstractCenter):
    """Controlled mutation center via Pipelines."""

    async def execute(self, deps: CenterDeps) -> CenterResult:
        # 1. Detect capabilities
        caps = await self.capabilities.detect_all(deps.target)

        # 2. Select appropriate pipeline
        pipeline = self._select_pipeline(caps, deps.task)

        # 3. Execute pipeline (includes mandatory HITL)
        return await pipeline.execute()
```

**Consequences:**

- Clear separation of concerns
- Appropriate security for each operation type
- All mutations go through Pipeline + HITL
- Read-only operations are fast (no approval needed)

---

## ADR-014: Pipeline System for CHANGE Operations

**Status:** Accepted (v0.8.0)

**Context:** All state-changing operations need consistent validation, preview, approval, and rollback capabilities.

**Decision:** Implement mandatory pipeline stages for all CHANGE operations:

```text
Plan → Diff/Dry-run → Summary → HITL → Apply → Post-check → Rollback
```

**Pipeline Types:**

| Pipeline | Dry-run Command | Use Case |
|----------|-----------------|----------|
| **AnsiblePipeline** | `ansible-playbook --check --diff` | Configuration, packages, services |
| **TerraformPipeline** | `terraform plan` | Cloud infrastructure |
| **KubernetesPipeline** | `kubectl diff` | Container orchestration |
| **BashPipeline** | Preview only | Fallback for simple commands |

**Implementation:**
```python
class AbstractPipeline(ABC):
    @abstractmethod
    async def plan(self) -> PlanResult: ...

    @abstractmethod
    async def diff(self) -> DiffResult: ...

    @abstractmethod
    async def apply(self) -> ApplyResult: ...

    @abstractmethod
    async def rollback(self) -> RollbackResult: ...

    async def execute(self) -> PipelineResult:
        """Execute full pipeline with HITL."""
        plan = await self.plan()
        diff = await self.diff()
        summary = self._generate_summary(plan, diff)

        if not await self._request_hitl(summary):
            return PipelineResult(aborted=True)

        result = await self.apply()
        post_check = await self._post_check()

        if not post_check.success:
            await self.rollback()

        return result
```

**Consequences:**

- Consistent change management across all tools
- Mandatory preview before apply
- Automatic rollback on failure
- Full audit trail

---

## ADR-015: CenterClassifier for Intent Routing

**Status:** Accepted (v0.8.0)

**Context:** User requests need to be routed to the appropriate center (DIAGNOSTIC or CHANGE) based on intent.

**Decision:** Use a hybrid pattern-matching + LLM classifier:

1. **Pattern Matching (Fast Path)**: Regex patterns for clear intents
2. **LLM Fallback**: Fast model for ambiguous cases
3. **Clarification**: User prompt when confidence < 0.7

**Implementation:**
```python
class CenterClassifier:
    CONFIDENCE_THRESHOLD = 0.7

    async def classify(self, user_input: str) -> CenterClassification:
        # 1. Try pattern-based classification
        result = self._classify_patterns(user_input)

        # 2. LLM fallback if low confidence
        if result.confidence < self.CONFIDENCE_THRESHOLD:
            llm_result = await self._classify_with_llm(user_input)
            if llm_result.confidence > result.confidence:
                result = llm_result

        # 3. Request clarification if still ambiguous
        if result.confidence < self.CONFIDENCE_THRESHOLD:
            result.clarification_needed = True

        return result
```

**Pattern Examples:**

| Pattern | Center |
|---------|--------|
| `check status`, `show logs`, `what is` | DIAGNOSTIC |
| `restart`, `deploy`, `fix`, `update` | CHANGE |

**Consequences:**

- Fast routing for clear intents (< 1ms)
- Accurate classification via LLM fallback
- Safe default to DIAGNOSTIC when unsure
- User clarification prevents misrouting

---

## ADR-016: Brain/Fast Model Configuration

**Status:** Accepted (v0.8.0)

**Context:** Different tasks require different model capabilities and cost trade-offs.

**Decision:** Two model roles with separate configuration:

| Role | Purpose | Example Models |
|------|---------|----------------|
| **brain** | Complex reasoning, planning, analysis | Claude Sonnet, GPT-4o |
| **fast** | Routing, fingerprinting, quick decisions | Claude Haiku, GPT-4o-mini |

**Configuration:**
```yaml
model:
  provider: anthropic
  brain: claude-sonnet-4-5-20250514
  fast: claude-haiku-4-5-20250514
```

**CLI Commands:**
```bash
/model brain claude-sonnet-4    # Set brain model
/model fast claude-haiku        # Set fast model
/model show                     # Show current config
```

**Usage in Code:**
```python
# CenterClassifier uses fast model
model = ctx.config.get_model("fast")

# Orchestrator uses brain model
model = ctx.config.get_model("brain")
```

**Consequences:**

- Cost optimization (fast model for simple tasks)
- Better performance (quick routing)
- Flexibility (different models per role)

---

## ADR-017: Capability Detection

**Status:** Accepted (v0.8.0)

**Context:** The CHANGE center needs to know which tools are available on target hosts to select the appropriate pipeline.

**Decision:** Implement capability detection module (`merlya/capabilities/`):

```python
class CapabilityDetector:
    async def detect_host(self, host: Host) -> HostCapabilities:
        return HostCapabilities(
            ssh=await self._detect_ssh(host),
            tools=[
                await self._detect_ansible(),
                await self._detect_terraform(),
                await self._detect_kubectl(),
                await self._detect_git(),
            ],
            web_access=await self._detect_web_access(),
        )
```

**Detected Capabilities:**

| Tool | Detection | Config Validation |
|------|-----------|-------------------|
| Ansible | `which ansible` | Inventory exists |
| Terraform | `which terraform` | `.tf` files present |
| kubectl | `which kubectl` | kubeconfig valid |
| git | `which git` | `.git` directory |

**Caching:**
- TTL-based cache (24h default)
- Invalidated on host changes
- Per-host capability storage

**Consequences:**

- Automatic pipeline selection
- No manual tool configuration
- Graceful fallback to BashPipeline

---

## Future Considerations

### Under Evaluation

- **Fingerprint Module** - Semantic signature extraction for command approval
- **Knowledge Base** - Three-tier knowledge system (general/validated/observed)
- **ElevationManager Refactor** - Simplified explicit elevation (no auto-detection)

### Implemented (v0.8.0)

- ~~Kubernetes integration~~ → KubernetesPipeline
- ~~Terraform integration~~ → TerraformPipeline
- ~~Ansible integration~~ → AnsiblePipeline

### Rejected

- **GUI Application** - Focus on CLI/API for automation
- **Custom LLM training** - Too resource-intensive for scope
- **Multi-tenant SaaS** - Security complexity, out of scope
- **ONNX embeddings** - Removed in v0.8.0 for simplicity (see ADR-005)
