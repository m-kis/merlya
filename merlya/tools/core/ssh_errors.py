"""
Merlya Tools - SSH error explanation.

Human-readable explanations for SSH errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True)
class SSHErrorInfo:
    """Structured SSH error information."""

    symptom: str
    explanation: str
    suggestion: str


@dataclass(frozen=True)
class _ErrorContext:
    """Context for error info builders."""

    target: str
    host: str


# Error detection functions
def _is_timeout(s: str) -> bool:
    return any(p in s for p in ("errno 60", "errno 110", "timed out"))


def _is_refused(s: str) -> bool:
    return "connection refused" in s or "errno 111" in s


def _is_unreachable(s: str) -> bool:
    return "no route to host" in s or "network is unreachable" in s


def _is_dns_failure(s: str) -> bool:
    return "name or service not known" in s or "nodename nor servname provided" in s


def _is_auth_failure(s: str) -> bool:
    return "authentication failed" in s or "permission denied" in s


def _is_host_key_failure(s: str) -> bool:
    return "host key verification failed" in s


# Error info builders
def _timeout_info(ctx: _ErrorContext) -> SSHErrorInfo:
    return SSHErrorInfo(
        symptom=f"Connection timeout to {ctx.target}",
        explanation=f"Could not establish TCP connection to {ctx.target}:22",
        suggestion=f"Check: VPN? {ctx.target} reachable? Try: ping {ctx.target}",
    )


def _refused_info(ctx: _ErrorContext) -> SSHErrorInfo:
    return SSHErrorInfo(
        symptom=f"Connection refused by {ctx.target}",
        explanation="SSH service not running or port blocked",
        suggestion=f"Check: systemctl status sshd on {ctx.target}",
    )


def _unreachable_info(ctx: _ErrorContext) -> SSHErrorInfo:
    return SSHErrorInfo(
        symptom=f"No route to host {ctx.target}",
        explanation="Network path does not exist (routing issue)",
        suggestion="Check: VPN? Network config? Firewall?",
    )


def _dns_info(ctx: _ErrorContext) -> SSHErrorInfo:
    return SSHErrorInfo(
        symptom=f"DNS resolution failed for {ctx.host}",
        explanation="Could not resolve hostname to IP",
        suggestion="Check: Hostname spelling? DNS config? /etc/hosts?",
    )


def _auth_info(ctx: _ErrorContext) -> SSHErrorInfo:
    return SSHErrorInfo(
        symptom=f"Authentication failed for {ctx.host}",
        explanation="SSH key or password rejected",
        suggestion="Check: ssh-add -l, authorized_keys, username",
    )


def _host_key_info(ctx: _ErrorContext) -> SSHErrorInfo:
    return SSHErrorInfo(
        symptom=f"Host key verification failed for {ctx.host}",
        explanation="Server key doesn't match known_hosts",
        suggestion=f"If expected: ssh-keygen -R {ctx.host}",
    )


# Registry: (detector, builder) pairs in priority order
_ERROR_HANDLERS: list[tuple[Callable[[str], bool], Callable[[_ErrorContext], SSHErrorInfo]]] = [
    (_is_timeout, _timeout_info),
    (_is_refused, _refused_info),
    (_is_unreachable, _unreachable_info),
    (_is_dns_failure, _dns_info),
    (_is_auth_failure, _auth_info),
    (_is_host_key_failure, _host_key_info),
]


def explain_ssh_error(error: Exception, host: str, via: str | None = None) -> SSHErrorInfo:
    """
    Parse SSH error and return human-readable explanation.

    Args:
        error: The exception that occurred.
        host: Target host name.
        via: Optional jump host used.

    Returns:
        SSHErrorInfo with symptom, explanation, and suggestion.
    """
    error_str = str(error).lower()
    ctx = _ErrorContext(target=via or host, host=host)

    for detector, builder in _ERROR_HANDLERS:
        if detector(error_str):
            return builder(ctx)

    # Generic fallback
    return SSHErrorInfo(
        symptom=str(error),
        explanation="SSH connection or execution error",
        suggestion="Check SSH connectivity: ssh <user>@<host>",
    )
