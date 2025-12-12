# Agent Tools

The Merlya agent has access to various tools for infrastructure management.

## Core Tools

### `list_hosts`
List hosts from inventory.

**Parameters:**
- `tag` (optional): Filter by tag
- `status` (optional): Filter by health status
- `limit` (optional): Max results

**Example prompts:**
- "Show me all production servers"
- "List hosts tagged with database"

### `get_host`
Get detailed information about a specific host.

**Parameters:**
- `name`: Host name or pattern

**Example prompts:**
- "What's the IP of web01?"
- "Show me details for the database server"

### `bash`
Execute a command locally on the Merlya host machine.

**Parameters:**
- `command`: Command to execute
- `timeout` (default: 60): Command timeout in seconds

**Use cases:**
- kubectl, aws, gcloud, az CLI commands
- docker commands (local daemon)
- Local file operations
- Any CLI tool installed locally

**Example prompts:**
- "Check pods in namespace production"
- "List AWS EC2 instances"
- "Show local docker containers"

**Note:** This is the universal fallback for local operations. Dangerous commands are blocked (rm -rf /, mkfs, etc.).

### `ssh_execute`
Execute a command on a remote host.

**Parameters:**
- `host`: Target host name (inventory entry or direct hostname/IP)
- `command`: Command to execute
- `timeout` (default: 60): Command timeout in seconds
- `elevation` (optional): Elevation method (sudo, doas, su)
- `via` (optional): Jump host for SSH tunneling

**Proactive mode:** If the host is not in inventory, the agent will attempt direct connection instead of failing.

**Example prompts:**
- "Check disk usage on web01"
- "Restart nginx on @web01 via @bastion"
- "Run 'uptime' on all production servers"

### `ask_user`
Ask the user a question.

**Parameters:**
- `question`: Question to ask
- `choices` (optional): List of valid choices

**Used when:** Agent needs clarification or user input.

### `request_confirmation`
Request yes/no confirmation.

**Parameters:**
- `message`: Confirmation message

**Used when:** Before destructive operations.

## System Tools

### `get_system_info`
Get OS and system information.

**Returns:** OS name, version, kernel, architecture

### `get_cpu_info`
Get CPU usage and information.

**Returns:** CPU count, usage percentage, load average

### `get_memory_info`
Get memory usage.

**Returns:** Total, used, available, percentage

### `get_disk_info`
Get disk usage for all mount points.

**Returns:** Filesystems with size, used, available

### `get_process_list`
List running processes.

**Parameters:**
- `sort_by`: cpu, memory, pid
- `limit`: Max processes to return

### `get_service_status`
Check service status.

**Parameters:**
- `service_name`: Name of the service

**Returns:** Status, enabled, active

### `get_uptime`
Get system uptime.

**Returns:** Uptime string, boot time

## File Tools

### `read_file`
Read contents of a remote file.

**Parameters:**
- `host`: Target host
- `path`: File path
- `lines` (optional): Number of lines to read

### `write_file`
Write content to a remote file.

**Parameters:**
- `host`: Target host
- `path`: File path
- `content`: File content
- `mode` (optional): File permissions

### `list_directory`
List directory contents.

**Parameters:**
- `host`: Target host
- `path`: Directory path
- `all_files`: Include hidden files
- `long_format`: Detailed listing

### `search_files`
Search for files by pattern.

**Parameters:**
- `host`: Target host
- `path`: Search path
- `pattern`: Glob pattern (e.g., "*.log")
- `file_type`: f (file), d (directory)
- `max_depth`: Search depth

## Security Tools

### `check_open_ports`
Scan for open ports.

**Parameters:**
- `host`: Target host
- `include_listening`: Include listening ports
- `include_established`: Include established connections

### `audit_ssh_keys`
Audit SSH keys on a host.

**Returns:** Key information, permissions, issues

### `check_users`
List system users.

**Parameters:**
- `host`: Target host
- `include_system`: Include system users

### `check_sudo_config`
Check sudo configuration.

**Returns:** Sudoers rules, NOPASSWD entries

### `check_failed_logins`
Check for failed login attempts.

**Returns:** Recent failed logins from auth logs

### `check_pending_updates`
Check for pending system updates.

**Returns:** Available updates count, package list

### `check_critical_services`
Check status of critical services.

**Services checked:** sshd, firewalld/ufw, fail2ban

### `check_security_config`
Audit security configuration.

**Checks:** SSH hardening, firewall rules, SELinux/AppArmor

## Web Tools

### `web_search`
Search the web using DuckDuckGo.

**Parameters:**
- `query`: Search query
- `max_results` (default: 5): Maximum results

**Example prompts:**
- "Search for nginx configuration best practices"
- "Find documentation for systemd service files"

## Interaction Tools

### `request_credentials`
Request credentials from user.

**Parameters:**
- `service`: Service name
- `fields`: List of fields to request

**Used when:** Authentication is required for a service.

### `request_elevation`
Prepare for privilege elevation.

**Parameters:**
- `host`: Target host
- `method` (optional): sudo, doas, su

**Returns:** Elevation command prefix, detection results

## Tool Selection

The router suggests tools based on user intent:

| Intent Keywords | Tools Activated |
|-----------------|-----------------|
| cpu, memory, disk, process | system |
| file, log, config, read, write | files |
| port, firewall, ssh, security | security |
| docker, container | docker (local via bash) |
| kubernetes, k8s, pod | kubernetes (local via bash) |
| aws, gcloud, az, terraform | cloud CLI (local via bash) |
| search, find, google | web |

**When to use bash vs ssh_execute:**
- `bash`: Local tools (kubectl, aws, docker, gcloud, az, terraform, etc.)
- `ssh_execute`: Commands on remote servers via SSH

The agent may use additional tools based on context and reasoning.
