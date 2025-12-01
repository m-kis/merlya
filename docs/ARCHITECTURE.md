# Merlya Architecture

## Overview

Merlya is an AI-powered infrastructure orchestration CLI that uses natural language to manage servers, services, and infrastructure.

```text
┌─────────────────────────────────────────────────────────────┐
│                      User Interface                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │    REPL     │  │     CLI     │  │   Slash Commands    │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
└─────────┼────────────────┼────────────────────┼─────────────┘
          │                │                    │
          v                v                    v
┌─────────────────────────────────────────────────────────────┐
│                     Orchestration Layer                      │
│  ┌─────────────────────────────────────────────────────────┐│
│  │              AutoGen Multi-Agent System                 ││
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐  ││
│  │  │ Planner  │  │ Executor │  │ Error Corrector      │  ││
│  │  └──────────┘  └──────────┘  └──────────────────────┘  ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────┬───────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          v               v               v
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│ LLM Router  │  │   Context   │  │  Security   │
│             │  │   Manager   │  │             │
│ - OpenRouter│  │ - Inventory │  │ - Risk      │
│ - Anthropic │  │ - SSH Scan  │  │ - Perms     │
│ - OpenAI    │  │ - Cache     │  │ - Audit     │
│ - Ollama    │  │             │  │             │
└─────────────┘  └──────┬──────┘  └─────────────┘
                        │
                        v
┌─────────────────────────────────────────────────────────────┐
│                      Execution Layer                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐│
│  │   SSH    │  │ Ansible  │  │Terraform │  │  Kubernetes  ││
│  │ Executor │  │ Runner   │  │ Executor │  │   Executor   ││
│  └──────────┘  └──────────┘  └──────────┘  └──────────────┘│
└─────────────────────────────────────────────────────────────┘
```

## Key Components

### 1. User Interface Layer

#### REPL (`merlya/repl/`)

- Interactive command-line interface
- Conversation memory
- Slash command handling
- Rich terminal output
- Command handlers: [commands/](merlya/repl/commands/)

#### CLI (`merlya/cli.py`)

- Click-based command structure
- Single query mode (`merlya ask "..."`)
- Configuration commands

### 2. Orchestration Layer

#### AutoGen Orchestrator (`merlya/agents/ag2_orchestrator.py`)
- Multi-agent coordination using AG2/AutoGen
- Tool registration and execution
- Streaming response handling

#### Tools (`merlya/agents/autogen_tools.py`)
- 20+ infrastructure tools
- Host validation (anti-hallucination)
- Hook system for extensibility

### 3. LLM Layer

#### LLM Router (`merlya/llm/router.py`)
- Multi-provider support
- Automatic fallback
- Model configuration

**Supported Providers:**
| Provider | Models | Use Case |
|----------|--------|----------|
| OpenRouter | Claude, GPT-4, etc. | Recommended |
| Anthropic | Claude 3.x | Direct access |
| OpenAI | GPT-4, GPT-3.5 | Alternative |
| Ollama | Llama, Mistral | Offline/local |

### 4. Context Layer

#### Context Manager (`merlya/context/manager.py`)

- Orchestrates local and remote scanning
- Smart caching (fingerprint-based for inventory)
- JIT (Just-In-Time) host scanning

#### Local Scanner (`merlya/context/local_scanner/`)

- Comprehensive local machine scanning
- 12h TTL with SQLite persistence
- Scans: OS, network, services, processes, resources

#### On-Demand Scanner (`merlya/context/on_demand_scanner/`)

- JIT remote host scanning (single host at a time)
- Async with retry and rate limiting
- Cache per scan type (basic, system, services, full)

#### Host Registry (`merlya/context/host_registry.py`)

- Central host database
- Fuzzy matching
- Validation with suggestions

### 5. Security Layer

#### Risk Assessor (`merlya/security/risk_assessor.py`)
- Command risk classification
- Confirmation requirements

#### Permissions (`merlya/security/permissions.py`)
- Operation authorization
- Audit trail

### 6. Execution Layer

#### SSH Executor (`merlya/executors/ssh.py`)
- Connection pooling
- Jump host support
- Timeout handling
- Visual spinner during connection

#### Action Executor (`merlya/executors/action_executor.py`)

- Unified execution interface
- Local and remote commands
- Batch execution with progress tracking (`execute_batch()`)

### 7. CI/CD Integration Layer

#### CI Manager (`merlya/ci/manager.py`)

- Central CI/CD orchestration
- Multi-platform support (GitHub Actions, GitLab CI)
- Workflow triggering and monitoring

#### CI Adapters (`merlya/ci/adapters/`)

- Platform-specific adapters (GitHub, GitLab)
- Error classification and analysis
- Learning from past failures

#### CI Clients (`merlya/ci/clients/`)

- CLI-based execution (`gh`, `gitlab`)
- API-based execution (REST clients)
- Authentication and security

### 8. Triage Layer

#### Priority Classifier (`merlya/triage/`)

- 3-tier classification: Smart (embeddings) → AI (LLM) → Signal (keywords)
- Intent detection: QUERY, ACTION, ANALYSIS
- Priority levels: P0 (critical) → P3 (normal)

#### Signal Detector

- Deterministic keyword-based classification
- Environment detection (prod, staging, dev)
- Impact amplifiers

See [TRIAGE.md](TRIAGE.md) for detailed documentation.

### 9. UX Layer

#### Display Manager (`merlya/utils/display.py`)

- Centralized console output
- Spinners for long operations
- Progress bars for batch operations
- Consistent Rich styling

## Data Flow

### Query Processing

```text
1. User Input
   │
   v
2. REPL parses input
   │
   ├── Slash command? → Execute directly
   │
   └── Natural language? → Continue
          │
          v
3. Orchestrator receives query
   │
   v
4. Context enrichment
   │ - Add inventory
   │ - Add host details
   │ - Add conversation history
   │
   v
5. LLM generates plan
   │
   v
6. Tool execution
   │ - Validate hosts
   │ - Check permissions
   │ - Execute commands
   │
   v
7. Response synthesis
   │
   v
8. Display to user
```

### SSH Execution Flow

```text
1. execute_command(host, command)
   │
   v
2. Validate host against registry
   │
   ├── Invalid? → Return error with suggestions
   │
   └── Valid? → Continue
          │
          v
3. Check risk level
   │
   ├── Critical? → Require --confirm
   │
   └── Low/Moderate? → Continue
          │
          v
4. Get connection from pool
   │
   v
5. Execute command
   │
   v
6. Handle result
   │
   ├── Success? → Return output
   │
   └── Error? → Try error correction
```

## Configuration

### Environment Variables

```bash
# LLM Provider
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=anthropic/claude-sonnet-4

# Or other providers
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
OLLAMA_HOST=http://localhost:11434

# Merlya settings
MERLYA_ENV=dev           # Environment
MERLYA_DEBUG=1           # Debug mode
```

### File Structure

```text
~/.merlya/
├── .env                 # Environment variables
├── config.yaml          # Configuration
├── inventory.yaml       # Custom inventory
├── hooks.yaml           # Hook definitions
├── commands/            # Custom slash commands
│   └── mycommand.md
└── logs/
    └── merlya.log
```

## Extension Points

### Custom Slash Commands

Create `~/.merlya/commands/deploy.md`:

```markdown
---
name: deploy
description: Deploy application
aliases: [d]
---

Deploy {{$1}} to {{$2}} environment:
1. Pull latest code
2. Run migrations
3. Restart services
```

### Hooks

Create `~/.merlya/hooks.yaml`:

```yaml
hooks:
  tool_execute_start:
    - name: slack_notify
      action: webhook
      config:
        url: https://hooks.slack.com/...
```

### Custom Tools

Register in `merlya/agents/autogen_tools.py`:

```python
def my_custom_tool(
    param: Annotated[str, "Parameter description"]
) -> str:
    """Tool description."""
    # Implementation
    return "Result"
```

## Performance Considerations

### Connection Pooling
- SSH connections are reused
- Reduces 2FA prompts
- Configurable pool size

### Caching
- Context cached with fingerprints
- TTL-based invalidation
- Force refresh available

### Streaming

- LLM responses stream in real-time
- Reduces perceived latency

### Visual Feedback

Operations longer than 1 second show visual indicators:

| Operation | Indicator | Location |
|-----------|-----------|----------|
| LLM requests | Spinner "Thinking..." | `LLMRouter.generate()` |
| SSH connections | Spinner "Connecting..." | `SSHManager.execute()` |
| Host scan | Spinner "Scanning..." | `ContextManager.scan_host()` |
| Batch execution | Progress bar | `ActionExecutor.execute_batch()` |

```python
from merlya.utils.display import get_display_manager

display = get_display_manager()

# Spinner for single operations
with display.spinner("Processing..."):
    # long operation

# Progress bar for batch operations
with display.progress_bar("Scanning") as progress:
    task = progress.add_task("Hosts", total=10)
    for host in hosts:
        progress.advance(task)
```
