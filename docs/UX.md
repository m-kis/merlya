# Merlya UX - Visual Feedback System

This document describes the visual feedback system that provides real-time status updates during long-running operations.

## Overview

Merlya provides visual feedback for operations that take more than 1 second, ensuring the user always knows what's happening. This includes:

- **Spinners** for single operations (LLM calls, SSH connections)
- **Progress bars** for batch operations (multi-host scans, batch execution)

## Display Manager

The `DisplayManager` is the central component for all visual feedback. It's a singleton that ensures consistent styling across the application.

### Basic Usage

```python
from merlya.utils.display import get_display_manager

display = get_display_manager()
```

### Spinners

Use spinners for single long-running operations:

```python
# Context manager (recommended)
with display.spinner("Processing request..."):
    result = perform_long_operation()

# With custom spinner type
with display.spinner("Connecting...", spinner_type="dots"):
    connection = establish_connection()
```

**Available spinner types:** `dots`, `line`, `arc`, `bouncingBall`, `moon`, etc.

### Progress Bars

Use progress bars for batch operations with known total:

```python
with display.progress_bar("Processing items") as progress:
    task = progress.add_task("[cyan]Items", total=100)

    for item in items:
        process(item)
        progress.advance(task)
```

**Progress bar features:**

- Spinner column (animated)
- Description column
- Bar column (visual progress)
- Percentage column
- Elapsed time column

### Simple Messages

```python
display.show_success("Operation completed successfully")
display.show_warning("Something might be wrong")
display.show_error("Operation failed", details="Connection timeout")
display.show_info("Processing started")
display.show_step(1, 5, "Initializing", status="running")
```

**Step statuses:** `pending`, `running`, `completed`, `failed`, `skipped`

## Integration Points

### LLM Router

The `LLMRouter.generate()` method shows a spinner during API calls:

```
🧠 Thinking (openrouter)...
```

**Parameters:**

- `show_spinner: bool = True` - Set to `False` to disable

```python
from merlya.llm.router import LLMRouter

router = LLMRouter()

# With spinner (default)
response = router.generate(prompt, system_prompt)

# Without spinner
response = router.generate(prompt, system_prompt, show_spinner=False)
```

### SSH Manager

The `SSHManager.execute()` method shows a spinner during connection:

```
🔌 Connecting to web-prod-01...
```

**Parameters:**

- `show_spinner: bool = True` - Set to `False` to disable

```python
from merlya.executors.ssh import SSHManager

ssh = SSHManager()

# With spinner (default)
exit_code, stdout, stderr = ssh.execute("web-01", "uptime")

# Without spinner (for batch operations)
exit_code, stdout, stderr = ssh.execute("web-01", "uptime", show_spinner=False)
```

### Context Manager

The `ContextManager._scan_remote_hosts()` method shows a progress bar for multi-host scans:

```
⠋ Scanning: web-prod-03 ━━━━━━━━━━━━━━━━━━ 60% 0:00:12
```

### Action Executor

The `ActionExecutor.execute_batch()` method shows a progress bar for batch execution:

```python
from merlya.executors.action_executor import ActionExecutor

executor = ActionExecutor()

# With progress bar (default)
results = executor.execute_batch([
    {"target": "web-01", "command": "systemctl status nginx"},
    {"target": "web-02", "command": "systemctl status nginx"},
    {"target": "db-01", "command": "systemctl status postgresql"},
])

# Without progress bar
results = executor.execute_batch(actions, show_progress=False)
```

## Nesting Behavior

The DisplayManager handles nested spinners gracefully:

```python
with display.spinner("Outer operation..."):
    # This prints a message instead of starting a nested spinner
    with display.spinner("Inner operation..."):
        do_inner_work()
```

When a spinner is already active, nested spinners will print their message as a simple status line instead of creating a visual conflict.

## Convenience Functions

For quick access, use the module-level convenience functions:

```python
from merlya.utils.display import spinner, progress_bar

# Spinner
with spinner("Processing..."):
    do_work()

# Progress bar
with progress_bar("Items", total=10) as p:
    task = p.add_task("Processing", total=10)
    for i in range(10):
        p.advance(task)
```

## Styling and Theming

The DisplayManager uses a custom Rich theme:

| Style | Color | Usage |
|-------|-------|-------|
| `info` | dim cyan | Information messages |
| `warning` | yellow | Warning messages |
| `error` | bold red | Error messages |
| `success` | bold green | Success messages |
| `command` | bold blue | Command display |
| `thinking` | italic dim white | LLM thinking indicator |
| `result` | white | Results display |
| `progress` | cyan | Progress indicators |

## Testing

For testing, reset the singleton to get a fresh instance:

```python
from merlya.utils.display import reset_display_manager

def test_display():
    reset_display_manager()
    display = get_display_manager()
    # test...
```

## Best Practices

1. **Always use spinners for operations > 1s**
   - LLM calls, SSH connections, HTTP requests

2. **Use progress bars for batch operations**
   - Multi-host scans, file processing, deployments

3. **Disable spinners in batch contexts**
   - When inside a progress bar, use `show_spinner=False`

4. **Provide meaningful messages**
   - Include the target or operation type in spinner messages

5. **Handle nested operations**
   - The DisplayManager handles this, but be aware of the behavior

## See Also

- [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- [TOOLS.md](TOOLS.md) - Available tools
- [CONTRIBUTING.md](../CONTRIBUTING.md) - Logging and display conventions
