"""
Sentinel Agent - Proactive Monitoring System.

Runs as a background daemon to:
- Periodically scan critical hosts
- Detect anomalies before they become incidents
- Automatically create incidents in the knowledge graph
- Optionally trigger auto-remediation

This shifts Athena from reactive to proactive mode.
"""

import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from athena_ai.agents.sentinel_service.alerts import AlertManager
from athena_ai.agents.sentinel_service.checks import CheckExecutor
from athena_ai.agents.sentinel_service.models import (
    Alert,
    AlertSeverity,
    CheckResult,
    HealthCheck,
    SentinelStatus,
)
from athena_ai.utils.logger import logger

__all__ = [
    "SentinelAgent",
    "Alert",
    "AlertSeverity",
    "CheckResult",
    "HealthCheck",
    "SentinelStatus",
    "get_sentinel_agent",
]


class SentinelAgent:
    """
    Proactive monitoring agent that runs in background.

    Features:
    - Configurable health checks (ping, port, HTTP, custom)
    - Anomaly detection based on thresholds
    - Automatic incident creation
    - Integration with RemediationAgent for auto-healing
    - Alert callbacks for notifications

    Usage:
        sentinel = SentinelAgent()

        # Add checks
        sentinel.add_check(HealthCheck(
            name="web-prod-health",
            target="web-prod-1",
            check_type="http",
            parameters={"url": "http://web-prod-1/health", "expected_status": 200}
        ))

        # Start monitoring
        sentinel.start()

        # Later...
        sentinel.stop()
    """

    def __init__(
        self,
        executor=None,
        auto_remediate: bool = False,
        remediation_mode: str = "conservative",
        alert_callback: Optional[Callable[[Alert], None]] = None,
    ):
        """
        Initialize SentinelAgent.

        Args:
            executor: Command executor for running checks
            auto_remediate: Enable automatic remediation
            remediation_mode: Mode for RemediationAgent if auto_remediate=True
            alert_callback: Callback for alert notifications
        """
        self.status = SentinelStatus.STOPPED

        # Components
        self.check_executor = CheckExecutor(executor)
        self.alert_manager = AlertManager(auto_remediate, alert_callback)

        # Health checks configuration
        self._checks: Dict[str, HealthCheck] = {}
        self._check_results: Dict[str, List[CheckResult]] = {}

        # Background thread
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # Stats
        self._stats = {
            "checks_run": 0,
            "checks_passed": 0,
            "checks_failed": 0,
            "started_at": None,
        }

    # =========================================================================
    # Check Management
    # =========================================================================

    def add_check(self, check: HealthCheck) -> bool:
        """Add a health check."""
        with self._lock:
            if check.name in self._checks:
                logger.warning(f"Check '{check.name}' already exists, updating")

            self._checks[check.name] = check
            self._check_results[check.name] = []

            logger.info(f"Added check: {check.name} ({check.check_type}) -> {check.target}")
            return True

    def remove_check(self, name: str) -> bool:
        """Remove a health check."""
        with self._lock:
            if name not in self._checks:
                return False

            del self._checks[name]
            self._check_results.pop(name, None)

            logger.info(f"Removed check: {name}")
            return True

    def enable_check(self, name: str) -> bool:
        """Enable a health check."""
        with self._lock:
            if name in self._checks:
                self._checks[name].enabled = True
                return True
            return False

    def disable_check(self, name: str) -> bool:
        """Disable a health check."""
        with self._lock:
            if name in self._checks:
                self._checks[name].enabled = False
                return True
            return False

    def list_checks(self) -> List[HealthCheck]:
        """List all health checks."""
        with self._lock:
            return list(self._checks.values())

    # =========================================================================
    # Lifecycle Management
    # =========================================================================

    def start(self) -> bool:
        """Start the sentinel monitoring."""
        if self.status == SentinelStatus.RUNNING:
            logger.warning("Sentinel is already running")
            return False

        if not self._checks:
            logger.warning("No health checks configured")
            return False

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._monitoring_loop,
            name="SentinelAgent",
            daemon=True,
        )
        self._thread.start()

        self.status = SentinelStatus.RUNNING
        self._stats["started_at"] = datetime.now().isoformat()

        logger.info(f"Sentinel started with {len(self._checks)} checks")
        return True

    def stop(self) -> bool:
        """Stop the sentinel monitoring."""
        if self.status != SentinelStatus.RUNNING:
            return False

        self._stop_event.set()

        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

        self.status = SentinelStatus.STOPPED
        logger.info("Sentinel stopped")
        return True

    def pause(self) -> bool:
        """Pause monitoring without stopping the thread."""
        if self.status == SentinelStatus.RUNNING:
            self.status = SentinelStatus.PAUSED
            logger.info("Sentinel paused")
            return True
        return False

    def resume(self) -> bool:
        """Resume monitoring after pause."""
        if self.status == SentinelStatus.PAUSED:
            self.status = SentinelStatus.RUNNING
            logger.info("Sentinel resumed")
            return True
        return False

    # =========================================================================
    # Monitoring Loop
    # =========================================================================

    def _monitoring_loop(self):
        """Main monitoring loop running in background thread."""
        check_schedules: Dict[str, float] = {}

        while not self._stop_event.is_set():
            if self.status == SentinelStatus.PAUSED:
                time.sleep(1)
                continue

            current_time = time.time()

            with self._lock:
                checks_to_run = []
                for name, check in self._checks.items():
                    if not check.enabled:
                        continue

                    last_run = check_schedules.get(name, 0)
                    if current_time - last_run >= check.interval_seconds:
                        checks_to_run.append(check)
                        check_schedules[name] = current_time

            # Run checks outside lock
            for check in checks_to_run:
                try:
                    result = self.check_executor.run_check(check)
                    self._process_result(result)
                except Exception as e:
                    logger.error(f"Error running check {check.name}: {e}")
                    self.status = SentinelStatus.ERROR

            # Sleep briefly to avoid busy loop
            time.sleep(1)

    def _process_result(self, result: CheckResult):
        """Process a check result and handle alerts."""
        check_name = result.check.name

        with self._lock:
            # Store result history (keep last 100)
            self._check_results[check_name].append(result)
            if len(self._check_results[check_name]) > 100:
                self._check_results[check_name] = self._check_results[check_name][-100:]

            self._stats["checks_run"] += 1
            if result.success:
                self._stats["checks_passed"] += 1
            else:
                self._stats["checks_failed"] += 1

        # Delegate alert processing to AlertManager
        self.alert_manager.process_result(result)

    # =========================================================================
    # Status & Reporting
    # =========================================================================

    def get_status(self) -> Dict[str, Any]:
        """Get sentinel status and statistics."""
        with self._lock:
            stats = self._stats.copy()
            stats.update(self.alert_manager.stats)

            return {
                "status": self.status.value,
                "checks_configured": len(self._checks),
                "checks_enabled": sum(1 for c in self._checks.values() if c.enabled),
                "active_alerts": len(self.alert_manager.get_alerts()),
                "stats": stats,
                "alerts": [
                    {
                        "id": a.id,
                        "target": a.target,
                        "severity": a.severity.value,
                        "message": a.message,
                        "failures": a.consecutive_failures,
                    }
                    for a in self.alert_manager.get_alerts()
                ],
            }

    def get_check_history(self, check_name: str, limit: int = 10) -> List[Dict]:
        """Get recent results for a check."""
        with self._lock:
            results = self._check_results.get(check_name, [])[-limit:]
            return [
                {
                    "success": r.success,
                    "response_time_ms": r.response_time_ms,
                    "timestamp": r.timestamp,
                    "error": r.error,
                }
                for r in results
            ]

    def get_alerts(self, include_acknowledged: bool = False) -> List[Alert]:
        """Get active alerts."""
        return self.alert_manager.get_alerts(include_acknowledged)

    def acknowledge_alert(self, check_name: str) -> bool:
        """Acknowledge an alert."""
        return self.alert_manager.acknowledge_alert(check_name)


# Singleton instance
_sentinel_instance: Optional[SentinelAgent] = None


def get_sentinel_agent(
    executor=None,
    auto_remediate: bool = False,
) -> SentinelAgent:
    """Get or create the sentinel agent instance."""
    global _sentinel_instance

    if _sentinel_instance is None:
        _sentinel_instance = SentinelAgent(
            executor=executor,
            auto_remediate=auto_remediate,
        )

    return _sentinel_instance
