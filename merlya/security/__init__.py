"""
Security Module for Merlya.

Provides:
- Risk assessment for commands
- Preflight safety checks
- Security audit logging
- Credential management
- Permission detection
"""

from .audit_logger import (
    AuditEvent,
    AuditEventType,
    AuditLogger,
    get_audit_logger,
)
from .credentials import CredentialManager
from .permissions import PermissionManager
from .preflight_checker import (
    CheckResult,
    PreflightChecker,
    PreflightResult,
    get_preflight_checker,
)
from .risk_assessor import RiskAssessor

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
