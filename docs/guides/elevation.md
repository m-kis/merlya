# Privilege Elevation (sudo / doas / su)

Merlya handles privilege elevation **transparently**: you declare *how* a host should be elevated in the inventory, and the system applies the correct wrapper automatically. The AI agent sends plain commands — it never needs to add `sudo` prefixes or manage passwords.

---

## How It Works

```
┌──────────────────────────────────────────────────────────────┐
│                  TRANSPARENT ELEVATION FLOW                  │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  1. LLM sends a plain command                               │
│     └── "apt update"                                        │
│                                                              │
│  2. System reads host's elevation_method from inventory     │
│     └── box-1 → elevation_method = sudo_password            │
│                                                              │
│  3. System checks the keyring for a stored credential       │
│     └── Found: @sudo:box-1:password                         │
│     └── Not found: prompts user once, stores for session    │
│                                                              │
│  4. System wraps the command                                │
│     └── "sudo -S apt update" (stdin = @sudo:box-1:password) │
│                                                              │
│  5. Credential resolved at execution time (never sent to LLM)│
│     └── Actual: sudo -S apt update  (stdin: s3cr3t)         │
│     └── Logged: sudo -S apt update  (stdin: ***)            │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**What the LLM sees:** plain command (`apt update`) + result.

**What actually runs:** `sudo -S apt update` with the password piped on stdin.

**What gets logged:** `sudo -S apt update` with stdin masked as `***`.

---

## Elevation Methods

Each host has one `elevation_method` value. Choose the one that matches how that host is configured.

| Method | Command applied | Password needed | Typical use case |
|--------|----------------|-----------------|------------------|
| `none` | *(command unchanged)* | No | Non-root access, or already root |
| `sudo` | `sudo <cmd>` | No | NOPASSWD sudoers entry |
| `sudo_password` | `sudo -S <cmd>` | Yes (stdin) | Password-protected sudo |
| `doas` | `doas <cmd>` | No | OpenBSD/Alpine doas, NOPASSWD |
| `doas_password` | `doas <cmd>` | Yes (stdin) | Password-protected doas |
| `su` | `su -c '<cmd>'` | Yes (stdin) | Root password (no sudo) |

> **`none` is the default.** If a host has no `elevation_method` configured, commands run as the SSH user with no wrapping.

---

## Configuring Elevation on a Host

### When adding a host

```bash
/hosts add web-01 192.168.1.10 --user deploy --elevation sudo_password
```

### When editing an existing host

```bash
/hosts edit web-01
# Opens an interactive form — set the elevation_method field
```

Or via natural language:

```
Merlya > Set web-01 elevation method to sudo_password
```

### Checking current config

```bash
/hosts get web-01
```

```
Host: web-01
  Hostname:         192.168.1.10
  User:             deploy
  Elevation method: sudo_password
```

---

## Managing Elevation Credentials

### How credentials are looked up

When a host has a password-based elevation method (`sudo_password`, `doas_password`, `su`), the system:

1. Looks up `sudo:<hostname>:password` in the OS keyring (or `root:<hostname>:password` for `su`)
2. If found → uses it immediately, no prompt
3. If not found → prompts the user (hidden input), stores in keyring for the session

The lookup uses the host's **inventory name** (e.g. `web-01`), not its IP or FQDN.

### Credential key naming

| Elevation method | Keyring key | Example |
|-----------------|-------------|---------|
| `sudo_password` | `sudo:<name>:password` | `sudo:web-01:password` |
| `doas_password` | `doas:<name>:password` | `doas:box-1:password` |
| `su` | `root:<name>:password` | `root:db-prod:password` |

### Pre-storing credentials (before a session or in CI)

```bash
# sudo password
/secret set sudo:web-01:password

# root password (su method)
/secret set root:db-prod:password

# doas password
/secret set doas:box-1:password
```

Both commands prompt for the value with hidden input. The raw password is stored in the OS keyring and never written to disk or sent to the LLM.

### Checking stored credentials

```bash
/secret list
```

```
Secret Store Status
  Backend: keyring (macOS Keychain)
  Stored secrets:
    - sudo:web-01:password
    - root:db-prod:password
```

### Clearing a stored credential

```bash
/secret clear sudo:web-01:password
```

---

## Usage Examples

### NOPASSWD sudo (most common for managed servers)

```bash
# 1. On the host, add sudoers entry
echo "deploy ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/merlya

# 2. In Merlya inventory
/hosts edit web-01
# Set elevation_method = sudo
```

```
Merlya > Check disk usage on web-01

> df -h /
Filesystem  Size  Used Avail Use% Mounted on
/dev/sda1   100G   42G   58G  42% /
```

The system automatically ran `sudo df -h /`. No prompt, no password.

---

### Password-protected sudo

```bash
# 1. In Merlya inventory
/hosts edit box-1
# Set elevation_method = sudo_password

# 2. Pre-store the credential (optional — will be prompted if missing)
/secret set sudo:box-1:password
```

```
Merlya > Restart nginx on box-1

🔐 Elevation required for box-1 (sudo_password)
Password: ****
✅ Credential stored for this session.

> sudo -S systemctl restart nginx
```

On the second command to the same host:

```
Merlya > Check nginx status on box-1

> sudo -S systemctl status nginx    ← no prompt, credential reused
● nginx.service - A high performance web server
   Active: active (running)
```

---

### Root password (su method)

For servers without sudo, where you must use the root password directly:

```bash
# In Merlya inventory
/hosts edit legacy-server
# Set elevation_method = su
```

```
Merlya > Read /etc/shadow on legacy-server

🔐 Elevation required for legacy-server (su, root password)
Password: ****

> su -c 'cat /etc/shadow'
root:*:19000:0:99999:7:::
...
```

---

### No elevation (default)

If the SSH user already has the required permissions, or the host is used read-only:

```bash
/hosts edit monitoring-agent
# Set elevation_method = none  (or leave unset)
```

Commands run exactly as typed, with no wrapper.

---

## Instructions to the AI Agent

The agent is explicitly told not to add `sudo`, `doas`, or `su` prefixes to commands. The system prompt says:

> Elevation is handled **transparently** by the system based on the host's configuration.
> Just run commands naturally — `apt update`, `cat /var/log/syslog`, `systemctl status nginx`.
> The system will apply `sudo`, `sudo -S`, or `su -c` automatically when the host requires it.
> Do NOT add sudo/doas/su prefixes yourself.

If the agent does add a prefix (e.g. `sudo apt update`), the system strips it before applying the configured wrapper — so double-prefixing (`sudo sudo apt update`) never occurs.

---

## Non-Interactive Mode (CI/CD)

In `--yes` mode, Merlya cannot prompt for credentials. If a credential is missing, the command fails immediately with a clear error:

```
❌ Cannot obtain elevation credentials in non-interactive mode.

Missing: sudo:web-01:password

To fix this:
  1. Pre-store the credential: merlya secret set sudo:web-01:password
  2. Or configure NOPASSWD sudo on the host and set elevation_method = sudo
  3. Or run in interactive mode (without --yes)
```

**Best practice for CI:** use `elevation_method = sudo` with NOPASSWD sudoers entries, or pre-store credentials in the keyring before running automation.

---

## Troubleshooting

### Commands fail with "permission denied" even though elevation is configured

1. Check the host's elevation method:
   ```bash
   /hosts get web-01
   ```
2. Verify the credential is stored:
   ```bash
   /secret list
   ```
3. If using `sudo_password` but the credential is wrong, clear it and re-enter:
   ```bash
   /secret clear sudo:web-01:password
   ```
   Then re-run — the system will prompt again.

### "No elevation configured" in logs but elevation_method is set

The system looks up hosts by their **inventory name** first, then by hostname/IP. If you're using the IP address in your command but the host is stored under a name, the lookup falls back automatically. If this still fails, check that the name matches exactly:

```bash
/hosts list
```

### Double-prefixing (`sudo sudo ...`)

This cannot happen — the system always strips any existing `sudo`/`doas`/`su` prefix from the LLM's command before applying the configured wrapper.

### `su` method: "incorrect password" despite correct password

Make sure you stored the credential under `root:<hostname>:password`, not `sudo:<hostname>:password`:

```bash
/secret set root:legacy-server:password
```

---

## Related

- [Secrets & Security](./secrets-security.md) — how credentials are stored and protected
- [SSH Management](./ssh-management.md) — SSH connection setup and host management
- [Configuration Reference](../reference/configuration.md)
