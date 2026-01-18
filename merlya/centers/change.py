"""
Merlya Centers - Change Center.

Controlled mutation center for modifying system state.
All changes go through Pipelines with mandatory HITL approval.
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
    RiskLevel,
)

if TYPE_CHECKING:
    from merlya.capabilities.detector import CapabilityDetector
    from merlya.capabilities.models import HostCapabilities, LocalCapabilities
    from merlya.core.context import SharedContext
    from merlya.pipelines.base import AbstractPipeline, PipelineDeps, PipelineResult
    from merlya.provisioners.base import ProvisionerResult


class ChangeCenter(AbstractCenter):
    """
    Controlled mutation center.

    All changes MUST go through a Pipeline with:
    - Plan: Validate what will change
    - Diff: Show preview (dry-run)
    - Summary: Human-readable description
    - HITL: User approval required
    - Apply: Execute changes
    - Post-check: Verify success
    - Rollback: Revert if failed
    """

    def __init__(
        self,
        ctx: SharedContext,
        capabilities: CapabilityDetector | None = None,
    ):
        """
        Initialize change center.

        Args:
            ctx: Shared context with infrastructure access.
            capabilities: Optional capability detector (creates one if not provided).
        """
        super().__init__(ctx)
        self._capabilities = capabilities
        self._last_pipeline_result: PipelineResult | None = None

    @property
    def mode(self) -> CenterMode:
        """Get center mode."""
        return CenterMode.CHANGE

    @property
    def allowed_tools(self) -> list[str]:
        """Get list of allowed tools for CHANGE operations."""
        return [
            # Via Pipelines
            "execute_pipeline",
            # SSH with HITL
            "ssh_execute",
            # Files
            "write_file",
            "edit_file",
            # Elevation
            "request_elevation",
            "request_credentials",
            # Host management
            "list_hosts",
            "get_host",
        ]

    @property
    def risk_level(self) -> RiskLevel:
        """Change operations are always high risk."""
        return RiskLevel.HIGH

    async def execute(self, deps: CenterDeps) -> CenterResult:
        """
        Execute change operation via appropriate Pipeline.

        Args:
            deps: Dependencies with target and task.

        Returns:
            Result with applied changes and rollback info.
        """
        start_time = datetime.now(UTC)

        logger.info(f"⚡ ChangeCenter: Processing change request for {deps.target}")

        try:
            # 1. Validate target
            host = await self.validate_target(deps.target)
            if host is None and deps.target != "local":
                return self._create_result(
                    success=False,
                    message=f"Host '{deps.target}' not found",
                )

            # 2. Detect capabilities
            caps = await self._get_capabilities(deps.target, host)

            # 3. Check for IaC provisioning task first
            provisioner_result = await self._try_provisioner(deps)
            if provisioner_result is not None:
                duration = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
                # Extract apply results (if available)
                apply_result = provisioner_result.apply
                rollback_data = apply_result.rollback_data if apply_result else None
                resources_created = apply_result.resources_created if apply_result else []
                resources_updated = apply_result.resources_updated if apply_result else []
                resources_deleted = apply_result.resources_deleted if apply_result else []

                return CenterResult(
                    success=provisioner_result.success,
                    message=self._format_provisioner_result(provisioner_result),
                    mode=self.mode,
                    applied=provisioner_result.success and not provisioner_result.aborted,
                    rollback_available=rollback_data is not None,
                    post_check_passed=None,
                    data={
                        "provisioner": True,
                        "action": provisioner_result.action.value
                        if provisioner_result.action
                        else None,
                        "provider": deps.extra.get("cloud_provider"),
                        "resources_created": resources_created,
                        "resources_updated": resources_updated,
                        "resources_deleted": resources_deleted,
                        "aborted": provisioner_result.aborted,
                        "aborted_reason": provisioner_result.aborted_reason,
                    },
                    started_at=start_time,
                    completed_at=datetime.now(UTC),
                    duration_ms=duration,
                )

            # 4. Select appropriate pipeline
            pipeline = await self._select_pipeline(deps, caps)
            if pipeline is None:
                return self._create_result(
                    success=False,
                    message="No suitable pipeline available for this operation",
                    data={"available_tools": self._list_available_tools(caps)},
                )

            # 5. Execute pipeline (includes HITL)
            logger.info(f"📋 Using {pipeline.name} pipeline for {deps.target}")
            result = await pipeline.execute()
            self._last_pipeline_result = result

            # 5. Build response
            duration = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

            return CenterResult(
                success=result.success,
                message=self._format_pipeline_result(result),
                mode=self.mode,
                applied=result.apply is not None and result.apply.success,
                rollback_available=result.rollback is not None,
                post_check_passed=(result.post_check.success if result.post_check else None),
                data={
                    "pipeline": pipeline.name,
                    "aborted": result.aborted,
                    "aborted_reason": result.aborted_reason,
                    "hitl_approved": result.hitl_approved,
                    "rollback_triggered": result.rollback_triggered,
                },
                started_at=start_time,
                completed_at=datetime.now(UTC),
                duration_ms=duration,
            )

        except Exception as e:
            logger.error(f"❌ ChangeCenter error: {e}")
            return self._create_result(
                success=False,
                message=f"Change operation failed: {e}",
            )

    async def _get_capabilities(
        self,
        target: str,
        host: Any | None,
    ) -> HostCapabilities | LocalCapabilities:
        """Get capabilities for target."""
        from merlya.capabilities.detector import CapabilityDetector

        detector = self._capabilities
        if detector is None:
            detector = CapabilityDetector(self._ctx)

        if target == "local" or host is None:
            return await detector.detect_local()
        return await detector.detect_host(host)

    async def _select_pipeline(
        self,
        deps: CenterDeps,
        caps: HostCapabilities | LocalCapabilities,
    ) -> AbstractPipeline | None:
        """
        Select the most appropriate pipeline based on capabilities.

        Priority order:
        1. Ansible (if available and task matches)
        2. Terraform (if available and task matches)
        3. Kubernetes (if kubectl available and task matches)
        4. Bash (fallback)

        Args:
            deps: Task dependencies.
            caps: Detected capabilities.

        Returns:
            Selected pipeline or None if none suitable.
        """
        from merlya.capabilities.models import ToolName
        from merlya.pipelines.base import PipelineDeps
        from merlya.pipelines.bash import BashPipeline

        pipeline_deps = PipelineDeps(
            target=deps.target,
            task=deps.task,
            extra=deps.extra,
        )

        # Check for Ansible
        if caps.has_tool(ToolName.ANSIBLE):
            pipeline = await self._try_ansible_pipeline(deps, pipeline_deps)
            if pipeline:
                return pipeline

        # Check for Terraform
        if caps.has_tool(ToolName.TERRAFORM):
            pipeline = await self._try_terraform_pipeline(deps, pipeline_deps)
            if pipeline:
                return pipeline

        # Check for Kubernetes
        if caps.has_tool(ToolName.KUBECTL):
            pipeline = await self._try_kubernetes_pipeline(deps, pipeline_deps)
            if pipeline:
                return pipeline

        # Fallback to Bash pipeline
        commands = await self._extract_bash_commands(deps.task)
        if commands:
            return BashPipeline(
                ctx=self._ctx,
                deps=pipeline_deps,
                commands=commands,
            )

        return None

    async def _try_ansible_pipeline(
        self,
        deps: CenterDeps,
        _pipeline_deps: PipelineDeps,
    ) -> AbstractPipeline | None:
        """Try to create Ansible pipeline if task matches."""
        # Check if task looks like Ansible work
        ansible_keywords = [
            "playbook",
            "ansible",
            "deploy",
            "configure",
            "provision",
            "install package",
            "service",
        ]
        task_lower = deps.task.lower()

        if any(kw in task_lower for kw in ansible_keywords):
            # TODO: Import AnsiblePipeline when implemented (#18)
            logger.debug("🔧 Ansible pipeline would be selected (not yet implemented)")
        return None

    async def _try_terraform_pipeline(
        self,
        deps: CenterDeps,
        _pipeline_deps: PipelineDeps,
    ) -> AbstractPipeline | None:
        """Try to create Terraform pipeline if task matches."""
        # Check if task looks like Terraform work
        tf_keywords = [
            "terraform",
            "infrastructure",
            "create instance",
            "provision cloud",
            "aws",
            "gcp",
            "azure",
        ]
        task_lower = deps.task.lower()

        if any(kw in task_lower for kw in tf_keywords):
            # TODO: Import TerraformPipeline when implemented (#19)
            logger.debug("🔧 Terraform pipeline would be selected (not yet implemented)")
        return None

    async def _try_kubernetes_pipeline(
        self,
        deps: CenterDeps,
        _pipeline_deps: PipelineDeps,
    ) -> AbstractPipeline | None:
        """Try to create Kubernetes pipeline if task matches."""
        # Check if task looks like K8s work
        k8s_keywords = [
            "kubectl",
            "kubernetes",
            "k8s",
            "pod",
            "deployment",
            "scale",
            "rollout",
            "namespace",
        ]
        task_lower = deps.task.lower()

        if any(kw in task_lower for kw in k8s_keywords):
            # TODO: Import KubernetesPipeline when implemented (#20)
            logger.debug("🔧 Kubernetes pipeline would be selected (not yet implemented)")
        return None

    async def _extract_bash_commands(self, task: str) -> list[str]:
        """
        Extract bash commands from task description.

        This is a simple extraction - in production, the LLM
        would generate appropriate commands based on the task.

        Args:
            task: Task description.

        Returns:
            List of bash commands to execute.
        """
        # For now, return empty - the LLM agent should provide commands
        # This method is a placeholder for future LLM integration
        logger.debug(f"📝 Would extract commands from: {task[:50]}...")
        return []

    def _list_available_tools(
        self,
        caps: HostCapabilities | LocalCapabilities,
    ) -> list[str]:
        """List available tools from capabilities."""
        return [tool.name.value for tool in caps.tools if tool.installed and tool.config_valid]

    def _format_pipeline_result(self, result: PipelineResult) -> str:
        """Format pipeline result for human consumption."""
        lines = []

        if result.aborted:
            lines.append(f"⏹️ Pipeline aborted: {result.aborted_reason}")
            if result.aborted_at:
                lines.append(f"   Stage: {result.aborted_at.value}")
            return "\n".join(lines)

        if result.success:
            lines.append("✅ Change applied successfully")

            if result.apply:
                if result.apply.resources_created:
                    lines.append(f"   Created: {len(result.apply.resources_created)} resources")
                if result.apply.resources_modified:
                    lines.append(f"   Modified: {len(result.apply.resources_modified)} resources")
                if result.apply.resources_deleted:
                    lines.append(f"   Deleted: {len(result.apply.resources_deleted)} resources")

            if result.post_check and result.post_check.success:
                lines.append("   ✓ Post-check passed")

        else:
            lines.append("❌ Change failed")

            if result.rollback_triggered:
                lines.append(f"   ↩️ Rollback triggered: {result.rollback_reason}")
                if result.rollback:
                    if result.rollback.success:
                        lines.append("   ✓ Rollback successful")
                    else:
                        lines.append("   ✗ Rollback failed")
                        for err in result.rollback.errors:
                            lines.append(f"      - {err}")

        if result.duration_ms:
            lines.append(f"   Duration: {result.duration_ms}ms")

        return "\n".join(lines)

    @property
    def last_result(self) -> PipelineResult | None:
        """Get last pipeline execution result."""
        return self._last_pipeline_result

    async def _try_provisioner(self, deps: CenterDeps) -> ProvisionerResult | None:
        """
        Try to handle task as IaC provisioning operation.

        Checks if the task is an IaC operation (provision, update, destroy)
        and routes to the appropriate provisioner.

        Args:
            deps: Center dependencies with task and extra context.

        Returns:
            ProvisionerResult if handled as IaC, None otherwise.
        """
        # Check if this is an IaC task via extra context
        iac_operation = deps.extra.get("iac_operation")
        cloud_provider = deps.extra.get("cloud_provider")

        if not iac_operation:
            return None

        logger.info(f"🏗️ IaC operation detected: {iac_operation} on {cloud_provider or 'auto'}")

        try:
            from merlya.provisioners.base import ProvisionerAction, ProvisionerDeps
            from merlya.provisioners.registry import ProvisionerRegistry

            # Get provisioner registry
            registry = ProvisionerRegistry.get_instance()

            # Map operation to action
            action_map = {
                "provision": ProvisionerAction.CREATE,
                "create": ProvisionerAction.CREATE,
                "update": ProvisionerAction.UPDATE,
                "modify": ProvisionerAction.UPDATE,
                "destroy": ProvisionerAction.DELETE,
                "delete": ProvisionerAction.DELETE,
            }
            action = action_map.get(iac_operation.lower())
            if action is None:
                logger.warning(f"Unknown IaC operation: {iac_operation}")
                return None

            # Build provisioner deps
            provisioner_deps = ProvisionerDeps(
                action=action,
                provider=cloud_provider or "auto",
                resources=deps.extra.get("resources", []),
                dry_run=deps.extra.get("dry_run", False),
                extra={
                    "template_name": deps.extra.get("template"),
                    "template_vars": deps.extra.get("template_vars", {}),
                },
            )

            # Get provisioner and execute
            try:
                provisioner = registry.get(provisioner_deps)
                result: ProvisionerResult = await provisioner.execute()
                return result
            except ValueError as e:
                logger.warning(f"No provisioner available for provider {cloud_provider}: {e}")
                return None

        except ImportError as e:
            logger.debug(f"Provisioner module not available: {e}")
            return None
        except Exception as e:
            logger.error(f"Provisioner execution failed: {e}")
            # Return failed result instead of None to indicate we tried
            from merlya.provisioners.base import ProvisionerAction, ProvisionerResult

            return ProvisionerResult(
                success=False,
                action=ProvisionerAction.CREATE,
                aborted=True,
                aborted_reason=str(e),
            )

    def _format_provisioner_result(self, result: ProvisionerResult) -> str:
        """Format provisioner result for human consumption."""
        lines = []

        if result.aborted:
            lines.append(f"⏹️ Provisioner aborted: {result.aborted_reason}")
            return "\n".join(lines)

        action_emoji = {
            "CREATE": "🆕",
            "UPDATE": "🔄",
            "DELETE": "🗑️",
        }
        emoji = action_emoji.get(result.action.value if result.action else "", "🏗️")

        if result.success:
            lines.append(f"{emoji} Provisioning completed successfully")

            # Get resource counts from apply result
            if result.apply:
                if result.apply.resources_created:
                    lines.append(f"   Created: {len(result.apply.resources_created)} resources")
                if result.apply.resources_updated:
                    lines.append(f"   Updated: {len(result.apply.resources_updated)} resources")
                if result.apply.resources_deleted:
                    lines.append(f"   Deleted: {len(result.apply.resources_deleted)} resources")

                if result.apply.outputs:
                    lines.append("   Outputs:")
                    for key, value in result.apply.outputs.items():
                        # Truncate long values
                        display_value = str(value)[:50]
                        if len(str(value)) > 50:
                            display_value += "..."
                        lines.append(f"      {key}: {display_value}")

        else:
            lines.append(f"{emoji} Provisioning failed")

            if result.apply and result.apply.rollback_data:
                lines.append("   ↩️ Rollback data available")

        if result.duration_seconds:
            lines.append(f"   Duration: {int(result.duration_seconds * 1000)}ms")

        return "\n".join(lines)
