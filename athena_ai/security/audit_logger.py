"""
Security Audit Logger for Athena.

Provides comprehensive audit logging for:
- Command execution
- Security decisions
- Access attempts
- Configuration changes
- Incident responses

Designed for compliance and forensics.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from athena_ai.utils.logger import logger


class AuditEventType(str, Enum):
    """Types of audit events."""
    # Command execution
    COMMAND_EXECUTED = "command_executed"
    COMMAND_BLOCKED = "command_blocked"
    COMMAND_FAILED = "command_failed"

    # Access events
    ACCESS_GRANTED = "access_granted"
    ACCESS_DENIED = "access_denied"
    SESSION_START = "session_start"
    SESSION_END = "session_end"

    # Security events
    SECURITY_WARNING = "security_warning"
    SECURITY_ALERT = "security_alert"
    PREFLIGHT_BLOCK = "preflight_block"
    CVE_DETECTED = "cve_detected"

    # Configuration
    CONFIG_CHANGED = "config_changed"
    SECRET_ACCESSED = "secret_accessed"

    # Incident response
    INCIDENT_CREATED = "incident_created"
    INCIDENT_RESOLVED = "incident_resolved"
    ESCALATION = "escalation"


@dataclass
class AuditEvent:
    """An audit log event."""
    event_type: AuditEventType
    timestamp: str = ""
    session_id: str = ""
    user: str = ""
    target: str = ""  # Host, service, or resource
    action: str = ""  # Command or operation
    result: str = ""  # success, failure, blocked
    details: Dict[str, Any] = field(default_factory=dict)
    environment: str = ""
    priority: str = ""  # P0, P1, P2, P3
    risk_level: str = ""  # low, moderate, high, critical
    ip_address: str = ""
    checksum: str = ""  # Integrity check

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()
        if not self.checksum:
            self.checksum = self._compute_checksum()

    def _compute_checksum(self) -> str:
        """Compute integrity checksum for the event."""
        data = f"{self.event_type}:{self.timestamp}:{self.session_id}:{self.action}:{self.target}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        d = asdict(self)
        d["event_type"] = self.event_type.value
        return d

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())


class AuditLogger:
    """
    Security audit logger with multiple output targets.

    Features:
    - File-based audit trail
    - Real-time alerting for critical events
    - Event integrity verification
    - Query and export capabilities
    """

    def __init__(
        self,
        log_dir: Optional[str] = None,
        environment: str = "dev",
        alert_callback: Optional[Callable] = None,
    ):
        # Setup log directory
        if log_dir is None:
            log_dir = str(Path.home() / ".athena" / "audit")
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.environment = environment
        self.alert_callback = alert_callback

        # Current session tracking
        self._session_id: Optional[str] = None
        self._user: str = ""

        # In-memory buffer for recent events
        self._buffer: List[AuditEvent] = []
        self._buffer_size = 1000

    def set_session(self, session_id: str, user: str = ""):
        """Set the current session context."""
        self._session_id = session_id
        self._user = user

    def _get_log_file(self) -> Path:
        """Get the current log file path (daily rotation)."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        return self.log_dir / f"audit-{date_str}.jsonl"

    def log(self, event: AuditEvent) -> None:
        """
        Log an audit event.

        Args:
            event: AuditEvent to log
        """
        # Fill in session context if not set
        if not event.session_id and self._session_id:
            event.session_id = self._session_id
        if not event.user and self._user:
            event.user = self._user
        if not event.environment:
            event.environment = self.environment

        # Recompute checksum after filling context
        event.checksum = event._compute_checksum()

        # Write to file
        log_file = self._get_log_file()
        with open(log_file, "a") as f:
            f.write(event.to_json() + "\n")

        # Add to buffer
        self._buffer.append(event)
        if len(self._buffer) > self._buffer_size:
            self._buffer = self._buffer[-self._buffer_size:]

        # Trigger alerts for critical events
        if event.event_type in (
            AuditEventType.SECURITY_ALERT,
            AuditEventType.PREFLIGHT_BLOCK,
            AuditEventType.ACCESS_DENIED,
        ) or event.risk_level == "critical":
            self._trigger_alert(event)

        logger.debug(f"Audit: {event.event_type.value} - {event.action}")

    def _trigger_alert(self, event: AuditEvent) -> None:
        """Trigger alert for critical events."""
        if self.alert_callback:
            try:
                self.alert_callback(event)
            except Exception as e:
                logger.error(f"Alert callback failed: {e}")

        # Always log critical events
        logger.warning(
            f"SECURITY AUDIT: {event.event_type.value} | "
            f"Target: {event.target} | Action: {event.action} | "
            f"Result: {event.result}"
        )

    # =========================================================================
    # Convenience methods for common events
    # =========================================================================

    def log_command(
        self,
        command: str,
        target: str,
        result: str = "success",
        risk_level: str = "low",
        details: Dict = None,
    ) -> None:
        """Log a command execution."""
        event_type = AuditEventType.COMMAND_EXECUTED
        if result == "blocked":
            event_type = AuditEventType.COMMAND_BLOCKED
        elif result == "failure":
            event_type = AuditEventType.COMMAND_FAILED

        self.log(AuditEvent(
            event_type=event_type,
            target=target,
            action=command,
            result=result,
            risk_level=risk_level,
            details=details or {},
        ))

    def log_access(
        self,
        resource: str,
        granted: bool,
        reason: str = "",
    ) -> None:
        """Log an access attempt."""
        self.log(AuditEvent(
            event_type=AuditEventType.ACCESS_GRANTED if granted else AuditEventType.ACCESS_DENIED,
            target=resource,
            action="access_request",
            result="granted" if granted else "denied",
            details={"reason": reason},
        ))

    def log_security_warning(
        self,
        message: str,
        target: str = "",
        details: Dict = None,
    ) -> None:
        """Log a security warning."""
        self.log(AuditEvent(
            event_type=AuditEventType.SECURITY_WARNING,
            target=target,
            action=message,
            result="warning",
            risk_level="moderate",
            details=details or {},
        ))

    def log_security_alert(
        self,
        message: str,
        target: str = "",
        details: Dict = None,
    ) -> None:
        """Log a security alert (critical)."""
        self.log(AuditEvent(
            event_type=AuditEventType.SECURITY_ALERT,
            target=target,
            action=message,
            result="alert",
            risk_level="critical",
            details=details or {},
        ))

    def log_preflight_block(
        self,
        command: str,
        reason: str,
        target: str = "",
    ) -> None:
        """Log a preflight check block."""
        self.log(AuditEvent(
            event_type=AuditEventType.PREFLIGHT_BLOCK,
            target=target,
            action=command,
            result="blocked",
            risk_level="critical",
            details={"block_reason": reason},
        ))

    def log_cve_detection(
        self,
        cve_id: str,
        package: str,
        severity: str,
        details: Dict = None,
    ) -> None:
        """Log a CVE detection."""
        self.log(AuditEvent(
            event_type=AuditEventType.CVE_DETECTED,
            target=package,
            action=f"CVE detected: {cve_id}",
            result="detected",
            risk_level="high" if severity in ("CRITICAL", "HIGH") else "moderate",
            details={"cve_id": cve_id, "severity": severity, **(details or {})},
        ))

    def log_incident(
        self,
        incident_id: str,
        title: str,
        priority: str,
        resolved: bool = False,
        details: Dict = None,
    ) -> None:
        """Log incident creation or resolution."""
        self.log(AuditEvent(
            event_type=AuditEventType.INCIDENT_RESOLVED if resolved else AuditEventType.INCIDENT_CREATED,
            target=incident_id,
            action=title,
            result="resolved" if resolved else "created",
            priority=priority,
            risk_level="high" if priority in ("P0", "P1") else "moderate",
            details=details or {},
        ))

    def log_session_start(self, metadata: Dict = None) -> None:
        """Log session start."""
        self.log(AuditEvent(
            event_type=AuditEventType.SESSION_START,
            action="Session started",
            result="success",
            details=metadata or {},
        ))

    def log_session_end(self, stats: Dict = None) -> None:
        """Log session end."""
        self.log(AuditEvent(
            event_type=AuditEventType.SESSION_END,
            action="Session ended",
            result="success",
            details=stats or {},
        ))

    # =========================================================================
    # Query and export
    # =========================================================================

    def get_recent_events(
        self,
        event_type: Optional[AuditEventType] = None,
        limit: int = 100,
    ) -> List[AuditEvent]:
        """Get recent events from buffer."""
        events = self._buffer[-limit:]

        if event_type:
            events = [e for e in events if e.event_type == event_type]

        return events

    def query_logs(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        event_type: Optional[str] = None,
        target: Optional[str] = None,
    ) -> List[Dict]:
        """
        Query audit logs from files.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            event_type: Filter by event type
            target: Filter by target

        Returns:
            List of matching events as dicts
        """
        results = []

        # Find relevant log files
        log_files = sorted(self.log_dir.glob("audit-*.jsonl"))

        for log_file in log_files:
            # Filter by date if specified
            file_date = log_file.stem.replace("audit-", "")
            if start_date and file_date < start_date:
                continue
            if end_date and file_date > end_date:
                continue

            # Read and filter events
            try:
                with open(log_file, "r") as f:
                    for line in f:
                        event = json.loads(line)

                        if event_type and event.get("event_type") != event_type:
                            continue
                        if target and target not in event.get("target", ""):
                            continue

                        results.append(event)
            except Exception as e:
                logger.error(f"Failed to read audit log {log_file}: {e}")

        return results

    def export_logs(
        self,
        output_file: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        format: str = "jsonl",  # jsonl or json
    ) -> int:
        """
        Export audit logs to a file.

        Returns:
            Number of events exported
        """
        events = self.query_logs(start_date=start_date, end_date=end_date)

        output_path = Path(output_file)

        if format == "json":
            with open(output_path, "w") as f:
                json.dump(events, f, indent=2)
        else:
            with open(output_path, "w") as f:
                for event in events:
                    f.write(json.dumps(event) + "\n")

        logger.info(f"Exported {len(events)} audit events to {output_file}")
        return len(events)

    def verify_integrity(self, event_dict: Dict) -> bool:
        """Verify the integrity of an audit event."""
        # Recreate checksum
        data = (
            f"{event_dict.get('event_type')}:{event_dict.get('timestamp')}:"
            f"{event_dict.get('session_id')}:{event_dict.get('action')}:{event_dict.get('target')}"
        )
        expected_checksum = hashlib.sha256(data.encode()).hexdigest()[:16]

        return event_dict.get("checksum") == expected_checksum

    def get_stats(self) -> Dict[str, Any]:
        """Get audit logging statistics."""
        # Count log files
        log_files = list(self.log_dir.glob("audit-*.jsonl"))

        # Count events in buffer by type
        event_counts = {}
        for event in self._buffer:
            event_type = event.event_type.value
            event_counts[event_type] = event_counts.get(event_type, 0) + 1

        return {
            "log_dir": str(self.log_dir),
            "log_files": len(log_files),
            "buffer_size": len(self._buffer),
            "recent_events_by_type": event_counts,
        }


# Singleton instance
_default_logger: Optional[AuditLogger] = None


def get_audit_logger(
    log_dir: Optional[str] = None,
    environment: str = "dev",
) -> AuditLogger:
    """Get the default AuditLogger instance."""
    global _default_logger

    if _default_logger is None:
        _default_logger = AuditLogger(log_dir=log_dir, environment=environment)

    return _default_logger
