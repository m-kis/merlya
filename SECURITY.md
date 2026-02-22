# Security Policy

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report vulnerabilities by email: **security@merlya.fr**

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Your suggested fix (optional)

We will acknowledge your report within 48 hours and aim to patch critical issues within 7 days.

## Security Model

### Secrets — never exposed to the LLM

Secrets (passwords, tokens, SSH passphrases) are stored in the **OS keyring** (macOS Keychain, Linux Secret Service, Windows Credential Manager) and referenced by `@secret-name` placeholders. The LLM sees only the reference, never the value. Resolution happens at execution time only.

```
User input  →  LLM sees: "mysql -u admin -p @db:password"
Executed as →  "mysql -u admin -p 'actualvalue'"
Logged as   →  "mysql -u admin -p ***"
```

### Target resolution — `@hostname` vs `@secret`

| Prefix | Meaning | Example |
|--------|---------|---------|
| `@name` | Inventory host lookup | `@web-01` → resolves hostname + username from DB |
| `@secret-name` | Keyring secret reference | `@db:password` → resolved at runtime |
| `user@ip` | Explicit SSH user + IP | `ubuntu@192.168.1.5` |
| `1.2.3.4` | Direct IP (no user) | `192.168.1.5` |

Plain hostnames without `@` are rejected to prevent LLM hallucinations.

### Human-in-the-loop (HITL)

Every state-changing operation (service restart, file write, package install) requires explicit user confirmation before execution. The Execution specialist enforces `require_confirmation=True` by default; it cannot be bypassed by the LLM.

### Privilege escalation

Elevation (sudo, doas, su) is **never auto-detected**. It must be explicitly configured per host. Elevation passwords are stored in the keyring under `elevation:hostname:password`.

### Loop detection

The `ToolCallTracker` detects repetitive patterns (same command 3+ times, A-B-A-B alternation) and halts execution. This prevents runaway agent loops on misconfigured or unreachable hosts.

### Blocked commands (Diagnostic specialist)

The read-only Diagnostic specialist maintains a blocklist of destructive commands (`rm`, `dd`, `mkfs`, `shutdown`, etc.) that cannot be executed even if the LLM requests them.

### Plaintext password detection

Before any SSH command is executed, Merlya scans for patterns like `echo 'pass' | sudo -S`, `mysql -p'value'`, `sshpass -p value` and rejects them with a clear error, forcing use of `@secret-name` references instead.

### Audit trail

Every tool call, command executed, and secret accessed is logged to a local SQLite database (`~/.merlya/merlya.db`). Logs can be exported in JSON format for SIEM integration:

```bash
merlya> /audit export --format json --since 24h > audit.json
```

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest (main) | Yes |
| < 0.8.0 | No |

## Dependencies

We run `pip-audit` and `bandit` on every push via CI. Check the [Security tab](https://github.com/m-kis/merlya/security/dependabot) for active Dependabot alerts.

---

*For full details on the secrets architecture, see [docs/guides/secrets-security.md](docs/guides/secrets-security.md).*
