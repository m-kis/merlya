# Contributing to Merlya

This document outlines the development principles, architectural patterns, and workflow that all contributors must follow.

## Development Principles

### 1. SOLID Principles

#### Single Responsibility Principle (SRP)

Each class/module has one reason to change.

```python
# Good: Dedicated classes
class RiskAssessor:
    """Evaluates risk only."""
    pass

class AuditLogger:
    """Logs audit events only."""
    pass

class HostRegistry:
    """Manages host validation only."""
    pass

# Bad: God classes
class ServerManager:
    """Manages, executes, logs, validates... everything."""
    pass
```

#### Open/Closed Principle (OCP)

Open for extension, closed for modification. Use the Registry pattern.

```python
# Good: Register new agents without modifying existing code
from merlya.agent import AgentRegistry

registry = AgentRegistry.get_instance()
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
from abc import ABC, abstractmethod

class LLMRouter(ABC):
    @abstractmethod
    async def chat(self, messages: list[Message]) -> Response:
        pass

class BaseAgent:
    def __init__(
        self,
        context: SharedContext,
        llm: LLMRouter | None = None,
        executor: ActionExecutor | None = None,
    ):
        self.context = context
        self.llm = llm or create_default_llm()
        self.executor = executor or create_default_executor()

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
    _instance: "MyManager | None" = None

    def __new__(cls) -> "MyManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset for tests."""
        cls._instance = None
```

#### Registry Pattern

Use for dynamic registration and lookup.

```python
from typing import TypeVar, Generic

T = TypeVar("T")

class Registry(Generic[T]):
    def __init__(self):
        self._items: dict[str, type[T]] = {}

    def register(self, name: str, cls: type[T]) -> None:
        self._items[name] = cls

    def get(self, name: str, **kwargs) -> T:
        return self._items[name](**kwargs)
```

### 3. Security-First Design

**Never execute commands on unvalidated hosts.**

```python
from merlya.hosts import HostResolver, HostNotFoundError

resolver = HostResolver(host_repo)
try:
    resolved = await resolver.resolve(hostname)
except HostNotFoundError as e:
    return {"error": e.message, "suggestions": e.suggestions}
```

**Always validate inputs with Pydantic.**

```python
from pydantic import BaseModel, field_validator

class CommandInput(BaseModel):
    target: str
    command: str
    timeout: int = 60

    @field_validator("target")
    @classmethod
    def validate_target(cls, v: str) -> str:
        if not v or ".." in v or v.startswith("/"):
            raise ValueError("Invalid target")
        return v

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        if v < 1 or v > 3600:
            raise ValueError("Timeout must be 1-3600")
        return v
```

### 4. Error Handling

Use the unified exception hierarchy:

```python
from merlya.hosts import HostNotFoundError

# Raise specific exceptions
if not host_valid:
    raise HostNotFoundError(
        f"Host '{hostname}' not found",
        suggestions=find_similar_hosts(hostname),
    )
```

### 5. Testing Requirements

- Reset singletons between tests using `reset_instance()`
- Mock external dependencies (SSH, APIs)
- Test both success and failure paths

```python
import pytest
from merlya.ssh import SSHPool

@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset all singletons between tests."""
    yield
    SSHPool.reset_instance()

async def test_ssh_execute_success(mock_ssh):
    pool = SSHPool.get_instance()
    stdout, stderr, code = await pool.execute("host", "uptime")
    assert code == 0
```

---

## Code Quality Standards

| Metric | Target | Enforcement |
|--------|--------|-------------|
| Max lines per file | 600 | Code review |
| Max lines per function | 50 | Code review |
| Max parameters per function | 4 | Ruff + review |
| No `Any` type | Required | mypy strict |
| No `print()` | Required | Ruff (use logger) |
| All inputs validated | Required | Pydantic |
| Test coverage | > 80% | CI |

---

## Logging & Visual Output

**Use emojis for ALL output** (user-facing AND logs).

### Emoji Convention

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
| Timer | ⏱️ | Timing/performance |
| Critical | 🚨 | Critical alert (P0/P1) |
| Scan | 🔍 | Scan/discovery |
| Config | ⚙️ | Configuration |
| File | 📁 | File operations |
| Log | 📋 | Logs/history |

### Logger Usage

```python
from loguru import logger

# Always use emojis in logs
logger.debug("🔍 Detailed info for debugging")
logger.info("✅ Operation completed successfully")
logger.info("⚡ Executing command on host")
logger.info("🖥️ Scanning host web-prod-01")
logger.warning("⚠️ Something unexpected happened")
logger.error("❌ Operation failed: connection refused")
```

---

## Development Workflow

### Branch Strategy

```
main              # Production-ready, protected
  └── feat/xxx    # New features
  └── fix/xxx     # Bug fixes
  └── docs/xxx    # Documentation
  └── refactor/xxx # Refactoring
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

---

## Project Structure

```
merlya/
├── merlya/
│   ├── __init__.py
│   ├── core/               # SharedContext, types, logging
│   │   ├── context.py      # SharedContext (socle commun)
│   │   ├── types.py        # Enums, dataclasses
│   │   └── logging.py      # Loguru config + emoji helpers
│   ├── config/             # Configuration
│   │   ├── models.py       # Pydantic config models
│   │   └── loader.py       # YAML loader
│   ├── i18n/               # Internationalization
│   │   ├── loader.py       # Translation loader
│   │   └── locales/        # JSON locale files
│   │       ├── en.json
│   │       └── fr.json
│   ├── persistence/        # SQLite storage
│   │   ├── database.py     # Database connection
│   │   ├── models.py       # Data models
│   │   └── repositories.py # Data access layer
│   ├── secrets/            # Keyring integration
│   │   └── store.py        # Secret storage
│   ├── health/             # Startup checks
│   │   └── checks.py       # Health check implementations
│   ├── hosts/              # Host management
│   │   └── resolver.py     # Host resolution
│   ├── ssh/                # SSH executor
│   │   └── pool.py         # Connection pool
│   ├── ui/                 # Console interface
│   │   └── console.py      # Rich-based UI
│   ├── router/             # Intent classification
│   ├── agent/              # PydanticAI agent
│   ├── commands/           # Slash commands
│   ├── tools/              # Agent tools
│   │   ├── core/           # Always-active tools
│   │   ├── system/         # System info tools
│   │   ├── files/          # File operation tools
│   │   └── security/       # Security tools
│   └── setup/              # First-run wizard
├── tests/                  # Test files
├── pyproject.toml          # Project config
├── ARCHITECTURE_DECISIONS.md
├── CONTRIBUTING.md
└── README.md
```

---

## Testing

### Run Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=merlya

# Specific module
pytest tests/test_ssh.py

# Watch mode
pytest-watch
```

### Test Naming

```python
class TestSSHPool:
    async def test_returns_stdout_on_success(self):
        ...

    async def test_handles_timeout_gracefully(self):
        ...

    async def test_raises_error_for_blocked_commands(self):
        ...
```

---

## Linting & Formatting

```bash
# Check lint errors
ruff check .

# Fix lint errors
ruff check --fix .

# Format code
ruff format .

# Type check
mypy merlya/
```

---

## i18n Guidelines

### Adding Translations

1. Add key to `merlya/i18n/locales/en.json` (required)
2. Add key to `merlya/i18n/locales/fr.json`
3. Use the `t()` function in code

```python
from merlya.i18n import t

# Simple translation
message = t("commands.hosts.added", name="web-01")

# Output: "Host 'web-01' added"
```

### Key Naming Convention

Use dot-separated hierarchical keys:
- `commands.<command>.<action>` - Command output
- `errors.<category>.<type>` - Error messages
- `prompts.<type>` - User prompts
- `health.<check>.<status>` - Health check messages

---

## Documentation

Documentation lives in this repository and is built with **MkDocs Material**.

### Structure

```text
merlya/
├── mkdocs.yml              # MkDocs configuration + navigation
├── docs/                   # Markdown source files
│   ├── index.md
│   ├── getting-started/
│   ├── guides/
│   ├── reference/          # CLI, configuration, API docs
│   └── architecture/
└── .github/workflows/
    └── docs.yml            # Build + deploy to GitHub Pages
```

### Updating Documentation

1. Install documentation dependencies:

   ```bash
   pip install -e ".[docs]"
   ```

2. Preview locally:

   ```bash
   mkdocs serve  # Opens http://localhost:8000
   ```

3. Commit and push (Conventional Commits):

   ```bash
   git add . && git commit -m "docs: update documentation"
   git push
   ```

The documentation is **automatically deployed** to GitHub Pages on push to `main`.

### When to Update Documentation

- New CLI commands or options → `docs/reference/cli.md`
- New features in `merlya run` → `docs/reference/non-interactive.md`
- Configuration changes → `docs/reference/configuration.md`
- New guides or tutorials → `docs/guides/`

---

## Release Process

1. Update version in `pyproject.toml` and `merlya/__init__.py`
2. Update CHANGELOG.md
3. Create PR to main
4. After merge, tag the version: `git tag v0.x.x && git push --tags`
5. CI builds and publishes to PyPI

---

## Getting Help

- Issues: https://github.com/m-kis/merlya/issues
- Discussions: https://github.com/m-kis/merlya/discussions
