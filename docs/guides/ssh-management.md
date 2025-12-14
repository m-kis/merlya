# SSH Management

Merlya provides powerful SSH management capabilities with connection pooling, jump hosts, and intelligent retry logic.

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

Configure in `hosts.toml`:

```toml
[hosts.internal-db]
hostname = "10.0.1.50"
user = "dbadmin"
jump_host = "bastion.example.com"
```

## Host Groups

Define and use host groups:

```toml
# ~/.config/merlya/hosts.toml
[groups.web-tier]
hosts = ["web-01", "web-02", "web-03"]

[groups.db-tier]
hosts = ["db-master", "db-replica-01"]
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
# Adjust pool size
merlya config set ssh.max_connections 20
```
