# LLM Providers

Merlya supports multiple LLM providers, from cloud APIs to local models.

## Supported Providers

| Provider | Models | Pros | Cons |
|----------|--------|------|------|
| **OpenRouter** | 100+ models | Free tier, many models | Variable latency |
| **Anthropic** | Claude 3.5 Sonnet/Haiku | Great reasoning | Paid API |
| **OpenAI** | GPT-4o, GPT-4o-mini | Fast, reliable | Paid API |
| **Mistral** | Mistral Large, Small | European, great quality | Paid API |
| **Groq** | Llama, Mixtral | Extremely fast inference | Paid API |
| **Ollama** | Llama, Qwen, Mistral | Free, private (local or cloud) | Setup required |

---

## OpenRouter (Default)

OpenRouter is the **default provider** - it offers access to 100+ models including free options.

### Setup

```bash
# Option A (recommended): interactive prompt + keyring storage
merlya
/model provider openrouter

# Option B (CI/CD): API key via env var
export OPENROUTER_API_KEY="..."
merlya config set model.provider openrouter
merlya config set model.model amazon/nova-2-lite-v1:free
```

### Free Models

| Model | Quality | Speed |
|-------|---------|-------|
| `amazon/nova-2-lite-v1:free` | Good | Fast |
| `google/gemini-2.0-flash-lite-001` | Great | Fast |
| `meta-llama/llama-3.2-3b-instruct:free` | Good | Very fast |

### Premium Models

| Model | Quality | Cost |
|-------|---------|------|
| `anthropic/claude-3.5-sonnet` | Excellent | $$ |
| `openai/gpt-4o` | Excellent | $$ |
| `google/gemini-pro` | Great | $ |

Get your API key at: [openrouter.ai/keys](https://openrouter.ai/keys)

---

## Anthropic

### Setup

```bash
export ANTHROPIC_API_KEY="..."
merlya config set model.provider anthropic
merlya config set model.model claude-3-5-sonnet-latest
```

### Recommended Models

| Model | Speed | Quality | Cost |
|-------|-------|---------|------|
| `claude-3-5-sonnet-latest` | Fast | Excellent | $$ |
| `claude-3-5-haiku-latest` | Very fast | Great | $ |
| `claude-3-opus-latest` | Slow | Best | $$$ |

---

## OpenAI

### Setup

```bash
export OPENAI_API_KEY="..."
merlya config set model.provider openai
merlya config set model.model gpt-4o
```

### Recommended Models

| Model | Speed | Quality | Cost |
|-------|-------|---------|------|
| `gpt-4o` | Fast | Excellent | $$ |
| `gpt-4o-mini` | Very fast | Great | $ |
| `gpt-4-turbo` | Medium | Excellent | $$$ |

### Custom Base URL

For Azure OpenAI or proxies:

```bash
merlya config set model.base_url https://your-endpoint.openai.azure.com
```

---

## Mistral

European AI provider with strong multilingual support.

### Setup

```bash
export MISTRAL_API_KEY="..."
merlya config set model.provider mistral
merlya config set model.model mistral-large-latest
```

### Recommended Models

| Model | Speed | Quality | Cost |
|-------|-------|---------|------|
| `mistral-large-latest` | Fast | Excellent | $$ |
| `mistral-small-latest` | Very fast | Great | $ |
| `codestral-latest` | Fast | Great for code | $$ |

Get your API key at: [console.mistral.ai](https://console.mistral.ai/)

---

## Groq

Ultra-fast inference with custom LPU hardware.

### Setup

```bash
export GROQ_API_KEY="..."
merlya config set model.provider groq
merlya config set model.model llama-3.3-70b-versatile
```

### Recommended Models

| Model | Speed | Quality | Cost |
|-------|-------|---------|------|
| `llama-3.3-70b-versatile` | Very fast | Excellent | $ |
| `llama-3.1-8b-instant` | Ultra fast | Good | $ |
| `mixtral-8x7b-32768` | Fast | Great | $ |

Get your API key at: [console.groq.com](https://console.groq.com/)

---

## Ollama (Local + Cloud)

Ollama supports both **local** and **cloud** deployment.

### Local Setup (Free, Private)

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull a model
ollama pull llama3.2

# Configure Merlya
merlya config set llm.provider ollama
merlya config set llm.model llama3.2
# Base URL defaults to http://localhost:11434
```

### Cloud Setup (Ollama.com)

For cloud-hosted Ollama:

```bash
merlya config set llm.provider ollama
merlya config set llm.model llama3.2-cloud  # "cloud" suffix triggers cloud mode
export OLLAMA_API_KEY="..."
merlya config set llm.base_url https://ollama.com/v1
```

!!! info "Automatic Cloud Detection"
    Merlya automatically detects cloud mode when:

    - Model name contains "cloud"
    - Base URL is not localhost/127.0.0.1
    - `OLLAMA_API_KEY` environment variable is set

### Recommended Local Models

| Model | RAM | Quality | Speed |
|-------|-----|---------|-------|
| `llama3.2` | 4GB | Great | Fast |
| `qwen2.5:7b` | 8GB | Excellent | Fast |
| `mistral-nemo:12b` | 16GB | Excellent | Medium |
| `codellama:13b` | 16GB | Great for code | Medium |

### GPU Acceleration

Ollama automatically uses GPU if available:

```bash
# Check GPU usage
ollama ps

# Force CPU only
OLLAMA_GPU_LAYERS=0 ollama serve
```

---

## Provider Selection in Setup Wizard

On first run, Merlya's [setup wizard](../getting-started/quickstart.md#setup-wizard) offers:

```
╭───────────────────────────────────────────────────────────────────╮
│                      LLM Configuration                            │
├───────────────────────────────────────────────────────────────────┤
│  1. OpenRouter (recommended - multi-model)                        │
│  2. Anthropic (Claude direct)                                     │
│  3. OpenAI (GPT models)                                           │
│  4. Mistral (Mistral AI)                                          │
│  5. Groq (fast inference)                                         │
│  6. Ollama (local models)                                         │
╰───────────────────────────────────────────────────────────────────╯
```

---

## Router Fallback Model

Merlya uses a separate "router" model for intent classification when pattern matching has low confidence:

```bash
# Configure router fallback (fast, cheap model recommended)
merlya config set router.llm_fallback openrouter:google/gemini-2.0-flash-lite-001
```

---

## Switching Providers

```bash
# Use OpenRouter for free tier
merlya config set model.provider openrouter
merlya config set model.model amazon/nova-2-lite-v1:free

# Switch to Anthropic for complex tasks
merlya config set model.provider anthropic

# Switch to local Ollama for privacy
merlya config set model.provider ollama
merlya config set model.model llama3.2
```

---

## Environment Variables

Override settings with environment variables:

```bash
export OPENROUTER_API_KEY=or-xxx
export ANTHROPIC_API_KEY=sk-ant-xxx
export OPENAI_API_KEY=sk-xxx
export MISTRAL_API_KEY=xxx
export GROQ_API_KEY=gsk_xxx
export OLLAMA_API_KEY=xxx  # For cloud Ollama only
export OLLAMA_BASE_URL=http://localhost:11434/v1
```

---

## Troubleshooting

### API Key Issues

```bash
# In the REPL:
/model show

# Or in CI/CD:
export OPENROUTER_API_KEY="..."
```

### Keyring Unavailable

If you see "Keyring unavailable (in-memory)" warning:

```bash
# Linux: Install secret service
sudo apt install gnome-keyring

# macOS: Keychain should work automatically

# Fallback: Use environment variables instead
export OPENROUTER_API_KEY=your-key
```

### Ollama Not Responding

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Start Ollama
ollama serve

# Or restart the service
systemctl restart ollama
```
