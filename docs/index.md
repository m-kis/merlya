# Merlya Documentation

Merlya is an AI-powered infrastructure assistant that enables natural language management of your servers via SSH.

## Table of Contents

1. [Architecture](architecture.md) - System design and components
2. [Configuration](configuration.md) - Setup and configuration options
3. [Commands](commands.md) - Slash commands reference
4. [Tools](tools.md) - Available agent tools
5. [SSH & Jump Hosts](ssh.md) - SSH connection management
6. [Extending Merlya](extending.md) - Adding tools and commands

## Quick Start

```bash
# Install from PyPI
pip install merlya

# Run Merlya
merlya
```

On first run, Merlya will guide you through:
1. Language selection (English/French)
2. LLM provider configuration
3. Host inventory import

## How It Works

```
User Input → Intent Router → Agent → Tools → Response
     ↓            ↓           ↓        ↓
  "Check      Classify     Execute   SSH
   disk on    as DIAG     ssh_exec  commands
   @web01"    + system
             tools
```

1. **User Input**: Natural language request or slash command
2. **Intent Router**: Classifies intent (diagnostic/remediation/query/chat)
3. **Agent**: PydanticAI-based agent with ReAct loop
4. **Tools**: Execute operations (SSH, file ops, monitoring)
5. **Response**: Markdown-formatted result with suggestions

## Key Features

- **Natural Language**: Ask questions like "What's using disk space on web01?"
- **SSH Pool**: Connection reuse with automatic cleanup
- **Jump Hosts**: Access servers via bastion with `via @hostname`
- **Multi-language**: English and French support
- **Secure**: Keyring integration, no credentials in config files
- **Extensible**: Add custom tools and commands
