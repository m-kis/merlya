# Contributing to Athena

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

### Logging

Use `logger` from `athena_ai.utils.logger`:

```python
from athena_ai.utils.logger import logger

logger.debug("Detailed info for debugging")
logger.info("General operational info")
logger.warning("Something unexpected")
logger.error("Error occurred")
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
