"""
Merlya Pipelines - Bash Fallback Pipeline.

Pipeline for executing bash commands when no structured IaC tool is available.
Provides maximum safety checks and explicit HITL approval.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.pipelines.base import (
    AbstractPipeline,
    ApplyResult,
    DiffResult,
    PipelineDeps,
    PlanResult,
    PostCheckResult,
    RollbackResult,
)

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


class BashPipeline(AbstractPipeline):
    """
    Fallback pipeline for direct bash command execution.

    Used when:
    - No structured IaC tool is available
    - One-off commands that don't fit IaC patterns
    - Emergency debugging with explicit approval

    Safety measures:
    - Explicit HITL approval required
    - Command sanitization
    - Audit logging
    - Optional rollback command
    """

    def __init__(
        self,
        ctx: SharedContext,
        deps: PipelineDeps,
        commands: list[str],
        rollback_commands: list[str] | None = None,
        check_commands: list[str] | None = None,
    ):
        """
        Initialize Bash pipeline.

        Args:
            ctx: Shared context.
            deps: Pipeline dependencies.
            commands: Commands to execute.
            rollback_commands: Commands to run on rollback (optional).
            check_commands: Commands to verify success (optional).
        """
        super().__init__(ctx, deps)
        self._commands = commands
        self._rollback_commands = rollback_commands or []
        self._check_commands = check_commands or []
        self._executed_commands: list[dict[str, Any]] = []
        self._original_state: dict[str, Any] = {}

    @property
    def name(self) -> str:
        """Get pipeline name."""
        return "bash"

    async def plan(self) -> PlanResult:
        """
        Plan stage: Validate commands for safety.

        Returns:
            PlanResult with validation status.
        """
        warnings: list[str] = []
        errors: list[str] = []

        for i, cmd in enumerate(self._commands, 1):
            # Check for dangerous patterns
            danger_check = self._check_dangerous_patterns(cmd)
            if danger_check["blocked"]:
                errors.append(f"Command {i}: {danger_check['reason']}")
            elif danger_check["warning"]:
                warnings.append(f"Command {i}: {danger_check['warning']}")

        if errors:
            return PlanResult(
                success=False,
                plan_output="Commands contain blocked patterns",
                errors=errors,
                warnings=warnings,
            )

        plan_output = self._format_command_list(self._commands)

        return PlanResult(
            success=True,
            plan_output=plan_output,
            resources_affected=[self._deps.target],
            warnings=warnings,
        )

    async def diff(self) -> DiffResult:
        """
        Diff stage: Show what commands will be executed.

        For bash, there's no real dry-run, so we just display
        the commands that will be executed.

        Returns:
            DiffResult with command preview.
        """
        diff_lines = ["Commands to be executed:", ""]
        for i, cmd in enumerate(self._commands, 1):
            diff_lines.append(f"  {i}. {cmd}")

        if self._check_commands:
            diff_lines.extend(["", "Post-check commands:"])
            for i, cmd in enumerate(self._check_commands, 1):
                diff_lines.append(f"  {i}. {cmd}")

        if self._rollback_commands:
            diff_lines.extend(["", "Rollback commands (if needed):"])
            for i, cmd in enumerate(self._rollback_commands, 1):
                diff_lines.append(f"  {i}. {cmd}")

        risk = self._assess_command_risk()

        return DiffResult(
            success=True,
            diff_output="\n".join(diff_lines),
            modifications=len(self._commands),
            risk_assessment=risk,
        )

    async def apply(self) -> ApplyResult:
        """
        Apply stage: Execute commands via SSH.

        Returns:
            ApplyResult with execution details.
        """
        start_time = datetime.now(UTC)
        output_lines: list[str] = []
        resources_modified: list[str] = []

        try:
            pool = await self._ctx.get_ssh_pool()

            for i, cmd in enumerate(self._commands, 1):
                logger.info(f"⚡ Executing command {i}/{len(self._commands)}: {cmd[:50]}...")

                result = await pool.execute(
                    self._deps.target,
                    cmd,
                    timeout=300,  # 5 min timeout per command
                )

                self._executed_commands.append(
                    {
                        "command": cmd,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "exit_code": result.exit_code,
                    }
                )

                output_lines.append(f"--- Command {i}: {cmd} ---")
                output_lines.append(f"Exit code: {result.exit_code}")
                if result.stdout:
                    output_lines.append(f"Output:\n{result.stdout}")
                if result.stderr:
                    output_lines.append(f"Stderr:\n{result.stderr}")
                output_lines.append("")

                if result.exit_code != 0:
                    duration = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
                    return ApplyResult(
                        success=False,
                        output="\n".join(output_lines),
                        resources_modified=resources_modified,
                        duration_ms=duration,
                        rollback_data={"executed": self._executed_commands},
                    )

                resources_modified.append(f"command:{i}")

            duration = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

            return ApplyResult(
                success=True,
                output="\n".join(output_lines),
                resources_modified=resources_modified,
                duration_ms=duration,
                rollback_data={"executed": self._executed_commands},
            )

        except Exception as e:
            duration = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
            return ApplyResult(
                success=False,
                output=f"Exception during execution: {e}",
                resources_modified=resources_modified,
                duration_ms=duration,
                rollback_data={"executed": self._executed_commands},
            )

    async def rollback(self) -> RollbackResult:
        """
        Rollback stage: Execute rollback commands if defined.

        Returns:
            RollbackResult with rollback status.
        """
        if not self._rollback_commands:
            return RollbackResult(
                success=False,
                output="No rollback commands defined",
                errors=["Rollback not available: no commands specified"],
            )

        output_lines: list[str] = []
        resources_restored: list[str] = []
        errors: list[str] = []

        try:
            pool = await self._ctx.get_ssh_pool()

            for i, cmd in enumerate(self._rollback_commands, 1):
                logger.info(
                    f"↩️ Executing rollback {i}/{len(self._rollback_commands)}: {cmd[:50]}..."
                )

                result = await pool.execute(
                    self._deps.target,
                    cmd,
                    timeout=300,
                )

                output_lines.append(f"--- Rollback {i}: {cmd} ---")
                output_lines.append(f"Exit code: {result.exit_code}")
                if result.stdout:
                    output_lines.append(result.stdout)

                if result.exit_code != 0:
                    errors.append(f"Rollback command {i} failed: {result.stderr}")
                else:
                    resources_restored.append(f"rollback:{i}")

            return RollbackResult(
                success=len(errors) == 0,
                output="\n".join(output_lines),
                resources_restored=resources_restored,
                partial=len(errors) > 0 and len(resources_restored) > 0,
                errors=errors,
            )

        except Exception as e:
            return RollbackResult(
                success=False,
                output="\n".join(output_lines),
                resources_restored=resources_restored,
                partial=len(resources_restored) > 0,
                errors=[f"Rollback exception: {e}"],
            )

    async def post_check(self) -> PostCheckResult:
        """
        Post-check stage: Verify commands succeeded.

        Returns:
            PostCheckResult with verification status.
        """
        if not self._check_commands:
            # No explicit checks defined - consider successful
            return PostCheckResult(
                success=True,
                checks_passed=["no_checks_defined"],
                warnings=["No post-check commands defined"],
            )

        checks_passed: list[str] = []
        checks_failed: list[str] = []
        warnings: list[str] = []

        try:
            pool = await self._ctx.get_ssh_pool()

            for i, cmd in enumerate(self._check_commands, 1):
                logger.debug(f"🔍 Running check {i}: {cmd[:50]}...")

                result = await pool.execute(
                    self._deps.target,
                    cmd,
                    timeout=60,
                )

                if result.exit_code == 0:
                    checks_passed.append(f"check_{i}")
                else:
                    checks_failed.append(f"check_{i}: {result.stderr or 'non-zero exit'}")

            return PostCheckResult(
                success=len(checks_failed) == 0,
                checks_passed=checks_passed,
                checks_failed=checks_failed,
                warnings=warnings,
            )

        except Exception as e:
            return PostCheckResult(
                success=False,
                checks_passed=checks_passed,
                checks_failed=[f"check_exception: {e}"],
                warnings=warnings,
            )

    def _check_dangerous_patterns(self, command: str) -> dict[str, Any]:
        """
        Check command for dangerous patterns.

        Args:
            command: Command to check.

        Returns:
            Dict with 'blocked', 'reason', and 'warning' keys.
        """
        cmd_lower = command.lower().strip()

        # Blocked patterns - never allow
        blocked_patterns = [
            ("rm -rf /", "Recursive delete of root filesystem"),
            ("dd if=", "Low-level disk write"),
            ("mkfs", "Filesystem format"),
            (":(){:|:&};:", "Fork bomb"),
            ("> /dev/sd", "Direct disk write"),
            ("chmod 777 /", "Dangerous permission change on root"),
        ]

        for pattern, reason in blocked_patterns:
            if pattern in cmd_lower:
                return {"blocked": True, "reason": reason, "warning": None}

        # Warning patterns - allow but warn
        warning_patterns = [
            ("rm -r", "Recursive delete"),
            ("systemctl stop", "Stopping service"),
            ("systemctl restart", "Restarting service"),
            ("kill -9", "Forceful process termination"),
            ("reboot", "System reboot"),
            ("shutdown", "System shutdown"),
            ("> /etc/", "Writing to /etc/"),
            ("curl | bash", "Piping remote script to bash"),
            ("wget | sh", "Piping remote script to shell"),
        ]

        for pattern, warning in warning_patterns:
            if pattern in cmd_lower:
                return {"blocked": False, "reason": None, "warning": warning}

        return {"blocked": False, "reason": None, "warning": None}

    def _assess_command_risk(self) -> str:
        """
        Assess overall risk level of commands.

        Returns:
            Risk level: low, medium, high, critical.
        """
        high_risk_patterns = ["rm", "kill", "systemctl", "service", "shutdown", "reboot"]
        medium_risk_patterns = [">", ">>", "mv", "cp", "chmod", "chown"]

        high_count = 0
        medium_count = 0

        for cmd in self._commands:
            cmd_lower = cmd.lower()
            for pattern in high_risk_patterns:
                if pattern in cmd_lower:
                    high_count += 1
                    break
            for pattern in medium_risk_patterns:
                if pattern in cmd_lower:
                    medium_count += 1
                    break

        if high_count > 0:
            return "high"
        if medium_count > 2:
            return "high"
        if medium_count > 0:
            return "medium"
        return "low"

    def _format_command_list(self, commands: list[str]) -> str:
        """Format commands for display."""
        lines = [f"  {i}. {cmd}" for i, cmd in enumerate(commands, 1)]
        return "Commands to execute:\n" + "\n".join(lines)
