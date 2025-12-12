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
Execute 'uptime' on web-01 through @jump-host
Analyse 192.168.1.100 via @ansible
```

### Patterns Detected

Merlya recognizes these patterns:

**English:**
- `via @hostname`
- `through @hostname`
- `using bastion @hostname`

**French:**
- `via @hostname`
- `via la machine @hostname`
- `en passant par @hostname`
- `à travers @hostname`

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

### Using @ Mentions

Reference hosts with `@`:

```
Check memory on @web01
```

This resolves `web01` from inventory and uses its configuration.

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

Merlya automatically handles privilege elevation (sudo, doas, su) on remote hosts.

### Automatic Detection

When connecting to a host, Merlya detects available elevation methods:

1. **sudo NOPASSWD** - Tests `sudo -n true` (non-interactive)
2. **doas** - Common on BSD systems
3. **sudo with password** - Standard sudo requiring password
4. **su** - Last resort, requires root password

### Method Priority

```
1. sudo (NOPASSWD)      - Best: no password needed
2. doas (NOPASSWD)      - Common on BSD
3. sudo_with_password   - Fallback with password
4. su                   - Last resort
```

### Password Handling

Elevation passwords are stored securely:

1. **Keyring storage** - macOS Keychain, Linux Secret Service
2. **Reference tokens** - Commands use `@elevation:hostname:password`
3. **Safe logging** - Logs show `@elevation:...`, never actual passwords

### Usage in Commands

Merlya handles elevation automatically:

```
> Read /var/log/secure on @web01
# Merlya detects "Permission denied"
# Prompts for elevation if needed
# Retries with sudo/doas/su
```

You can also explicitly request elevation:

```
> Run 'systemctl restart nginx' on @web01 with sudo
> Execute 'cat /etc/shadow' on @db01 as root
```

### Secret References

For commands requiring passwords, use secret references:

```
> Connect to MongoDB with password @db-prod-password on @db01
```

Secret references (`@name`) are:
- Stored in system keyring
- Resolved at execution time
- Never appear in logs

### Elevation Configuration

Per-host elevation settings are cached in host metadata:

```bash
/hosts show @web01
# Shows detected elevation method
```

### Troubleshooting

#### "Permission denied" persists

**Solutions:**
- Check user has sudo/doas access on target
- Verify `/etc/sudoers` configuration
- Try explicit elevation: `run as root`

#### Password prompt loops

**Solutions:**
- Clear cached password: `/secret delete elevation:hostname:password`
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
