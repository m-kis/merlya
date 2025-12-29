# SSH Management

Merlya provides powerful SSH management capabilities with connection pooling, jump hosts, auto-healing elevation, and intelligent retry logic.

## Connecting to Servers

### Basic Connection

```
Merlya > Connect to server.example.com

Connecting to server.example.com...
Connected successfully.

Merlya > Run "uptime"

> ssh server.example.com "uptime"
 10:30:15 up 30 days,  2:45,  1 user,  load average: 0.08, 0.12, 0.09
```

### With Credentials

```
Merlya > Connect to server.example.com as user admin with key ~/.ssh/admin_key

Connecting to server.example.com as admin...
Using key: ~/.ssh/admin_key
Connected successfully.
```

## Connection Pooling

Merlya automatically manages SSH connections:

- **Reuses connections** - No reconnection overhead
- **Automatic cleanup** - Idle connections are closed
- **Concurrent connections** - Execute on multiple servers in parallel

```
Merlya > Check uptime on all web servers

Executing on 5 servers in parallel...

web-01: up 45 days
web-02: up 45 days
web-03: up 12 days
web-04: up 45 days
web-05: up 3 days (recently restarted)
```

## Jump Hosts (Bastion)

Connect through a bastion/jump host:

```
Merlya > Connect to internal-db via bastion.example.com

Connecting through jump host: bastion.example.com
Connected to internal-db via bastion.
```

Configure jump hosts when adding hosts:

```bash
/hosts add internal-db 10.0.1.50 --user dbadmin --jump bastion.example.com
```

## Host Groups

Define and use host groups:

```bash
# Create a group
/hosts group create web-tier

# Add hosts to group
/hosts group add web-tier web-01 web-02 web-03
```

```
Merlya > Restart nginx on all web-tier servers

I'll restart nginx on all web-tier servers (web-01, web-02, web-03).

> ssh web-01 "sudo systemctl restart nginx"
> ssh web-02 "sudo systemctl restart nginx"
> ssh web-03 "sudo systemctl restart nginx"

Nginx restarted on all 3 servers.
```

## File Transfer

### Upload Files

```
Merlya > Upload config.yml to /etc/app/ on web-01

Uploading config.yml to web-01:/etc/app/config.yml...
Transfer complete (2.3 KB).
```

### Download Files

```
Merlya > Download /var/log/app.log from web-01

Downloading web-01:/var/log/app.log...
Saved to: ./app.log (45 KB)
```

## Error Handling

### Automatic Retry

Failed connections are automatically retried:

```
Merlya > Connect to flaky-server.example.com

Connection attempt 1 failed: Connection timeout
Retrying in 5 seconds...
Connection attempt 2 succeeded.
Connected to flaky-server.example.com.
```

### Connection Errors

```
Merlya > Connect to unknown-server.example.com

Unable to connect to unknown-server.example.com:
- Error: Host not found
- Suggestion: Check the hostname or add it to /etc/hosts
```

## Security

### Host Key Verification

```
Merlya > Connect to new-server.example.com

Warning: Unknown host key for new-server.example.com
Fingerprint: SHA256:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

Do you want to add this host to known_hosts? [y/N]
```

### Key-Based Authentication

Merlya supports various SSH key types:

- RSA (2048+ bits)
- Ed25519 (recommended)
- ECDSA

```bash
# Generate a new key
ssh-keygen -t ed25519 -f ~/.ssh/merlya_key

# Configure Merlya to use it
merlya config set ssh.default_key ~/.ssh/merlya_key
```

## Best Practices

1. **Use SSH keys** instead of passwords
2. **Configure jump hosts** for internal servers
3. **Use host groups** for batch operations
4. **Set appropriate timeouts** for slow networks
5. **Review commands** before execution on production

## Troubleshooting

### Connection Timeout

```bash
# Increase timeout
merlya config set ssh.timeout 60
```

### Permission Denied

```bash
# Check key permissions
chmod 600 ~/.ssh/your_key
chmod 700 ~/.ssh
```

### Too Many Connections

```bash
# Adjust pool size in ~/.merlya/config.yaml
ssh:
  max_connections: 20
```

## Privilege Elevation

Merlya automatically handles privilege elevation (sudo, doas, su) with an auto-healing fallback system.

### SSH Commands

```bash
# Basic SSH commands
/ssh connect <host>       # Connect to a host
/ssh exec <host> <cmd>    # Execute command
/ssh config <host>        # Configure SSH (user, key, port, jump)
/ssh test <host>          # Test connection with diagnostics
/ssh disconnect [host]    # Disconnect

# Elevation commands
/ssh elevation detect <host>   # Detect sudo/doas/su capabilities
/ssh elevation status <host>   # Show elevation status and failed methods
/ssh elevation reset [host]    # Clear failed methods (retry with new password)
```

### Elevation Priority

Merlya tries elevation methods in order:

1. **sudo (NOPASSWD)** - Best: no password needed
2. **doas (NOPASSWD)** - Common on BSD
3. **sudo_with_password** - Fallback with password
4. **doas_with_password** - Alternative with password
5. **su** - Last resort (root password)

### Auto-Healing Fallback

When an elevation method fails (wrong password):

1. Merlya **verifies** the password with a test command
2. **Marks failed** methods to avoid retry loops
3. **Tries next** method in the chain automatically
4. **Caches** passwords only after verification succeeds

```text
Merlya > Read /etc/shadow on web01

🔒 Command may require elevation. Use sudo_with_password? [y/N] y
🔑 Your password for elevation: ****
🔐 Verifying sudo_with_password...
❌ sudo_with_password failed (wrong password?)
🔒 Trying fallback methods: su
🔑 su (root password): ****
🔐 Verifying su...
✅ su verified
root:*:19000:0:99999:7:::
```

### Resetting Elevation

If passwords change or you need to retry:

```bash
# Reset for one host
/ssh elevation reset web01

# Reset for all hosts
/ssh elevation reset
```
