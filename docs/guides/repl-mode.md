# REPL Mode

Merlya's REPL (Read-Eval-Print Loop) is the main interactive interface for working with your infrastructure.

## Starting the REPL

```bash
merlya
```

## Welcome Screen

On startup, Merlya displays a status banner (provider/router/keyring) and an experimental warning.
Use `/help` to see the available slash commands.

!!! warning "Experimental Software"
    Merlya is in early development. Always review commands before executing them on production systems.

---

## Features

### Natural Language Input

Just type your request in plain English (or French):

```
Merlya > Check disk space on all web servers
Merlya > Redémarre nginx sur web-01
Merlya > Show me the logs from the last hour on db-master
```

### Autocompletion

The REPL provides intelligent autocompletion:

- **Slash commands**: Type `/` and press Tab
- **Host mentions**: Type `@` and press Tab to see available hosts
- **Variable mentions**: Type `@` to reference saved variables

### Host Names and Secret References

Reference hosts by name and secrets with `@` prefix:

```
Merlya > Check memory on web-01 and web-02
Merlya > Deploy using @deploy_key credentials
```

Host names are resolved from inventory. Secrets (`@name`) are resolved from keyring.

### Command History

- **Up/Down arrows**: Navigate through previous commands
- History is persisted across sessions in `~/.merlya/history`

---

## Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/help <command>` | Show help for a specific command |
| `/new [title]` | Start a new conversation |
| `/conv list` | List saved conversations |
| `/conv load <id>` | Load a previous conversation |
| `/hosts` | List configured hosts |
| `/hosts add <name>` | Add a new host (interactive) |
| `/scan` | Scan for infrastructure |
| `/model show` | Show current model/router status |
| `/language <code>` | Set the REPL language (e.g., `/language fr`) |
| `/exit` | Exit the REPL |

### Examples

```
Merlya > /help
Merlya > /hosts
Merlya > /hosts add prod-db --test
Merlya > /model provider openai
Merlya > /model model gpt-4o
Merlya > /new "Debugging nginx issue"
```

---

## Status Indicators

The welcome screen shows system status:

| Indicator | Meaning |
|-----------|---------|
| ✅ | Feature is working correctly |
| ⚠️ | Feature has warnings (check message) |
| ❌ | Feature is unavailable |

### Provider Status

```
Provider: ✅ openrouter (amazon/nova-2-lite-v1:free)
```

Shows the configured LLM provider and model.

### Router Status

```
Router: ✅ local (intent-classifier-v1)
```

- **local**: Using pattern matching for intent classification (fast, offline)
- **llm fallback**: Using LLM for routing when confidence is low

### Keyring Status

```
Keyring: ✅ Keyring
Keyring: ⚠️ Keyring unavailable (in-memory)
```

API keys are stored securely in your system keyring. If unavailable, they're stored in memory only (lost on exit).

---

## Response Format

Agent responses include:

```
Merlya > Check uptime on web-01

Connecting to web-01.example.com...

> ssh web-01 "uptime"

 14:32:01 up 45 days,  3:21,  2 users,  load average: 0.15, 0.10, 0.05

The server has been running for 45 days with low load average, indicating
stable operation and low system stress.

Actions: ssh_execute
Suggestions: Check memory usage, Review recent logs
```

- **Command output**: The actual command executed and its output
- **Analysis**: AI-generated analysis of the results
- **Actions**: List of tools/actions used
- **Suggestions**: Recommended follow-up actions

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+C` | Cancel current request |
| `Ctrl+D` | Exit REPL |
| `Tab` | Autocomplete |
| `↑` / `↓` | Navigate history |
| `Ctrl+R` | Search history |

---

## Session Management

### New Conversation

```
Merlya > /new "Investigating slow queries"
```

Clears history and starts fresh. Optionally provide a title.

### List Conversations

```
Merlya > /conv list

ID      | Title                      | Messages | Last Updated
--------|----------------------------|----------|-------------
abc123  | Debugging nginx issue      | 15       | 2 hours ago
def456  | Server migration           | 42       | Yesterday
ghi789  | Investigating slow queries | 3        | Just now
```

### Load Conversation

```
Merlya > /conv load abc123

Loaded conversation: "Debugging nginx issue" (15 messages)
```

---

## Tips for Best Results

1. **Be specific**: "Check disk space on web-01" is better than "check disk"
2. **Provide context**: "The nginx service crashed after the update"
3. **Name your targets**: Use the hostname from inventory or specify the server explicitly
4. **Review before executing**: Always check commands before running on production
5. **Use slash commands**: Quick actions like `/hosts` are faster than natural language

---

## Language Support

Merlya supports English and French. Set your language:

```bash
merlya config set general.language fr
```

Or use `/language fr` inside the REPL.
