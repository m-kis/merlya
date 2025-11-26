import time
from typing import Callable, Dict, List, Optional

from athena_ai.agents.sentinel_service.models import Alert, AlertSeverity, CheckResult
from athena_ai.knowledge import get_knowledge_manager
from athena_ai.utils.logger import logger


class AlertManager:
    """Manages alerts, incidents, and remediation."""

    def __init__(
        self,
        auto_remediate: bool = False,
        alert_callback: Optional[Callable[[Alert], None]] = None,
    ):
        self.auto_remediate = auto_remediate
        self.alert_callback = alert_callback or self._default_alert_handler
        self.knowledge = get_knowledge_manager()

        self._alerts: Dict[str, Alert] = {}
        self._failure_counts: Dict[str, int] = {}

        self.stats = {
            "alerts_created": 0,
            "incidents_created": 0,
            "remediations_triggered": 0,
        }

    def _default_alert_handler(self, alert: Alert):
        """Default alert handler - logs the alert."""
        logger.warning(
            f"SENTINEL ALERT [{alert.severity.value.upper()}]: "
            f"{alert.target} - {alert.message}"
        )

    def process_result(self, result: CheckResult):
        """Process a check result and handle alerts."""
        check_name = result.check.name

        if result.success:
            # Reset failure count on success
            if self._failure_counts.get(check_name, 0) > 0:
                logger.info(f"Check {check_name} recovered after {self._failure_counts[check_name]} failures")
            self._failure_counts[check_name] = 0

            # Clear active alert if any
            if check_name in self._alerts:
                del self._alerts[check_name]
        else:
            # Increment failure count
            self._failure_counts[check_name] = self._failure_counts.get(check_name, 0) + 1
            failures = self._failure_counts[check_name]

            # Check if threshold reached
            if failures >= result.check.threshold_failures:
                self._create_alert(result)

    def _create_alert(self, result: CheckResult):
        """Create an alert for a failed check."""
        check = result.check
        failures = self._failure_counts[check.name]

        # Determine severity
        if failures >= check.threshold_failures * 3:
            severity = AlertSeverity.CRITICAL
        elif failures >= check.threshold_failures * 2:
            severity = AlertSeverity.WARNING
        else:
            severity = AlertSeverity.INFO

        # Create alert
        alert_id = f"alert_{check.name}_{int(time.time())}"
        alert = Alert(
            id=alert_id,
            check_name=check.name,
            target=check.target,
            severity=severity,
            message=result.error or f"Check failed {failures} times",
            timestamp=result.timestamp,
            consecutive_failures=failures,
        )

        # Store alert
        self._alerts[check.name] = alert
        self.stats["alerts_created"] += 1

        # Notify via callback
        self.alert_callback(alert)

        # Create incident if critical
        if severity == AlertSeverity.CRITICAL:
            self._create_incident(alert, result)

        # Trigger remediation if enabled
        if self.auto_remediate and severity in [AlertSeverity.WARNING, AlertSeverity.CRITICAL]:
            self._trigger_remediation(alert, result)

    def _create_incident(self, alert: Alert, result: CheckResult):
        """Create an incident in the knowledge graph."""
        try:
            symptoms = [
                f"{result.check.check_type} check failed",
                result.error or "Unknown error",
            ]

            if result.details:
                for key, value in result.details.items():
                    symptoms.append(f"{key}: {value}")

            # Map severity to priority
            priority_map = {
                AlertSeverity.CRITICAL: "P1",
                AlertSeverity.WARNING: "P2",
                AlertSeverity.INFO: "P3",
            }

            incident_id = self.knowledge.record_incident(
                title=f"[Sentinel] {alert.check_name}: {alert.message}",
                priority=priority_map.get(alert.severity, "P2"),
                description=f"Automatically detected by Sentinel Agent after {alert.consecutive_failures} consecutive failures",
                service=result.check.parameters.get("service", result.check.target),
                host=result.check.target,
                symptoms=symptoms,
                tags=["sentinel", "auto-detected", result.check.check_type],
            )

            alert.incident_id = incident_id
            self.stats["incidents_created"] += 1

            logger.info(f"Created incident {incident_id} for alert {alert.id}")

        except Exception as e:
            logger.error(f"Failed to create incident: {e}")

    def _trigger_remediation(self, alert: Alert, result: CheckResult):
        """Trigger automatic remediation."""
        try:
            # Get remediation suggestion
            remediation = self.knowledge.get_remediation_for_incident(
                symptoms=[result.error or "check failed"],
                service=result.check.target,
                title=alert.message,
            )

            if not remediation:
                logger.info(f"No remediation found for {alert.check_name}")
                return

            # Only auto-remediate if safe
            if not remediation.get("auto_executable", False):
                logger.info(f"Remediation for {alert.check_name} requires manual approval")
                return

            logger.info(f"Triggering auto-remediation for {alert.check_name}")
            self.stats["remediations_triggered"] += 1

            # Note: Actual execution would require context_manager
            # This is a placeholder for the integration point

        except Exception as e:
            logger.error(f"Remediation failed: {e}")

    def get_alerts(self, include_acknowledged: bool = False) -> List[Alert]:
        """Get active alerts."""
        alerts = list(self._alerts.values())
        if not include_acknowledged:
            alerts = [a for a in alerts if not a.acknowledged]
        return alerts

    def acknowledge_alert(self, check_name: str) -> bool:
        """Acknowledge an alert."""
        if check_name in self._alerts:
            self._alerts[check_name].acknowledged = True
            return True
        return False
