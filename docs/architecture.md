# Architecture

## Project Structure

```
merlya/
├── agent/          # PydanticAI agent and tools
│   ├── orchestrator/     # Specialist delegation tools + runner
│   │   ├── specialist_tools.py  # delegate_diagnostic/execution/security/query
│   │   ├── specialist_runner.py
│   │   └── models.py    # DelegationResult
│   ├── specialists/      # Specialist agent implementations
│   │   ├── diagnostic.py # DiagnosticSpecialist (read-only, blocks dangerous commands)
│   │   ├── execution.py  # ExecutionSpecialist (HITL required for mutations)
│   │   ├── security.py   # SecuritySpecialist
│   │   └── query.py      # QuerySpecialist
│   └── ... (other agent files)
├── capabilities/   # Capability detection for hosts/tools
│   ├── detector.py # CapabilityDetector (SSH, Ansible, TF, K8s)
│   ├── models.py   # HostCapabilities, ToolCapability
│   └── cache.py    # TTL cache for capabilities
├── cli/            # CLI entry point
├── commands/       # Slash command system
├── config/         # Configuration management + policies
│   ├── loader.py   # Config loading
│   ├── models.py   # Pydantic config models
│   ├── tiers.py    # Tier configuration (deprecated, kept for compatibility)
│   └── policies.py # Policy management (guardrails)
├── core/           # Shared context, logging, and observability
│   ├── context.py  # SharedContext (central dependency container)
│   ├── metrics.py  # In-memory metrics (Counter, Histogram, Gauge, MetricsRegistry)
│   └── resilience.py # Circuit breaker and retry decorators
├── health/         # Startup health checks
├── hosts/          # Host resolution
├── i18n/           # Internationalization (EN, FR)
├── mcp/            # MCP (Model Context Protocol) integration
│   └── manager.py  # MCPManager (async-safe singleton)
├── parser/         # Input/output parsing service
│   ├── service.py  # ParserService (heuristic-based parsing)
│   ├── models.py   # Pydantic models (IncidentInput, ParsedLog)
│   ├── smart_extractor.py  # SmartExtractor (LLM + regex hybrid)
│   └── backends/   # Heuristic backend
├── persistence/    # SQLite database layer
│   ├── database.py # Async DB with migration locking
│   └── repositories.py # Typed repositories
├── pipelines/      # IaC pipelines for execution operations
│   ├── base.py     # AbstractPipeline, PipelineStage
│   ├── ansible.py  # AnsiblePipeline (ad-hoc/inline/repo)
│   ├── terraform.py # TerraformPipeline
│   ├── kubernetes.py # KubernetesPipeline
│   └── bash.py     # BashPipeline (fallback)
├── provisioners/   # Multi-cloud IaC provisioning (v0.9.0)
│   ├── base.py     # AbstractProvisioner, ProvisionerResult
│   ├── registry.py # ProvisionerRegistry (singleton)
│   ├── credentials.py # CredentialResolver (multi-source)
│   ├── backends/   # IaC backend implementations
│   │   ├── base.py # AbstractProvisionerBackend, BackendType
│   │   ├── terraform.py # TerraformBackend
│   │   └── mcp_backend.py # MCPBackend
│   ├── providers/  # Cloud provider abstractions
│   │   ├── base.py # AbstractCloudProvider, ProviderType
│   │   └── registry.py # CloudProviderRegistry
│   └── state/      # Resource state tracking
│       ├── models.py # ResourceState, StateSnapshot, DriftResult
│       ├── repository.py # SQLite persistence
│       └── tracker.py # StateTracker (drift detection)
├── templates/      # IaC template system (v0.9.0)
│   ├── models.py   # Template, TemplateVariable, TemplateInstance
│   ├── registry.py # TemplateRegistry (thread-safe singleton)
│   ├── instantiation.py # TemplateInstantiator (Jinja2)
│   ├── loaders/    # Template loading strategies
│   │   ├── base.py # AbstractTemplateLoader
│   │   ├── filesystem.py # FilesystemTemplateLoader
│   │   └── embedded.py # EmbeddedTemplateLoader
│   └── builtin/    # Built-in templates
│       └── basic-vm/ # Basic VM template (AWS/GCP/Azure)
├── repl/           # Interactive console
├── router/         # Intent classification
│   ├── classifier.py # IntentRouter with fast/heavy path
│   └── handler.py  # Request handler (fast path, skills, agent)
├── secrets/        # Keyring integration
├── security/       # Permission management + audit
│   ├── permissions.py # PermissionManager (password TTL, locking)
│   └── audit.py    # AuditLogger
├── session/        # Session and context management
│   ├── manager.py  # SessionManager
│   ├── context_tier.py # ContextTierPredictor (auto tier detection)
│   └── summarizer.py # LLM-based summarization
├── setup/          # First-run wizard
├── ssh/            # SSH connection pool
├── tools/          # Tool implementations
│   ├── core/       # Core tools (ssh_execute, list_hosts)
│   ├── files/      # File operations
│   ├── system/     # System monitoring
│   ├── security/   # Security auditing
│   ├── web/        # Web search
│   ├── logs/       # Log store (raw log persistence)
│   └── context/    # Context tools (host summaries)
└── ui/             # Console UI (Rich)
```

## Core Components

### 1. Agent System (`merlya/agent/`)

The agent is built on **PydanticAI** with a ReAct loop for reasoning and action. As of v0.8.3, `MerlyaAgent` delegates work to specialist agents via delegation tools registered in `merlya/agent/orchestrator/specialist_tools.py`.

**Key Classes:**
- `MerlyaAgent` - Main agent wrapper with conversation management and specialist delegation
- `AgentDependencies` - Dependency injection for tools
- `AgentResponse` - Structured response (message, actions, suggestions)

**Delegation Tools:**
- `delegate_diagnostic(target, task)` - Read-only investigation (DiagnosticSpecialist)
- `delegate_execution(target, task)` - Mutations with mandatory HITL (ExecutionSpecialist)
- `delegate_security(target, task)` - Security audits (SecuritySpecialist)
- `delegate_query(question)` - Inventory queries (QuerySpecialist)
- `list_hosts` / `get_host` / `ask_user` - Direct tools

**Features:**
- 120s timeout to prevent LLM hangs
- Conversation persistence to SQLite
- Tool registration via decorators
- Rationalized limits: `DEFAULT_TOOL_RETRIES=3`, `DEFAULT_TOOL_CALLS_LIMIT=50`

### 2. SmartExtractor (`merlya/parser/smart_extractor.py`)

Extracts host references from natural language using a hybrid LLM + regex approach.

**Extraction Methods:**

1. **Fast Model (LLM)** - Uses the fast model for semantic understanding
2. **Regex Patterns** - Fallback patterns for common host references
3. **Inventory Matching** - Validates against known hosts

**Output:**

The SmartExtractor injects detected hosts into the agent context, enabling the agent to work with the correct targets without explicit host specification in prompts.

### 3. Specialist Agents (`merlya/agent/specialists/`)

`MerlyaAgent` delegates to four specialist agents based on the nature of the request. The agent selects which specialist to invoke via its system prompt — no separate classifier step is required.

| Specialist | Purpose | HITL Required |
|-----------|---------|---------------|
| `DiagnosticSpecialist` | Read-only investigation; blocks dangerous commands | No |
| `ExecutionSpecialist` | Mutations (write, restart, deploy) | Yes (mandatory) |
| `SecuritySpecialist` | Security audits | No |
| `QuerySpecialist` | Inventory queries | No |

**DiagnosticSpecialist guardrails:**
- Enforces `blocked_commands` list (rm, kill, restart, reboot, shutdown, apt/yum install, chmod, chown, systemctl start/stop)
- All SSH operations are read-only (df, free, ps, cat, tail, grep, kubectl get/describe/logs)

**ExecutionSpecialist guardrails:**
- HITL approval is mandatory before any mutation is applied
- Integrates with the Pipeline system (Ansible / Terraform / Kubernetes / Bash)

### 4. Pipelines (`merlya/pipelines/`)

All execution (mutation) operations go through a mandatory pipeline:

```text
Plan → Diff/Dry-run → Summary → HITL → Apply → Post-check → Rollback
```

**Pipeline Stages:**
```python
class PipelineStage(str, Enum):
    PLAN = "plan"          # Validate what will change
    DIFF = "diff"          # Preview changes (dry-run)
    SUMMARY = "summary"    # Human-readable description
    HITL = "hitl"          # User approval required
    APPLY = "apply"        # Execute changes
    POST_CHECK = "post_check"  # Verify success
    ROLLBACK = "rollback"  # Revert if failed
```

**Available Pipelines:**

| Pipeline           | Use Case                             | Dry-run            |
| ------------------ | ------------------------------------ | ------------------ |
| AnsiblePipeline    | Service management, config, packages | `--check --diff`   |
| TerraformPipeline  | Cloud infrastructure                 | `terraform plan`   |
| KubernetesPipeline | Container orchestration              | `kubectl diff`     |
| BashPipeline       | Fallback for simple commands         | Preview only       |

### 5. SSH Pool (`merlya/ssh/`)

Manages SSH connections with pooling and authentication.

**Features:**
- Connection reuse (LRU eviction at 50 connections)
- Jump host/bastion support via `via` parameter
- SSH agent integration
- Passphrase callback for encrypted keys
- MFA/keyboard-interactive support

**Key Classes:**
- `SSHPool` - Singleton connection pool
- `SSHAuthManager` - Authentication handling
- `SSHResult` - Command result (stdout, stderr, exit_code)

### 6. Shared Context (`merlya/core/context.py`)

Central dependency container passed to all components.

```python
SharedContext
├── config          # Configuration
├── i18n            # Translations
├── secrets         # Keyring store
├── ui              # Console output
├── db              # SQLite connection
├── hosts           # HostRepository
├── variables       # VariableRepository
├── conversations   # ConversationRepository
├── router          # IntentRouter
└── ssh_pool        # SSHPool (lazy)
```

### 7. Observability (`merlya/core/`)

#### Metrics (`merlya/core/metrics.py`)

Thread-safe in-memory metrics registry. Accessible via the `/metrics` slash command.

**Metric Types:** `Counter`, `Histogram`, `Gauge`, `MetricsRegistry`

**Tracked metrics:**
- `merlya_commands_total` - Executions by type/status
- `merlya_ssh_duration_seconds` - SSH latency histogram
- `merlya_llm_calls_total` - LLM API calls by provider/model
- `merlya_pipeline_executions` - Pipeline runs by type/status
- `merlya_retry_attempts_total` - Retry counts

**Design:** Thread-safe via `threading.Lock`. Histogram uses a sliding window (max 10k observations) to prevent memory growth. No external backend — Prometheus/Grafana deferred to V2.0.

#### Resilience (`merlya/core/resilience.py`)

Circuit breaker and retry decorators for SSH, LLM, and pipeline operations.

**Patterns:**
- `@circuit_breaker(failure_threshold=5, recovery_timeout=60)` — Opens after 5 consecutive failures; auto-recovers after 60s
- `@retry(max_attempts=3, exponential_base=2.0)` — Exponential backoff retries

### 8. Persistence (`merlya/persistence/`)

SQLite database with async access via aiosqlite.

**Tables:**
- `hosts` - Inventory with metadata
- `variables` - User-defined variables
- `conversations` - Chat history with messages
- `command_history` - Executed commands log
- `raw_logs` - Stored command outputs with TTL
- `sessions` - Session context and summaries

**Migration Safety:**
- Single atomic transaction for all migrations
- Migration lock prevents concurrent updates
- Stale lock detection (30s timeout)

### 9. Session Manager (`merlya/session/`)

Manages context tiers and automatic summarization.

**Context Tiers:**
```python
class ContextTier(Enum):
    MINIMAL = "minimal"    # ~10 messages, 2000 tokens
    STANDARD = "standard"  # ~30 messages, 4000 tokens
    EXTENDED = "extended"  # ~100 messages, 8000 tokens
```

**Auto-detection:** Based on available RAM:
- ≥8GB → EXTENDED
- ≥4GB → STANDARD
- <4GB → MINIMAL

**Summarization Chain:**
1. LLM extractive (key sentences)
2. Main LLM fallback
3. Smart truncation

### 10. Parser Service (`merlya/parser/`)

Structures all input/output before LLM processing.

**Backend:**
Heuristic-based parsing using regex patterns and rule-based extraction.

**Output Models:**
```python
class ParsingResult(BaseModel):
    confidence: float       # 0.0-1.0
    coverage_ratio: float   # % of text parsed
    has_unparsed_blocks: bool
    truncated: bool
```

### 11. MCP Manager (`merlya/mcp/`)

Integrates external MCP servers (GitHub, Slack, etc.).

**Async-safe Singleton:**
```python
manager = await MCPManager.create(config, secrets)
```

**Tool Namespacing:** Tools prefixed as `server.tool_name`

**Environment Resolution:**
- `${VAR}` - Required (raises if missing)
- `${VAR:-default}` - Optional with fallback

### 12. Policy System (`merlya/config/policies.py`)

Guardrails and safety controls.

**PolicyConfig:**
```yaml
policy:
  context_tier: "auto"           # auto-detect or manual
  max_tokens_per_call: 8000
  max_hosts_per_skill: 10
  max_parallel_subagents: 5
  require_confirmation_for_write: true
  audit_logging: true
```

**Guardrails:**
- No destructive commands without confirmation
- Per-host async locking for capability detection
- Audit logging of all executed commands

### 13. Security Layer (`merlya/security/`, `merlya/agent/history.py`)

Comprehensive security controls for credential handling and agent behavior.

#### Privilege Elevation (`merlya/security/permissions.py`)

**Method Priority:**
```python
ELEVATION_PRIORITY = {
    "sudo": 1,       # NOPASSWD sudo - best option
    "doas": 2,       # Often NOPASSWD on BSD systems
    "sudo_with_password": 3,  # Requires password prompt
    "su": 4,         # Last resort - requires root password
}
```

**Detection Flow:**
1. Test `sudo -n true` (non-interactive)
2. If success → `sudo` (NOPASSWD)
3. If fail → check for `doas`, `su`
4. Cache capability in host metadata

**Password Security:**
- Passwords stored in system keyring (macOS Keychain, Linux Secret Service)
- Commands receive `@elevation:hostname:password` references, not raw values
- `resolve_secrets()` expands references at execution time
- Logs show `@secret` references, never actual values

#### Secret References (`merlya/tools/core/tools.py`)

**Pattern:** `@service:host:field` (e.g., `@elevation:web01:password`, `@db:prod:token`)

```python
SECRET_PATTERN = re.compile(r"(?:^|(?<=[\s;|&='\"]))\@([a-zA-Z][a-zA-Z0-9_:.-]*)")

def resolve_secrets(command: str, secrets: SecretStore) -> tuple[str, str]:
    """Returns (resolved_command, safe_command_for_logging)"""
```

**Unsafe Password Detection:**
```python
# Forbidden patterns (leaks password in logs):
# - echo 'pass' | sudo -S
# - -p'password'
# - --password=pass
detect_unsafe_password(command) -> str | None  # Returns warning if unsafe
```

#### Loop Detection (`merlya/agent/history.py`)

Prevents agent from spinning on unproductive patterns.

**Detection Modes:**
1. **Same call repeated** - Same tool+args called 3+ times in window
2. **Consecutive identical** - Last N calls are ALL identical
3. **Alternating pattern** - A→B→A→B oscillation

**Configuration:**
```python
LOOP_DETECTION_WINDOW = 10    # Messages to examine
LOOP_THRESHOLD_SAME_CALL = 3  # Max identical calls
```

**Response:** Injects system message to redirect agent approach.

#### Session Message Persistence

Messages persisted to SQLite for session resumption:
- `session_messages` table with sequence numbers
- PydanticAI `ModelMessagesTypeAdapter` for serialization
- Automatic trimming to `MAX_MESSAGES_IN_MEMORY` on load

## Request Flow

```
┌────────────────────────────────────────────────────────┐
│ User: "Check disk usage on web01 via bastion"         │
└──────────────────────┬─────────────────────────────────┘
                       │
                       ▼
         ┌─────────────────────────┐
         │ REPL receives input     │
         └───────────┬─────────────┘
                     │
                     ▼
         ┌─────────────────────────────────┐
         │ handle_message()                │
         │ • SmartExtractor detects hosts  │
         │ • Injects host context          │
         └───────────┬─────────────────────┘
                     │
                     ▼
         ┌─────────────────────────────────┐
         │ MerlyaAgent.run()               │
         │ • ReAct loop reasons over task  │
         │ • Selects specialist via system │
         │   prompt guidance               │
         │   → delegate_diagnostic(        │
         │       target="web01",           │
         │       task="check disk usage"   │
         │     )                           │
         └───────────┬─────────────────────┘
                     │
                     ▼
         ┌─────────────────────────────────┐
         │ DiagnosticSpecialist runs       │
         │ • Enforces blocked_commands     │
         │ • ssh_execute(                  │
         │     host="web01",               │
         │     command="df -h",            │
         │     via="bastion"               │
         │   )                             │
         │ • Returns DelegationResult      │
         └───────────┬─────────────────────┘
                     │
                     ▼
         ┌─────────────────────────────────┐
         │ Display Response                │
         │ • Markdown render               │
         │ • Actions taken                 │
         │ • Suggestions                   │
         └─────────────────────────────────┘
```

## Startup Flow

```
merlya
  │
  ├─ Configure logging
  │
  ├─ First run? → Setup wizard
  │   ├─ Language selection
  │   ├─ LLM provider config
  │   └─ Inventory import
  │
  ├─ Health checks
  │   ├─ Disk space
  │   ├─ RAM availability
  │   ├─ SSH available
  │   ├─ LLM provider reachable
  │   └─ Keyring accessible
  │
  ├─ Create SharedContext
  │   ├─ Load config
  │   ├─ Initialize database
  │   └─ Create repositories
  │
  ├─ Initialize router
  │   └─ Load pattern matcher
  │
  ├─ Create agent
  │   └─ Register all tools (including delegation tools)
  │
  └─ Start REPL loop
```

## Tool Execution

Tools are Python functions decorated with `@agent.tool`:

```python
@agent.tool
async def ssh_execute(
    ctx: RunContext[AgentDependencies],
    host: str,
    command: str,
    timeout: int = 60,
    elevation: str | None = None,
    via: str | None = None,
) -> dict[str, Any]:
    """Execute command on remote host."""
    result = await _ssh_execute(
        ctx.deps.context, host, command,
        timeout=timeout, elevation=elevation, via=via
    )
    if result.success:
        return result.data
    raise ModelRetry(f"SSH failed: {result.error}")
```

The agent decides which tools to call based on:
1. System prompt guidance (which specialist to delegate to)
2. LLM reasoning

### 14. Provisioners System (`merlya/provisioners/`)

Multi-cloud IaC provisioning abstraction layer for creating, updating, and destroying infrastructure resources.

**Architecture:**

```text
ProvisionerRegistry (singleton)
    └── AbstractProvisioner
            ├── AbstractCloudProvider (AWS, GCP, Azure, etc.)
            └── AbstractProvisionerBackend (Terraform, MCP)
```

**Key Classes:**

- `AbstractProvisioner` - Base class defining the provisioning workflow
- `ProvisionerRegistry` - Thread-safe singleton for provisioner discovery
- `CredentialResolver` - Multi-source credential resolution (keyring, env, files)

**Provisioner Actions:**
```python
class ProvisionerAction(str, Enum):
    CREATE = "create"   # Provision new resources
    UPDATE = "update"   # Modify existing resources
    DELETE = "delete"   # Destroy resources
```

**Provisioning Stages:**
```python
class ProvisionerStage(str, Enum):
    VALIDATE = "validate"      # Check credentials and inputs
    PLAN = "plan"              # Generate execution plan
    DIFF = "diff"              # Show changes (dry-run)
    SUMMARY = "summary"        # Human-readable summary
    HITL = "hitl"              # User approval required
    APPLY = "apply"            # Execute changes
    POST_CHECK = "post_check"  # Verify success
    ROLLBACK = "rollback"      # Revert on failure
```

**Backends:**

| Backend          | Use Case                         | MCP Support |
|------------------|----------------------------------|-------------|
| TerraformBackend | Cloud infrastructure via HCL     | Optional    |
| MCPBackend       | Direct cloud API via MCP servers | Primary     |

**Providers:**

| Provider | Type          | Backend Priority |
|----------|---------------|------------------|
| AWS      | Public Cloud  | MCP → Terraform  |
| GCP      | Public Cloud  | MCP → Terraform  |
| Azure    | Public Cloud  | MCP → Terraform  |
| Proxmox  | Private Cloud | API → Terraform  |

### 15. Templates System (`merlya/templates/`)

Reusable IaC template system with Jinja2 rendering and validation.

**Key Classes:**

- `Template` - Template definition with variables and outputs
- `TemplateRegistry` - Thread-safe singleton for template discovery
- `TemplateInstantiator` - Jinja2-based template rendering
- `AbstractTemplateLoader` - Interface for template sources

**Template Categories:**

```python
class TemplateCategory(str, Enum):
    COMPUTE = "compute"       # VMs, instances
    NETWORK = "network"       # VPCs, subnets, firewalls
    STORAGE = "storage"       # Disks, buckets, volumes
    DATABASE = "database"     # RDS, Cloud SQL, etc.
    CONTAINER = "container"   # Kubernetes, ECS
    SECURITY = "security"     # IAM, certificates
```

**Variable Types:**
```python
class VariableType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    LIST = "list"
    MAP = "map"
    SECRET = "secret"  # Masked in logs
```

**Template YAML Schema:**

```yaml
name: basic-vm
version: "1.0.0"
category: compute
description: "Basic VM with customizable specs"
providers: [aws, gcp, azure]
backends:
  - backend: terraform
    entry_point: main.tf.j2
variables:
  - name: vm_name
    type: string
    required: true
    description: "Instance name"
  - name: instance_type
    type: string
    provider_defaults:
      aws: "t3.micro"
      gcp: "e2-micro"
outputs:
  - name: public_ip
    description: "Public IP address"
```

**Template Loading:**

```python
# Registry auto-discovers templates from multiple sources
registry = TemplateRegistry.get_instance()
registry.register_loader(FilesystemTemplateLoader(path))
registry.register_loader(EmbeddedTemplateLoader())

# Get and instantiate template
template = registry.get("basic-vm", version="1.0.0")
instance = instantiator.instantiate(
    template=template,
    variables={"vm_name": "web-01", "cpu": 2, "memory_gb": 4},
    provider="aws",
    backend=IaCBackend.TERRAFORM
)
```

**Version Management:**

- Templates stored with versioned keys (`name:version`) and unversioned (`name`)
- Unversioned key always points to highest semantic version
- Manual registrations preserved on reload

### 16. State Tracking (`merlya/provisioners/state/`)

SQLite-based resource state management with drift detection.

**Key Classes:**

- `ResourceState` - State of a single managed resource
- `StateSnapshot` - Point-in-time snapshot of all resources
- `DriftResult` - Result of drift detection comparison
- `StateTracker` - Coordinates state operations
- `StateRepository` - SQLite persistence layer

**Resource Status:**

```python
class ResourceStatus(str, Enum):
    PENDING = "pending"     # Planned but not created
    CREATING = "creating"   # Creation in progress
    ACTIVE = "active"       # Exists and healthy
    UPDATING = "updating"   # Update in progress
    DELETING = "deleting"   # Deletion in progress
    DELETED = "deleted"     # Has been deleted
    FAILED = "failed"       # Operation failed
    UNKNOWN = "unknown"     # State cannot be determined
```

**Drift Detection:**

```python
class DriftStatus(str, Enum):
    NO_DRIFT = "no_drift"  # Matches expected state
    DRIFTED = "drifted"    # Differs from expected
    MISSING = "missing"    # Resource no longer exists
    UNKNOWN = "unknown"    # Unable to determine
```

**State Persistence:**

```python
# ResourceState includes rollback data
resource.save_for_rollback()  # Deep copy of actual_config
resource.previous_config      # Available for restore

# Snapshots enable point-in-time recovery
snapshot = await tracker.create_snapshot(
    provider="aws",
    description="Pre-deployment backup"
)
```

**Database Schema:**

```sql
-- Resources table
CREATE TABLE resources (
    resource_id TEXT PRIMARY KEY,
    resource_type TEXT NOT NULL,
    name TEXT NOT NULL,
    provider TEXT NOT NULL,
    region TEXT,
    status TEXT NOT NULL,
    expected_config TEXT NOT NULL,  -- JSON
    actual_config TEXT NOT NULL,    -- JSON
    tags TEXT NOT NULL,             -- JSON
    outputs TEXT NOT NULL,          -- JSON
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_checked_at TEXT,
    previous_config TEXT            -- JSON (for rollback)
);

-- Snapshots table
CREATE TABLE snapshots (
    snapshot_id TEXT PRIMARY KEY,
    provider TEXT,
    session_id TEXT,
    resource_ids TEXT NOT NULL,     -- JSON array
    created_at TEXT NOT NULL,
    description TEXT
);
```

**State Workflow:**

```text
1. Plan      → Save expected_config
2. Apply     → Update actual_config, status=ACTIVE
3. Check     → Compare expected vs actual
4. Drift     → Generate DriftResult with differences
5. Rollback  → Restore from previous_config
```
