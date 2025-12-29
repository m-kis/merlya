# Configuration Reference

Complete reference for all configuration options.

## Configuration Files

| File | Purpose |
|------|---------|
| `~/.merlya/config.yaml` | Main configuration |
| `~/.merlya/merlya.db` | Hosts inventory (SQLite) |
| `~/.merlya/history` | Command history |
| `~/.merlya/logs/` | Log files |

---

## General Settings

### general.language

UI language.

| Type | Default | Values |
|------|---------|--------|
| string | `en` | `en`, `fr` |

```yaml
general:
  language: en
```

---

### general.log_level

!!! warning "Legacy Setting"
    This setting is deprecated. Use `logging.console_level` instead.
    Kept for backwards compatibility as fallback.

| Type | Default | Values |
|------|---------|--------|
| string | `info` | `debug`, `info`, `warning`, `error` |

```yaml
general:
  log_level: info  # Deprecated, use logging.console_level
```

---

### general.data_dir

Data directory path.

| Type | Default |
|------|---------|
| string | `~/.merlya` |

```yaml
general:
  data_dir: ~/.merlya
```

---

## Model Settings

### model.provider

LLM provider to use.

| Type | Default | Values |
|------|---------|--------|
| string | `openrouter` | `openrouter`, `anthropic`, `openai`, `ollama` |

```yaml
model:
  provider: openrouter
```

---

### model.model

Model name/identifier.

| Type | Default |
|------|---------|
| string | `amazon/nova-2-lite-v1:free` |

```yaml
model:
  model: amazon/nova-2-lite-v1:free
```

**Provider-specific examples:**

| Provider | Example Model |
|----------|---------------|
| OpenRouter | `amazon/nova-2-lite-v1:free`, `anthropic/claude-3.5-sonnet` |
| Anthropic | `claude-3-5-sonnet-latest`, `claude-3-5-haiku-latest` |
| OpenAI | `gpt-4o`, `gpt-4o-mini` |
| Ollama | `llama3.2`, `qwen2.5:7b` |

---

### model.api_key_env

Environment variable name for API key.

| Type | Default |
|------|---------|
| string | _(auto-detected)_ |

```yaml
model:
  api_key_env: OPENROUTER_API_KEY
```

!!! info "API Key Storage"
    API keys are stored securely in your system's keyring, not in config files.
    The `api_key_env` setting specifies which environment variable to check.

---

### model.base_url

Custom API endpoint URL (for Ollama or custom providers).

| Type | Default |
|------|---------|
| string | Provider default |

```yaml
model:
  base_url: http://localhost:11434/v1
```

---

## Router Settings

The router classifies user intent to determine appropriate actions.

### router.type

Router type for intent classification.

| Type | Default | Values |
|------|---------|--------|
| string | `local` | `local`, `llm` |

- `local`: Uses pattern matching for intent classification (fast, no model required)
- `llm`: Uses LLM for classification (more accurate, requires API)

```yaml
router:
  type: local
```

---

### router.llm_fallback

LLM model for fallback classification.

| Type | Default |
|------|---------|
| string | `openrouter:google/gemini-2.0-flash-lite-001` |

```yaml
router:
  llm_fallback: openrouter:google/gemini-2.0-flash-lite-001
```

---

## SSH Settings

### ssh.connect_timeout

Connection timeout in seconds.

| Type | Default | Range |
|------|---------|-------|
| integer | `30` | 5 - 120 |

```yaml
ssh:
  connect_timeout: 30
```

---

### ssh.pool_timeout

Connection pool timeout in seconds.

| Type | Default | Range |
|------|---------|-------|
| integer | `600` | 60 - 3600 |

```yaml
ssh:
  pool_timeout: 600
```

---

### ssh.command_timeout

Command execution timeout in seconds.

| Type | Default | Range |
|------|---------|-------|
| integer | `60` | 5 - 3600 |

```yaml
ssh:
  command_timeout: 60
```

---

### ssh.default_user

Default SSH username.

| Type | Default |
|------|---------|
| string | _(none)_ |

```yaml
ssh:
  default_user: deploy
```

---

### ssh.default_key

Default SSH private key path.

| Type | Default |
|------|---------|
| string | _(none)_ |

```yaml
ssh:
  default_key: ~/.ssh/id_ed25519
```

---

## UI Settings

### ui.theme

Color theme.

| Type | Default | Values |
|------|---------|--------|
| string | `auto` | `auto`, `light`, `dark` |

```yaml
ui:
  theme: auto
```

---

### ui.markdown

Enable markdown rendering in responses.

| Type | Default |
|------|---------|
| boolean | `true` |

```yaml
ui:
  markdown: true
```

---

### ui.syntax_highlight

Enable syntax highlighting for code blocks.

| Type | Default |
|------|---------|
| boolean | `true` |

```yaml
ui:
  syntax_highlight: true
```

---

## Logging Settings

### logging.console_level

Console log level for terminal output.

| Type | Default | Values |
|------|---------|--------|
| string | `info` | `debug`, `info`, `warning`, `error` |

```yaml
logging:
  console_level: info
```

!!! tip "CLI Flags"
    Use `merlya --verbose` to override console logging to `debug` level.
    For non-interactive runs, `merlya run -q/--quiet` reduces user-facing output (it does not change the configured log level).

---

### logging.file_level

File log level.

| Type | Default | Values |
|------|---------|--------|
| string | `debug` | `debug`, `info`, `warning`, `error` |

```yaml
logging:
  file_level: debug
```

---

### logging.max_size_mb

Maximum log file size in MB before rotation.

| Type | Default | Range |
|------|---------|-------|
| integer | `10` | 1 - 100 |

```yaml
logging:
  max_size_mb: 10
```

---

### logging.max_files

Maximum number of log files to keep.

| Type | Default | Range |
|------|---------|-------|
| integer | `5` | 1 - 20 |

```yaml
logging:
  max_files: 5
```

---

### logging.retention_days

Log retention in days.

| Type | Default | Range |
|------|---------|-------|
| integer | `7` | 1 - 90 |

```yaml
logging:
  retention_days: 7
```

---

## Hosts Configuration

Hosts are stored in a SQLite database and managed via the `/hosts` commands.

### Host Properties

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `name` | string | Yes | Unique host identifier |
| `hostname` | string | Yes | Server hostname or IP |
| `port` | integer | No | SSH port (default: 22) |
| `username` | string | No | SSH username |
| `private_key` | string | No | SSH private key path |
| `jump_host` | string | No | Jump/bastion host name |
| `tags` | array | No | Tags for filtering |

### Managing Hosts

```bash
# Add a host
/hosts add web-01

# Import from SSH config
/hosts import ~/.ssh/config --format=ssh

# List hosts
/hosts list

# Show host details
/hosts show web-01

# Add tags
/hosts tag web-01 production

# Delete a host
/hosts delete old-server
```

---

## Complete Example

```yaml
# ~/.merlya/config.yaml

general:
  language: en

model:
  provider: openrouter
  model: amazon/nova-2-lite-v1:free
  api_key_env: OPENROUTER_API_KEY

router:
  type: local
  tier: balanced
  llm_fallback: openrouter:google/gemini-2.0-flash-lite-001

ssh:
  connect_timeout: 30
  pool_timeout: 600
  command_timeout: 60
  default_user: deploy
  default_key: ~/.ssh/id_ed25519

ui:
  theme: auto
  markdown: true
  syntax_highlight: true

logging:
  console_level: info
  file_level: debug
  max_size_mb: 10
  max_files: 5
  retention_days: 7
```

---

## Environment Variables

Override settings with environment variables:

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `OLLAMA_API_KEY` | Ollama cloud API key |
| `MERLYA_ROUTER_FALLBACK` | Override router fallback model |
| `MERLYA_ROUTER_MODEL` | Override local router model |
