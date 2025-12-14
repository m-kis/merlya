# API Reference

Merlya can be used as a Python library in your own applications.

## Installation

```bash
pip install merlya
```

## Quick Start

```python
from merlya import Merlya

# Initialize with default config
agent = Merlya()

# Or with custom settings
agent = Merlya(
    provider="openai",
    model="gpt-4o-mini",
    api_key="sk-..."
)

# Run a task
result = await agent.run("Check disk space on web servers")
print(result)
```

## Core Classes

### Merlya

Main entry point for the library.

```python
class Merlya:
    def __init__(
        self,
        provider: str = "openai",
        model: str = None,
        api_key: str = None,
        config_path: str = None
    )
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `provider` | str | LLM provider name |
| `model` | str | Model identifier |
| `api_key` | str | API key (uses keyring if not provided) |
| `config_path` | str | Custom config file path |

**Methods:**

#### run

Execute a natural language task.

```python
async def run(
    self,
    prompt: str,
    confirm: bool = True,
    timeout: int = 300
) -> TaskResult
```

#### chat

Start an interactive chat session.

```python
async def chat(
    self,
    system_prompt: str = None,
    history: list = None
) -> None
```

#### connect

Connect to an SSH host.

```python
async def connect(
    self,
    host: str,
    user: str = None,
    key: str = None
) -> SSHConnection
```

---

### SSHConnection

Represents an SSH connection.

```python
class SSHConnection:
    hostname: str
    user: str
    connected: bool
```

**Methods:**

#### execute

Run a command on the remote host.

```python
async def execute(
    self,
    command: str,
    sudo: bool = False,
    timeout: int = 60
) -> CommandResult
```

#### upload

Upload a file to the remote host.

```python
async def upload(
    self,
    local_path: str,
    remote_path: str
) -> None
```

#### download

Download a file from the remote host.

```python
async def download(
    self,
    remote_path: str,
    local_path: str
) -> None
```

#### close

Close the connection.

```python
async def close(self) -> None
```

---

### TaskResult

Result of a task execution.

```python
@dataclass
class TaskResult:
    success: bool
    output: str
    commands: list[CommandResult]
    analysis: str
    duration: float
```

---

### CommandResult

Result of a single command execution.

```python
@dataclass
class CommandResult:
    command: str
    stdout: str
    stderr: str
    exit_code: int
    host: str
    duration: float
```

---

## Usage Examples

### Basic Task Execution

```python
import asyncio
from merlya import Merlya

async def main():
    agent = Merlya()

    # Run a task
    result = await agent.run(
        "Check if nginx is running on web-01",
        confirm=False
    )

    if result.success:
        print(f"Output: {result.output}")
    else:
        print(f"Failed: {result.output}")

asyncio.run(main())
```

### SSH Operations

```python
import asyncio
from merlya import Merlya

async def main():
    agent = Merlya()

    # Connect to a server
    conn = await agent.connect("web-01.example.com", user="deploy")

    # Execute commands
    result = await conn.execute("uptime")
    print(f"Uptime: {result.stdout}")

    result = await conn.execute("df -h /")
    print(f"Disk: {result.stdout}")

    # Close connection
    await conn.close()

asyncio.run(main())
```

### Batch Operations

```python
import asyncio
from merlya import Merlya

async def check_server(agent, hostname):
    conn = await agent.connect(hostname)
    result = await conn.execute("uptime")
    await conn.close()
    return hostname, result.stdout

async def main():
    agent = Merlya()
    servers = ["web-01", "web-02", "web-03"]

    # Run in parallel
    tasks = [check_server(agent, s) for s in servers]
    results = await asyncio.gather(*tasks)

    for hostname, uptime in results:
        print(f"{hostname}: {uptime}")

asyncio.run(main())
```

### Custom LLM Provider

```python
from merlya import Merlya

# Use Ollama
agent = Merlya(
    provider="ollama",
    model="qwen2.5:7b",
    base_url="http://localhost:11434"
)

# Use Anthropic
agent = Merlya(
    provider="anthropic",
    model="claude-3-5-sonnet-20241022",
    api_key="sk-ant-..."
)
```

### Error Handling

```python
import asyncio
from merlya import Merlya
from merlya.exceptions import (
    ConnectionError,
    AuthenticationError,
    CommandError
)

async def main():
    agent = Merlya()

    try:
        conn = await agent.connect("server.example.com")
        result = await conn.execute("some-command")
    except ConnectionError as e:
        print(f"Connection failed: {e}")
    except AuthenticationError as e:
        print(f"Authentication failed: {e}")
    except CommandError as e:
        print(f"Command failed: {e.exit_code} - {e.stderr}")

asyncio.run(main())
```

## Type Hints

Merlya is fully typed. Use with your favorite IDE for autocompletion:

```python
from merlya import Merlya, TaskResult, SSHConnection

async def my_function(agent: Merlya) -> TaskResult:
    return await agent.run("Check servers")
```
