# Non-Interactive Mode Reference

Complete reference for Merlya's non-interactive (batch) execution mode.

## Overview

Non-interactive mode (`merlya run`) executes commands without user interaction, making it ideal for:

- **CI/CD pipelines** (GitHub Actions, GitLab CI, Jenkins)
- **Scheduled tasks** (cron, systemd timers)
- **Shell scripts** and automation
- **Docker containers**
- **Monitoring and alerting**

## Command Syntax

```bash
merlya run [OPTIONS] [COMMAND]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `COMMAND` | Natural language command or slash command to execute |

### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--file FILE` | `-f` | Load tasks from YAML or text file |
| `--yes` | `-y` | Skip confirmation prompts (auto-confirm) |
| `--format FORMAT` | | Output format: `text` (default) or `json` |
| `--quiet` | `-q` | Minimal output (errors only) |
| `--verbose` | | Enable verbose logging (use `merlya --verbose run ...`) |
| `--help` | | Show help message |

---

## Single Command Execution

Execute a single command:

```bash
merlya run "Check disk space on all web servers"
```

With auto-confirmation (required for commands that modify systems):

```bash
merlya run --yes "Restart nginx on web-01"
```

---

## Slash Commands

Execute internal Merlya commands directly without AI processing:

```bash
merlya run "/scan web-01"
merlya run "/hosts list"
merlya run "/health"
```

### Allowed Commands

Most read-only and diagnostic commands work in batch mode:

| Command | Description |
|---------|-------------|
| `/health` | Check system health |
| `/hosts list` | List all hosts |
| `/hosts show <name>` | Show host details |
| `/hosts import <file>` | Import hosts from file |
| `/hosts export <file>` | Export hosts to file |
| `/hosts tag <name> <tag>` | Add tag to host |
| `/hosts untag <name> <tag>` | Remove tag from host |
| `/scan <host>` | Scan host for system info |
| `/model show` | Show current model config |
| `/model provider <name>` | Change LLM provider |
| `/model model <name>` | Change model |
| `/log level <level>` | Set log level |
| `/variable list` | List variables |
| `/variable get <name>` | Get variable value |
| `/secret list` | List secret names |

### Blocked Commands

These commands are not available in batch mode:

| Command | Reason |
|---------|--------|
| `/exit`, `/quit`, `/q` | Session control (no session in batch) |
| `/new` | Starts new conversation |
| `/conv`, `/conversation` | Requires conversation context |

### Interactive Commands

These commands require user input and cannot run in batch mode:

| Command | Reason |
|---------|--------|
| `/hosts add <name>` | Prompts for hostname, port, username |
| `/ssh config <host>` | Prompts for SSH configuration |
| `/secret set <name>` | Requires secure input prompt |

### Examples

```bash
# Quick health check
merlya run "/health"

# List all hosts with production tag
merlya run "/hosts list --tag=production"

# Scan a server
merlya run "/scan web-01 --quick"

# Full scan with JSON output
merlya run --format json "/scan web-01 --full"

# Import hosts from SSH config
merlya run "/hosts import ~/.ssh/config --format=ssh"

# Change model for subsequent commands
merlya run "/model provider anthropic"
```

---

## Task File Execution

Execute multiple tasks from a file:

```bash
merlya run --file tasks.yml
```

### YAML Format

```yaml
# tasks.yml
tasks:
  - description: "Check disk space"
    prompt: "Check disk usage on all servers, warn if above 80%"

  - description: "Check memory"
    prompt: "Check memory usage on all servers"

  - prompt: "Verify nginx is running on web tier"
```

Fields:

| Field | Required | Description |
|-------|----------|-------------|
| `prompt` | Yes | The natural language command |
| `description` | No | Human-readable task description |

### Text Format

Simple one-command-per-line format:

```text
# tasks.txt
Check disk space on all servers
List running services
Verify backup status from last 24h
```

Lines starting with `#` are treated as comments.

---

## Output Formats

### Text Output (Default)

Human-readable output:

```bash
merlya run "Check uptime on web-01"
```

```
Running health checks...
Executing: Check uptime on web-01

> ssh web-01 "uptime"
 14:32:01 up 45 days,  3:21,  2 users,  load average: 0.15, 0.10, 0.05

The server has been running for 45 days with low load average.

Completed: 1/1 tasks passed
```

### JSON Output

Machine-parseable output for automation:

```bash
merlya run --format json "Check uptime on web-01"
```

```json
{
  "success": true,
  "total": 1,
  "passed": 1,
  "failed": 0,
  "tasks": [
    {
      "task": "Check uptime on web-01",
      "success": true,
      "message": "The server has been running for 45 days with low load average.",
      "actions": ["ssh_execute"]
    }
  ]
}
```

### Quiet Mode

Only errors are displayed:

```bash
merlya run --quiet --yes "Check server health"
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All tasks succeeded |
| 1 | One or more tasks failed |

Use exit codes in scripts:

```bash
#!/bin/bash
if merlya run --quiet --yes "Check all servers healthy"; then
    echo "All systems operational"
else
    echo "Issues detected!"
    exit 1
fi
```

---

## Environment Variables

Configure Merlya via environment variables (useful in containers):

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `MERLYA_ROUTER_MODEL` | Override local router model |
| `MERLYA_ROUTER_FALLBACK` | LLM fallback model |

Example:

```bash
OPENROUTER_API_KEY=or-xxx merlya run "Check disk space"
```

---

## Use Cases

### Cron Job

```bash
# /etc/cron.d/merlya-health
0 6 * * * root /usr/local/bin/merlya run --format json --yes \
    "Run daily health checks" >> /var/log/merlya/daily.log 2>&1
```

### Shell Script

```bash
#!/bin/bash
set -e

LOG_FILE="/var/log/merlya/deploy.log"

echo "$(date): Starting deployment" >> $LOG_FILE

# Pre-flight checks
RESULT=$(merlya run --format json --yes "Verify all servers healthy")

if echo "$RESULT" | jq -e '.success' > /dev/null; then
    echo "$(date): Pre-flight passed" >> $LOG_FILE
    merlya run --yes "Deploy version $VERSION to production"
else
    echo "$(date): Pre-flight FAILED" >> $LOG_FILE
    exit 1
fi
```

### GitHub Actions

```yaml
- name: Health Check
  env:
    OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
  run: |
    pip install merlya
    merlya run --format json --yes "Check all production servers"
```

### Docker

```bash
docker run -e OPENROUTER_API_KEY=or-xxx merlya:latest \
    run --yes --format json "Check disk space"
```

---

## Best Practices

1. **Always use `--yes` in automation** - Prompts will hang without TTY
2. **Use `--format json` for parsing** - Reliable structured output
3. **Check exit codes** - Handle failures gracefully
4. **Log output** - Keep records of automated actions
5. **Test in staging first** - Before automating production tasks
6. **Set timeouts** - Wrap long-running commands with `timeout`

```bash
# Example with timeout
timeout 300 merlya run --yes "Deploy to production" || {
    echo "Deployment timed out after 5 minutes"
    exit 1
}
```

---

## Credential Requirements

When using `--yes` mode with commands that require elevated privileges (sudo, su), you must pre-configure credentials.

### Why Credentials Can't Be Prompted

In non-interactive mode:

- No TTY available for password prompts
- `--yes` auto-confirms but can't provide credentials
- Agent will fail immediately with clear error message

### Solutions

#### 1. Store in Keyring (Recommended)

```bash
# Store sudo password for a specific host
merlya secret set sudo:192.168.1.7:password

# Store for multiple hosts
merlya secret set sudo:web-01:password
merlya secret set sudo:db-01:password
```

#### 2. Configure NOPASSWD Sudo

On target hosts, add to `/etc/sudoers.d/merlya`:

```bash
# Allow specific user to run commands without password
cedric ALL=(ALL) NOPASSWD: ALL

# Or limit to specific commands
cedric ALL=(ALL) NOPASSWD: /usr/bin/systemctl, /usr/bin/journalctl
```

#### 3. Use Interactive Mode

For one-off elevated commands, run without `--yes`:

```bash
merlya run "Restart nginx on web-01"
# Merlya will prompt for password when needed
```

### Error Messages

When credentials are missing in `--yes` mode:

```text
❌ Cannot obtain credentials in non-interactive mode.

Missing: password for sudo@192.168.1.7

To fix this, before running in --yes mode:
1. Store credentials in keyring:
   merlya secret set sudo:192.168.1.7:password
2. Or configure NOPASSWD sudo on the target host
3. Or run in interactive mode (without --yes)
```

---

## Troubleshooting

### "Health checks failed"

The LLM provider is not configured or unreachable:

```bash
# Check configuration
merlya config show

# Set API key
export OPENROUTER_API_KEY=or-xxx
```

### "Host not found"

The target host is not in the inventory:

```bash
# List available hosts
merlya run "List all hosts"

# Or add the host first (interactive mode)
merlya
/hosts add web-01
```

### No output in JSON mode

Ensure you're capturing both stdout and stderr:

```bash
RESULT=$(merlya run --format json "..." 2>&1)
```
