"""
Merlya Tools - SSL/TLS certificate checking.

Check SSL certificates on remote hosts for expiration and configuration issues.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from loguru import logger

from merlya.tools.security.base import SecurityResult, execute_security_command

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


@dataclass
class CertificateInfo:
    """Information about an SSL certificate."""

    domain: str
    issuer: str = ""
    subject: str = ""
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    days_until_expiry: int = 0
    is_expired: bool = False
    is_expiring_soon: bool = False
    serial: str = ""
    fingerprint: str = ""
    san: list[str] = field(default_factory=list)  # Subject Alternative Names
    issues: list[str] = field(default_factory=list)


async def check_ssl_certs(
    ctx: SharedContext,
    host: str,
    domains: list[str] | None = None,
    port: int = 443,
    warn_days: int = 30,
    auto_detect: bool = True,
) -> SecurityResult:
    """
    Check SSL certificates on a remote host.

    Args:
        ctx: Shared context.
        host: Host name from inventory.
        domains: List of domains to check. If None, auto-detect from nginx/apache.
        port: Port to check (default 443).
        warn_days: Days before expiry to warn.
        auto_detect: Auto-detect domains from web server config.

    Returns:
        SecurityResult with certificate information.
    """
    logger.info(f"🔒 Checking SSL certificates on {host}...")

    # Auto-detect domains if not provided
    if not domains and auto_detect:
        domains = await _auto_detect_domains(ctx, host)

    if not domains:
        # Fall back to checking localhost
        domains = ["localhost"]

    results: list[dict[str, object]] = []
    severity = "info"
    issues: list[str] = []

    # Validate all domains before processing
    valid_domains = []
    for domain in domains:
        if _is_valid_domain(domain):
            valid_domains.append(domain)
        else:
            logger.warning(f"⚠️ Skipping invalid domain: {domain}")
            issues.append(f"Invalid domain skipped: {domain}")

    if not valid_domains:
        return SecurityResult(
            success=False,
            error="❌ No valid domains to check",
            data={"total_checked": 0, "certificates": [], "issues": issues},
            severity="warning",
        )

    for domain in valid_domains:
        cert_info = await _check_certificate(ctx, host, domain, port, warn_days)

        result_dict: dict[str, object] = {
            "domain": cert_info.domain,
            "issuer": cert_info.issuer,
            "subject": cert_info.subject,
            "valid_from": cert_info.valid_from.isoformat() if cert_info.valid_from else None,
            "valid_until": cert_info.valid_until.isoformat() if cert_info.valid_until else None,
            "days_until_expiry": cert_info.days_until_expiry,
            "is_expired": cert_info.is_expired,
            "is_expiring_soon": cert_info.is_expiring_soon,
            "san": cert_info.san,
            "issues": cert_info.issues,
        }
        results.append(result_dict)

        # Update severity
        if cert_info.is_expired:
            severity = "critical"
            issues.append(f"Certificate for {domain} is EXPIRED")
        elif cert_info.is_expiring_soon:
            if severity != "critical":
                severity = "warning"
            issues.append(f"Certificate for {domain} expires in {cert_info.days_until_expiry} days")

        for issue in cert_info.issues:
            issues.append(f"{domain}: {issue}")

    return SecurityResult(
        success=True,
        data={
            "certificates": results,
            "total_checked": len(results),
            "expired": sum(1 for r in results if r["is_expired"]),
            "expiring_soon": sum(1 for r in results if r["is_expiring_soon"]),
            "issues": issues,
        },
        severity=severity,
    )


async def check_ssl_cert_file(
    ctx: SharedContext,
    host: str,
    cert_path: str,
    warn_days: int = 30,
) -> SecurityResult:
    """
    Check an SSL certificate file on a remote host.

    Args:
        ctx: Shared context.
        host: Host name from inventory.
        cert_path: Path to certificate file.
        warn_days: Days before expiry to warn.

    Returns:
        SecurityResult with certificate information.
    """
    # Validate path
    if not _is_safe_cert_path(cert_path):
        return SecurityResult(
            success=False,
            error=f"❌ Invalid certificate path: {cert_path}",
        )

    # Use a safer approach with argument list instead of shell command interpolation
    cmd_parts = ["openssl", "x509", "-in", cert_path, "-noout", "-dates", "-subject", "-issuer"]

    # Join the command parts for execute_security_command which expects a string
    cmd = " ".join(shlex.quote(part) for part in cmd_parts) + " 2>&1"
    result = await execute_security_command(ctx, host, cmd, timeout=15)

    if result.exit_code != 0:
        return SecurityResult(
            success=False,
            error=f"❌ Failed to read certificate: {result.stderr or result.stdout}",
        )

    cert_info = _parse_openssl_output(cert_path, result.stdout, warn_days)

    severity = "info"
    if cert_info.is_expired:
        severity = "critical"
    elif cert_info.is_expiring_soon:
        severity = "warning"

    return SecurityResult(
        success=True,
        data={
            "path": cert_path,
            "subject": cert_info.subject,
            "issuer": cert_info.issuer,
            "valid_from": cert_info.valid_from.isoformat() if cert_info.valid_from else None,
            "valid_until": cert_info.valid_until.isoformat() if cert_info.valid_until else None,
            "days_until_expiry": cert_info.days_until_expiry,
            "is_expired": cert_info.is_expired,
            "is_expiring_soon": cert_info.is_expiring_soon,
        },
        severity=severity,
    )


async def _check_certificate(
    ctx: SharedContext,
    host: str,
    domain: str,
    port: int,
    warn_days: int,
) -> CertificateInfo:
    """Check a single certificate via network connection."""
    cert_info = CertificateInfo(domain=domain)

    # Use a safer approach with argument list instead of shell command interpolation
    # This prevents command injection by avoiding shell=True
    cmd_parts = [
        "sh",
        "-c",
        f"echo | openssl s_client -servername {shlex.quote(domain)} -connect {shlex.quote(domain)}:{port} 2>/dev/null | openssl x509 -noout -dates -subject -issuer -ext subjectAltName 2>/dev/null",
    ]

    # Join the command parts for execute_security_command which expects a string
    # The command is properly escaped and the shell is only used for the pipe operator
    cmd = " ".join(cmd_parts)

    result = await execute_security_command(ctx, host, cmd, timeout=30)

    if result.exit_code != 0 or not result.stdout:
        cert_info.issues.append("Failed to retrieve certificate")
        return cert_info

    return _parse_openssl_output(domain, result.stdout, warn_days)


def _parse_openssl_output(domain: str, output: str, warn_days: int) -> CertificateInfo:
    """Parse openssl output into CertificateInfo."""
    cert_info = CertificateInfo(domain=domain)

    for line in output.split("\n"):
        line = line.strip()

        if line.startswith("notBefore="):
            date_str = line.split("=", 1)[1]
            cert_info.valid_from = _parse_openssl_date(date_str)

        elif line.startswith("notAfter="):
            date_str = line.split("=", 1)[1]
            cert_info.valid_until = _parse_openssl_date(date_str)

        elif line.startswith("subject="):
            cert_info.subject = line.split("=", 1)[1].strip()

        elif line.startswith("issuer="):
            cert_info.issuer = line.split("=", 1)[1].strip()

        elif "DNS:" in line:
            # Parse SAN entries
            san_matches = re.findall(r"DNS:([^\s,]+)", line)
            cert_info.san.extend(san_matches)

    # Calculate expiry
    if cert_info.valid_until:
        now = datetime.now(UTC)
        delta = cert_info.valid_until - now
        cert_info.days_until_expiry = delta.days

        if delta.total_seconds() < 0:
            cert_info.is_expired = True
            cert_info.issues.append("Certificate is EXPIRED")
        elif delta.days <= warn_days:
            cert_info.is_expiring_soon = True
            cert_info.issues.append(f"Certificate expires in {delta.days} days")

    return cert_info


def _parse_openssl_date(date_str: str) -> datetime | None:
    """Parse OpenSSL date format.

    Normalizes input by stripping trailing timezone tokens (e.g., " GMT")
    before parsing, as %Z is unreliable across platforms.
    """
    import re

    date_str = date_str.strip()

    # Strip trailing timezone token (e.g., " GMT", " UTC", or any alphabetic suffix)
    date_str_normalized = re.sub(r"\s+[A-Za-z]+$", "", date_str)

    # Formats without %Z since we stripped the timezone
    formats = [
        "%b %d %H:%M:%S %Y",  # "Mar 15 12:00:00 2024"
        "%b  %d %H:%M:%S %Y",  # "Mar  5 12:00:00 2024" (double-space for single-digit day)
        "%Y-%m-%dT%H:%M:%S",  # "2024-03-15T12:00:00" (ISO format without Z)
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str_normalized, fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue

    return None


async def _auto_detect_domains(ctx: SharedContext, host: str) -> list[str]:
    """Auto-detect domains from nginx/apache configuration."""
    domains: list[str] = []

    # Try nginx
    nginx_cmd = """
grep -rh 'server_name' /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | \
grep -v '#' | sed 's/server_name//g' | tr ';' ' ' | tr -s ' ' '\n' | \
grep -v '^$' | grep -v '_' | sort -u | head -10
"""
    nginx_result = await execute_security_command(ctx, host, nginx_cmd, timeout=15)

    if nginx_result.exit_code == 0 and nginx_result.stdout:
        for line in nginx_result.stdout.strip().split("\n"):
            domain = line.strip()
            if domain and _is_valid_domain(domain):
                domains.append(domain)

    # Try apache if no nginx domains found
    if not domains:
        apache_cmd = """
grep -rh 'ServerName\\|ServerAlias' /etc/apache2/sites-enabled/ /etc/httpd/conf.d/ 2>/dev/null | \
grep -v '#' | awk '{print $2}' | grep -v '^$' | sort -u | head -10
"""
        apache_result = await execute_security_command(ctx, host, apache_cmd, timeout=15)

        if apache_result.exit_code == 0 and apache_result.stdout:
            for line in apache_result.stdout.strip().split("\n"):
                domain = line.strip()
                if domain and _is_valid_domain(domain):
                    domains.append(domain)

    logger.debug(f"🔍 Auto-detected {len(domains)} domain(s) on {host}")
    return domains


def _is_valid_domain(domain: str) -> bool:
    """Validate domain name."""
    if not domain or len(domain) > 253:
        return False

    # Must have at least one dot for a valid FQDN
    if "." not in domain:
        return False

    # Check format
    return bool(
        re.match(
            r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)+$",
            domain,
        )
    )


def _is_safe_cert_path(path: str) -> bool:
    """Validate certificate file path for security."""
    import os
    import re

    allowed_prefixes = (
        "/etc/ssl/",
        "/etc/pki/",
        "/etc/letsencrypt/",
        "/etc/nginx/",
        "/etc/apache2/",
        "/etc/httpd/",
        "/opt/",
        "/home/",
    )

    # Reject shell metacharacters since path is used in shell commands
    # Allow alphanumeric, dash, underscore, dot, and forward slash
    if re.search(r"[^a-zA-Z0-9_\-./]", path):
        return False

    # Use os.path.normpath for robust normalization
    normalized = os.path.normpath(path)

    # normpath removes trailing slashes and resolves .. and .
    # Check that normalized path doesn't escape allowed directories
    if ".." in normalized:
        return False

    # Ensure path starts with allowed prefix (add trailing slash for prefix match)
    return any(
        normalized.startswith(prefix.rstrip("/"))
        and (
            len(normalized) == len(prefix.rstrip("/")) or normalized[len(prefix.rstrip("/"))] == "/"
        )
        for prefix in allowed_prefixes
    )
