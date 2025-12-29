"""
Merlya Pipelines - Ansible Pipeline.

Pipeline for executing Ansible playbooks and ad-hoc commands.
Supports three modes: ad-hoc, inline (generated playbook), and repository.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
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


class AnsibleMode(str, Enum):
    """Ansible execution modes."""

    AD_HOC = "ad_hoc"  # Single module command: ansible host -m service ...
    INLINE = "inline"  # Temporary playbook generated from task
    REPOSITORY = "repository"  # Playbook from existing IaC repository


class AnsiblePipeline(AbstractPipeline):
    """
    Pipeline for Ansible operations.

    Modes:
    - AD_HOC: Single ansible command using a module (e.g., service, package)
    - INLINE: Generates a temporary playbook for more complex tasks
    - REPOSITORY: Uses existing playbooks from a configured repository

    All modes support:
    - --check (dry-run) for diff stage
    - --diff for showing changes
    - Rollback via separate playbook or ad-hoc command
    """

    def __init__(
        self,
        ctx: SharedContext,
        deps: PipelineDeps,
        mode: AnsibleMode = AnsibleMode.AD_HOC,
        module: str | None = None,
        module_args: str | None = None,
        playbook_path: str | None = None,
        playbook_content: str | None = None,
        inventory: str | None = None,
        extra_vars: dict[str, Any] | None = None,
        rollback_playbook: str | None = None,
        check_tasks: list[str] | None = None,
    ):
        """
        Initialize Ansible pipeline.

        Args:
            ctx: Shared context.
            deps: Pipeline dependencies.
            mode: Execution mode (ad_hoc, inline, repository).
            module: Ansible module name for ad-hoc mode (e.g., "service", "package").
            module_args: Module arguments for ad-hoc mode.
            playbook_path: Path to playbook for repository mode.
            playbook_content: YAML content for inline mode.
            inventory: Inventory path or host pattern.
            extra_vars: Extra variables to pass to ansible.
            rollback_playbook: Playbook to run on rollback.
            check_tasks: Tasks to run for post-check verification.
        """
        super().__init__(ctx, deps)
        self._mode = mode
        self._module = module
        self._module_args = module_args
        self._playbook_path = playbook_path
        self._playbook_content = playbook_content
        self._inventory = inventory or deps.target
        self._extra_vars = extra_vars or {}
        self._rollback_playbook = rollback_playbook
        self._check_tasks = check_tasks or []

        # Temp file for inline playbook
        self._temp_playbook: Path | None = None

        # Execution state
        self._check_output: str = ""
        self._apply_output: str = ""

    @property
    def name(self) -> str:
        """Get pipeline name."""
        return f"ansible-{self._mode.value}"

    async def plan(self) -> PlanResult:
        """
        Plan stage: Validate Ansible configuration.

        Returns:
            PlanResult with validation status.
        """
        warnings: list[str] = []
        errors: list[str] = []

        # Validate mode-specific requirements
        if self._mode == AnsibleMode.AD_HOC:
            if not self._module:
                errors.append("AD_HOC mode requires 'module' parameter")
        elif self._mode == AnsibleMode.INLINE:
            if not self._playbook_content:
                errors.append("INLINE mode requires 'playbook_content' parameter")
        elif self._mode == AnsibleMode.REPOSITORY and not self._playbook_path:
            errors.append("REPOSITORY mode requires 'playbook_path' parameter")

        # Check if ansible is available
        ansible_check = await self._check_ansible_available()
        if not ansible_check["available"]:
            errors.append(f"Ansible not available: {ansible_check.get('error', 'unknown')}")

        if errors:
            return PlanResult(
                success=False,
                plan_output="Ansible validation failed",
                errors=errors,
                warnings=warnings,
            )

        # Build plan output
        plan_lines = [f"Mode: {self._mode.value}"]
        if self._mode == AnsibleMode.AD_HOC:
            plan_lines.append(f"Module: {self._module}")
            plan_lines.append(f"Args: {self._module_args or 'none'}")
        elif self._mode == AnsibleMode.INLINE:
            plan_lines.append("Playbook: (inline generated)")
        elif self._mode == AnsibleMode.REPOSITORY:
            plan_lines.append(f"Playbook: {self._playbook_path}")

        plan_lines.append(f"Target: {self._deps.target}")
        if self._extra_vars:
            plan_lines.append(f"Extra vars: {list(self._extra_vars.keys())}")

        return PlanResult(
            success=True,
            plan_output="\n".join(plan_lines),
            resources_affected=[self._deps.target],
            warnings=warnings,
            metadata={"mode": self._mode.value},
        )

    async def diff(self) -> DiffResult:
        """
        Diff stage: Run ansible --check --diff.

        Returns:
            DiffResult with preview of changes.
        """
        try:
            cmd = await self._build_ansible_command(check_mode=True)
            result = await self._run_local_command(cmd)

            self._check_output = result.get("stdout", "") + result.get("stderr", "")

            # Parse diff output for change counts
            additions = self._check_output.count("+ ")
            deletions = self._check_output.count("- ")
            changes = self._check_output.lower().count("changed=")

            # Assess risk
            risk = "low"
            if deletions > 0 or "remove" in self._check_output.lower():
                risk = "high"
            elif changes > 3:
                risk = "medium"

            return DiffResult(
                success=result.get("exit_code", 1) == 0,
                diff_output=self._check_output or "No changes detected",
                additions=additions,
                modifications=changes,
                deletions=deletions,
                risk_assessment=risk,
            )

        except Exception as e:
            logger.error(f"❌ Ansible diff failed: {e}")
            return DiffResult(
                success=False,
                diff_output=f"Diff failed: {e}",
                risk_assessment="unknown",
            )

    async def apply(self) -> ApplyResult:
        """
        Apply stage: Execute ansible playbook/command.

        Returns:
            ApplyResult with execution details.
        """
        start_time = datetime.now(UTC)

        try:
            cmd = await self._build_ansible_command(check_mode=False)
            result = await self._run_local_command(cmd)

            self._apply_output = result.get("stdout", "") + result.get("stderr", "")

            duration = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

            success = result.get("exit_code", 1) == 0

            # Parse resources modified
            resources = []
            if "ok=" in self._apply_output:
                resources.append("ansible_ok")
            if "changed=" in self._apply_output:
                resources.append("ansible_changed")

            return ApplyResult(
                success=success,
                output=self._apply_output,
                resources_modified=resources,
                duration_ms=duration,
                rollback_data={
                    "mode": self._mode.value,
                    "target": self._deps.target,
                    "rollback_playbook": self._rollback_playbook,
                },
            )

        except Exception as e:
            duration = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
            return ApplyResult(
                success=False,
                output=f"Apply failed: {e}",
                duration_ms=duration,
                rollback_data={},
            )
        finally:
            # Clean up temp playbook
            self._cleanup_temp_playbook()

    async def rollback(self) -> RollbackResult:
        """
        Rollback stage: Execute rollback playbook or reverse action.

        Returns:
            RollbackResult with rollback status.
        """
        if not self._rollback_playbook:
            return RollbackResult(
                success=False,
                output="No rollback playbook defined",
                errors=["Rollback not available: no playbook specified"],
            )

        try:
            cmd = f"ansible-playbook {self._rollback_playbook} -i {self._inventory}"
            if self._extra_vars:
                import json

                cmd += f" -e '{json.dumps(self._extra_vars)}'"

            result = await self._run_local_command(cmd)

            output = result.get("stdout", "") + result.get("stderr", "")
            success = result.get("exit_code", 1) == 0

            return RollbackResult(
                success=success,
                output=output,
                resources_restored=["ansible_rollback"] if success else [],
                errors=[] if success else [f"Rollback failed: exit {result.get('exit_code')}"],
            )

        except Exception as e:
            return RollbackResult(
                success=False,
                output=f"Rollback exception: {e}",
                errors=[str(e)],
            )

    async def post_check(self) -> PostCheckResult:
        """
        Post-check stage: Verify ansible changes succeeded.

        Returns:
            PostCheckResult with verification status.
        """
        if not self._check_tasks:
            # Check if apply output shows success
            if "failed=0" in self._apply_output.lower():
                return PostCheckResult(
                    success=True,
                    checks_passed=["ansible_no_failures"],
                )
            return PostCheckResult(
                success=True,
                checks_passed=["default_pass"],
                warnings=["No post-check tasks defined"],
            )

        checks_passed: list[str] = []
        checks_failed: list[str] = []

        for i, task in enumerate(self._check_tasks, 1):
            try:
                result = await self._run_local_command(task)
                if result.get("exit_code", 1) == 0:
                    checks_passed.append(f"check_{i}")
                else:
                    checks_failed.append(f"check_{i}: {result.get('stderr', 'failed')}")
            except Exception as e:
                checks_failed.append(f"check_{i}: {e}")

        return PostCheckResult(
            success=len(checks_failed) == 0,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
        )

    async def _check_ansible_available(self) -> dict[str, Any]:
        """Check if ansible is available locally."""
        try:
            result = await self._run_local_command("ansible --version")
            return {
                "available": result.get("exit_code", 1) == 0,
                "version": result.get("stdout", "").split("\n")[0],
            }
        except Exception as e:
            return {"available": False, "error": str(e)}

    async def _build_ansible_command(self, check_mode: bool = False) -> str:
        """
        Build the ansible command based on mode.

        Args:
            check_mode: If True, add --check --diff flags.

        Returns:
            Command string to execute.
        """
        import json

        if self._mode == AnsibleMode.AD_HOC:
            cmd = f"ansible {self._inventory} -m {self._module}"
            if self._module_args:
                cmd += f" -a '{self._module_args}'"
        else:
            # Playbook mode (inline or repository)
            playbook_path = self._playbook_path

            if self._mode == AnsibleMode.INLINE:
                # Create temp playbook
                self._temp_playbook = await self._create_temp_playbook()
                playbook_path = str(self._temp_playbook)

            cmd = f"ansible-playbook {playbook_path} -i {self._inventory}"

        # Add extra vars
        if self._extra_vars:
            cmd += f" -e '{json.dumps(self._extra_vars)}'"

        # Add check/diff flags
        if check_mode:
            cmd += " --check --diff"

        return cmd

    async def _create_temp_playbook(self) -> Path:
        """Create temporary playbook file for inline mode."""
        if not self._playbook_content:
            msg = "No playbook content provided for inline mode"
            raise ValueError(msg)

        _fd, path = tempfile.mkstemp(suffix=".yml", prefix="merlya_ansible_")
        temp_path = Path(path)

        with temp_path.open("w") as f:
            f.write(self._playbook_content)

        logger.debug(f"📝 Created temp playbook: {temp_path}")
        return temp_path

    def _cleanup_temp_playbook(self) -> None:
        """Clean up temporary playbook file."""
        if self._temp_playbook and self._temp_playbook.exists():
            try:
                self._temp_playbook.unlink()
                logger.debug(f"🗑️ Cleaned up temp playbook: {self._temp_playbook}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to cleanup temp playbook: {e}")

    async def _run_local_command(self, cmd: str) -> dict[str, Any]:
        """
        Run a command locally.

        Args:
            cmd: Command to execute.

        Returns:
            Dict with stdout, stderr, exit_code.
        """
        import asyncio

        logger.debug(f"🔧 Running local: {cmd[:80]}...")

        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await proc.communicate()

        return {
            "stdout": stdout.decode() if stdout else "",
            "stderr": stderr.decode() if stderr else "",
            "exit_code": proc.returncode,
        }
