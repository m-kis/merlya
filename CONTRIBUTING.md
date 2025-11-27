# Contributing to Athena

This document outlines the development principles, architectural patterns, and workflow that all contributors must follow.

## Development Principles

### 1. SOLID Principles

#### Single Responsibility Principle (SRP)
Each class/module has one reason to change.

```python
# Good: Dedicated classes
class RiskAssessor:    # Only assesses risk
class AuditLogger:     # Only logs audit events
class HostRegistry:    # Only manages host validation

# Bad: God classes that do everything
class ServerManager:   # Manages, executes, logs, validates...
```

#### Open/Closed Principle (OCP)
Open for extension, closed for modification. Use the Registry pattern.

```python
# Good: Register new agents without modifying existing code
from athena_ai.core.registry import get_registry

registry = get_registry()
registry.register("MyNewAgent", MyNewAgent)

# Bad: Hard-coded if/elif chains
if agent_type == "diagnostic":
    return DiagnosticAgent()
elif agent_type == "remediation":
    return RemediationAgent()
# Adding new agent requires modifying this code
```

#### Dependency Inversion Principle (DIP)
Depend on abstractions, inject dependencies.

```python
# Good: Accept dependencies via constructor
class BaseAgent:
    def __init__(
        self,
        context_manager: ContextManager,
        llm: Optional[LLMRouter] = None,
        executor: Optional[ActionExecutor] = None,
    ):
        self.llm = llm if llm is not None else LLMRouter()
        self.executor = executor if executor is not None else ActionExecutor()

# Bad: Hard-coded instantiation
class BadAgent:
    def __init__(self):
        self.llm = LLMRouter()  # Can't inject mocks for testing
```

### 2. Design Patterns

#### Singleton Pattern
Use for global services. **Always provide `reset_instance()` for testing.**

```python
class MyManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing)."""
        cls._instance = None
```

#### Registry Pattern
Use for dynamic registration and lookup.

```python
# Register at startup
registry.register("DiagnosticAgent", DiagnosticAgent)

# Lookup dynamically
agent = registry.get("DiagnosticAgent", context_manager=ctx)
```

### 3. Security-First Design

**Never execute commands on unvalidated hosts.**

```python
# Always validate hosts
from athena_ai.tools.base import validate_host

is_valid, message = validate_host(hostname)
if not is_valid:
    return {"error": message}
```

**Always audit security-relevant operations.**

```python
from athena_ai.security.audit_logger import get_audit_logger

audit = get_audit_logger()
audit.log_command(command, target, result="success", risk_level="moderate")
```

### 4. Error Handling

Use the unified exception hierarchy from `athena_ai.core.exceptions`:

```python
from athena_ai.core.exceptions import (
    ValidationError,
    ExecutionError,
    SecurityError,
    HostNotFoundError,
)

# Raise specific exceptions
if not host_valid:
    raise HostNotFoundError(f"Host '{hostname}' not found", details={"suggestions": suggestions})
```

### 5. Testing Requirements

- Reset singletons between tests using `reset_instance()`
- Mock external dependencies (SSH, APIs)
- Test both success and failure paths
- Use fixtures from `tests/conftest.py`

```python
@pytest.fixture(autouse=True)
def reset_singletons():
    from athena_ai.core.registry import AgentRegistry
    AgentRegistry.reset_instance()
    yield
    AgentRegistry.reset_instance()
```

---

## Development Workflow

### Branch Strategy

```
main              # Production-ready, protected
  └── dev         # Integration branch
       ├── feat/xxx    # New features
       ├── fix/xxx     # Bug fixes
       └── docs/xxx    # Documentation
```

**Rules:**
- Never push directly to `main`
- All changes via Pull Request
- PRs require at least 1 review
- CI must pass before merge

### Commit Convention

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation
- `refactor`: Code refactoring
- `test`: Tests
- `chore`: Maintenance

**Examples:**
```bash
feat(repl): add /export command for session history
fix(ssh): handle connection timeout gracefully
docs(readme): update installation instructions
refactor(orchestrator): extract LLM routing logic
```

### Pull Request Template

```markdown
## Summary
Brief description of changes

## Type
- [ ] Feature
- [ ] Bug fix
- [ ] Documentation
- [ ] Refactoring

## Testing
- [ ] Unit tests added/updated
- [ ] Manual testing done
- [ ] No breaking changes

## Checklist
- [ ] Code follows project style
- [ ] Documentation updated
- [ ] CHANGELOG updated (if user-facing)
```

## Code Style

### Python

- Python 3.11+
- Type hints everywhere
- Docstrings for public functions
- Max line length: 100 chars

```python
def execute_command(
    target: str,
    command: str,
    timeout: int = 60
) -> dict[str, Any]:
    """
    Execute command on target host.

    Args:
        target: Hostname or IP
        command: Shell command
        timeout: Timeout in seconds

    Returns:
        Dict with 'success', 'stdout', 'stderr', 'exit_code'
    """
```

### Imports

```python
# Standard library
import os
from typing import Optional

# Third-party
import click
from rich.console import Console

# Local
from athena_ai.utils.logger import logger
```

### Logging & Visual Output

**Use emojis and colors for user-facing output.** This improves readability and helps users quickly identify issues.

#### Emoji Convention

| Category | Emoji | Usage |
|----------|-------|-------|
| Success | ✅ | Operation completed successfully |
| Error | ❌ | Operation failed |
| Warning | ⚠️ | Something unexpected but recoverable |
| Info | ℹ️ | General information |
| Thinking | 🧠 | AI processing/reasoning |
| Executing | ⚡ | Command execution |
| Security | 🔒 | Security-related messages |
| Question | ❓ | Awaiting user input |
| Host | 🖥️ | Host/server related |
| Network | 🌐 | Network operations |
| Database | 🗄️ | Database operations |
| Time | ⏱️ | Timing/performance |
| Critical | 🚨 | Critical alert (P0/P1) |

#### Rich Console for User Output

Use `DisplayManager` for all user-facing output:

```python
from athena_ai.utils.display import get_display_manager

display = get_display_manager()

# Success
display.console.print("✅ [bold green]Command executed successfully[/bold green]")

# Error
display.console.print("❌ [bold red]Connection failed[/bold red]: timeout after 30s")

# Warning
display.console.print("⚠️ [yellow]Host not in registry, using direct connection[/yellow]")

# Execution
display.console.print("⚡ [blue]Executing on web-prod-01:[/blue] systemctl status nginx")

# Security
display.console.print("🔒 [cyan]Risk level:[/cyan] [bold red]critical[/bold red] - requires confirmation")

# Critical alert
display.console.print("🚨 [bold red]P0 ALERT:[/bold red] Production database unreachable!")
```

#### Logger for Debug/Internal Logs

Use `logger` for internal/debug logs (not user-facing):

```python
from athena_ai.utils.logger import logger

logger.debug("Detailed info for debugging")
logger.info("General operational info")
logger.warning("Something unexpected")
logger.error("Error occurred")
```

#### Examples in Context

```python
# Good: Visual feedback with emoji and color
def execute_command(target: str, command: str) -> dict:
    display = get_display_manager()

    display.console.print(f"⚡ [blue]Executing on {target}:[/blue] {command}")

    result = executor.run(command)

    if result["success"]:
        display.console.print(f"✅ [green]Success[/green] (exit code: 0)")
    else:
        display.console.print(f"❌ [red]Failed[/red] (exit code: {result['exit_code']})")
        display.console.print(f"   [dim]{result['stderr']}[/dim]")

    return result

# Good: Priority-based visual alerts
def show_priority_alert(priority: str, message: str):
    display = get_display_manager()

    if priority == "P0":
        display.console.print(f"🚨 [bold red]P0 CRITICAL:[/bold red] {message}")
    elif priority == "P1":
        display.console.print(f"⚠️ [bold yellow]P1 URGENT:[/bold yellow] {message}")
    elif priority == "P2":
        display.console.print(f"ℹ️ [blue]P2:[/blue] {message}")
    else:
        display.console.print(f"📋 [dim]P3:[/dim] {message}")
```

## Project Structure

```
athena/
├── athena_ai/
│   ├── __init__.py          # Package version
│   ├── cli.py               # CLI entry point
│   ├── repl.py              # Interactive REPL
│   ├── agents/              # AI agents (AutoGen)
│   ├── context/             # Infrastructure context
│   ├── domains/             # Domain services
│   ├── executors/           # SSH, Ansible, etc.
│   ├── knowledge/           # Knowledge graph
│   ├── llm/                 # LLM routing
│   ├── memory/              # Conversation memory
│   ├── security/            # Auth, permissions
│   └── utils/               # Utilities
├── docs/                    # Documentation
├── tests/                   # Test suite
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── README.md
├── ROADMAP.md
└── pyproject.toml
```

## Testing

### Run Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=athena_ai

# Specific test
pytest tests/test_ssh.py -v
```

### Test Naming

```python
def test_ssh_execute_success():
    """SSH execute returns stdout on success."""

def test_ssh_execute_timeout():
    """SSH execute handles timeout gracefully."""
```

## Documentation

### Where to Document

| What | Where |
|------|-------|
| User guide | README.md |
| API reference | docs/API.md |
| Architecture | docs/ARCHITECTURE.md |
| Changelog | CHANGELOG.md |
| Roadmap | ROADMAP.md |

### Documentation Updates

- Update docs with every user-facing change
- Keep CHANGELOG.md current
- Add docstrings to new functions

## Release Process

1. Update version in `athena_ai/__init__.py`
2. Update CHANGELOG.md
3. Create PR to main
4. After merge, create GitHub release
5. CI publishes to PyPI

## Getting Help

- Issues: https://github.com/m-kis/athena/issues
- Discussions: https://github.com/m-kis/athena/discussions
