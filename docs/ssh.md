# SSH & Jump Hosts

Merlya manages SSH connections with pooling, authentication, and jump host support.

## Connection Pool

Connections are reused to improve performance:

- **Pool size**: 50 connections max (LRU eviction)
- **Pool timeout**: 600 seconds (configurable)
- **Connect timeout**: 30 seconds
- **Command timeout**: 60 seconds

## Authentication

Merlya tries authentication methods in order:

1. **SSH Agent** - Keys loaded in ssh-agent
2. **Key file** - Private key from inventory or default
3. **Passphrase prompt** - For encrypted keys
4. **Password** - If configured
5. **Keyboard-interactive** - For MFA

### SSH Agent

If `ssh-agent` is running, Merlya uses it automatically:

```bash
# Start agent and add key
eval $(ssh-agent)
ssh-add ~/.ssh/id_ed25519
```

### Encrypted Keys

For encrypted private keys, Merlya prompts for the passphrase:

```
Enter passphrase for key /home/user/.ssh/id_ed25519: ****
```

Passphrases can be cached in keyring for the session.

### MFA/2FA

Keyboard-interactive authentication is supported for MFA:

```
Enter MFA code: 123456
```

## Jump Hosts / Bastions

Access servers through a bastion host using the `via` parameter.

### Natural Language

```
Check disk on db-server via bastion
Execute 'uptime' on web-01 through jump-host
Analyse 192.168.1.100 via ansible
```

### Patterns Detected

Merlya recognizes these patterns:

**English:**

- `via hostname`
- `through hostname`
- `using bastion hostname`

**French:**

- `via hostname`
- `via la machine hostname`
- `en passant par hostname`
- `à travers hostname`

### How It Works

```
┌──────────┐      ┌──────────┐      ┌──────────┐
│  Merlya  │ ──── │  Bastion │ ──── │  Target  │
│          │ SSH  │ (jump)   │ SSH  │ (db-01)  │
└──────────┘      └──────────┘      └──────────┘
```

1. Merlya connects to bastion via SSH
2. Creates tunnel through bastion to target
3. Executes commands on target through tunnel
4. Returns results

### Inventory Configuration

Set a default jump host for a host in inventory:

```bash
/hosts add db-internal 10.0.0.50 --jump bastion
```

The `via` parameter in commands overrides inventory settings.

### Multiple Hops

For multiple jump hosts, configure the chain in inventory:

```bash
/hosts add jump1 1.2.3.4
/hosts add jump2 10.0.0.1 --jump jump1
/hosts add target 192.168.1.100 --jump jump2
```

## Host Resolution

When you reference a host, Merlya resolves it in order:

1. **Inventory** - Hosts added via `/hosts add`
2. **SSH Config** - `~/.ssh/config` entries
3. **Known hosts** - `~/.ssh/known_hosts`
4. **/etc/hosts** - System hosts file
5. **DNS** - Standard DNS resolution

### Host Names

Reference hosts by their inventory name (without `@`):

```
Check memory on web01
```

This resolves `web01` from inventory and uses its configuration.

> **Note**: The `@` prefix is reserved for secret references (e.g., `@db-password`), not host names.

## SSH Configuration

### In `~/.merlya/config.yaml`:

```yaml
ssh:
  pool_timeout: 600      # Connection reuse time
  connect_timeout: 30    # Connection timeout
  command_timeout: 60    # Command timeout
  default_user: admin    # Default SSH user
  default_key: ~/.ssh/id_ed25519  # Default key
```

### Per-Host Configuration

When adding hosts:

```bash
/hosts add web01 10.0.1.5 \
  --user deploy \
  --port 2222 \
  --key ~/.ssh/deploy_key \
  --jump bastion
```

## Troubleshooting

### Connection Timeout

```
SSH connection failed: Connection timeout
```

**Solutions:**
- Check network connectivity
- Verify host is reachable
- Increase `connect_timeout` in config

### Authentication Failed

```
Authentication failed for user@host
```

**Solutions:**
- Verify SSH key is correct
- Check ssh-agent is running
- Ensure public key is in `authorized_keys`

### Permission Denied

```
Permission denied (publickey,password)
```

**Solutions:**
- Check username is correct
- Verify key permissions (600 for private key)
- Try with password authentication

### Jump Host Issues

```
Failed to connect through jump host
```

**Solutions:**
- Verify jump host is accessible
- Check jump host authentication
- Ensure target is reachable from jump host

### Host Key Verification

```
Host key verification failed
```

**Solutions:**
- Add host to `~/.ssh/known_hosts`
- Or enable auto-add (less secure)

## Privilege Elevation

Merlya handles privilege elevation (sudo, doas, su) on remote hosts using **explicit per-host configuration**. No auto-detection - you configure the elevation method when adding a host.

### Configuration

Elevation is configured per-host in the inventory:

```bash
# Configure elevation when editing a host
/hosts edit web01
# → Prompts for elevation_method: none, sudo, sudo_password, doas, doas_password, su

# Or import with elevation configured (TOML/YAML/CSV)
/hosts import inventory.toml
```

### Elevation Methods

| Method           | Description                | Password Required |
| ---------------- | -------------------------- | ----------------- |
| `none`           | No elevation (default)     | No                |
| `sudo`           | sudo with NOPASSWD         | No                |
| `sudo_password`  | sudo requiring password    | Yes               |
| `doas`           | doas with NOPASSWD (BSD)   | No                |
| `doas_password`  | doas requiring password    | Yes               |
| `su`             | su (root password)         | Yes               |

### TOML Example

```toml
[hosts.web01]
hostname = "192.168.1.10"
user = "deploy"
elevation_method = "sudo_password"
elevation_user = "root"

[hosts.db01]
hostname = "192.168.1.20"
user = "admin"
elevation_method = "sudo"  # NOPASSWD configured
```

### Password Handling

Elevation passwords are handled securely:

1. **Prompt on demand** - Asks for password when needed
2. **Session caching** - Optionally cache for current session
3. **Keyring storage** - Store in system keyring (macOS Keychain, Linux Secret Service)
4. **Reference tokens** - Commands use `@elevation:hostname:password`
5. **Safe logging** - Logs show `@elevation:...`, never actual passwords

### Usage in Commands

When a command requires elevation, Merlya:

1. Checks host's `elevation_method` configuration
2. Prompts for confirmation (DIAGNOSTIC) or HITL approval (CHANGE)
3. Requests password if needed
4. Executes with appropriate elevation

```bash
> Read /var/log/secure on web01
# Host web01 has elevation_method=sudo_password
# Prompts: "Execute as root on web01? [Y/n]"
# If yes, prompts for password
# Executes: sudo -S cat /var/log/secure
```

### Clear Elevation Passwords

```bash
/secret clear-elevation           # List stored elevation passwords
/secret clear-elevation web01     # Clear for specific host
/secret clear-elevation --all     # Clear all elevation passwords
```

### Secret References

For commands requiring passwords, use secret references:

```
> Connect to MongoDB with password @db-prod-password on db01
```

Secret references (`@name`) are:
- Stored in system keyring
- Resolved at execution time
- Never appear in logs

### Elevation Configuration

Per-host elevation settings are cached in host metadata:

```bash
/hosts show web01
# Shows detected elevation method
```

### Troubleshooting

#### "Permission denied" persists

**Solutions:**
- Check user has sudo/doas access on target
- Run `/ssh elevation detect <host>` to check capabilities
- Verify `/etc/sudoers` configuration
- Try explicit elevation: `run as root`

#### Wrong password loops

Merlya prevents infinite loops by tracking failed methods:

```bash
# Check which methods have failed
/ssh elevation status <host>

# Reset to try again with correct password
/ssh elevation reset <host>
```

#### User not in sudoers

If `/ssh elevation detect` shows "user NOT in sudoers":
- Merlya will automatically fall back to su
- Or add the user to sudoers on the remote host

#### Password prompt loops

**Solutions:**
- Clear cached password: `/secret delete elevation:hostname:password`
- Reset elevation: `/ssh elevation reset <host>`
- Check password is correct
- Verify sudo doesn't require TTY (`requiretty` in sudoers)

## Security Best Practices

1. **Use SSH keys** instead of passwords
2. **Use SSH agent** to avoid passphrase prompts
3. **Use jump hosts** for internal servers
4. **Limit pool timeout** for sensitive environments
5. **Audit SSH keys** regularly with `/scan --security`
6. **Use NOPASSWD sudo** for automation accounts
7. **Never embed passwords** in commands - use `@secret` references
