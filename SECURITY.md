# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.5.x   | :white_check_mark: |
| < 0.5   | :x:                |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, please report them via email to: **security@merlya.fr**

You should receive a response within 48 hours. If for some reason you do not, please follow up via email to ensure we received your original message.

Please include the following information in your report:

- Type of issue (e.g., buffer overflow, SQL injection, cross-site scripting, etc.)
- Full paths of source file(s) related to the manifestation of the issue
- The location of the affected source code (tag/branch/commit or direct URL)
- Any special configuration required to reproduce the issue
- Step-by-step instructions to reproduce the issue
- Proof-of-concept or exploit code (if possible)
- Impact of the issue, including how an attacker might exploit it

## Security Measures

Merlya implements several security measures:

### Credential Storage

- API keys and secrets are stored in the system keyring (macOS Keychain, Windows Credential Manager, Linux Secret Service)
- No credentials are stored in configuration files
- In-memory fallback with warning if keyring is unavailable

### SSH Security

- SSH connections use asyncssh with secure defaults
- Support for MFA/2FA authentication
- Jump host (bastion) support for secure access
- Connection pooling with automatic cleanup

### Input Validation

- All user inputs are validated using Pydantic models
- Host names are validated before any SSH operations
- Commands are sanitized to prevent injection attacks

### Code Security

- Regular security scanning with Bandit
- Dependency auditing with pip-audit
- No execution of untrusted code
- Strict type checking with mypy

## Security Best Practices for Users

1. **Keep Merlya updated** - Always use the latest version
2. **Secure your API keys** - Never share or commit API keys
3. **Use SSH keys** - Prefer SSH keys over passwords
4. **Review commands** - Always review commands before execution on production systems
5. **Limit permissions** - Use least privilege principle for SSH access

## Disclosure Policy

When we receive a security bug report, we will:

1. Confirm the problem and determine affected versions
2. Audit code to find similar problems
3. Prepare fixes for all supported versions
4. Release new versions and publish security advisory

## Comments on this Policy

If you have suggestions on how this process could be improved, please submit a pull request.
