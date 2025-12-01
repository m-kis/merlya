# Merlya Agents

Merlya uses a multi-agent architecture for intelligent infrastructure management.

## Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     Unified Orchestrator                      │
│  ┌─────────────────────────────────────────────────────────┐│
│  │                    Mode Selection                        ││
│  │   BASIC: Single Engineer Agent                          ││
│  │   ENHANCED: Multi-Agent Team (Planner + Security +      ││
│  │             Engineer + Knowledge Manager)               ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        v                   v                   v
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Remediation│     │   Sentinel  │     │   Planner   │
│    Agent    │     │    Agent    │     │             │
└─────────────┘     └─────────────┘     └─────────────┘
```

---

## Orchestrator

The unified orchestrator manages request processing with two modes.

### Basic Mode (Single Agent)

Uses a single DevSecOps Engineer agent for straightforward requests.

```python
from merlya.agents import Orchestrator, OrchestratorMode

orchestrator = Orchestrator(
    env="prod",
    mode=OrchestratorMode.BASIC,
    language="fr"
)

response = await orchestrator.process_request(
    user_query="check disk space on web-01",
    conversation_history=history
)
```

### Enhanced Mode (Multi-Agent Team)

Uses multiple specialized agents for complex requests.

```python
orchestrator = Orchestrator(
    env="prod",
    mode=OrchestratorMode.ENHANCED
)
```

**Team Composition:**

| Agent | Role | Tools |
|-------|------|-------|
| **Planner** | Creates step-by-step plans | None (planning only) |
| **Security Expert** | Reviews plans for security | Audit tools |
| **DevSecOps Engineer** | Executes operations | All tools |
| **Knowledge Manager** | Stores findings | Knowledge graph |

**Workflow:**
1. Planner creates execution plan
2. Security Expert reviews for risks
3. DevSecOps Engineer executes
4. Knowledge Manager stores learnings

---

## DevSecOps Engineer Agent

The primary execution agent with 15+ years of simulated experience.

### Capabilities

- Linux systems administration
- Database management (MongoDB, PostgreSQL, MySQL)
- Kubernetes and Docker
- Networking and security
- Infrastructure automation

### Behavior by Intent

**ANALYSIS Mode:**
```
- Dig deep: check logs, configs, status
- EXPLAIN findings in clear terms
- PROPOSE solutions with example commands
- Ask before executing fixes
- Educate the user (teaching moment)
```

**QUERY Mode:**
```
- Collect requested information efficiently
- Present results clearly and organized
- READ-ONLY: avoid making changes
```

**ACTION Mode:**
```
- Verify targets before acting
- Execute the requested task
- Report results clearly
```

### Available Tools

```
CORE:       list_hosts, scan_host, execute_command, check_permissions
FILES:      read_remote_file, write_remote_file, tail_logs, grep_files
SYSTEM:     disk_info, memory_info, process_list, network_connections
SERVICES:   service_control
CONTAINERS: docker_exec, kubectl_exec
```

### Response Format

```markdown
## Analysis
[What was found and what it means]

## Root Cause / Explanation
[Technical explanation in clear terms]

## Recommendations
[Concrete solutions with example commands]
```bash
# Example command with explanation
command here
```

## Next Steps
[What the user should do next]
```

---

## Remediation Agent

Self-healing agent for automatic issue resolution.

### Modes

| Mode | Description |
|------|-------------|
| `SUGGEST` | Suggest fixes, don't execute |
| `CONFIRM` | Suggest and ask for confirmation |
| `AUTO` | Automatically execute safe fixes |

### Usage

```python
from merlya.agents import get_remediation_agent, RemediationMode

agent = get_remediation_agent(
    mode=RemediationMode.CONFIRM,
    max_retries=3
)

result = await agent.remediate(
    error="Connection refused to mongodb:27017",
    context={"host": "db-01", "service": "mongodb"}
)

# RemediationResult(
#     success=True,
#     action_taken="Restarted mongodb service",
#     rollback_available=True
# )
```

### Supported Error Types

| Error Type | Auto-Remediation |
|------------|------------------|
| Service down | Restart service |
| Disk full | Clean temp files, suggest expansion |
| Connection refused | Check service, firewall |
| Permission denied | Suggest elevation |
| OOM | Identify memory hog, suggest limits |

---

## Sentinel Agent

Monitoring agent for health checks and alerts.

### Features

- Periodic health checks
- Alert generation
- Threshold monitoring
- Multi-host support

### Usage

```python
from merlya.agents import get_sentinel_agent, AlertSeverity

sentinel = get_sentinel_agent(
    check_interval=60,  # seconds
    alert_threshold=AlertSeverity.WARNING
)

# Add health checks
sentinel.add_check(HealthCheck(
    name="disk_space",
    target="web-01",
    command="df -h / | tail -1 | awk '{print $5}' | tr -d '%'",
    threshold=80,
    comparison="gt"
))

# Start monitoring
await sentinel.start()

# Get status
status = sentinel.get_status()
# SentinelStatus(
#     active_checks=5,
#     alerts=[Alert(severity=WARNING, message="Disk at 85%")],
#     last_check="2024-01-15T10:30:00"
# )
```

### Alert Severities

| Severity | Description |
|----------|-------------|
| `INFO` | Informational, no action needed |
| `WARNING` | Attention needed, not critical |
| `ERROR` | Problem detected, action required |
| `CRITICAL` | Immediate attention required |

---

## Planner Agent

Creates execution plans for complex requests.

### Features

- Step-by-step planning
- Dependency identification
- Rollback planning
- Resource estimation

### Usage

```python
from merlya.agents import Planner

planner = Planner(model_client=client)

plan = await planner.create_plan(
    request="Deploy new nginx configuration to all web servers",
    context={"hosts": ["web-01", "web-02", "web-03"]}
)

# Plan:
# 1. Backup current nginx.conf on all hosts
# 2. Validate new configuration syntax
# 3. Deploy to web-01 (canary)
# 4. Verify web-01 health
# 5. Deploy to remaining hosts
# 6. Verify all hosts healthy
# Rollback: Restore backed up configs
```

---

## Agent Registry

Agents can be registered and retrieved dynamically.

```python
from merlya.core import get_registry, register_agent

# Register custom agent
@register_agent("my_agent")
class MyAgent:
    async def run(self, task: str) -> str:
        ...

# Retrieve agent
registry = get_registry()
agent = registry.get("my_agent")
```

---

## Conversation Context

Agents maintain conversation context for natural follow-ups.

```python
# First request
response = await orchestrator.process_request(
    "check nginx status on web-01",
    conversation_history=[]
)

# Follow-up (understands "it" refers to nginx)
response = await orchestrator.process_request(
    "restart it",
    conversation_history=[
        {"role": "user", "content": "check nginx status on web-01"},
        {"role": "assistant", "content": "nginx is running..."}
    ]
)
```

---

## Tool Restrictions

Agents respect tool restrictions based on triage:

```python
# Query intent = read-only tools
allowed_tools = ["list_hosts", "scan_host", "disk_info", "read_remote_file"]

# Action intent = all tools
allowed_tools = None  # No restrictions

# The planner enforces these
result = await planner.execute_basic(
    user_query="...",
    allowed_tools=allowed_tools
)
```

---

## Error Handling

Agents use consistent error handling:

```python
# Success response
"✅ Task completed successfully"

# Error with suggestion
"❌ ERROR: Permission denied on web-01
   Suggestion: Use request_elevation() to retry with sudo"

# Blocked operation
"❌ BLOCKED: Host 'unknown' not in inventory
   Available hosts: web-01, web-02, db-01"
```

---

## Configuration

### LLM Configuration

```python
orchestrator = Orchestrator(
    env="prod",
    model_config={
        "provider": "anthropic",
        "model": "claude-3-sonnet",
        "temperature": 0.1
    }
)
```

### Environment

```python
# Production environment (more cautious)
orchestrator = Orchestrator(env="prod")

# Development environment (more permissive)
orchestrator = Orchestrator(env="dev")
```

### Language

```python
# French responses
orchestrator = Orchestrator(language="fr")

# English responses (default)
orchestrator = Orchestrator(language="en")
```

---

## Hooks

Agents emit events via the hook system:

```python
from merlya.core import get_hook_manager, HookEvent

hooks = get_hook_manager()

@hooks.on(HookEvent.BEFORE_TOOL_CALL)
def log_tool_call(context):
    print(f"Calling tool: {context.tool_name}")

@hooks.on(HookEvent.AFTER_TOOL_CALL)
def handle_result(context):
    if context.error:
        print(f"Tool failed: {context.error}")
```

### Available Events

| Event | Description |
|-------|-------------|
| `BEFORE_TOOL_CALL` | Before a tool is executed |
| `AFTER_TOOL_CALL` | After a tool completes |
| `BEFORE_LLM_CALL` | Before LLM request |
| `AFTER_LLM_CALL` | After LLM response |
| `ERROR` | When an error occurs |

---

## See Also

- [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- [TOOLS.md](TOOLS.md) - Available tools
- [TRIAGE.md](TRIAGE.md) - Request classification
