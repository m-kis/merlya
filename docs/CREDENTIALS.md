# Secure Credential Management

Athena handles database credentials securely with multiple flexible options.

## How It Works

### 1. Credential Variables (Recommended - Most Secure & Convenient)

Define reusable credential variables that you can reference with `@variable` syntax:

```bash
# Define non-sensitive values (usernames, hostnames)
/credentials set mongo-user admin

# Define sensitive values SECURELY (passwords, API keys, tokens, SSH keys)
/credentials set-secret mongo-pass          # Prompts with hidden input
/credentials set-secret api-key             # Prompts with hidden input
/credentials set-secret ssh-private-key     # Prompts with hidden input

# Use them in queries
check mongo status on HOST using @mongo-user @mongo-pass
show replica set status for HOST with credentials @mongo-user @mongo-pass
query database on HOST -u @mongo-user -p @mongo-pass
```

**Management commands:**
```bash
/credentials list              # List all variables (passwords/secrets masked)
/credentials delete mongo-pass # Delete a specific variable
/credentials clear             # Clear all credentials and variables
```

**How it works:**
- Variables stored in session memory (not persisted to disk)
- Referenced with `@variable-name` syntax in queries
- System resolves `@variables` before executing
- Password-like variables masked in `/credentials list`
- Cleared automatically on REPL exit

**Benefits:**
- ✅ Define once, reuse everywhere
- ✅ Credentials not repeated in every query
- ✅ Easy to update (just `/credentials set` again)
- ✅ Clean query syntax

### 2. Pass Credentials Directly in Query
Simply include credentials directly in your natural language query:

```
# Examples of supported formats:
"check mongo status on HOST user admin password secret123"
"show replica set status for HOST username admin passwd mypass"
"query mongo on HOST with credentials admin/secret123"
"connect to HOST using admin:secret123"
"check database on HOST -u admin -p secret"
```

**How it works:**
- AI automatically detects and extracts credentials from your prompt
- Credentials are passed securely to the command executor
- Pattern matching supports multiple formats (see examples above)
- Credentials are cached in memory for the session (cleared on exit)

**Security:**
- While credentials appear in your prompt, the AI model already receives them anyway
- This is more convenient than typing them separately
- Session-scoped caching means you only type them once

### 2. Interactive Prompts (Fallback)
When MongoDB credentials are needed but not in the query, you'll be prompted securely:

```
[Credentials needed for mongodb on mongo-preprod-1]
mongodb username: admin
mongodb password: [hidden input with getpass]
```

- Password input uses `getpass` (no echo to terminal)
- Credentials cached in memory for the session
- Never written to disk or logs

### 2. Environment Variables (Recommended for Automation)
Set credentials before starting Athena:

```bash
export MONGODB_USER="admin"
export MONGODB_PASS="your_password"

# Then start REPL
python -m athena_ai.cli repl
```

### 3. Session Management
Credentials are cached per session:

```
# Clear cached credentials
/credentials clear

# Start fresh session
/session new
```

## Example: MongoDB Replica Set Status

When you ask: `"show replica set status for mongo-preprod-1"`

**Before (with placeholders - INSECURE):**
```bash
mongosh --host mongo-preprod-1 -u <user> -p <pass> --eval 'rs.status()'
```

**After (secure):**
```bash
# If credentials not in env vars, system prompts:
[Credentials needed for mongodb on mongo-preprod-1]
mongodb username: admin
mongodb password: ********

# Then executes:
mongosh --host mongo-preprod-1 -u admin -p [REDACTED] --eval 'rs.status()'
```

## Security Features

✅ **Secure Input**: Uses Python `getpass` module (no terminal echo)
✅ **In-Memory Only**: Credentials stored in session memory, cleared on exit
✅ **No Disk Storage**: Never persisted to files or logs
✅ **Redacted Logs**: Passwords replaced with [REDACTED] in command output
✅ **Session Scope**: Credentials cleared when REPL exits

## Best Practices

1. **For Interactive Use**: Let system prompt you (most secure)
2. **For Automation**: Use environment variables
3. **Clear When Done**: Use `/credentials clear` before sharing terminal
4. **Audit**: Check `/credentials` command to see what's cached

## Future Enhancements

- Encrypted credential storage (like macOS Keychain, Linux Secret Service)
- Per-host credential management
- Integration with vault systems (HashiCorp Vault, AWS Secrets Manager)
- MFA support for database connections
