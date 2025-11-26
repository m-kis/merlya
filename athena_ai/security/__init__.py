"""
Security Module for Athena.

Provides:
- Risk assessment for commands
- Preflight safety checks
- Security audit logging
- Credential management
- Permission detection
"""

from .risk_assessor import RiskAssessor
from .preflight_checker import (
    PreflightChecker,
    PreflightResult,
    CheckResult,
    get_preflight_checker,
)
from .audit_logger import (
    AuditLogger,
    AuditEvent,
    AuditEventType,
    get_audit_logger,
)
from .credentials import CredentialManager
from .permissions import PermissionManager

__all__ = [
    # Risk Assessment
    "RiskAssessor",
    # Preflight Checks
    "PreflightChecker",
    "PreflightResult",
    "CheckResult",
    "get_preflight_checker",
    # Audit Logging
    "AuditLogger",
    "AuditEvent",
    "AuditEventType",
    "get_audit_logger",
    # Credentials
    "CredentialManager",
    # Permissions
    "PermissionManager",
]
