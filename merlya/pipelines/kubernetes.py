"""
Merlya Pipelines - Kubernetes Pipeline.

Pipeline for executing Kubernetes operations via kubectl.
Supports apply, rollout, scale, and delete operations.
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


class KubernetesOperation(str, Enum):
    """Kubernetes operation types."""

    APPLY = "apply"  # kubectl apply -f
    DELETE = "delete"  # kubectl delete
    SCALE = "scale"  # kubectl scale
    ROLLOUT = "rollout"  # kubectl rollout restart/undo
    PATCH = "patch"  # kubectl patch


class KubernetesPipeline(AbstractPipeline):
    """
    Pipeline for Kubernetes operations.

    Operations:
    - APPLY: Apply manifest files or inline YAML
    - DELETE: Delete resources
    - SCALE: Scale deployments/statefulsets
    - ROLLOUT: Restart or undo rollouts
    - PATCH: Patch resources

    Supports:
    - --dry-run=server for diff
    - rollout undo for rollback
    - kubectl get for post-check
    """

    def __init__(
        self,
        ctx: SharedContext,
        deps: PipelineDeps,
        operation: KubernetesOperation = KubernetesOperation.APPLY,
        manifest_path: str | None = None,
        manifest_content: str | None = None,
        resource_type: str | None = None,
        resource_name: str | None = None,
        namespace: str = "default",
        replicas: int | None = None,
        context: str | None = None,
        kubeconfig: str | None = None,
    ):
        """
        Initialize Kubernetes pipeline.

        Args:
            ctx: Shared context.
            deps: Pipeline dependencies.
            operation: Type of Kubernetes operation.
            manifest_path: Path to manifest file(s) for apply.
            manifest_content: YAML content for inline apply.
            resource_type: Resource type (deployment, service, etc).
            resource_name: Resource name.
            namespace: Kubernetes namespace.
            replicas: Number of replicas for scale operation.
            context: Kubernetes context to use.
            kubeconfig: Path to kubeconfig file.
        """
        super().__init__(ctx, deps)
        self._operation = operation
        self._manifest_path = manifest_path
        self._manifest_content = manifest_content
        self._resource_type = resource_type
        self._resource_name = resource_name
        self._namespace = namespace
        self._replicas = replicas
        self._context = context
        self._kubeconfig = kubeconfig

        # Temp file for inline manifest
        self._temp_manifest: Path | None = None

        # State for rollback
        self._original_replicas: int | None = None
        self._rollout_revision: str | None = None
        self._diff_output: str = ""
        self._apply_output: str = ""

    @property
    def name(self) -> str:
        """Get pipeline name."""
        return f"kubernetes-{self._operation.value}"

    async def plan(self) -> PlanResult:
        """
        Plan stage: Validate kubectl configuration.

        Returns:
            PlanResult with validation status.
        """
        warnings: list[str] = []
        errors: list[str] = []

        # Check kubectl is available
        kubectl_check = await self._check_kubectl_available()
        if not kubectl_check["available"]:
            return PlanResult(
                success=False,
                plan_output="kubectl not available",
                errors=[kubectl_check.get("error", "kubectl not found")],
            )

        # Validate operation-specific requirements
        if self._operation == KubernetesOperation.APPLY:
            if not self._manifest_path and not self._manifest_content:
                errors.append("APPLY requires manifest_path or manifest_content")
        elif self._operation in (
            KubernetesOperation.DELETE,
            KubernetesOperation.ROLLOUT,
            KubernetesOperation.PATCH,
        ):
            if not self._resource_type or not self._resource_name:
                errors.append(f"{self._operation.value} requires resource_type and resource_name")
        elif self._operation == KubernetesOperation.SCALE:
            if not self._resource_type or not self._resource_name:
                errors.append("SCALE requires resource_type and resource_name")
            if self._replicas is None:
                errors.append("SCALE requires replicas count")

        if errors:
            return PlanResult(
                success=False,
                plan_output="Kubernetes validation failed",
                errors=errors,
                warnings=warnings,
            )

        # Build plan output
        plan_lines = [
            f"Operation: {self._operation.value}",
            f"Namespace: {self._namespace}",
        ]

        if self._manifest_path:
            plan_lines.append(f"Manifest: {self._manifest_path}")
        if self._manifest_content:
            plan_lines.append("Manifest: (inline)")
        if self._resource_type:
            plan_lines.append(f"Resource: {self._resource_type}/{self._resource_name}")
        if self._replicas is not None:
            plan_lines.append(f"Replicas: {self._replicas}")
        if self._context:
            plan_lines.append(f"Context: {self._context}")

        return PlanResult(
            success=True,
            plan_output="\n".join(plan_lines),
            resources_affected=[
                f"{self._resource_type}/{self._resource_name}"
                if self._resource_type
                else "manifest"
            ],
            warnings=warnings,
            metadata={"operation": self._operation.value, "namespace": self._namespace},
        )

    async def diff(self) -> DiffResult:
        """
        Diff stage: Run kubectl with --dry-run.

        Returns:
            DiffResult with change preview.
        """
        try:
            if self._operation == KubernetesOperation.APPLY:
                cmd = await self._build_apply_command(dry_run=True)
            elif self._operation == KubernetesOperation.SCALE:
                # Store original replicas for diff
                self._original_replicas = await self._get_current_replicas()
                diff_text = f"Scaling {self._resource_type}/{self._resource_name}\n"
                diff_text += f"  Current replicas: {self._original_replicas}\n"
                diff_text += f"  Target replicas: {self._replicas}"

                return DiffResult(
                    success=True,
                    diff_output=diff_text,
                    modifications=1 if self._original_replicas != self._replicas else 0,
                    risk_assessment="medium" if self._replicas == 0 else "low",
                )
            elif self._operation == KubernetesOperation.ROLLOUT:
                diff_text = f"Rollout restart: {self._resource_type}/{self._resource_name}"
                return DiffResult(
                    success=True,
                    diff_output=diff_text,
                    modifications=1,
                    risk_assessment="medium",
                )
            elif self._operation == KubernetesOperation.DELETE:
                diff_text = f"Delete resource: {self._resource_type}/{self._resource_name}"
                return DiffResult(
                    success=True,
                    diff_output=diff_text,
                    deletions=1,
                    risk_assessment="high",
                )
            else:
                cmd = self._build_base_command() + " get " + self._build_resource_selector()

            result = await self._run_kubectl(cmd)
            self._diff_output = result.get("stdout", "") + result.get("stderr", "")

            # Count changes
            additions = self._diff_output.count("created")
            modifications = self._diff_output.count("configured") + self._diff_output.count(
                "changed"
            )
            deletions = self._diff_output.count("deleted")

            # Assess risk (DELETE handled above with early return)
            risk = "low"
            if deletions > 0:
                risk = "high"
            elif modifications > 0:
                risk = "medium"

            return DiffResult(
                success=result.get("exit_code", 1) == 0 or "dry run" in self._diff_output.lower(),
                diff_output=self._diff_output or "No changes detected",
                additions=additions,
                modifications=modifications,
                deletions=deletions,
                risk_assessment=risk,
            )

        except Exception as e:
            logger.error(f"❌ Kubernetes diff failed: {e}")
            return DiffResult(
                success=False,
                diff_output=f"Diff failed: {e}",
                risk_assessment="unknown",
            )

    async def apply(self) -> ApplyResult:
        """
        Apply stage: Execute kubectl operation.

        Returns:
            ApplyResult with execution details.
        """
        start_time = datetime.now(UTC)

        try:
            # Store rollback info before applying
            if self._operation == KubernetesOperation.ROLLOUT:
                self._rollout_revision = await self._get_rollout_revision()
            elif self._operation == KubernetesOperation.SCALE and self._original_replicas is None:
                self._original_replicas = await self._get_current_replicas()

            # Build and execute command
            if self._operation == KubernetesOperation.APPLY:
                cmd = await self._build_apply_command(dry_run=False)
            elif self._operation == KubernetesOperation.SCALE:
                cmd = self._build_scale_command()
            elif self._operation == KubernetesOperation.ROLLOUT:
                cmd = self._build_rollout_command()
            elif self._operation == KubernetesOperation.DELETE:
                cmd = self._build_delete_command()
            else:
                cmd = self._build_base_command() + " " + self._build_resource_selector()

            result = await self._run_kubectl(cmd)
            self._apply_output = result.get("stdout", "") + result.get("stderr", "")

            duration = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
            success = result.get("exit_code", 1) == 0

            return ApplyResult(
                success=success,
                output=self._apply_output,
                resources_modified=[f"{self._resource_type}/{self._resource_name}"]
                if self._resource_type
                else ["manifest"],
                duration_ms=duration,
                rollback_data={
                    "operation": self._operation.value,
                    "resource_type": self._resource_type,
                    "resource_name": self._resource_name,
                    "namespace": self._namespace,
                    "original_replicas": self._original_replicas,
                    "rollout_revision": self._rollout_revision,
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
            self._cleanup_temp_manifest()

    async def rollback(self) -> RollbackResult:
        """
        Rollback stage: Undo the Kubernetes operation.

        Returns:
            RollbackResult with rollback status.
        """
        try:
            if self._operation == KubernetesOperation.ROLLOUT:
                # Use kubectl rollout undo
                cmd = f"{self._build_base_command()} rollout undo {self._resource_type}/{self._resource_name}"
                if self._rollout_revision:
                    cmd += f" --to-revision={self._rollout_revision}"

            elif self._operation == KubernetesOperation.SCALE:
                # Restore original replicas
                if self._original_replicas is not None:
                    cmd = f"{self._build_base_command()} scale {self._resource_type}/{self._resource_name} --replicas={self._original_replicas}"
                else:
                    return RollbackResult(
                        success=False,
                        output="Cannot rollback scale: original replicas unknown",
                        errors=["Original replica count not stored"],
                    )

            elif self._operation == KubernetesOperation.DELETE:
                # Cannot easily rollback a delete
                return RollbackResult(
                    success=False,
                    output="Cannot rollback delete operation",
                    errors=["Delete operations cannot be automatically rolled back"],
                )

            elif self._operation == KubernetesOperation.APPLY:
                # Would need to apply previous version
                return RollbackResult(
                    success=False,
                    output="Rollback for apply requires previous manifest version",
                    errors=["Use kubectl rollout undo for deployments"],
                )

            else:
                return RollbackResult(
                    success=False,
                    output=f"Rollback not supported for {self._operation.value}",
                    errors=["Operation type does not support rollback"],
                )

            result = await self._run_kubectl(cmd)
            success = result.get("exit_code", 1) == 0

            return RollbackResult(
                success=success,
                output=result.get("stdout", "") + result.get("stderr", ""),
                resources_restored=[f"{self._resource_type}/{self._resource_name}"]
                if success
                else [],
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
        Post-check stage: Verify Kubernetes resources are healthy.

        Returns:
            PostCheckResult with verification status.
        """
        checks_passed: list[str] = []
        checks_failed: list[str] = []
        warnings: list[str] = []

        if not self._resource_type or not self._resource_name:
            return PostCheckResult(
                success=True,
                checks_passed=["no_resource_check"],
                warnings=["No specific resource to check"],
            )

        # Check 1: Resource exists
        get_cmd = (
            f"{self._build_base_command()} get {self._resource_type}/{self._resource_name} -o name"
        )
        get_result = await self._run_kubectl(get_cmd)

        if get_result.get("exit_code", 1) == 0:
            checks_passed.append("resource_exists")
        else:
            if self._operation == KubernetesOperation.DELETE:
                checks_passed.append("resource_deleted")
            else:
                checks_failed.append("resource_exists: resource not found")

        # Check 2: For deployments, check rollout status
        if self._resource_type in ("deployment", "deployments", "deploy"):
            status_cmd = f"{self._build_base_command()} rollout status {self._resource_type}/{self._resource_name} --timeout=60s"
            status_result = await self._run_kubectl(status_cmd)

            if status_result.get("exit_code", 1) == 0:
                checks_passed.append("rollout_complete")
            else:
                warnings.append("rollout_status: rollout may still be in progress")

        # Check 3: Check pod status if applicable
        if self._resource_type in ("deployment", "deployments", "deploy", "statefulset", "sts"):
            pods_cmd = f"{self._build_base_command()} get pods -l app={self._resource_name} -o jsonpath='{{.items[*].status.phase}}'"
            pods_result = await self._run_kubectl(pods_cmd)

            if pods_result.get("exit_code", 1) == 0:
                phases = pods_result.get("stdout", "").strip().split()
                if all(p == "Running" for p in phases if p):
                    checks_passed.append("pods_running")
                elif phases:
                    warnings.append(f"pods_status: {' '.join(phases)}")

        return PostCheckResult(
            success=len(checks_failed) == 0,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            warnings=warnings,
        )

    async def _check_kubectl_available(self) -> dict[str, Any]:
        """Check if kubectl is available."""
        try:
            result = await self._run_kubectl("version --client -o json")
            return {
                "available": result.get("exit_code", 1) == 0,
                "version": "kubectl available",
            }
        except Exception as e:
            return {"available": False, "error": str(e)}

    def _build_base_command(self) -> str:
        """Build base kubectl command with context and namespace."""
        cmd = "kubectl"
        if self._kubeconfig:
            cmd += f" --kubeconfig={self._kubeconfig}"
        if self._context:
            cmd += f" --context={self._context}"
        cmd += f" -n {self._namespace}"
        return cmd

    async def _build_apply_command(self, dry_run: bool = False) -> str:
        """Build kubectl apply command."""
        cmd = f"{self._build_base_command()} apply"

        if self._manifest_content:
            self._temp_manifest = await self._create_temp_manifest()
            cmd += f" -f {self._temp_manifest}"
        elif self._manifest_path:
            cmd += f" -f {self._manifest_path}"

        if dry_run:
            cmd += " --dry-run=server -o yaml"

        return cmd

    def _build_scale_command(self) -> str:
        """Build kubectl scale command."""
        return f"{self._build_base_command()} scale {self._resource_type}/{self._resource_name} --replicas={self._replicas}"

    def _build_rollout_command(self) -> str:
        """Build kubectl rollout restart command."""
        return f"{self._build_base_command()} rollout restart {self._resource_type}/{self._resource_name}"

    def _build_delete_command(self) -> str:
        """Build kubectl delete command."""
        return f"{self._build_base_command()} delete {self._resource_type}/{self._resource_name}"

    def _build_resource_selector(self) -> str:
        """Build resource selector string."""
        if self._resource_type and self._resource_name:
            return f"{self._resource_type}/{self._resource_name}"
        return ""

    async def _get_current_replicas(self) -> int | None:
        """Get current replica count for a resource."""
        cmd = f"{self._build_base_command()} get {self._resource_type}/{self._resource_name} -o jsonpath='{{.spec.replicas}}'"
        result = await self._run_kubectl(cmd)
        if result.get("exit_code", 1) == 0:
            try:
                return int(result.get("stdout", "").strip())
            except ValueError:
                return None
        return None

    async def _get_rollout_revision(self) -> str | None:
        """Get current rollout revision."""
        cmd = f"{self._build_base_command()} rollout history {self._resource_type}/{self._resource_name} --revision=0"
        result = await self._run_kubectl(cmd)
        if result.get("exit_code", 1) == 0:
            # Parse revision from output
            output = result.get("stdout", "")
            for line in output.split("\n"):
                if "REVISION" in line:
                    continue
                parts = line.split()
                if parts:
                    revision: str = parts[0]
                    return revision
        return None

    async def _create_temp_manifest(self) -> Path:
        """Create temporary manifest file."""
        if not self._manifest_content:
            msg = "No manifest content provided"
            raise ValueError(msg)

        _fd, path = tempfile.mkstemp(suffix=".yaml", prefix="merlya_k8s_")
        temp_path = Path(path)

        with temp_path.open("w") as f:
            f.write(self._manifest_content)

        logger.debug(f"📝 Created temp manifest: {temp_path}")
        return temp_path

    def _cleanup_temp_manifest(self) -> None:
        """Clean up temporary manifest file."""
        if self._temp_manifest and self._temp_manifest.exists():
            try:
                self._temp_manifest.unlink()
                logger.debug(f"🗑️ Cleaned up temp manifest: {self._temp_manifest}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to cleanup temp manifest: {e}")

    async def _run_kubectl(self, cmd: str) -> dict[str, Any]:
        """
        Run a kubectl command.

        Args:
            cmd: Full kubectl command.

        Returns:
            Dict with stdout, stderr, exit_code.
        """
        import asyncio

        logger.debug(f"🔧 Running: {cmd[:80]}...")

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
