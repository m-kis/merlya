# Athena Tools Reference

This document describes all built-in tools available in Athena for infrastructure management.

## Overview

Tools are modular functions that execute specific infrastructure operations. They follow the Single Responsibility Principle (SRP) and are organized by domain.

```
athena_ai/tools/
├── base.py          # Core utilities, context injection
├── commands.py      # Command execution
├── hosts.py         # Host discovery and scanning
├── files.py         # File operations
├── system.py        # System information
├── security.py      # Security audits
├── containers.py    # Docker/Kubernetes
├── web.py           # Web operations
├── interaction.py   # User interaction
└── infra_tools.py   # Code generation (Terraform, Ansible, Dockerfile)
```

---

## Core Tools

### `execute_command(target, command, reason, timeout=30)`

Execute a shell command on a target host.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `target` | `str` | Yes | Hostname or 'local' |
| `command` | `str` | Yes | Shell command to execute |
| `reason` | `str` | Yes | Justification for audit trail |
| `timeout` | `int` | No | Timeout in seconds (default: 30) |

**Returns:** `str` - Command output or error message

**Example:**
```python
result = execute_command(
    target="web-prod-01",
    command="systemctl status nginx",
    reason="Check nginx status for debugging"
)
```

**Risk Levels:**
- `low`: Read-only commands (ps, df, cat, ls)
- `moderate`: Configuration changes (chmod, chown, mkdir)
- `critical`: Service control, deletions (rm, shutdown, reboot)

---

### `add_route(target, destination, gateway, interface=None)`

Add a network route on a target host.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `target` | `str` | Yes | Target hostname |
| `destination` | `str` | Yes | Destination network (e.g., "10.0.0.0/8") |
| `gateway` | `str` | Yes | Gateway IP address |
| `interface` | `str` | No | Network interface |

**Returns:** `str` - Success/error message

---

## Host Discovery Tools

### `list_hosts()`

List all known hosts from the infrastructure inventory.

**Returns:** `str` - Formatted list of hostnames with their sources

**Sources checked:**
- SSH config (`~/.ssh/config`)
- `/etc/hosts`
- Ansible inventory (if configured)
- Custom inventory files

---

### `scan_host(hostname)`

Scan a host on-demand (JIT - Just In Time) to gather system information.

This function is called automatically when connecting to a new host for the first time.
Results are cached with a 30-minute TTL.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `hostname` | `str` | Yes | Host to scan |

**Returns:** `str` - Host information including:

- IP address and reachability
- OS version (if accessible via SSH)
- Basic system info

**Caching:** Results are cached per host. Use `/refresh <hostname>` to force rescan.

---

### `check_permissions(target)`

Check what permissions are available on a target host.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `target` | `str` | Yes | Target hostname |

**Returns:** `str` - Permission summary:
- Current user
- Sudo availability
- SSH key status
- Writable directories

---

### `get_infrastructure_context()`

Get a summary of the entire infrastructure.

**Returns:** `str` - Infrastructure overview:
- Total hosts count
- Hosts by environment (prod, staging, dev)
- Connection status summary

---

## File Operations

### `read_remote_file(host, path, lines=100)`

Read a file from a remote host.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `host` | `str` | Yes | Target hostname |
| `path` | `str` | Yes | Absolute file path |
| `lines` | `int` | No | Number of lines to read (default: 100) |

**Returns:** `str` - File contents

---

### `write_remote_file(host, path, content, backup=True)`

Write content to a file on a remote host.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `host` | `str` | Yes | Target hostname |
| `path` | `str` | Yes | Absolute file path |
| `content` | `str` | Yes | Content to write |
| `backup` | `bool` | No | Create backup before writing (default: True) |

**Returns:** `str` - Success/error message with backup path if created

---

### `tail_logs(host, path, lines=50, grep=None)`

Tail a log file on a remote host.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `host` | `str` | Yes | Target hostname |
| `path` | `str` | Yes | Log file path |
| `lines` | `int` | No | Number of lines (default: 50) |
| `grep` | `str` | No | Filter pattern |

**Returns:** `str` - Log contents

**Example:**
```python
# Get last 100 lines of nginx error log with "500" errors
result = tail_logs(
    host="web-prod-01",
    path="/var/log/nginx/error.log",
    lines=100,
    grep="500"
)
```

---

### `glob_files(host, pattern)`

Find files matching a glob pattern.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `host` | `str` | Yes | Target hostname |
| `pattern` | `str` | Yes | Glob pattern (e.g., "/var/log/*.log") |

**Returns:** `str` - List of matching files

---

### `grep_files(host, pattern, path)`

Search for a pattern in files.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `host` | `str` | Yes | Target hostname |
| `pattern` | `str` | Yes | Search pattern (regex) |
| `path` | `str` | Yes | File or directory path |

**Returns:** `str` - Matching lines with file names

---

### `find_file(host, name, path="/")`

Find files by name.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `host` | `str` | Yes | Target hostname |
| `name` | `str` | Yes | File name pattern |
| `path` | `str` | No | Search root (default: "/") |

**Returns:** `str` - List of matching file paths

---

## System Information

### `disk_info(host)`

Get disk usage information.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `host` | `str` | Yes | Target hostname |

**Returns:** `str` - Disk usage per mount point

---

### `memory_info(host)`

Get memory usage information.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `host` | `str` | Yes | Target hostname |

**Returns:** `str` - Memory statistics (total, used, free, cached)

---

### `process_list(host, filter=None)`

List running processes.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `host` | `str` | Yes | Target hostname |
| `filter` | `str` | No | Process name filter |

**Returns:** `str` - Process list with PID, CPU, memory usage

---

### `network_connections(host)`

Show network connections.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `host` | `str` | Yes | Target hostname |

**Returns:** `str` - Active network connections (listening ports, established connections)

---

### `service_control(host, service, action)`

Control a systemd service.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `host` | `str` | Yes | Target hostname |
| `service` | `str` | Yes | Service name |
| `action` | `str` | Yes | Action: start, stop, restart, status, enable, disable |

**Returns:** `str` - Service status after action

**Example:**
```python
result = service_control(
    host="web-prod-01",
    service="nginx",
    action="restart"
)
```

---

## Security Tools

### `audit_host(hostname)`

Perform a security audit on a host.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `hostname` | `str` | Yes | Target hostname |

**Returns:** `str` - Security audit report:
- Open ports
- Running services
- User accounts
- SSH configuration
- Firewall rules
- File permissions issues

---

### `analyze_security_logs(host, hours=24)`

Analyze security-related logs.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `host` | `str` | Yes | Target hostname |
| `hours` | `int` | No | Hours to analyze (default: 24) |

**Returns:** `str` - Security events summary:
- Failed login attempts
- Sudo usage
- SSH connections
- Suspicious activities

---

## Container Tools

### `docker_exec(container, command, host="local")`

Execute a command in a Docker container.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `container` | `str` | Yes | Container name or ID |
| `command` | `str` | Yes | Command to execute |
| `host` | `str` | No | Docker host (default: "local") |

**Returns:** `str` - Command output

**Example:**
```python
result = docker_exec(
    container="nginx-proxy",
    command="nginx -t",
    host="docker-host-01"
)
```

---

### `kubectl_exec(namespace, pod, command, container=None)`

Execute a command in a Kubernetes pod.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `namespace` | `str` | Yes | Kubernetes namespace |
| `pod` | `str` | Yes | Pod name |
| `command` | `str` | Yes | Command to execute |
| `container` | `str` | No | Container name (for multi-container pods) |

**Returns:** `str` - Command output

---

## Web Tools

### `web_search(query)`

Search the web for information.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `query` | `str` | Yes | Search query |

**Returns:** `str` - Search results summary

**Note:** Requires DuckDuckGo search (optional dependency)

---

### `web_fetch(url)`

Fetch content from a URL.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `url` | `str` | Yes | URL to fetch |

**Returns:** `str` - Page content (text extracted)

---

## User Interaction Tools

### `ask_user(question)`

Ask the user a question and wait for response.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `question` | `str` | Yes | Question to ask |

**Returns:** `str` - User's response

**Note:** Automatically pauses the spinner during input.

---

### `request_elevation(target, command, error_message, reason=None)`

Request privilege escalation after a permission error.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `target` | `str` | Yes | Target host |
| `command` | `str` | Yes | Failed command |
| `error_message` | `str` | Yes | Original error |
| `reason` | `str` | No | Explanation for user |

**Returns:** `str` - Result of elevated command or denial message

---

### `remember_skill(trigger, solution, context="")`

Teach Athena a new skill.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `trigger` | `str` | Yes | Problem description |
| `solution` | `str` | Yes | Solution command/procedure |
| `context` | `str` | No | Tags (e.g., "linux production") |

**Returns:** `str` - Confirmation

---

### `recall_skill(query)`

Search learned skills.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `query` | `str` | Yes | Search query |

**Returns:** `str` - Matching skills

---

## Code Generation Tools

### `GenerateTerraformTool`

Generate Terraform configurations.

**Methods:**
- `generate(resource_type, params)` - Generate HCL code
- `validate(code)` - Validate Terraform syntax

---

### `GenerateAnsibleTool`

Generate Ansible playbooks.

**Methods:**
- `generate(task_description, hosts)` - Generate playbook YAML
- `validate(playbook)` - Validate playbook syntax

---

### `GenerateDockerfileTool`

Generate Dockerfiles.

**Methods:**
- `generate(base_image, requirements)` - Generate Dockerfile
- `validate(dockerfile)` - Validate Dockerfile syntax

---

## Batch Execution

### `execute_batch(actions, stop_on_failure=False, show_progress=True)`

Execute multiple actions with progress tracking.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `actions` | `List[Dict]` | Yes | List of action dictionaries |
| `stop_on_failure` | `bool` | No | Stop on first failure (default: False) |
| `show_progress` | `bool` | No | Show progress bar (default: True) |

**Action Dictionary:**

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `target` | `str` | Yes | Hostname or 'local' |
| `command` | `str` | Yes | Shell command |
| `action_type` | `str` | No | Action type (default: 'shell') |
| `confirm` | `bool` | No | Skip risk confirmation |
| `timeout` | `int` | No | Timeout in seconds (default: 60) |

**Returns:** `List[Dict]` - List of execution results

**Example:**

```python
from athena_ai.executors.action_executor import ActionExecutor

executor = ActionExecutor()
results = executor.execute_batch([
    {"target": "web-01", "command": "systemctl status nginx"},
    {"target": "web-02", "command": "systemctl status nginx"},
    {"target": "db-01", "command": "systemctl status postgresql"},
], stop_on_failure=True)
```

---

## Context Utilities

### `DisplayManager`

Centralized display manager with spinners and progress bars.

```python
from athena_ai.utils.display import get_display_manager

display = get_display_manager()

# Spinner for long operations
with display.spinner("Connecting to host..."):
    # long operation
    pass

# Progress bar for batch operations
with display.progress_bar("Processing") as progress:
    task = progress.add_task("Items", total=10)
    for i in range(10):
        # do work
        progress.advance(task)

# Simple messages
display.show_success("Operation completed")
display.show_warning("Something might be wrong")
display.show_error("Operation failed", details="Connection timeout")
display.show_info("Processing started")
```

### `StatusManager` (Legacy)

Manages the Rich spinner/status that can be paused during user input.

```python
from athena_ai.tools import get_status_manager

status = get_status_manager()
status.set_console(console)
status.start("[cyan]Processing...[/cyan]")
# ... operations ...
status.stop()

# Pause for user input
with status.pause_for_input():
    response = input("Enter value: ")
```

---

### `ToolContext`

Dependency injection container for tools.

```python
from athena_ai.tools import get_tool_context

ctx = get_tool_context()
ctx.executor        # Command executor
ctx.permissions     # Permission manager
ctx.credentials     # Credential manager
ctx.console         # Rich console
```

---

## Error Handling

All tools follow consistent error handling:

```python
# Success
"✅ SUCCESS: Operation completed"
"✅ File written to /path/to/file"

# Errors
"❌ ERROR: Permission denied"
"❌ BLOCKED: Host 'unknown-host' not in inventory"
"❌ TIMEOUT: Command exceeded 30s limit"
```

---

## Security Considerations

1. **Host Validation**: All tools validate hostnames against the inventory
2. **Risk Assessment**: Commands are classified by risk level
3. **Audit Trail**: All operations are logged with timestamps and reasons
4. **Credential Isolation**: Credentials are never logged or displayed
5. **Permission Checks**: Elevation requests require user confirmation

---

## See Also

- [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- [CREDENTIALS.md](CREDENTIALS.md) - Credential management
- [TESTING.md](TESTING.md) - Testing tools
