"""
Security audit tools.
"""
from typing import Annotated

from athena_ai.tools.base import get_tool_context, validate_host
from athena_ai.utils.logger import logger


def audit_host(
    target: Annotated[str, "Target host to audit"]
) -> str:
    """
    Perform a security audit on a target host.

    Checks: open ports, SSH config, sudo privileges.

    Args:
        target: Host to audit

    Returns:
        Security report
    """
    ctx = get_tool_context()
    logger.info(f"Tool: audit_host {target}")

    is_valid, message = validate_host(target)
    if not is_valid:
        return f"❌ BLOCKED: Cannot audit '{target}'\n\n{message}\n\n💡 Use list_hosts()"

    report = [f"🔒 SECURITY AUDIT: {target}", ""]

    # Open Ports
    res = ctx.executor.execute(target, "ss -tuln | grep LISTEN")
    if res['success']:
        report.append("📡 Open Ports:")
        for line in res['stdout'].strip().split('\n')[:10]:
            parts = line.split()
            if len(parts) >= 5:
                report.append(f"   - {parts[4]}")
    else:
        report.append("📡 Open Ports: ⚠️ Failed")

    report.append("")

    # SSH Config
    res = ctx.executor.execute(target, "grep -E '^(PermitRootLogin|PasswordAuthentication)' /etc/ssh/sshd_config")
    report.append("🔑 SSH Configuration:")
    if res['success']:
        for line in res['stdout'].strip().split('\n'):
            if "PermitRootLogin yes" in line:
                report.append(f"   ❌ {line} (High Risk!)")
            elif "PasswordAuthentication yes" in line:
                report.append(f"   ⚠️ {line} (Consider key-based)")
            else:
                report.append(f"   ✅ {line}")
    else:
        report.append("   ❓ Could not read sshd_config")

    report.append("")

    # Sudoers
    res = ctx.executor.execute(target, "grep -v '^#' /etc/sudoers | grep -v '^$'")
    report.append("🛡️ Privileged Access:")
    if res['success']:
        lines = res['stdout'].strip().split('\n')
        report.append(f"   Found {len(lines)} active sudoers rules")
    else:
        report.append("   ℹ️ Cannot read /etc/sudoers")

    return "\n".join(report)


def analyze_security_logs(
    target: Annotated[str, "Target host to analyze"],
    lines: Annotated[int, "Number of log lines to check"] = 50
) -> str:
    """
    Analyze security logs for suspicious activity.

    Args:
        target: Host to analyze
        lines: Number of lines to check

    Returns:
        Analysis summary
    """
    ctx = get_tool_context()
    logger.info(f"Tool: analyze_security_logs {target}")

    is_valid, message = validate_host(target)
    if not is_valid:
        return f"❌ BLOCKED: Cannot analyze '{target}'\n\n{message}\n\n💡 Use list_hosts()"

    # Detect log file
    check = ctx.executor.execute(target, "ls /var/log/auth.log 2>/dev/null || ls /var/log/secure 2>/dev/null")
    if not check['success'] or not check['stdout'].strip():
        return f"❌ Could not find auth.log or secure log on {target}"

    log_file = check['stdout'].strip()
    res = ctx.executor.execute(target, f"tail -n {lines} {log_file}")

    if not res['success']:
        return f"❌ Failed to read logs: {res.get('stderr')}"

    log_content = res['stdout']
    analysis = [f"📋 LOG ANALYSIS: {target} ({log_file})", ""]

    failed = log_content.count("Failed password")
    sudo = log_content.count("sudo:")
    accepted = log_content.count("Accepted publickey") + log_content.count("Accepted password")

    analysis.append(f"📊 Summary (last {lines} lines):")
    analysis.append(f"   - Failed Logins: {failed} " + ("⚠️ HIGH" if failed > 5 else "✅"))
    analysis.append(f"   - Sudo Usage: {sudo}")
    analysis.append(f"   - Successful Logins: {accepted}")

    if failed > 0:
        analysis.append("")
        analysis.append("⚠️ Suspicious Activity:")
        for line in log_content.split('\n'):
            if "Failed password" in line:
                analysis.append(f"   - {line[:80]}...")

    return "\n".join(analysis)
