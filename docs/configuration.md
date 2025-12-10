# Configuration

Merlya stores configuration in `~/.merlya/config.yaml`.

## Full Configuration Reference

```yaml
general:
  language: en              # en, fr
  data_dir: ~/.merlya       # Base data directory

model:
  provider: openrouter      # LLM provider
  model: amazon/nova-2-lite-v1:free
  api_key_env: null         # Environment variable name for API key

router:
  type: local               # local (ONNX), llm
  model: null               # Embedding model ID
  tier: null                # performance, balanced, lightweight
  llm_fallback: openrouter:google/gemini-2.0-flash-lite-001

ssh:
  pool_timeout: 600         # Connection reuse timeout (seconds)
  connect_timeout: 30       # Initial connection timeout
  command_timeout: 60       # Command execution timeout
  default_user: null        # Default SSH username
  default_key: null         # Default private key path

ui:
  theme: auto               # auto, light, dark
  markdown: true            # Enable markdown rendering
  syntax_highlight: true    # Enable syntax highlighting

logging:
  console_level: info       # Console log level (debug, info, warning, error)
  file_level: debug         # File log level
  max_size_mb: 10           # Max log file size
  max_files: 5              # Number of log files to keep
  retention_days: 7         # Log retention period

mcp:
  default_timeout: 30       # Default timeout (seconds) for MCP requests
  servers: {}               # MCP servers (see examples below)
```

## LLM Providers

### OpenRouter (Recommended)

```yaml
model:
  provider: openrouter
  model: amazon/nova-2-lite-v1:free
  api_key_env: OPENROUTER_API_KEY
```

Set your API key:
```bash
export OPENROUTER_API_KEY=sk-or-...
```

Or store in keyring:
```bash
merlya
# First run wizard will prompt for API key
```

### Anthropic

```yaml
model:
  provider: anthropic
  model: claude-3-5-sonnet-latest
  api_key_env: ANTHROPIC_API_KEY
```

### OpenAI

```yaml
model:
  provider: openai
  model: gpt-4o
  api_key_env: OPENAI_API_KEY
```

### Mistral

```yaml
model:
  provider: mistral
  model: mistral-large-latest
  api_key_env: MISTRAL_API_KEY
```

Available models: `mistral-large-latest`, `mistral-small-latest`, `codestral-latest`, `open-mistral-nemo`

### Groq

```yaml
model:
  provider: groq
  model: llama-3.1-70b-versatile
  api_key_env: GROQ_API_KEY
```

Groq offers fast inference on open models. Available models: `llama-3.1-70b-versatile`, `llama-3.1-8b-instant`, `mixtral-8x7b-32768`

### Ollama (Local)

```yaml
model:
  provider: ollama
  model: llama3.2
```

No API key required for local Ollama.

## Router Configuration

The router classifies user intent before sending to the LLM.

### Local Router (ONNX)

Uses local embeddings for fast, private classification:

```yaml
router:
  type: local
  tier: balanced  # performance, balanced, lightweight
```

**Tiers:**
- `performance` - Best accuracy, more RAM
- `balanced` - Good tradeoff (default)
- `lightweight` - Low RAM usage

### LLM Router

Falls back to LLM when local confidence is low:

```yaml
router:
  llm_fallback: openrouter:google/gemini-2.0-flash-lite-001
```

## SSH Configuration

```yaml
ssh:
  pool_timeout: 600      # Keep connections alive for 10 min
  connect_timeout: 30    # 30s to establish connection
  command_timeout: 60    # 60s max per command
  default_user: admin    # Default username if not specified
  default_key: ~/.ssh/id_ed25519  # Default private key
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `MISTRAL_API_KEY` | Mistral API key |
| `GROQ_API_KEY` | Groq API key |
| `MERLYA_ROUTER_MODEL` | Override router model |
| `MERLYA_ROUTER_FALLBACK` | Override LLM fallback |
| `SSH_AUTH_SOCK` | SSH agent socket |
| `GITHUB_TOKEN` | Token used by the GitHub MCP server example |
| `SLACK_BOT_TOKEN` | Token used by the Slack MCP server example |

## Data Directory

Default: `~/.merlya/`

Contents:
```
~/.merlya/
├── config.yaml      # Configuration
├── merlya.db        # SQLite database
├── history          # Command history
└── logs/            # Log files
```

## Keyring Integration

API keys are stored securely in the system keyring:
- **macOS**: Keychain
- **Linux**: Secret Service (GNOME Keyring, KWallet)
- **Windows**: Windows Credential Manager

If keyring is unavailable, falls back to in-memory storage (not persisted).

## MCP Configuration

Configure MCP servers in `~/.merlya/config.yaml`:

```yaml
mcp:
  servers:
    github:
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_TOKEN: "${GITHUB_TOKEN}"
    slack:
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-slack"]
      env:
        SLACK_BOT_TOKEN: "${SLACK_BOT_TOKEN}"
```

**Environment variable resolution:**
- `${VAR}` - Required variable from OS env or Merlya keyring (warning if missing)
- `${VAR:-default}` - Optional variable with default fallback

Use `/mcp test <name>` to validate connectivity and list available tools.

## First Run Wizard

On first run, Merlya guides you through:

1. **Language Selection**
   - English or French

2. **LLM Provider**
   - Select provider
   - Enter API key (stored in keyring)
   - Choose model

3. **Inventory Import**
   - Scans for existing inventories:
     - `~/.ssh/config`
     - `~/.ssh/known_hosts`
     - `/etc/hosts`
     - Ansible inventory files
   - Select which to import

## Updating Configuration

Edit the config file directly:
```bash
$EDITOR ~/.merlya/config.yaml
```

Or use commands:
```bash
# Change language
/language fr

# Change model
/model set openrouter:anthropic/claude-3.5-sonnet
```

Changes take effect immediately for most settings.
