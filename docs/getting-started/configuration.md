# Configuration

Merlya uses a layered configuration system with sensible defaults.

## Configuration Files

| File | Purpose |
|------|---------|
| `~/.merlya/config.yaml` | Main configuration |
| `~/.merlya/merlya.db` | Hosts inventory (SQLite) |
| `~/.merlya/history` | Command history |
| `~/.merlya/logs/` | Log files |

## Configuration File

Configuration is stored in `~/.merlya/config.yaml`:

```yaml
# ~/.merlya/config.yaml
general:
  language: en          # UI language (en, fr)
  log_level: info       # debug, info, warning, error

model:
  provider: openrouter  # openrouter, anthropic, openai, ollama
  model: amazon/nova-2-lite-v1:free
  api_key_env: OPENROUTER_API_KEY

router:
  type: local           # local (pattern matching) or llm
  llm_fallback: openrouter:google/gemini-2.0-flash-lite-001

ssh:
  connect_timeout: 30
  pool_timeout: 600
  command_timeout: 60
```

## Setting Values

Use the `config` command to manage settings:

```bash
# Set a value
merlya config set model.provider anthropic

# Get a value
merlya config get model.provider

# Show all settings
merlya config show
```

## Environment Variables

API keys and settings can be set via environment variables:

```bash
export OPENROUTER_API_KEY=or-xxx
export OPENAI_API_KEY=sk-xxx
export ANTHROPIC_API_KEY=sk-ant-xxx
export OLLAMA_API_KEY=xxx  # For cloud Ollama only

# Override settings
export MERLYA_ROUTER_FALLBACK=openai:gpt-4o-mini
```

## LLM Configuration

### Provider Settings

| Setting | Description | Default |
|---------|-------------|---------|
| `model.provider` | LLM provider | `openrouter` |
| `model.model` | Model name/ID | `amazon/nova-2-lite-v1:free` |
| `model.api_key_env` | Env var name for API key | auto |

**Supported Providers:**

| Provider | Description |
|----------|-------------|
| `openrouter` | 100+ models, free tier available (default) |
| `anthropic` | Claude models |
| `openai` | GPT models |
| `mistral` | Mistral AI models |
| `groq` | Ultra-fast inference |
| `ollama` | Local or cloud models |

### API Keys

API keys are stored securely in your system keyring (recommended) or provided via environment variables:

- **macOS**: Keychain
- **Linux**: Secret Service (GNOME Keyring, KWallet)
- **Windows**: Credential Manager

```bash
# In the REPL, Merlya can prompt and store your key:
merlya
/model provider openai

# Or in non-interactive environments (CI/CD):
export OPENAI_API_KEY="..."

# Keys are never written to config files
cat ~/.merlya/config.yaml | grep api_key
# (no output - only api_key_env reference, not the actual key)
```

## SSH Configuration

| Setting | Description | Default |
|---------|-------------|---------|
| `ssh.connect_timeout` | Connection timeout (seconds) | `30` |
| `ssh.pool_timeout` | Pool timeout (seconds) | `600` |
| `ssh.command_timeout` | Command execution timeout | `60` |

## Hosts Management

Hosts are stored in a SQLite database (`~/.merlya/merlya.db`) and managed via slash commands:

```bash
# Add a host interactively
/hosts add web-01

# Import from SSH config
/hosts import ~/.ssh/config --format=ssh

# Import from /etc/hosts
/hosts import /etc/hosts --format=etc_hosts

# List all hosts
/hosts list

# Show host details
/hosts show web-01
```

**Supported Import Formats:**

| Format | Description |
|--------|-------------|
| `ssh` | SSH config file (`~/.ssh/config`) |
| `etc_hosts` | Linux `/etc/hosts` format |
| `json` | JSON array of host objects |
| `yaml` | YAML host configuration |
| `csv` | CSV with columns: name, hostname, port, username |

## Logging

Merlya uses [loguru](https://github.com/Delgan/loguru) for logging.

| Setting | Description | Default |
|---------|-------------|---------|
| `general.log_level` | Console log level | `info` |
| `logging.file_level` | File log level | `debug` |
| `logging.max_size_mb` | Max log file size | `10` |

Logs are stored in `~/.merlya/logs/`.

## Next Steps

- [SSH Management Guide](../guides/ssh-management.md)
- [LLM Providers Guide](../guides/llm-providers.md)
- [Automation Guide](../guides/automation.md)
