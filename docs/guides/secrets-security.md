# Secrets: The Red Line for Infrastructure AI Agents

> How Merlya guarantees your passwords never end up in logs, the LLM, or stored in plaintext.

## The Problem with Current AI Agents

As an infrastructure engineer, I've tested many AI agents: OpenHands, Gemini CLI, SHAI, and others. The same concerns kept coming back:

- **Decisions made "because the model thinks it's better"** — no justification or traceability
- **Commands executed implicitly** — no explicit confirmation for destructive operations
- **Secrets handled like regular variables** — displayed in logs, sent to APIs
- **Very few usable traces** — impossible to do a post-incident audit

These problems aren't anecdotal. In a production environment, they're deal-breakers.

## Merlya's "Secret-Zero-Trust" Architecture

Merlya was designed with a simple philosophy: **the LLM must never see secrets**.

### The Secrets Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        SECRETS FLOW                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. User enters password                                        │
│     └── prompt_secret() → System Keyring                        │
│                                                                 │
│  2. Merlya stores a REFERENCE                                   │
│     └── @db:password (not the value!)                           │
│                                                                 │
│  3. LLM generates a command                                     │
│     └── "mysql -p @db:password -e 'SELECT 1'"                   │
│                                                                 │
│  4. LATE resolution (execution-time)                            │
│     └── resolve_all_references() → mysql -p secretvalue         │
│                                                                 │
│  5. Return to LLM                                               │
│     └── "mysql -p *** -e 'SELECT 1'" (safe_command)             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

The secret is never:
- Displayed in logs
- Sent to the LLM
- Stored in plaintext on disk

### Layer 1: Secure Storage via Keyring

Secrets are stored in your **OS system keyring**:

| OS | Backend |
|----|---------|
| macOS | Keychain |
| Windows | Credential Manager |
| Linux | Secret Service (GNOME Keyring, KWallet) |

```python
# merlya/secrets/store.py
def set(self, name: str, value: str) -> None:
    if self._keyring_available:
        keyring.set_password(SERVICE_NAME, name, value)
    else:
        self._memory_store[name] = value  # Fallback with warning
```

If the keyring isn't available (Docker container without access), Merlya uses in-memory storage with an **explicit warning**: secrets will be lost on exit.

### Layer 2: References Instead of Values

When you enter a password, Merlya never returns it to the LLM. Instead, it generates a **reference**:

```python
# merlya/tools/interaction.py
safe_values = {}
for name, val in values.items():
    if name.lower() in {"password", "token", "secret", "key"}:
        secret_key = f"{key_prefix}:{name}"
        secret_store.set(secret_key, val)
        safe_values[name] = f"@{secret_key}"  # Reference, not value!
    else:
        safe_values[name] = val
```

The LLM sees `@db:password`, never `MySuperPassword123!`.

### Layer 3: Late Resolution

`@secret-name` references are resolved **only at execution time**, after the LLM has given its instruction:

```python
# merlya/tools/core/resolve.py
def resolve_secrets(command: str, secrets: SecretStore) -> tuple[str, str]:
    """
    SECURITY: This function should only be called at execution time,
    never before sending commands to the LLM.

    Returns:
        Tuple of (resolved_command, safe_command_for_logging).
    """
    for match in REFERENCE_PATTERN.finditer(command):
        secret_value = secrets.get(secret_name)
        resolved = resolved[:start] + secret_value + resolved[end:]
        safe = safe[:start] + "***" + safe[end:]
    return resolved, safe
```

The resolved command (`resolved`) is executed but **never logged or returned to the LLM**. Only the masked version (`safe`) is visible.

### Layer 4: Proactive Plaintext Password Detection

Merlya **blocks** commands containing plaintext passwords:

```python
# merlya/tools/core/security.py
UNSAFE_PASSWORD_PATTERNS = (
    re.compile(r"echo\s+['\"]?(?!@)[^'\"]+['\"]?\s*\|\s*sudo\s+-S"),  # echo 'pass' | sudo
    re.compile(r"-p['\"][^'\"@]+['\"]"),  # mysql -p'password'
    re.compile(r"--password[=\s]+['\"]?(?!@)[^@\s'\"]+"),  # --password=value
    re.compile(r"sshpass\s+-p\s+['\"]?(?!@)[^'\"@\s]+"),  # sshpass -p password
    # ... 8 patterns total
)

def detect_unsafe_password(command: str) -> str | None:
    for pattern in UNSAFE_PASSWORD_PATTERNS:
        if pattern.search(command):
            return "SECURITY: Command may contain a plaintext password."
    return None
```

If the LLM tries to generate `mysql -p'secretvalue'` instead of `mysql -p @db:password`, the command is **rejected** with a clear error message.

### Layer 5: Automatic Log Sanitization

Even if a secret passed through the other layers, the audit system would mask it:

```python
# merlya/audit/logger.py
_SENSITIVE_KEY_PATTERNS = (
    "password", "passwd", "pwd", "secret", "key", "token",
    "api_key", "bearer", "jwt", "oauth", "credential",
    "private_key", "ssh_key", "id_rsa", "certificate",
    # ... 30+ patterns
)

_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"^A[KBS]IA[A-Z0-9]{16}$"),  # AWS access key
    re.compile(r"^gh[pousr]_[A-Za-z0-9_]{36,}$"),  # GitHub token
    re.compile(r"^eyJ[A-Za-z0-9_-]*\.eyJ"),  # JWT
    # ... 9 patterns to detect secrets by their format
)
```

Sanitization is **recursive**: it traverses nested dicts and lists.

## Comparison with Other Agents

| Aspect | OpenHands | Gemini CLI | SHAI | Merlya |
|--------|-----------|------------|------|--------|
| Secrets in logs | Possible | Possible | Possible | Masked |
| Secrets sent to LLM | Yes | Yes | Yes | Never (references) |
| Secure storage | Env vars | Env vars | File | OS Keyring |
| Plaintext detection | No | No | No | 8 patterns |
| Audit trail | Basic | Basic | Minimal | SQLite + SIEM |

## Concrete Example

### What you type:
```
merlya> Connect to the MySQL database on db-prod and list tables
```

### What the LLM sees:
```
User: Connect to the MySQL database on db-prod and list tables
Assistant: I'll request MySQL credentials then list the tables.

Tool call: request_credentials(service="mysql", host="db-prod")
Tool result: {"username": "admin", "password": "@mysql:db-prod:password"}

Tool call: ssh_execute(host="db-prod", command="mysql -u admin -p @mysql:db-prod:password -e 'SHOW TABLES'")
Tool result: {
  "stdout": "Tables_in_mydb\nusers\norders\nproducts",
  "command": "mysql -u admin -p *** -e 'SHOW TABLES'"  // <- Masked!
}
```

### What's actually executed:
```bash
mysql -u admin -p 'MyRealPassword' -e 'SHOW TABLES'
```

### What's logged:
```
[AUDIT] COMMAND_EXECUTED: mysql -u admin -p *** -e 'SHOW TABLES' on db-prod
```

The password appears **nowhere** except in the actual command execution.

## Configuration

### Check keyring status

```bash
merlya> /secrets
```

Displays:
```
Secret Store Status
  Backend: keyring (macOS Keychain)
  Stored secrets: 3
    - mysql:db-prod:password
    - ssh:bastion:passphrase
    - api:monitoring:token
```

### Non-interactive mode (CI/CD)

In non-interactive mode (`merlya run --yes`), credentials **cannot be prompted**. Merlya will fail immediately with a clear error if credentials are needed but not pre-configured.

#### Pre-store credentials before running

```bash
# Store sudo password for target hosts
merlya secret set sudo:192.168.1.7:password

# Store database credentials
merlya secret set mysql:db-prod:password

# Then run in non-interactive mode
merlya run --yes "Check database status on db-prod"
```

#### Use NOPASSWD sudo

Configure sudo without password on target hosts:

```bash
# /etc/sudoers.d/merlya
cedric ALL=(ALL) NOPASSWD: /usr/bin/systemctl, /usr/bin/journalctl
```

#### Error handling

If credentials are missing in `--yes` mode, Merlya returns:

```text
❌ Cannot obtain credentials in non-interactive mode.

Missing: password for sudo@192.168.1.7

To fix this, before running in --yes mode:
1. Store credentials in keyring: merlya secret set sudo:192.168.1.7:password
2. Or configure NOPASSWD sudo on the target host
3. Or run in interactive mode (without --yes)
```

This **fail-fast behavior** prevents retry loops and wasted API calls.

## Audit and Compliance

Every secret access is traced:

```sql
SELECT * FROM audit_logs
WHERE event_type = 'secret_accessed'
ORDER BY created_at DESC;
```

```
| id | event_type | action | target | created_at |
|----|------------|--------|--------|------------|
| a1 | secret_accessed | get | mysql:db-prod:password | 2024-12-16 10:23:45 |
| a2 | secret_accessed | set | ssh:bastion:passphrase | 2024-12-16 10:22:30 |
```

SIEM export:
```bash
merlya> /audit export --format json --since 24h > audit.json
```

## Conclusion

Secrets are the first red line for any infrastructure AI agent. Merlya implements a **defense in depth** architecture with 5 layers of protection:

1. **Secure storage** via OS keyring
2. **References** instead of values for the LLM
3. **Late resolution** only at execution time
4. **Proactive detection** of plaintext passwords
5. **Automatic sanitization** in logs

This architecture ensures that even if one layer fails, the others protect your secrets.

---

*Merlya is an AI CLI agent for infrastructure management, designed with security as the absolute priority.*

**Useful links:**
- [Full documentation](../index.md)
- [SSH Guide](./ssh-management.md)
- [Configuration](../reference/configuration.md)
