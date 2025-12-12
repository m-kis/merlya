# Architecture

## Project Structure

```
merlya/
├── agent/          # PydanticAI agent and tools
├── cli/            # CLI entry point
├── commands/       # Slash command system
├── config/         # Configuration management + policies
│   ├── loader.py   # Config loading
│   ├── models.py   # Pydantic config models
│   ├── tiers.py    # Tier configuration (model selection)
│   └── policies.py # Policy management (guardrails)
├── core/           # Shared context and logging
├── health/         # Startup health checks
├── hosts/          # Host resolution
├── i18n/           # Internationalization (EN, FR)
├── mcp/            # MCP (Model Context Protocol) integration
│   └── manager.py  # MCPManager (async-safe singleton)
├── parser/         # Input/output parsing service
│   ├── service.py  # ParserService (tier-based backend selection)
│   ├── models.py   # Pydantic models (IncidentInput, ParsedLog)
│   └── backends/   # Heuristic and ONNX backends
├── persistence/    # SQLite database layer
│   ├── database.py # Async DB with migration locking
│   └── repositories.py # Typed repositories
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
│   └── summarizer.py # Hybrid summarization (ONNX + LLM)
├── setup/          # First-run wizard
├── skills/         # Reusable workflow system
│   ├── registry.py # SkillRegistry singleton
│   ├── loader.py   # YAML skill loader
│   ├── executor.py # SkillExecutor
│   └── builtin/    # Default skills (YAML)
├── ssh/            # SSH connection pool
├── subagents/      # Parallel execution system
│   ├── factory.py  # SubagentFactory
│   └── orchestrator.py # asyncio.gather orchestration
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

### 2. Intent Router (`merlya/router/`)

Classifies user intent to determine mode and required tools.

**Classification Methods:**
1. **ONNX Embeddings** - Local semantic classification (if available)
2. **LLM Fallback** - When confidence < 0.7
3. **Pattern Matching** - Keyword-based fallback

**Agent Modes:**
- `DIAGNOSTIC` - Information gathering (check, monitor, analyze)
- `REMEDIATION` - Actions (restart, deploy, fix)
- `QUERY` - Questions (what, how, explain)
- `CHAT` - General conversation

**RouterResult:**
```python
@dataclass
class RouterResult:
    mode: AgentMode
    tools: list[str]           # ["system", "files"]
    entities: dict             # {"hosts": ["web01"]}
    confidence: float
    jump_host: str | None      # Detected bastion
    credentials_required: bool
    elevation_required: bool
```

### 3. SSH Pool (`merlya/ssh/`)

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

### 4. Shared Context (`merlya/core/context.py`)

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

### 5. Persistence (`merlya/persistence/`)

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

### 6. Session Manager (`merlya/session/`)

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
1. ONNX extractive (key sentences)
2. Mini-LLM fallback
3. Main LLM fallback
4. Smart truncation

### 7. Skills System (`merlya/skills/`)

Reusable workflows for well-defined intents.

**Skill Configuration (YAML):**
```yaml
name: incident_triage
version: "1.0"
description: "Triage et diagnostic d'incidents"
intent_patterns:
  - "incident.*"
  - "problème.*"
tools_allowed:
  - ssh_execute
  - read_file
max_hosts: 5
timeout_seconds: 120
require_confirmation_for: ["restart", "kill"]
```

**Execution Flow:**
1. Router matches skill pattern
2. SkillExecutor validates input
3. Subagents parallelize per-host
4. Results aggregated

### 8. Parser Service (`merlya/parser/`)

Structures all input/output before LLM processing.

**Backend Selection (tier-based):**
- `performance` → ONNX NER model
- `balanced` → ONNX DistilBERT
- `lightweight` → Heuristic (regex + patterns)

**Output Models:**
```python
class ParsingResult(BaseModel):
    confidence: float       # 0.0-1.0
    coverage_ratio: float   # % of text parsed
    has_unparsed_blocks: bool
    truncated: bool
```

### 9. MCP Manager (`merlya/mcp/`)

Integrates external MCP servers (GitHub, Slack, etc.).

**Async-safe Singleton:**
```python
manager = await MCPManager.create(config, secrets)
```

**Tool Namespacing:** Tools prefixed as `server.tool_name`

**Environment Resolution:**
- `${VAR}` - Required (raises if missing)
- `${VAR:-default}` - Optional with fallback

### 10. Policy System (`merlya/config/policies.py`)

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

### 11. Security Layer (`merlya/security/`, `merlya/agent/history.py`)

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
│ User: "Check disk usage on @web01 via @bastion"       │
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
         │ Expand @mentions                │
         │ @web01 → resolve from inventory │
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
  │   ├─ ONNX router available
  │   └─ Keyring accessible
  │
  ├─ Create SharedContext
  │   ├─ Load config
  │   ├─ Initialize database
  │   └─ Create repositories
  │
  ├─ Initialize router
  │   └─ Load ONNX model (if available)
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
