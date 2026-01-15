"""
Merlya Audit - Operation logging and audit trail.

Provides audit logging for security-sensitive operations:
- Command executions
- Skill invocations
- Tool usage
- Configuration changes
"""

from merlya.audit.formatters import (
    is_sensitive_key,
    is_sensitive_value,
    sanitize_args,
    sanitize_value,
)
from merlya.audit.log_methods import (
    log_command,
    log_destructive,
    log_skill,
    log_tool,
)
from merlya.audit.logger import (
    LOGFIRE_AVAILABLE,
    AuditLogger,
    get_audit_logger,
)
from merlya.audit.models import AuditEvent, AuditEventType, ObservabilityStatus
from merlya.audit.storage import (
    MAX_RECENT_LIMIT,
    ensure_table,
    export_json,
    get_recent,
    store_event,
)

__all__ = [
    "LOGFIRE_AVAILABLE",
    # Storage
    "MAX_RECENT_LIMIT",
    # Logger
    "AuditEvent",
    "AuditEventType",
    "AuditLogger",
    "ObservabilityStatus",
    "ensure_table",
    "export_json",
    "get_audit_logger",
    "get_recent",
    # Formatters
    "is_sensitive_key",
    "is_sensitive_value",
    # Log methods
    "log_command",
    "log_destructive",
    "log_skill",
    "log_tool",
    "sanitize_args",
    "sanitize_value",
    "store_event",
]
