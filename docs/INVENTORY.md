# Inventory System

Merlya's inventory system manages your infrastructure hosts with support for multiple sources, relationships, and SSH key configuration.

## Overview

```text
┌─────────────────────────────────────────────────────┐
│                    Inventory                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │ /etc/hosts  │  │ CSV/JSON    │  │ SSH Config  │ │
│  │ (source 1)  │  │ (source 2)  │  │ (source 3)  │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘ │
│         │                │                │         │
│         └────────────────┼────────────────┘         │
│                          ↓                          │
│               ┌─────────────────┐                   │
│               │   Host Database  │                  │
│               │    (SQLite)      │                  │
│               └─────────────────┘                   │
│                          ↓                          │
│               Use @hostname in queries              │
└─────────────────────────────────────────────────────┘
```

---

## Commands

### Import Hosts

```bash
# Import from file
/inventory add <file>
/inventory add /etc/hosts
/inventory add ~/.ssh/config
/inventory add hosts.csv
/inventory add inventory.json
/inventory add inventory.yaml

# Add single host interactively
/inventory add-host [hostname]
/inventory add-host web-prod-01
```

### View Inventory

```bash
# List all sources
/inventory list

# Show hosts from all sources
/inventory show

# Show hosts from specific source
/inventory show <source_name>

# Limit results
/inventory show --limit 50
```

### Search Hosts

```bash
# Search by hostname, IP, or groups
/inventory search <pattern>
/inventory search prod
/inventory search 192.168
/inventory search web

# Limit results
/inventory search prod --limit 20
```

### Manage Inventory

```bash
# Remove a source (and its hosts)
/inventory remove <source_name>

# Export inventory
/inventory export inventory.json
/inventory export hosts.csv
/inventory export hosts.yaml

# Create snapshot
/inventory snapshot [name]

# Show statistics
/inventory stats
```

### SSH Key Management

```bash
# Show usage and current config
/inventory ssh-key

# Global SSH key (used for all hosts without specific config)
/inventory ssh-key set <path>       # Set global default key
/inventory ssh-key show             # Show global config
/inventory ssh-key clear            # Clear global key

# Per-host SSH key (overrides global)
/inventory ssh-key <hostname> set   # Set key for specific host
/inventory ssh-key <hostname> show  # Show host SSH config
/inventory ssh-key <hostname> clear # Clear host SSH config
```

### Relations

```bash
# Suggest relations (AI-powered)
/inventory relations suggest

# List validated relations
/inventory relations list
```

---

## Supported Import Formats

| Format | Extensions | Example |
|--------|------------|---------|
| CSV | `.csv` | `hostname,ip,environment` |
| JSON | `.json` | `[{"hostname": "...", "ip": "..."}]` |
| YAML | `.yaml`, `.yml` | Standard YAML format |
| INI (Ansible) | `.ini` | `[group]` sections |
| /etc/hosts | - | Standard hosts file |
| SSH Config | `config` | `~/.ssh/config` format |
| Plain text | `.txt` | Parsed with AI |

### CSV Format

```csv
hostname,ip_address,environment,groups,role
web-prod-01,10.0.1.1,production,web;frontend,webserver
db-prod-01,10.0.1.2,production,database;primary,mongodb
```

### JSON Format

```json
[
  {
    "hostname": "web-prod-01",
    "ip_address": "10.0.1.1",
    "environment": "production",
    "groups": ["web", "frontend"],
    "role": "webserver"
  }
]
```

### YAML Format

```yaml
- hostname: web-prod-01
  ip_address: 10.0.1.1
  environment: production
  groups:
    - web
    - frontend
  role: webserver
```

---

## Host References (@hostname)

Once imported, reference hosts with `@hostname` in queries:

```bash
# Single host
check nginx on @web-prod-01
show logs for @db-prod-01

# Multiple hosts
compare disk usage @db-master vs @db-replica
restart service on @backend-01 @backend-02 @backend-03

# With credentials (from /variables)
check mongo on @proddb using @mongo-user @mongo-pass
```

### Resolution

When you use `@hostname`:
1. System looks up the host in inventory
2. Resolves to hostname (and IP if available)
3. Makes host info available to agents

---

## SSH Key Configuration

Merlya provides flexible SSH key management with global defaults and per-host overrides.

### Key Resolution Priority

When connecting to a host, Merlya resolves SSH keys in this order:

1. **Host-specific key** from inventory metadata
2. **Global key** set via `/inventory ssh-key set`
3. **~/.ssh/config** `IdentityFile` for the host
4. **Default keys** (id_ed25519, id_ecdsa, id_rsa)

### Setting a Global SSH Key

```bash
# Set global default key (used for all hosts without specific config)
/inventory ssh-key set ~/.ssh/id_ed25519

# If key is encrypted, you'll be prompted for passphrase
> This key appears to be encrypted.
> Set passphrase now? (Y/n): y
> SSH key passphrase (hidden): ********
✓ Passphrase cached (session only, not persisted)
```

### Per-Host SSH Key

```bash
# Set key for a specific host
/inventory ssh-key web-prod-01 set
> SSH key path [~/.ssh/id_rsa]: ~/.ssh/id_web_prod
> Set/update passphrase? (y/N): y
> SSH key passphrase (hidden): ********
✓ Passphrase stored as secret

# View host SSH config
/inventory ssh-key web-prod-01 show

# Clear host-specific config (will fall back to global)
/inventory ssh-key web-prod-01 clear
```

### Passphrase Handling

- **Prompted on first use** (secure input with hidden characters)
- **Cached for session duration** as SECRET type variables
- **Never persisted** to disk
- **Cleared automatically** on REPL exit

Naming convention for passphrase secrets:

- Global: `ssh-passphrase-global`
- Per-host: `ssh-passphrase-<hostname>`
- Per-key: `ssh-passphrase-<key_filename>`

### Security Features

- **Path validation**: Keys must be in `~/.ssh`, `/etc/ssh`, or `MERLYA_SSH_KEY_DIR`
- **Permission check**: Warns if key permissions are not 0600/0400
- **Hostname validation**: RFC 1123 compliant hostnames and IPs
- **Sanitized logging**: Full paths never appear in debug logs

---

## Host Relations

The inventory system can detect and manage relationships between hosts.

### Relation Types

| Type | Description | Example |
|------|-------------|---------|
| `replicates` | Database replication | `db-master` → `db-replica` |
| `load_balances` | Load balancing | `lb-01` → `web-01`, `web-02` |
| `depends_on` | Service dependency | `app-01` → `db-01` |
| `cluster_member` | Cluster membership | `es-01` ↔ `es-02` |
| `backup_of` | Backup relationship | `backup-db` → `db-master` |

### Discovering Relations

```bash
/inventory relations suggest

# Output:
┏━━━┳━━━━━━━━━━┳━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ # ┃ Source   ┃ → ┃ Target     ┃ Type       ┃ Confidence ┃
┡━━━╇━━━━━━━━━━╇━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ 1 │ db-master│ → │ db-replica │ replicates │ 95%        │
│ 2 │ lb-prod  │ → │ web-01     │ load_balances │ 87%        │
└───┴──────────┴───┴────────────┴────────────┴────────────┘

Enter numbers to accept (e.g., '1,2'), 'all', or 'none':
> all
✓ Saved 2 relations
```

---

## Storage

### Database Location

`~/.merlya/storage.db`

### Host Schema

```text
hosts_v2
├── id (PRIMARY KEY)
├── hostname (UNIQUE)
├── ip_address
├── aliases (JSON array)
├── environment
├── groups (JSON array)
├── role
├── service
├── ssh_port (default: 22)
├── status (online/offline/unknown)
├── source_id (foreign key)
├── metadata (JSON - includes ssh_key_path, ssh_passphrase_secret)
├── created_at
└── updated_at
```

### Versioning

All changes to hosts are versioned:
- Track who made changes
- View history with audit trail
- Support rollback (planned)

---

## Statistics

```bash
/inventory stats
```

**Output:**

```text
Inventory Statistics

  Total hosts: 45

  By environment:
    production: 20
    staging: 15
    development: 10

  By source:
    /etc/hosts: 5
    infrastructure.csv: 40

  Relations: 12 (8 validated)
```

---

## Best Practices

1. **Organize by source** - Import related hosts together
2. **Use environments** - Tag hosts with `production`, `staging`, `dev`
3. **Group logically** - Use groups for service types (`web`, `db`, `cache`)
4. **Configure SSH keys** - For hosts requiring specific keys
5. **Review relations** - Accept only accurate suggestions
6. **Create snapshots** - Before major changes

---

## API Reference

### Python API

```python
from merlya.memory.persistence.inventory_repository import get_inventory_repository

repo = get_inventory_repository()

# Add a host
host_id = repo.add_host(
    hostname="web-prod-01",
    ip_address="10.0.1.1",
    environment="production",
    groups=["web", "frontend"],
    metadata={"ssh_key_path": "~/.ssh/id_web"}
)

# Search hosts
hosts = repo.search_hosts(pattern="prod", limit=50)

# Get host by name
host = repo.get_host_by_name("web-prod-01")

# Add relation
repo.add_relation(
    source_hostname="db-master",
    target_hostname="db-replica",
    relation_type="replicates",
    confidence=0.95
)

# Get stats
stats = repo.get_stats()
```

---

## See Also

- [VARIABLES.md](VARIABLES.md) - Variable system (including host aliases)
- [CREDENTIALS.md](CREDENTIALS.md) - Credential management
- [TOOLS.md](TOOLS.md) - Available infrastructure tools
