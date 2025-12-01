# Variables System

Merlya provides a powerful variable system for managing host aliases, configuration values, and secrets.

## Overview

Variables are referenced with `@variable_name` syntax in queries and are resolved automatically before execution.

```
User Query: "check nginx on @prodweb using @dbpass"
                            ↓
Resolved:   "check nginx on web-prod-01 using [secret]"
```

---

## Variable Types

| Type | Persistence | Use Case | Example |
|------|-------------|----------|---------|
| `host` | Persisted | Host aliases | `@proddb` → `db-prod-001` |
| `config` | Persisted | Configuration values | `@env` → `production` |
| `secret` | Memory only | Passwords, tokens, API keys | `@dbpass` → `********` |

---

## Commands

### Setting Variables

```bash
# Set a config variable (persisted)
/variables set <key> <value>
/variables set region eu-west-1
/variables set environment production

# IMPORTANT: Values can contain ANY characters without quotes
# JSON, URLs, hashes, SQL, etc. are all supported
/variables set API_CONFIG {"env":"prod","region":"eu-west-1"}
/variables set WEBHOOK https://api.example.com?token=abc123&callback=true
/variables set SECRET_HASH abc-123-{special}-456-[brackets]
/variables set QUERY SELECT * FROM users WHERE active=1 AND role='admin'
/variables set SSH_KEY ssh-rsa AAAAB3NzaC1yc2EA... user@host

# Set a host alias (persisted)
/variables set-host <key> <hostname>
/variables set-host proddb db-prod-001
/variables set-host prodweb web-prod-01

# Set a secret (secure hidden input, NOT persisted)
/variables set-secret <key>
/variables set-secret dbpass
/variables set-secret api-key
```

**Enhanced Parsing:** The `/variables set` command uses **raw parsing** mode that preserves ALL characters in the value without requiring quotes. This means you can set:
- JSON objects with braces and quotes
- URLs with query parameters
- Hashes with special characters
- SQL queries with spaces and quotes
- SSH keys with multiple parts
- Any other complex value type

### Managing Variables

```bash
# List all variables (secrets masked)
/variables list

# Delete a variable
/variables delete <key>
/variables delete proddb

# Clear all variables
/variables clear

# Clear only secrets (keep hosts and configs)
/variables clear-secrets
```

---

## Usage in Queries

Once defined, use variables with `@` prefix in your queries:

```bash
# Using host aliases
check mysql on @proddb
show logs for @prodweb

# Using secrets for credentials
check mongo on @proddb using @mongo-user @mongo-pass

# Combining multiple variables
deploy to @prodweb in @environment
```

### Resolution Priority

When resolving `@variable`:
1. **User variables** - Variables set via `/variables`
2. **Inventory hosts** - Hosts from `/inventory`

---

## Persistence

| Variable Type | Storage | Across Sessions |
|--------------|---------|-----------------|
| `host` | SQLite database | Yes |
| `config` | SQLite database | Yes |
| `secret` | Memory only | No (cleared on exit) |

**Location:** `~/.merlya/storage.db`

---

## Examples

### Database Credentials Setup

```bash
# Define host aliases
/variables set-host proddb mongo-prod-001
/variables set-host stagingdb mongo-staging-001

# Define username (persisted)
/variables set mongo-user admin

# Define password (secret, memory only)
/variables set-secret mongo-pass

# Use in queries
check replica status on @proddb using @mongo-user @mongo-pass
show slow queries on @stagingdb with credentials @mongo-user @mongo-pass
```

### Multi-Environment Setup

```bash
# Define environments
/variables set env production
/variables set region eu-west-1
/variables set cluster main

# Define hosts per environment
/variables set-host prod-api api-prod-001
/variables set-host staging-api api-staging-001

# Use in queries
deploy service to @prod-api in @region
check health of @staging-api
```

### SSH Key Passphrase

```bash
# Store SSH key passphrase as secret
/variables set-secret ssh-passphrase-proddb

# The inventory system will use this for hosts with SSH keys
# See: /inventory ssh-key <host>
```

---

## Variable List Output

```
┏━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ Variable    ┃ Type   ┃ Value           ┃ Persisted ┃
┡━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ @proddb     │ host   │ db-prod-001     │ Yes       │
│ @mongo-user │ config │ admin           │ Yes       │
│ @mongo-pass │ secret │ ********        │ No        │
│ @region     │ config │ eu-west-1       │ Yes       │
└─────────────┴────────┴─────────────────┴───────────┘
```

---

## Security

### Multi-Layer Protection

Merlya implements **LLM isolation** to protect secrets:

1. **Secrets never written to disk** - Only stored in memory
2. **Secrets masked in output** - Displayed as `********`
3. **Secrets cleared on exit** - Automatically removed when REPL exits
4. **Secure input** - Uses `getpass` (no terminal echo)
5. **No logging** - Secrets never appear in logs
6. **LLM Isolation** - LLMs see `@variable` placeholders, never actual values

### How Secrets Are Used

```
┌─────────────────────────────────────────┐
│ LLM Context (Untrusted)                 │
│ • Query: "ssh @dbhost using @dbpass"    │
│ • LLM sees: @dbhost, @dbpass            │
│ • LLM cannot access actual values       │
└─────────────────────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│ Execution Context (Trusted)             │
│ • Resolves: "ssh prod-db-001 using ..." │
│ • Executes with real credentials        │
│ • Redacts secrets from output           │
└─────────────────────────────────────────┘
```

**Key Principle:**

- LLMs **plan** with variable names (`@dbpass`)
- Tools **execute** with actual values (`secret123`)
- This enables remote access while protecting secrets from LLM context

---

## API Reference

### Python API

```python
from merlya.security.credentials import CredentialManager, VariableType

# Create manager
manager = CredentialManager()

# Set variables
manager.set_variable("proddb", "db-prod-001", VariableType.HOST)
manager.set_variable("region", "eu-west-1", VariableType.CONFIG)
manager.set_variable("dbpass", "secret123", VariableType.SECRET)

# Get variables
value = manager.get_variable("proddb")  # "db-prod-001"
var_type = manager.get_variable_type("proddb")  # VariableType.HOST

# Resolve @variables in text
resolved = manager.resolve_variables("check @proddb using @dbpass")
# "check db-prod-001 using secret123"

# List variables
all_vars = manager.list_variables_typed()
# {"proddb": ("db-prod-001", VariableType.HOST), ...}

# Delete/clear
manager.delete_variable("proddb")
manager.clear_secrets()  # Clear only secrets
manager.clear_variables()  # Clear all
```

---

## Tips

1. **Use host aliases** for frequently accessed servers
2. **Store usernames as config** (persisted) but **passwords as secrets** (memory only)
3. **Clear secrets** before sharing terminal: `/variables clear-secrets`
4. **Check what's stored**: `/variables list`

---

## See Also

- [CREDENTIALS.md](CREDENTIALS.md) - Full credential management documentation
- [INVENTORY.md](INVENTORY.md) - Host inventory system
- [COMMANDS.md](COMMANDS.md) - All slash commands
