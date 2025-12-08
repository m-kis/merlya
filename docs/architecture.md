# Architecture

## Project Structure

```
merlya/
├── agent/          # PydanticAI agent and tools
├── cli/            # CLI entry point
├── commands/       # Slash command system
├── config/         # Configuration management
├── core/           # Shared context and logging
├── health/         # Startup health checks
├── hosts/          # Host resolution
├── i18n/           # Internationalization (EN, FR)
├── persistence/    # SQLite database layer
├── repl/           # Interactive console
├── router/         # Intent classification
├── secrets/        # Keyring integration
├── security/       # Permission management
├── setup/          # First-run wizard
├── ssh/            # SSH connection pool
├── tools/          # Tool implementations
│   ├── core/       # Core tools (ssh_execute, list_hosts)
│   ├── files/      # File operations
│   ├── system/     # System monitoring
│   ├── security/   # Security auditing
│   └── web/        # Web search
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
