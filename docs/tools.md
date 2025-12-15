# Agent Tools

The Merlya agent has access to 50+ tools for infrastructure management.

## Core Tools

### `list_hosts`
List hosts from inventory.

**Parameters:**
- `tag` (optional): Filter by tag
- `status` (optional): Filter by health status
- `limit` (default: 50): Max results (1-1000)

**Example prompts:**
- "Show me all production servers"
- "List hosts tagged with database"

### `get_host`
Get detailed information about a specific host.

**Parameters:**
- `name`: Host name
- `include_metadata` (default: true): Include enriched metadata

**Returns:** id, name, hostname, port, username, tags, health_status, OS info, metadata

### `bash_execute`
Execute a command locally on the Merlya host machine.

**Parameters:**
- `command`: Command to execute
- `timeout` (default: 60): Command timeout in seconds (1-3600)

**Use cases:**
- kubectl, aws, gcloud, az CLI commands
- docker commands (local daemon)
- Local file operations
- Any CLI tool installed locally

**Note:** Dangerous commands are blocked (rm -rf /, mkfs, dd to devices, etc.).

### `ssh_execute`
Execute a command on a remote host via SSH with automatic elevation.

**Parameters:**
- `host`: Target host name (inventory entry or direct hostname/IP)
- `command`: Command to execute (supports @secret-name references)
- `timeout` (default: 60): Command timeout in seconds
- `connect_timeout` (optional): Connection timeout
- `elevation` (optional): Prepared elevation payload
- `via` (optional): Jump host/bastion for SSH tunneling
- `auto_elevate` (default: true): Auto-retry with elevation on permission errors

**Returns:** stdout, stderr, exit_code, host, command, elevation method, jump host

**Features:**
- Automatic privilege elevation (sudo, doas, su)
- Jump host support
- Password detection and warning
- Secret reference resolution

### `ask_user`
Ask the user for input.

**Parameters:**
- `question`: Question to ask
- `choices` (optional): List of valid choices
- `default` (optional): Default value
- `secret` (default: false): Whether to hide input

### `request_confirmation`
Request user confirmation before an action.

**Parameters:**
- `action`: Description of the action
- `details` (optional): Additional details
- `risk_level` (default: "moderate"): low, moderate, high, critical

**Returns:** True/False confirmation

### `get_variable`
Get a variable value.

**Parameters:**
- `name`: Variable name

### `set_variable`
Set a variable.

**Parameters:**
- `name`: Variable name
- `value`: Variable value
- `is_env` (default: false): Export as environment variable

**Security:** Blocks setting dangerous environment variables (PATH, LD_PRELOAD, etc.)

## System Tools

### `get_system_info`
Get OS and system information from a host.

**Parameters:**
- `host`: Target host name

**Returns:** hostname, OS, kernel, architecture, uptime, load average

### `check_cpu`
Check CPU usage on a host.

**Parameters:**
- `host`: Target host name
- `threshold` (default: 80): Warning threshold percentage

**Returns:** load_1m, load_5m, load_15m, cpu_count, use_percent, warning flag

### `check_memory`
Check memory usage on a host.

**Parameters:**
- `host`: Target host name
- `threshold` (default: 90): Warning threshold percentage

**Returns:** total_mb, used_mb, available_mb, buffers_mb, cached_mb, use_percent, warning flag

### `check_disk_usage`
Check disk usage on a specific filesystem.

**Parameters:**
- `host`: Target host name
- `path` (default: "/"): Filesystem path
- `threshold` (default: 90): Warning threshold percentage

**Returns:** filesystem, size, used, available, use_percent, mount point, warning flag

### `check_all_disks`
Check disk usage on all mounted filesystems.

**Parameters:**
- `host`: Target host name
- `threshold` (default: 90): Warning threshold percentage
- `exclude_types` (optional): Filesystem types to exclude

**Returns:** List of disk info, total_count, warnings count

### `list_processes`
List running processes on a host.

**Parameters:**
- `host`: Target host name
- `user` (optional): Filter by user
- `filter_name` (optional): Filter by process name
- `limit` (default: 20): Max processes (1-1000)
- `sort_by` (default: "cpu"): cpu, mem, pid

**Returns:** List of processes with user, pid, cpu%, mem%, command

### `check_service_status`
Check the status of a systemd service.

**Parameters:**
- `host`: Target host name
- `service`: Service name

**Returns:** service status, active state, sub state, main PID

### `manage_service`
Manage a systemd service.

**Parameters:**
- `host`: Target host name
- `service`: Service name
- `action`: start, stop, restart, reload, status, enable, disable
- `force` (default: false): Skip confirmation for dangerous actions

**Security:** Critical services (sshd, networking, docker) require extra confirmation

### `list_services`
List services on a host.

**Parameters:**
- `host`: Target host name
- `filter_state` (optional): Filter by state

### `analyze_logs`
Analyze log files on a host.

**Parameters:**
- `host`: Target host name
- `log_path` (default: "/var/log/syslog"): Path to log file
- `pattern` (optional): Grep pattern to filter
- `lines` (default: 50): Number of lines (1-10000)
- `level` (optional): error, warn, info, debug

**Returns:** log entries list and count

### `check_docker`
Check Docker status and containers.

**Parameters:**
- `host`: Target host name

**Returns:** Docker status, containers list, images list

### `health_summary`
Get consolidated health view across hosts.

**Parameters:**
- `hosts`: List of host names

**Returns:** Aggregated health summary

### `list_cron`
List crontab entries on a host.

**Parameters:**
- `host`: Target host name
- `user` (optional): Specific user
- `include_system` (default: true): Include /etc/cron.*

**Returns:** cron entries list

## Network Tools

### `check_network`
Perform network diagnostics from a remote host.

**Parameters:**
- `host`: Target host name
- `target` (optional): Specific target to check
- `check_dns` (default: true): Check DNS resolution
- `check_gateway` (default: true): Check default gateway
- `check_internet` (default: true): Check internet connectivity

**Returns:** interface info, gateway, DNS, internet status, issues list

### `ping`
Ping a target from a remote host.

**Parameters:**
- `host`: Source host name
- `target`: Target to ping
- `count` (default: 4, max: 10): Number of packets
- `timeout` (default: 5, max: 30): Timeout in seconds

**Returns:** target, reachable, packets sent/received, packet_loss%, RTT min/avg/max

### `traceroute`
Run traceroute from a remote host.

**Parameters:**
- `host`: Source host name
- `target`: Target to trace
- `max_hops` (default: 20, max: 30): Maximum hops

**Returns:** traceroute output and parsed hops

### `check_port`
Check if a port is reachable from a remote host.

**Parameters:**
- `host`: Source host name
- `target_host`: Target to check
- `port`: Port number (1-65535)
- `timeout` (default: 5): Connection timeout

**Returns:** port status, open flag, response_time_ms

### `dns_lookup`
Perform DNS lookup from a remote host.

**Parameters:**
- `host`: Source host name
- `query`: Domain to lookup
- `record_type` (default: "A"): A, AAAA, MX, NS, TXT, CNAME, SOA, PTR

**Returns:** DNS records list, resolved flag, response_time_ms

## File Tools

### `read_file`
Read file content from a remote host.

**Parameters:**
- `host_name`: Target host
- `path`: File path
- `lines` (optional): Number of lines (1-100000)
- `tail` (default: false): Read from end of file

### `write_file`
Write content to a file on a remote host.

**Parameters:**
- `host_name`: Target host
- `path`: File path
- `content`: Content to write
- `mode` (default: "0644"): File permissions
- `backup` (default: true): Create backup before writing

**Security:** Uses base64 encoding for safe transfer

### `list_directory`
List directory contents on a remote host.

**Parameters:**
- `host_name`: Target host
- `path`: Directory path
- `all_files` (default: false): Include hidden files
- `long_format` (default: false): Detailed listing

### `file_exists`
Check if a file exists on a remote host.

**Parameters:**
- `host_name`: Target host
- `path`: File path

**Returns:** "exists" or "not_found"

### `file_info`
Get file information (stat) from a remote host.

**Parameters:**
- `host_name`: Target host
- `path`: File path

**Returns:** name, size, owner, group, mode, modified timestamp

### `search_files`
Search for files on a remote host.

**Parameters:**
- `host_name`: Target host
- `path`: Search path
- `pattern`: File name pattern (1-256 chars)
- `file_type` (optional): f (file), d (directory)
- `max_depth` (optional): Maximum search depth (1-100)

**Returns:** List of matching file paths

### `delete_file`
Delete a file on a remote host.

**Parameters:**
- `host_name`: Target host
- `path`: File path
- `force` (default: false): Skip confirmation

**Security:** Refuses to delete system paths (/etc, /var, /usr, /home, /root, /bin, /sbin)

### `upload_file`
Upload a local file to a remote host via SFTP.

**Parameters:**
- `host_name`: Target host
- `local_path`: Local file path
- `remote_path`: Remote destination path
- `max_size` (default: 100MB): Maximum file size

### `download_file`
Download a file from a remote host via SFTP.

**Parameters:**
- `host_name`: Source host
- `remote_path`: Remote file path
- `local_path` (optional): Local destination path

### `compare_files`
Compare files between two hosts or between host and local.

**Parameters:**
- `host1`: First host (or "local")
- `path1`: Path on first host
- `host2` (optional): Second host (or "local")
- `path2` (optional): Path on second host
- `show_diff` (default: true): Include diff output
- `context_lines` (default: 3): Lines of context in diff

**Returns:** identical flag, hashes, sizes, diff lines, additions/deletions/changes

## Security Tools

### `check_open_ports`
Check open ports on a remote host.

**Parameters:**
- `host_name`: Target host
- `include_listening` (default: true): Include listening ports
- `include_established` (default: false): Include established connections

**Uses:** ss (Linux) or netstat (fallback)

### `audit_ssh_keys`
Audit SSH keys on a remote host.

**Parameters:**
- `host_name`: Target host

**Returns:** paths, permissions, key types, severity issues

**Security:** Validates key paths, checks permissions (should be 600)

### `check_security_config`
Check security configuration on a remote host.

**Parameters:**
- `host_name`: Target host

**Checks:** PermitRootLogin, PasswordAuthentication, PubkeyAuthentication, PermitEmptyPasswords, firewall status

### `check_users`
Audit user accounts on a remote host.

**Parameters:**
- `host_name`: Target host

**Returns:** users with shell access, empty password issues, severity levels

### `check_sudo_config`
Check sudoers configuration.

**Parameters:**
- `host_name`: Target host

**Returns:** sudo configuration audit

### `check_critical_services`
Check critical services status.

**Parameters:**
- `host_name`: Target host

**Services checked:** sshd, firewalld/ufw, fail2ban

### `check_failed_logins`
Check failed login attempts (24h lookback).

**Parameters:**
- `host_name`: Target host

**Returns:** failed login analysis, top offending IPs

**Severity:** Critical (>50 attempts), Warning (>20 attempts)

### `check_pending_updates`
Check for pending system updates.

**Parameters:**
- `host_name`: Target host

**Detects:** apt, dnf, yum package managers

**Severity:** Critical (>5 security updates), Warning (>10 total updates)

### `check_ssl_certs`
Check SSL certificates on a host.

**Parameters:**
- `host_name`: Target host

**Returns:** SSL certificate information, expiry warnings

## Web Tools

### `search_web`
Perform a web search using DuckDuckGo.

**Parameters:**
- `query`: Search query
- `max_results` (default: 5, max: 10): Maximum results
- `region` (optional): Region code (e.g., "fr-fr", "us-en")
- `safesearch` (default: "moderate"): off, moderate, strict
- `timeout` (default: 8.0): Max time in seconds

**Returns:** results list (title, url, snippet), count, cached flag

**Features:** Built-in caching (60s TTL)

## Interaction Tools

### `request_credentials`
Prompt the user for credentials.

**Parameters:**
- `service`: Service name (e.g., mysql, mongo, api)
- `host` (optional): Host context
- `fields` (optional): Fields to collect (default: username, password)
- `format_hint` (optional): token, json, passphrase, key
- `allow_store` (default: true): Offer storage in keyring

**Returns:** credential bundle with service, host, values dict, stored flag

### `request_elevation`
Request privilege elevation.

**Parameters:**
- `host`: Target host
- `method` (optional): sudo, doas, su

**Returns:** Elevation payload for use with ssh_execute

## Tool Selection

The router suggests tools based on user intent:

| Intent Keywords | Tools Activated |
|-----------------|-----------------|
| cpu, memory, disk, process | system |
| file, log, config, read, write | files |
| port, firewall, ssh, security | security |
| network, ping, dns, traceroute | network |
| docker, container | docker |
| kubernetes, k8s, pod | bash (kubectl) |
| aws, gcloud, az, terraform | bash (cloud CLI) |
| search, find, google | web |

**When to use bash_execute vs ssh_execute:**
- `bash_execute`: Local tools (kubectl, aws, docker, gcloud, az, terraform, etc.)
- `ssh_execute`: Commands on remote servers via SSH

The agent may use additional tools based on context and reasoning.
