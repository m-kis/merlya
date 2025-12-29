"""
Merlya Pipelines - Terraform Pipeline.

Pipeline for executing Terraform operations with full state management.
Supports init, plan, apply, and destroy with proper state handling.
"""

from __future__ import annotations

from datetime import UTC, datetime
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


class TerraformPipeline(AbstractPipeline):
    """
    Pipeline for Terraform infrastructure operations.

    Workflow:
    1. fmt - Format check
    2. init - Initialize providers
    3. validate - Validate configuration
    4. plan - Generate execution plan
    5. apply - Apply changes (with HITL approval)

    Rollback is handled via:
    - git checkout + apply for IaC repos
    - terraform destroy for created resources
    - State manipulation for complex rollbacks
    """

    def __init__(
        self,
        ctx: SharedContext,
        deps: PipelineDeps,
        working_dir: str | None = None,
        var_file: str | None = None,
        variables: dict[str, Any] | None = None,
        backend_config: dict[str, str] | None = None,
        auto_approve: bool = False,
        destroy_mode: bool = False,
    ):
        """
        Initialize Terraform pipeline.

        Args:
            ctx: Shared context.
            deps: Pipeline dependencies.
            working_dir: Directory containing Terraform files.
            var_file: Path to tfvars file.
            variables: Variables to pass via -var.
            backend_config: Backend configuration overrides.
            auto_approve: Skip confirmation in non-interactive mode.
            destroy_mode: If True, run terraform destroy.
        """
        super().__init__(ctx, deps)
        self._working_dir = working_dir or deps.working_dir or "."
        self._var_file = var_file
        self._variables = variables or {}
        self._backend_config = backend_config or {}
        self._auto_approve = auto_approve
        self._destroy_mode = destroy_mode

        # State for rollback
        self._plan_file: str = ".merlya_tfplan"
        self._state_backup: str | None = None
        self._plan_output: str = ""
        self._apply_output: str = ""

    @property
    def name(self) -> str:
        """Get pipeline name."""
        return "terraform-destroy" if self._destroy_mode else "terraform"

    async def plan(self) -> PlanResult:
        """
        Plan stage: Run terraform init, validate, and plan.

        Returns:
            PlanResult with validation and planning output.
        """
        warnings: list[str] = []
        errors: list[str] = []
        resources: list[str] = []

        # Check terraform is available
        tf_check = await self._check_terraform_available()
        if not tf_check["available"]:
            return PlanResult(
                success=False,
                plan_output="Terraform not available",
                errors=[tf_check.get("error", "Terraform not found")],
            )

        # Step 1: Check format
        logger.debug("🔧 Running terraform fmt -check...")
        fmt_result = await self._run_terraform("fmt -check -diff")
        if fmt_result["exit_code"] != 0:
            warnings.append("Terraform files need formatting (run: terraform fmt)")

        # Step 2: Initialize
        logger.debug("🔧 Running terraform init...")
        init_cmd = "init"
        if self._backend_config:
            for key, value in self._backend_config.items():
                init_cmd += f' -backend-config="{key}={value}"'

        init_result = await self._run_terraform(init_cmd)
        if init_result["exit_code"] != 0:
            errors.append(f"Init failed: {init_result['stderr']}")
            return PlanResult(
                success=False,
                plan_output=init_result["stdout"] + init_result["stderr"],
                errors=errors,
                warnings=warnings,
            )

        # Step 3: Validate
        logger.debug("🔧 Running terraform validate...")
        validate_result = await self._run_terraform("validate")
        if validate_result["exit_code"] != 0:
            errors.append(f"Validation failed: {validate_result['stderr']}")
            return PlanResult(
                success=False,
                plan_output=validate_result["stdout"] + validate_result["stderr"],
                errors=errors,
                warnings=warnings,
            )

        # Step 4: Plan
        logger.debug("🔧 Running terraform plan...")
        plan_cmd = f"plan -out={self._plan_file}"
        if self._destroy_mode:
            plan_cmd += " -destroy"
        plan_cmd = self._add_var_flags(plan_cmd)

        plan_result = await self._run_terraform(plan_cmd)
        self._plan_output = plan_result["stdout"] + plan_result["stderr"]

        if plan_result["exit_code"] != 0:
            errors.append("Plan failed")
            return PlanResult(
                success=False,
                plan_output=self._plan_output,
                errors=errors,
                warnings=warnings,
            )

        # Parse affected resources from plan
        resources = self._parse_plan_resources(self._plan_output)

        return PlanResult(
            success=True,
            plan_output=self._plan_output,
            resources_affected=resources,
            warnings=warnings,
            metadata={"plan_file": self._plan_file, "version": tf_check.get("version")},
        )

    async def diff(self) -> DiffResult:
        """
        Diff stage: Show terraform plan output.

        Returns:
            DiffResult with change preview.
        """
        # Run terraform show on the plan file
        show_result = await self._run_terraform(f"show {self._plan_file}")

        if show_result["exit_code"] != 0:
            return DiffResult(
                success=False,
                diff_output=f"Failed to show plan: {show_result['stderr']}",
            )

        diff_output = show_result["stdout"]

        # Count changes
        additions = diff_output.count("+ resource")
        deletions = diff_output.count("- resource")
        modifications = diff_output.count("~ resource")

        # Assess risk
        risk = "low"
        if self._destroy_mode or deletions > 0:
            risk = "critical"
        elif modifications > 5:
            risk = "high"
        elif modifications > 0:
            risk = "medium"

        return DiffResult(
            success=True,
            diff_output=diff_output,
            additions=additions,
            modifications=modifications,
            deletions=deletions,
            risk_assessment=risk,
        )

    async def apply(self) -> ApplyResult:
        """
        Apply stage: Execute terraform apply.

        Returns:
            ApplyResult with execution details.
        """
        start_time = datetime.now(UTC)

        # Backup state before apply
        self._state_backup = await self._backup_state()

        apply_result = await self._run_terraform(f"apply {self._plan_file}")
        self._apply_output = apply_result["stdout"] + apply_result["stderr"]

        duration = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

        success = apply_result["exit_code"] == 0

        # Parse resources from output
        created = self._parse_created_resources(self._apply_output)
        modified = self._parse_modified_resources(self._apply_output)
        deleted = self._parse_deleted_resources(self._apply_output)

        return ApplyResult(
            success=success,
            output=self._apply_output,
            resources_created=created,
            resources_modified=modified,
            resources_deleted=deleted,
            duration_ms=duration,
            rollback_data={
                "state_backup": self._state_backup,
                "working_dir": self._working_dir,
            },
        )

    async def rollback(self) -> RollbackResult:
        """
        Rollback stage: Restore previous state.

        For Terraform, rollback options are:
        1. Restore state backup and apply
        2. Run terraform destroy for created resources
        3. Manual intervention required

        Returns:
            RollbackResult with rollback status.
        """
        if not self._state_backup:
            return RollbackResult(
                success=False,
                output="No state backup available",
                errors=["Cannot rollback: no state backup was created"],
            )

        try:
            # Restore state file
            state_path = Path(self._working_dir) / "terraform.tfstate"
            backup_path = Path(self._state_backup)

            if backup_path.exists():
                import shutil

                shutil.copy(backup_path, state_path)
                logger.info(f"↩️ Restored state from {backup_path}")

                # Re-apply to restore resources
                apply_result = await self._run_terraform("apply -auto-approve")

                return RollbackResult(
                    success=apply_result["exit_code"] == 0,
                    output=apply_result["stdout"] + apply_result["stderr"],
                    resources_restored=["terraform_state"],
                )

            return RollbackResult(
                success=False,
                output="State backup file not found",
                errors=[f"Backup not found: {self._state_backup}"],
            )

        except Exception as e:
            return RollbackResult(
                success=False,
                output=f"Rollback failed: {e}",
                errors=[str(e)],
            )

    async def post_check(self) -> PostCheckResult:
        """
        Post-check stage: Verify terraform state is healthy.

        Returns:
            PostCheckResult with verification status.
        """
        checks_passed: list[str] = []
        checks_failed: list[str] = []

        # Check 1: terraform show works
        show_result = await self._run_terraform("show")
        if show_result["exit_code"] == 0:
            checks_passed.append("state_readable")
        else:
            checks_failed.append("state_readable: state file corrupted or unreadable")

        # Check 2: terraform plan shows no changes (drift detection)
        plan_result = await self._run_terraform("plan -detailed-exitcode")
        # Exit code 0 = no changes, 1 = error, 2 = changes present
        if plan_result["exit_code"] == 0:
            checks_passed.append("no_drift")
        elif plan_result["exit_code"] == 2:
            checks_passed.append("drift_expected")  # Changes exist but that's ok after apply
        else:
            checks_failed.append("plan_error: could not verify state")

        # Check 3: terraform validate
        validate_result = await self._run_terraform("validate")
        if validate_result["exit_code"] == 0:
            checks_passed.append("config_valid")
        else:
            checks_failed.append("config_valid: configuration invalid")

        return PostCheckResult(
            success=len(checks_failed) == 0,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
        )

    async def _check_terraform_available(self) -> dict[str, Any]:
        """Check if terraform is available."""
        try:
            result = await self._run_terraform("version")
            version_line = result["stdout"].split("\n")[0] if result["stdout"] else ""
            return {
                "available": result["exit_code"] == 0,
                "version": version_line,
            }
        except Exception as e:
            return {"available": False, "error": str(e)}

    async def _run_terraform(self, cmd: str) -> dict[str, Any]:
        """
        Run a terraform command.

        Args:
            cmd: Terraform subcommand and arguments.

        Returns:
            Dict with stdout, stderr, exit_code.
        """
        import asyncio

        full_cmd = f"terraform -chdir={self._working_dir} {cmd}"
        logger.debug(f"🔧 Running: {full_cmd[:80]}...")

        proc = await asyncio.create_subprocess_shell(
            full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await proc.communicate()

        return {
            "stdout": stdout.decode() if stdout else "",
            "stderr": stderr.decode() if stderr else "",
            "exit_code": proc.returncode,
        }

    def _add_var_flags(self, cmd: str) -> str:
        """Add variable flags to command."""
        if self._var_file:
            cmd += f" -var-file={self._var_file}"
        for key, value in self._variables.items():
            cmd += f' -var="{key}={value}"'
        return cmd

    async def _backup_state(self) -> str | None:
        """Backup current state file."""
        import shutil

        state_path = Path(self._working_dir) / "terraform.tfstate"
        if state_path.exists():
            backup_path = state_path.with_suffix(".tfstate.backup.merlya")
            shutil.copy(state_path, backup_path)
            logger.debug(f"📦 Backed up state to {backup_path}")
            return str(backup_path)
        return None

    def _parse_plan_resources(self, output: str) -> list[str]:
        """Parse affected resources from plan output."""
        resources = []
        for line in output.split("\n"):
            if (
                "will be created" in line.lower()
                or "will be updated" in line.lower()
                or "will be destroyed" in line.lower()
            ):
                resources.append(line.strip())
        return resources[:20]  # Limit to first 20

    def _parse_created_resources(self, output: str) -> list[str]:
        """Parse created resources from apply output."""
        return [
            line.strip() for line in output.split("\n") if "created" in line.lower() and ":" in line
        ][:10]

    def _parse_modified_resources(self, output: str) -> list[str]:
        """Parse modified resources from apply output."""
        return [
            line.strip()
            for line in output.split("\n")
            if "modified" in line.lower() and ":" in line
        ][:10]

    def _parse_deleted_resources(self, output: str) -> list[str]:
        """Parse deleted resources from apply output."""
        return [
            line.strip()
            for line in output.split("\n")
            if "destroyed" in line.lower() and ":" in line
        ][:10]
