"""
Merlya Centers - Diagnostic Center.

Read-only investigation center for gathering information
and analyzing system state without making changes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.centers.base import (
    AbstractCenter,
    CenterDeps,
    CenterMode,
    CenterResult,
    Evidence,
    RiskLevel,
)

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


# Tools allowed in DIAGNOSTIC mode (read-only)
DIAGNOSTIC_TOOLS = [
    # SSH Read
    "ssh_execute",  # With read-only validation
    # System
    "get_system_info",
    "check_disk_usage",
    "check_memory",
    "check_cpu",
    "list_processes",
    "check_service_status",
    # Files (read-only)
    "read_file",
    "list_directory",
    "search_files",
    # Logs
    "analyze_logs",
    "tail_log",
    # Kubernetes (read-only)
    "kubectl_get",
    "kubectl_describe",
    "kubectl_logs",
    "kubectl_events",
    # Security (audit)
    "check_open_ports",
    "audit_ssh_keys",
    "check_security_config",
    # Navigation
    "list_hosts",
    "get_host",
]

# Commands that are explicitly blocked in diagnostic mode
BLOCKED_COMMANDS = [
    "rm ",
    "rm -",
    "rmdir",
    "mv ",
    "cp ",
    "> ",
    ">> ",
    "chmod",
    "chown",
    "systemctl start",
    "systemctl stop",
    "systemctl restart",
    "service start",
    "service stop",
    "service restart",
    "kill ",
    "pkill",
    "killall",
    "reboot",
    "shutdown",
    "halt",
    "init ",
    "dd ",
    "mkfs",
    "fdisk",
    "parted",
    "apt install",
    "apt remove",
    "yum install",
    "yum remove",
    "dnf install",
    "dnf remove",
    "pip install",
    "npm install",
]


class DiagnosticCenter(AbstractCenter):
    """
    Read-only investigation center.

    Executes diagnostic commands and collects evidence without
    modifying system state. All operations are audited.
    """

    def __init__(self, ctx: SharedContext):
        """Initialize diagnostic center."""
        super().__init__(ctx)
        self._evidence: list[Evidence] = []

    @property
    def mode(self) -> CenterMode:
        """Get center mode."""
        return CenterMode.DIAGNOSTIC

    @property
    def allowed_tools(self) -> list[str]:
        """Get list of allowed tools."""
        return DIAGNOSTIC_TOOLS.copy()

    @property
    def risk_level(self) -> RiskLevel:
        """Diagnostic operations are low risk."""
        return RiskLevel.LOW

    async def execute(self, deps: CenterDeps) -> CenterResult:
        """
        Execute diagnostic operation.

        Args:
            deps: Dependencies with target and task.

        Returns:
            Result with collected evidence.
        """
        start_time = datetime.now(UTC)
        self._evidence = []

        logger.info(f"🔍 DiagnosticCenter: Starting investigation on {deps.target}")

        try:
            # Validate target exists
            host = await self.validate_target(deps.target)
            if host is None:
                return self._create_result(
                    success=False,
                    message=f"Host '{deps.target}' not found",
                )

            # Execute the diagnostic task
            result_data = await self._run_diagnostic(host, deps.task)

            duration = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

            return CenterResult(
                success=True,
                message=f"Diagnostic completed for {deps.target}",
                mode=self.mode,
                evidence=self._evidence,
                data=result_data,
                started_at=start_time,
                completed_at=datetime.now(UTC),
                duration_ms=duration,
            )

        except Exception as e:
            logger.error(f"❌ DiagnosticCenter error: {e}")
            return self._create_result(
                success=False,
                message=f"Diagnostic failed: {e}",
                evidence=self._evidence,
            )

    async def _run_diagnostic(self, host: Any, task: str) -> dict[str, Any]:
        """
        Run the diagnostic task using the specialist agent.

        Args:
            host: Resolved host object.
            task: User's diagnostic request.

        Returns:
            Collected diagnostic data including agent output.
        """
        from merlya.agent.confirmation import ConfirmationState
        from merlya.agent.specialists import run_diagnostic_agent
        from merlya.agent.specialists.deps import SpecialistDeps
        from merlya.agent.tracker import ToolCallTracker

        # Determine target name
        target_name = host.name if hasattr(host, "name") else str(host)

        # Create specialist deps with fresh tracker and confirmation state
        deps = SpecialistDeps(
            context=self._ctx,
            tracker=ToolCallTracker(),
            confirmation_state=ConfirmationState(),
            target=target_name,
        )

        logger.debug(f"🔍 Running diagnostic agent for target: {target_name}")

        # Run the specialist agent - this will actually execute commands
        try:
            output = await run_diagnostic_agent(deps=deps, task=task)

            return {
                "task": task,
                "host": target_name,
                "status": "completed",
                "output": output,
            }
        except Exception as e:
            logger.error(f"❌ Diagnostic agent failed: {e}")
            return {
                "task": task,
                "host": target_name,
                "status": "failed",
                "error": str(e),
            }

    async def execute_command(
        self,
        host_name: str,
        command: str,
        timeout: int = 60,
    ) -> Evidence:
        """
        Execute a diagnostic command and collect evidence.

        Args:
            host_name: Target host.
            command: Command to execute.
            timeout: Command timeout in seconds.

        Returns:
            Evidence from command execution.

        Raises:
            ValueError: If command is blocked.
        """
        # Validate command is read-only
        if not self._is_safe_command(command):
            raise ValueError(f"Command blocked in diagnostic mode: {command[:50]}...")

        start_time = datetime.now(UTC)

        try:
            pool = await self._ctx.get_ssh_pool()
            result = await pool.execute(host_name, command, timeout=timeout)

            duration = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

            evidence = Evidence(
                host=host_name,
                command=command,
                output=result.stdout,
                exit_code=result.exit_code,
                duration_ms=duration,
            )

            self._evidence.append(evidence)
            await self._audit_command(evidence)

            logger.debug(f"⚡ Executed diagnostic: {command[:50]}... -> {result.exit_code}")
            return evidence

        except Exception as e:
            duration = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
            evidence = Evidence(
                host=host_name,
                command=command,
                output=str(e),
                exit_code=-1,
                duration_ms=duration,
            )
            self._evidence.append(evidence)
            raise

    def _is_safe_command(self, command: str) -> bool:
        """
        Check if command is safe for diagnostic mode.

        Args:
            command: Command to validate.

        Returns:
            True if command is allowed.
        """
        command_lower = command.lower().strip()

        # Check against blocklist
        for blocked in BLOCKED_COMMANDS:
            if blocked.lower() in command_lower:
                logger.warning(f"⚠️ Blocked diagnostic command: {command[:50]}...")
                return False

        return True

    async def _audit_command(self, evidence: Evidence) -> None:
        """
        Store command execution in audit log.

        Args:
            evidence: Evidence to audit.
        """
        try:
            # Store in audit_logs table if available
            # This would use the persistence layer
            logger.debug(
                f"📋 Audit: {evidence.host} | {evidence.command[:30]}... | "
                f"exit={evidence.exit_code} | {evidence.duration_ms}ms"
            )
        except Exception as e:
            logger.warning(f"⚠️ Failed to audit command: {e}")

    async def check_disk_usage(self, host_name: str) -> Evidence:
        """Check disk usage on host."""
        return await self.execute_command(host_name, "df -h")

    async def check_memory(self, host_name: str) -> Evidence:
        """Check memory usage on host."""
        return await self.execute_command(host_name, "free -h")

    async def check_processes(self, host_name: str, filter_str: str = "") -> Evidence:
        """List processes on host."""
        cmd = f"ps aux | grep -i '{filter_str}'" if filter_str else "ps aux | head -20"
        return await self.execute_command(host_name, cmd)

    async def check_service(self, host_name: str, service: str) -> Evidence:
        """Check service status on host."""
        return await self.execute_command(
            host_name,
            f"systemctl status {service} 2>/dev/null || service {service} status",
        )

    async def tail_logs(
        self,
        host_name: str,
        log_path: str = "/var/log/syslog",
        lines: int = 50,
    ) -> Evidence:
        """Tail log file on host."""
        return await self.execute_command(
            host_name,
            f"tail -n {lines} {log_path} 2>/dev/null || tail -n {lines} /var/log/messages",
        )

    async def check_connectivity(self, host_name: str) -> Evidence:
        """Check basic connectivity to host."""
        return await self.execute_command(host_name, "echo 'ok' && uptime")
