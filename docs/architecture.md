# Architecture

## Project Structure

```
merlya/
├── agent/          # PydanticAI agent and tools
├── capabilities/   # Capability detection for hosts/tools
│   ├── detector.py # CapabilityDetector (SSH, Ansible, TF, K8s)
│   ├── models.py   # HostCapabilities, ToolCapability
│   └── cache.py    # TTL cache for capabilities
├── centers/        # Operational centers (DIAGNOSTIC/CHANGE)
│   ├── base.py     # AbstractCenter, CenterMode, RiskLevel
│   ├── diagnostic.py # DiagnosticCenter (read-only)
│   ├── change.py   # ChangeCenter (pipelines + HITL)
│   └── registry.py # CenterRegistry
├── cli/            # CLI entry point
├── commands/       # Slash command system
├── config/         # Configuration management + policies
│   ├── loader.py   # Config loading
│   ├── models.py   # Pydantic config models
│   ├── tiers.py    # Tier configuration (deprecated, kept for compatibility)
│   └── policies.py # Policy management (guardrails)
├── core/           # Shared context and logging
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
├── pipelines/      # IaC pipelines for CHANGE center
│   ├── base.py     # AbstractPipeline, PipelineStage
│   ├── ansible.py  # AnsiblePipeline (ad-hoc/inline/repo)
│   ├── terraform.py # TerraformPipeline
│   ├── kubernetes.py # KubernetesPipeline
│   └── bash.py     # BashPipeline (fallback)
├── repl/           # Interactive console
├── router/         # Intent classification
│   ├── classifier.py # IntentRouter with fast/heavy path
│   ├── center_classifier.py # CenterClassifier (DIAG/CHANGE)
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

The agent is built on **PydanticAI** with a ReAct loop for reasoning and action.

**Key Classes:**
- `MerlyaAgent` - Main agent wrapper with conversation management
- `AgentDependencies` - Dependency injection for tools
- `AgentResponse` - Structured response (message, actions, suggestions)

**Features:**
- 120s timeout to prevent LLM hangs
- Conversation persistence to SQLite
- Tool registration via decorators

### 2. SmartExtractor (`merlya/parser/smart_extractor.py`)

Extracts host references from natural language using a hybrid LLM + regex approach.

**Extraction Methods:**

1. **Fast Model (LLM)** - Uses the fast model for semantic understanding
2. **Regex Patterns** - Fallback patterns for common host references
3. **Inventory Matching** - Validates against known hosts

**Output:**

The SmartExtractor injects detected hosts into the agent context, enabling the orchestrator to work with the correct targets without explicit host specification in prompts.

### 3. Center Classifier (`merlya/router/center_classifier.py`)

Routes user requests to either DIAGNOSTIC or CHANGE center based on intent classification.

**CenterMode:**
```python
class CenterMode(str, Enum):
    DIAGNOSTIC = "diagnostic"  # Read-only investigation
    CHANGE = "change"          # Controlled mutations
```

**Classification Strategy:**

1. **Pattern Matching** - Fast regex-based classification for clear intents
2. **LLM Fallback** - Uses fast model for ambiguous cases
3. **Clarification** - Asks user if confidence < 0.7

**DIAGNOSTIC Patterns:** check, status, show, list, logs, analyze, why, what
**CHANGE Patterns:** restart, fix, deploy, install, update, scale, delete

### 4. Operational Centers (`merlya/centers/`)

Two operational centers handle all user requests:

#### DiagnosticCenter (Read-Only)

Executes investigation tasks without modifying system state.

**Allowed Tools:**
- SSH read commands (df, free, ps, cat, tail, grep)
- kubectl get/describe/logs
- Log analysis
- Security audits

**Blocked Commands:**

- rm, kill, restart, reboot, shutdown
- apt/yum install, pip install
- chmod, chown, systemctl start/stop

**Evidence Collection:**
```python
class Evidence(BaseModel):
    timestamp: datetime
    host: str
    command: str
    output: str
    exit_code: int
    duration_ms: int
```

#### ChangeCenter (Controlled Mutations)

All changes go through a Pipeline with mandatory HITL (Human-In-The-Loop) approval.

**Pipeline Selection:**

1. Ansible - if installed and task matches (deploy, configure, service)
2. Terraform - if installed and task matches (infrastructure, cloud)
3. Kubernetes - if kubectl available and task matches (pod, deployment, scale)
4. Bash - fallback with strict HITL

### 5. Pipelines (`merlya/pipelines/`)

All CHANGE operations go through a mandatory pipeline:

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

### 6. SSH Pool (`merlya/ssh/`)

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

### 7. Shared Context (`merlya/core/context.py`)

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
         │ IntentRouter.route()            │
         │ • Mode: DIAGNOSTIC              │
         │ • Tools: [system]               │
         │ • Entities: {hosts: ["web01"]}  │
         │ • Jump host: "bastion"          │
         └───────────┬─────────────────────┘
                     │
                     ▼
         ┌─────────────────────────────────┐
         │ Resolve host names              │
         │ web01 → resolve from inventory  │
         └───────────┬─────────────────────┘
                     │
                     ▼
         ┌─────────────────────────────────┐
         │ MerlyaAgent.run()               │
         │ • Inject router_result          │
         │ • Execute ReAct loop            │
         │   → get_host("web01")           │
         │   → ssh_execute(                │
         │       host="web01",             │
         │       command="df -h",          │
         │       via="bastion"             │
         │     )                           │
         │ • Persist conversation          │
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
  │   └─ Register all tools
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
1. Router-suggested tools
2. System prompt guidance
3. LLM reasoning
