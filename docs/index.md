# Merlya

**AI-powered infrastructure assistant for DevOps and SRE teams.**

Merlya is a command-line tool that combines the power of LLMs with practical infrastructure management capabilities:
SSH inventory, safe remote execution, diagnostics, and automation.

## Key Features

<div class="grid cards" markdown>

-   :material-chat-processing:{ .lg .middle } **Natural Language Interface**

    ---

    Ask questions like “check disk usage on @web-01” or “triage this incident log”.

-   :material-server-network:{ .lg .middle } **SSH Management**

    ---

    Async SSH pool, jump hosts, connection testing, and inventory import/export.

-   :material-robot:{ .lg .middle } **Local-First Routing + LLM Fallback**

    ---

    Intent routing prefers local classifiers when available, with safe fallbacks.

-   :material-security:{ .lg .middle } **Secure by Design**

    ---

    Secrets stored in the system keyring; inputs validated; consistent logging.

</div>

## Quick Example

```bash
pip install merlya

# Option A: let the first-run wizard guide you (recommended)
merlya

# Option B: for CI/CD, provide API keys via env vars
export OPENAI_API_KEY="..."
merlya run "Check disk usage on @web-01"
```

Ready to get started? See the [Installation Guide](getting-started/installation.md).

[Get Started :material-arrow-right:](getting-started/installation.md){ .md-button .md-button--primary }
[View on GitHub :material-github:](https://github.com/m-kis/merlya){ .md-button }
