# Secure Credential Management

Merlya handles credentials securely with multiple flexible options for SSH keys, database passwords, and API tokens.

## Variable Types

Merlya supports three types of variables:

| Type | Persistence | Use Case |
|------|-------------|----------|
| `HOST` | Persisted | Host aliases (@proddb, @webserver) |
| `CONFIG` | Persisted | Configuration values (@region, @env) |
| `SECRET` | Session only | Passwords, tokens, SSH passphrases |

## SSH Key Management

### Global SSH Key (Recommended)

Set a default SSH key used for all hosts without specific configuration:

```bash
# Set global SSH key
/inventory ssh-key set ~/.ssh/id_ed25519

# View current configuration
/inventory ssh-key show

# Clear global key
/inventory ssh-key clear
```

### Per-Host SSH Key

Override the global key for specific hosts:

```bash
# Set host-specific key
/inventory ssh-key web-prod-01 set

# View host SSH config
/inventory ssh-key web-prod-01 show

# Clear host-specific key
/inventory ssh-key web-prod-01 clear
```

### Key Resolution Priority

When connecting to a host, Merlya resolves SSH keys in this order:

1. **Host-specific key** from inventory metadata (`ssh_key_path`)
2. **Global key** set via `/inventory ssh-key set`
3. **~/.ssh/config** `IdentityFile` for the host
4. **Default keys** (id_ed25519, id_ecdsa, id_rsa)

### Passphrase Handling

SSH key passphrases are:

- **Prompted on first use** (secure input with hidden characters)
- **Cached for session duration** (VariableType.SECRET)
- **Never persisted** to disk
- **Cleared automatically** on REPL exit

```bash
# Passphrase will be prompted automatically when needed
# Or set it explicitly with secure input
/variables set-secret ssh-passphrase-global
```

### Security Features

- **Path validation**: Keys must be in `~/.ssh`, `/etc/ssh`, or `MERLYA_SSH_KEY_DIR`
- **Permission check**: Warns if key permissions are not 0600/0400
- **Hostname validation**: RFC 1123 compliant hostnames and IP addresses
- **Sanitized logging**: Full paths never appear in logs

## Database Credentials

### Using Variables (Recommended)

```bash
# Define reusable credential variables
/variables set mongo-user admin
/variables set-secret mongo-pass  # Prompts with hidden input

# Use them in queries
check mongo status on @proddb using @mongo-user @mongo-pass
```

### Pass Credentials in Query

Include credentials directly in your natural language query:

```
"check mongo status on HOST user admin password secret123"
"show replica set status for HOST username admin passwd mypass"
"connect to HOST using admin:secret123"
```

### Environment Variables

For automation, set credentials before starting Merlya:

```bash
export MONGODB_USER="admin"
export MONGODB_PASS="your_password"
python -m merlya.cli repl
```

### Interactive Prompts

When credentials are needed but not provided:

```
[Credentials needed for mongodb on mongo-preprod-1]
mongodb username: admin
mongodb password: [hidden input]
```

## Variable Management

```bash
# List all variables (secrets are masked)
/variables list

# Set a regular variable
/variables set myvar value

# Set a secret (hidden input)
/variables set-secret api-key

# Delete a variable
/variables delete myvar

# Clear all secrets (keeps HOST and CONFIG)
/variables clear-secrets

# Clear all variables
/variables clear
```

## Security Best Practices

1. **Use SECRET type** for all sensitive values (passwords, tokens, passphrases)
2. **Set restrictive permissions** on SSH keys (chmod 600)
3. **Clear secrets** before sharing terminal: `/variables clear-secrets`
4. **Use environment variables** for automation (never hardcode in scripts)
5. **Audit variables** with `/variables list` to see what's cached

## Security Features Summary

| Feature | Implementation |
|---------|---------------|
| Secure input | Python `getpass` module (no echo) |
| Session storage | In-memory only for secrets |
| Persistence | SQLite for HOST/CONFIG only |
| Log redaction | Passwords replaced with [REDACTED] |
| Path validation | Prevents path traversal attacks |
| Permission check | Validates SSH key file modes |

## Credential TTL

Session credentials (database passwords) expire after 15 minutes of inactivity.
SSH passphrases remain valid until REPL exit.

## Custom SSH Key Directory

Set the `MERLYA_SSH_KEY_DIR` environment variable to allow SSH keys from additional directories:

```bash
export MERLYA_SSH_KEY_DIR=/opt/custom/keys
```
