import socket
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Dict, Tuple

from merlya.agents.sentinel_service.models import CheckResult, HealthCheck


class CheckExecutor:
    """Executes health checks."""

    def __init__(self, executor=None):
        self.executor = executor

    def run_check(self, check: HealthCheck) -> CheckResult:
        """Run a single health check."""
        start_time = time.time()
        success = False
        error = None
        details: Dict[str, Any] = {}

        try:
            if check.check_type == "ping":
                success, details = self._check_ping(check)
            elif check.check_type == "port":
                success, details = self._check_port(check)
            elif check.check_type == "http":
                success, details = self._check_http(check)
            elif check.check_type == "command":
                success, details = self._check_command(check)
            elif check.check_type == "disk":
                success, details = self._check_disk(check)
            elif check.check_type == "memory":
                success, details = self._check_memory(check)
            elif check.check_type == "process":
                success, details = self._check_process(check)
            else:
                error = f"Unknown check type: {check.check_type}"
        except Exception as e:
            error = str(e)

        response_time = (time.time() - start_time) * 1000  # ms

        return CheckResult(
            check=check,
            success=success,
            response_time_ms=response_time,
            timestamp=datetime.now().isoformat(),
            error=error,
            details=details,
        )

    def _check_ping(self, check: HealthCheck) -> Tuple[bool, Dict[str, Any]]:
        """Check host reachability via ping."""
        target = check.target
        count = check.parameters.get("count", 1)

        try:
            result = subprocess.run(
                ["ping", "-c", str(count), "-W", str(check.timeout_seconds), target],
                capture_output=True,
                timeout=check.timeout_seconds + 2,
            )
            return result.returncode == 0, {"exit_code": result.returncode}
        except subprocess.TimeoutExpired:
            return False, {"error": "timeout"}
        except Exception as e:
            return False, {"error": str(e)}

    def _check_port(self, check: HealthCheck) -> Tuple[bool, Dict[str, Any]]:
        """Check if a port is open."""
        target = check.target
        port = check.parameters.get("port", 22)

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(check.timeout_seconds)
            result = sock.connect_ex((target, port))
            sock.close()
            return result == 0, {"port": port, "result": result}
        except Exception as e:
            return False, {"error": str(e)}

    def _check_http(self, check: HealthCheck) -> Tuple[bool, Dict[str, Any]]:
        """Check HTTP endpoint."""
        url = check.parameters.get("url", f"http://{check.target}/")
        expected_status = check.parameters.get("expected_status", 200)

        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=check.timeout_seconds) as response:
                status = response.status
                return status == expected_status, {"status": status, "expected": expected_status}
        except urllib.error.HTTPError as e:
            return e.code == expected_status, {"status": e.code, "expected": expected_status}
        except Exception as e:
            return False, {"error": str(e)}

    def _check_command(self, check: HealthCheck) -> Tuple[bool, Dict[str, Any]]:
        """Run a custom command and check exit code."""
        if not self.executor:
            return False, {"error": "No executor configured"}

        command = check.parameters.get("command", "true")
        expected_exit = check.parameters.get("expected_exit", 0)

        result = self.executor.execute(check.target, command, confirm=False)
        success = result.get("exit_code", 1) == expected_exit

        return success, {"exit_code": result.get("exit_code"), "expected": expected_exit}

    def _check_disk(self, check: HealthCheck) -> Tuple[bool, Dict[str, Any]]:
        """Check disk usage threshold."""
        if not self.executor:
            return False, {"error": "No executor configured"}

        threshold = check.parameters.get("threshold_percent", 90)
        path = check.parameters.get("path", "/")

        result = self.executor.execute(
            check.target,
            f"df -h {path} | tail -1 | awk '{{print $5}}' | tr -d '%'",
            confirm=False,
        )

        if result.get("success"):
            try:
                usage = int(result.get("stdout", "100").strip())
                return usage < threshold, {"usage_percent": usage, "threshold": threshold}
            except ValueError:
                return False, {"error": "Could not parse disk usage"}

        return False, {"error": result.get("stderr", "Unknown error")}

    def _check_memory(self, check: HealthCheck) -> Tuple[bool, Dict[str, Any]]:
        """Check memory usage threshold."""
        if not self.executor:
            return False, {"error": "No executor configured"}

        threshold = check.parameters.get("threshold_percent", 90)

        result = self.executor.execute(
            check.target,
            "free | grep Mem | awk '{print int($3/$2 * 100)}'",
            confirm=False,
        )

        if result.get("success"):
            try:
                usage = int(result.get("stdout", "100").strip())
                return usage < threshold, {"usage_percent": usage, "threshold": threshold}
            except ValueError:
                return False, {"error": "Could not parse memory usage"}

        return False, {"error": result.get("stderr", "Unknown error")}

    def _check_process(self, check: HealthCheck) -> Tuple[bool, Dict[str, Any]]:
        """Check if a process is running."""
        if not self.executor:
            return False, {"error": "No executor configured"}

        process_name = check.parameters.get("process", "")
        if not process_name:
            return False, {"error": "No process name specified"}

        result = self.executor.execute(
            check.target,
            f"pgrep -x {process_name}",
            confirm=False,
        )

        return result.get("success", False), {"process": process_name}
