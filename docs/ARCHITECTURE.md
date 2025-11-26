# Athena Architecture

## Overview

Athena is an AI-powered infrastructure orchestration CLI that uses natural language to manage servers, services, and infrastructure.

```
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

#### REPL (`athena_ai/repl.py`)
- Interactive command-line interface
- Conversation memory
- Slash command handling
- Rich terminal output

#### CLI (`athena_ai/cli.py`)
- Click-based command structure
- Single query mode (`athena ask "..."`)
- Configuration commands

### 2. Orchestration Layer

#### AutoGen Orchestrator (`athena_ai/agents/ag2_orchestrator.py`)
- Multi-agent coordination using AG2/AutoGen
- Tool registration and execution
- Streaming response handling

#### Tools (`athena_ai/agents/autogen_tools.py`)
- 20+ infrastructure tools
- Host validation (anti-hallucination)
- Hook system for extensibility

### 3. LLM Layer

#### LLM Router (`athena_ai/llm/router.py`)
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

#### Context Manager (`athena_ai/context/manager.py`)
- Infrastructure discovery
- Smart caching (fingerprint-based)
- Host registry

#### Discovery (`athena_ai/context/discovery.py`)
- SSH config parsing
- /etc/hosts parsing
- Remote host scanning

#### Host Registry (`athena_ai/context/host_registry.py`)
- Central host database
- Fuzzy matching
- Validation with suggestions

### 5. Security Layer

#### Risk Assessor (`athena_ai/security/risk_assessor.py`)
- Command risk classification
- Confirmation requirements

#### Permissions (`athena_ai/security/permissions.py`)
- Operation authorization
- Audit trail

### 6. Execution Layer

#### SSH Executor (`athena_ai/executors/ssh.py`)
- Connection pooling
- Jump host support
- Timeout handling

#### Action Executor (`athena_ai/executors/action_executor.py`)
- Unified execution interface
- Local and remote commands

## Data Flow

### Query Processing

```
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

```
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

# Athena settings
ATHENA_ENV=dev           # Environment
ATHENA_DEBUG=1           # Debug mode
```

### File Structure

```
~/.athena/
├── .env                 # Environment variables
├── config.yaml          # Configuration
├── inventory.yaml       # Custom inventory
├── hooks.yaml           # Hook definitions
├── commands/            # Custom slash commands
│   └── mycommand.md
└── logs/
    └── athena.log
```

## Extension Points

### Custom Slash Commands

Create `~/.athena/commands/deploy.md`:

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

Create `~/.athena/hooks.yaml`:

```yaml
hooks:
  tool_execute_start:
    - name: slack_notify
      action: webhook
      config:
        url: https://hooks.slack.com/...
```

### Custom Tools

Register in `athena_ai/agents/autogen_tools.py`:

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
