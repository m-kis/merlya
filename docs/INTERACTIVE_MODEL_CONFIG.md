# Interactive Model Configuration

## Overview

Merlya now provides **interactive model configuration** on first launch, allowing you to:
- Choose your preferred LLM provider (OpenRouter, Anthropic, OpenAI, Ollama)
- Configure task-specific models for cost optimization
- Set up mixed configurations (e.g., Ollama for corrections, OpenRouter for planning)
- Modify configuration at runtime using `/model` commands

## First Launch Experience

When you run Merlya for the first time (or if `~/.merlya/config.json` doesn't exist), you'll see:

```
============================================================
🤖 Welcome to Merlya AI - Model Configuration
============================================================

Let's configure your LLM providers and models.

Available providers:
  1. openrouter - Access 400+ models (Claude, GPT-4, Llama, etc.)
  2. anthropic  - Direct Anthropic API (Claude models)
  3. openai     - Direct OpenAI API (GPT models)
  4. ollama     - Local models (requires Ollama server)

Select default provider [1-4] (default: 1):
```

### Step 1: Choose Provider

Select your primary provider. This will be used by default for all tasks unless overridden.

**Example choices:**
- `1` → OpenRouter (recommended: access to 400+ models, best flexibility)
- `4` → Ollama (recommended for privacy and offline work)

### Step 2: Configure Default Model

After selecting a provider, you'll be prompted to choose a default model:

```
Choose default model for openrouter:
  Press Enter to use: anthropic/claude-4.5-sonnet-20250929
  Or type a custom model name
Model [anthropic/claude-4.5-sonnet-20250929]:
```

**Example inputs:**
- Press Enter → Use the recommended default
- `anthropic/claude-3.5-sonnet` → Use Claude 3.5 Sonnet
- `openai/gpt-4o` → Use GPT-4o via OpenRouter
- `meta-llama/llama-3.1-70b-instruct` → Use Llama 3.1 70B

### Step 3: Task-Specific Routing (Optional)

Optimize cost and performance by assigning different models to different task types:

```
Task-Specific Routing (optimize cost & performance):
  - correction: Fast, cheap model for simple tasks
  - planning:   Powerful model for complex reasoning
  - synthesis:  Balanced model for general tasks

Configure task-specific models? [y/N]:
```

If you choose `y`:

```
CORRECTION: Quick fixes, simple corrections (use fast/cheap model)
  Current: haiku
  Options: haiku (fastest), sonnet (balanced), opus (best)
  Or enter full model path (e.g., meta-llama/llama-3.1-70b-instruct)
  Model for correction [haiku]:

PLANNING: Complex planning, architecture decisions (use powerful model)
  Current: opus
  Options: haiku (fastest), sonnet (balanced), opus (best)
  Or enter full model path (e.g., meta-llama/llama-3.1-70b-instruct)
  Model for planning [opus]:

SYNTHESIS: General tasks, balanced workload (use balanced model)
  Current: sonnet
  Options: haiku (fastest), sonnet (balanced), opus (best)
  Or enter full model path (e.g., meta-llama/llama-3.1-70b-instruct)
  Model for synthesis [sonnet]:
```

**Cost Optimization Example:**
- **correction** → `haiku` (Claude Haiku: $0.25/$1.25 per 1M tokens)
- **planning** → `opus` (Claude Opus: $15/$75 per 1M tokens)
- **synthesis** → `sonnet` (Claude Sonnet: $3/$15 per 1M tokens)

This can **reduce costs by 80-90%** while maintaining quality for complex tasks.

### Step 4: Mixed Providers (Advanced)

For advanced users, you can use different providers for different tasks:

```
------------------------------------------------------------
Advanced: Use different providers for different tasks
------------------------------------------------------------
Configure mixed providers? [y/N]:
```

**Example Use Case:**
- Use **Ollama** (local, free) for simple corrections
- Use **OpenRouter** (cloud) for complex planning and synthesis

If Ollama is detected:
```
✓ Ollama server detected
Use Ollama for correction tasks? [y/N]: y

Available Ollama models:
  1. llama3.2:latest
  2. codellama:latest
  3. mistral:latest
Select model or press Enter for llama3:

✓ Correction tasks will use Ollama (llama3.2)
```

### Final Confirmation

```
============================================================
✓ Configuration saved to: /Users/username/.merlya/config.json
============================================================

You can change these settings anytime with /model commands
Type '/model help' in the REPL for more information.
```

## Runtime Configuration with `/model` Commands

You can modify your configuration at any time using `/model` commands:

### Show Current Configuration

```bash
/model show
```

**Output:**
```
🤖 Current Model Configuration

  Provider: openrouter
  Model: anthropic/claude-4.5-sonnet-20250929

⚙️ Task Models:
  correction: haiku
  planning: opus
  synthesis: sonnet
```

### Manage Task-Specific Models

```bash
# Show task configuration
/model task

# List valid tasks and aliases
/model task list

# Set model for specific task
/model task set correction haiku
/model task set planning opus
/model task set synthesis meta-llama/llama-3.1-70b-instruct

# Reset to defaults
/model task reset
```

**Example Output:**
```
⚙️ Task-Specific Model Configuration
┌────────────┬─────────────────────────────────────┬────────────────────────────────┐
│ Task       │ Model/Alias                         │ Description                    │
├────────────┼─────────────────────────────────────┼────────────────────────────────┤
│ correction │ haiku                               │ Fast corrections (simple)      │
│ planning   │ opus                                │ Complex planning (powerful)    │
│ synthesis  │ meta-llama/llama-3.1-70b-instruct  │ General synthesis (balanced)   │
└────────────┴─────────────────────────────────────┴────────────────────────────────┘

💡 Use aliases (haiku/sonnet/opus) or full model paths
```

### Switch Providers

```bash
# Switch to Ollama
/model provider ollama

# Switch to OpenRouter
/model provider openrouter

# Switch to Anthropic
/model provider anthropic
```

### Configure Local Models (Ollama)

```bash
# Enable Ollama
/model local on

# Disable Ollama (revert to cloud)
/model local off

# Set specific Ollama model
/model local set llama3.2

# List available Ollama models
/model list ollama
```

## Configuration File Format

The configuration is stored in `~/.merlya/config.json`:

```json
{
  "provider": "openrouter",
  "models": {
    "openrouter": "anthropic/claude-4.5-sonnet-20250929",
    "anthropic": "claude-3-5-sonnet-20241022",
    "openai": "gpt-4o",
    "ollama": "llama3.2"
  },
  "task_models": {
    "correction": "haiku",
    "planning": "opus",
    "synthesis": "meta-llama/llama-3.1-70b-instruct"
  }
}
```

### Model Aliases

Aliases are provider-aware and resolve to the best model for each provider:

**OpenRouter:**
- `haiku` → `anthropic/claude-3-5-haiku` (fastest)
- `sonnet` → `anthropic/claude-3.5-sonnet` (balanced)
- `opus` → `anthropic/claude-3-opus` (most capable)

**Anthropic (Direct):**
- `haiku` → `claude-3-haiku-20240307`
- `sonnet` → `claude-3-5-sonnet-20241022`
- `opus` → `claude-3-opus-20240229`

**OpenAI:**
- `fast` → `gpt-4o-mini`
- `balanced` → `gpt-4o`
- `best` → `gpt-4o-2024-11-20`

**Ollama:**
- `fast` → `mistral`
- `balanced` → `llama3`
- `best` → `deepseek-coder`

## Mixed Configuration Examples

### Example 1: Cost-Optimized Setup

```json
{
  "provider": "openrouter",
  "models": {
    "openrouter": "anthropic/claude-3.5-sonnet"
  },
  "task_models": {
    "correction": "haiku",           // Claude Haiku (cheap)
    "planning": "opus",              // Claude Opus (powerful)
    "synthesis": "sonnet"            // Claude Sonnet (balanced)
  }
}
```

**Cost Breakdown:**
- Corrections: 90% of requests → $0.25/$1.25 per 1M tokens
- Planning: 5% of requests → $15/$75 per 1M tokens
- Synthesis: 5% of requests → $3/$15 per 1M tokens
- **Average savings: 80-85%** vs using Opus for everything

### Example 2: Privacy-First (Ollama + Cloud Fallback)

```json
{
  "provider": "ollama",
  "models": {
    "ollama": "llama3.2",
    "openrouter": "anthropic/claude-3.5-sonnet"
  },
  "task_models": {
    "correction": "llama3.2",        // Local Ollama (free, private)
    "planning": "opus",              // Cloud (when needed)
    "synthesis": "llama3.2"          // Local Ollama (free, private)
  }
}
```

**Benefits:**
- 95% of requests stay local (corrections + synthesis)
- Only complex planning uses cloud
- **Zero cost** for routine tasks
- **Full privacy** for most operations

### Example 3: Multi-Cloud Setup

```json
{
  "provider": "openrouter",
  "models": {
    "openrouter": "meta-llama/llama-3.1-70b-instruct",
    "anthropic": "claude-3-5-sonnet-20241022",
    "openai": "gpt-4o"
  },
  "task_models": {
    "correction": "qwen/qwen-2.5-coder-7b-instruct",  // Fast coder model
    "planning": "anthropic/claude-3-opus",            // Best for architecture
    "synthesis": "meta-llama/llama-3.1-70b-instruct" // Open model
  }
}
```

## How It Works

### 1. Initialization Flow

```
LiteLLMRouter.__init__(auto_configure=True)
  ↓
ModelConfig.__init__(auto_configure=True)
  ↓
Check if ~/.merlya/config.json exists
  ↓ (No)
Run _interactive_setup()
  ↓
Save config.json
```

### 2. Model Resolution Flow

When a task is executed:

```
get_model(task="correction")
  ↓
Check task_models for "correction"
  ↓ (found: "haiku")
Is it an alias or full path?
  ↓ (alias)
_resolve_model_alias(provider="openrouter", alias="haiku")
  ↓
Return: "anthropic/claude-3-5-haiku"
```

### 3. Agent Reloading

When you change configuration with `/model` commands:

```
/model task set correction llama3
  ↓
model_config.set_task_model("correction", "llama3")
  ↓
Save config.json
  ↓
self.repl.orchestrator.reload_agents()
  ↓
All agents pick up new configuration
```

## Benefits

### 1. **Informed Consent**
Users choose their providers and models consciously, not silently defaulting to cloud services.

### 2. **Cost Optimization**
Task-specific routing can reduce costs by 80-90% while maintaining quality.

### 3. **Privacy Control**
Users can route sensitive tasks to local Ollama models while using cloud for complex planning.

### 4. **Flexibility**
Runtime configuration changes without restarting Merlya.

### 5. **Transparency**
Clear visibility into which model is used for which task.

## Security & Privacy

### Secret Resolution During Command Execution

**User Question:** *"concernant le pass, du coup si c'est invisible à tous comment merlya va l'utiliser pour acceder aux ressource distante par exemple ?"*

**Answer:** Secrets are **invisible to LLMs** but **visible to execution tools**.

#### Flow Example: SSH to Remote Server

```
User input: ssh @dbhost using @dbpass

Step 1: LLM receives query
  ↓ resolve_variables(query, resolve_secrets=False)
  ↓ Result: "ssh @dbhost using @dbpass"  <-- LLM sees variable names only

Step 2: LLM plans action
  ↓ Tool: execute_command(target="@dbhost", command="ssh ...", ...)

Step 3: Tool execution
  ↓ resolve_variables(command, resolve_secrets=True)  <-- ACTUAL VALUES
  ↓ Result: "ssh prod-db-001 using secret_password123"
  ↓ Execute actual SSH command with real credentials

Step 4: Result returned to LLM
  ↓ Redacted output (no passwords in logs)
  ↓ LLM only sees: "✅ Connected to prod-db-001"
```

#### Code Reference

In [`merlya/tools/commands.py:69`](merlya/tools/commands.py#L69):

```python
# Resolve @variable references
if ctx.credentials and '@' in command:
    resolved = ctx.credentials.resolve_variables(command, warn_missing=True)
    # ↑ resolve_secrets=True by default (resolves actual values)
    if resolved != command:
        command = resolved  # Now has real credentials

# Execute with retry
result = ctx.executor.execute(target, command, confirm=True)
```

In [`merlya/repl/core.py:174`](merlya/repl/core.py#L174) (LLM context):

```python
# When sending to LLM, keep variable names
resolved_query = self.credentials.resolve_variables(user_input, resolve_secrets=False)
# ↑ resolve_secrets=False (keeps @variable names for LLM)
```

#### Security Layers

1. **Input Masking** - `getpass.getpass()` prevents shoulder surfing
2. **Memory-Only Storage** - Secrets never written to disk
3. **LLM Isolation** - LLMs see `@variable` placeholders, not values
4. **Execution Resolution** - Tools resolve secrets just-in-time
5. **Output Redaction** - Secrets removed from logs and results
6. **UI Masking** - `/variables show` displays `********` for secrets

#### Trust Boundary

```
┌─────────────────────────────────────────────────┐
│ LLM Context (Untrusted)                         │
│ • Sees: "@dbpass"                               │
│ • Cannot access actual value                    │
└─────────────────────────────────────────────────┘
                    ↓ (boundary)
┌─────────────────────────────────────────────────┐
│ Execution Context (Trusted)                     │
│ • Sees: "secret_password123"                    │
│ • Resolves just-in-time for execution           │
│ • Redacts from output before returning to LLM   │
└─────────────────────────────────────────────────┘
```

This ensures:
- ✅ Merlya can use secrets for remote access
- ✅ LLMs never see actual secret values
- ✅ Secrets remain protected in logs and context
- ✅ Users maintain full control over credential usage

## Troubleshooting

### Config Not Triggering

If interactive setup doesn't run:

```bash
# Remove existing config
rm ~/.merlya/config.json

# Run Merlya again
merlya
```

### Ollama Not Detected

If Ollama is installed but not detected:

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Start Ollama
ollama serve

# Pull a model
ollama pull llama3.2
```

### Model Not Found

If you get "model not found" errors:

```bash
# For OpenRouter: Check model ID format
# Correct: anthropic/claude-3.5-sonnet
# Incorrect: claude-3.5-sonnet

# For Ollama: List available models
/model list ollama

# For other providers: Check provider documentation
```

## Future Enhancements

Planned improvements:
- [ ] Model cost tracking and budgets
- [ ] Automatic fallback on rate limits
- [ ] Model benchmarking for task types
- [ ] Multi-model ensembles for critical tasks
- [ ] Context-aware model selection (file types, complexity)

---

**Last Updated:** 2025-11-30
**Configuration Version:** 1.0
