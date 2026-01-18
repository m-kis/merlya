"""
Merlya Provisioners - MCP Backend.

Backend implementation using MCP servers for cloud operations.

v0.9.0: Initial implementation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.provisioners.backends.base import (
    AbstractProvisionerBackend,
    BackendCapabilities,
    BackendNotAvailableError,
    BackendResult,
    BackendType,
)
from merlya.provisioners.providers.base import ProviderType

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.provisioners.base import ProvisionerDeps
    from merlya.provisioners.providers.base import InstanceSpec


# MCP server mappings per provider
MCP_SERVERS: dict[ProviderType, dict[str, Any]] = {
    ProviderType.AWS: {
        "package": "@aws-sdk/mcp",
        "tools": {
            "create_instance": "aws_ec2_run_instances",
            "list_instances": "aws_ec2_describe_instances",
            "terminate_instance": "aws_ec2_terminate_instances",
            "start_instance": "aws_ec2_start_instances",
            "stop_instance": "aws_ec2_stop_instances",
        },
    },
    ProviderType.GCP: {
        "package": "@google-cloud/mcp",
        "tools": {
            "create_instance": "gcp_compute_instances_insert",
            "list_instances": "gcp_compute_instances_list",
            "delete_instance": "gcp_compute_instances_delete",
        },
    },
    ProviderType.AZURE: {
        "package": "@azure/mcp",
        "tools": {
            "create_instance": "azure_vm_create",
            "list_instances": "azure_vm_list",
            "delete_instance": "azure_vm_delete",
        },
    },
}


class MCPBackend(AbstractProvisionerBackend):
    """
    MCP-based backend for cloud operations.

    Uses MCP servers (when available) for direct cloud API access.
    Falls back to provider SDK or Terraform if MCP not available.
    """

    def __init__(
        self,
        ctx: SharedContext,
        deps: ProvisionerDeps,
        working_dir: str | None = None,
    ) -> None:
        """
        Initialize MCP backend.

        Args:
            ctx: Shared context with MCP manager.
            deps: Provisioner dependencies.
            working_dir: Working directory (unused for MCP).
        """
        super().__init__(ctx, deps, working_dir)
        try:
            self._provider = ProviderType(deps.provider.lower())
        except ValueError:
            self._provider = None  # type: ignore[assignment]
        self._mcp_available: bool | None = None
        self._planned_specs: list[InstanceSpec] = []
        self._created_resources: list[dict[str, Any]] = []

    @property
    def backend_type(self) -> BackendType:
        return BackendType.MCP

    @property
    def name(self) -> str:
        return "MCP"

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            can_plan=True,
            can_diff=False,  # MCP doesn't have native diff
            can_apply=True,
            can_destroy=True,
            can_rollback=True,
            supports_state=False,  # No persistent state
            supports_modules=False,
            supports_workspaces=False,
        )

    async def is_available(self) -> bool:
        """Check if MCP server is available for the provider."""
        if self._mcp_available is not None:
            return self._mcp_available

        # Check if provider is valid and has MCP support
        if self._provider is None or self._provider not in MCP_SERVERS:
            self._mcp_available = False
            return False

        # Check if MCP manager has the server configured
        if hasattr(self._ctx, "mcp_manager") and self._ctx.mcp_manager:
            server_name = f"{self._provider.value}-mcp"
            self._mcp_available = self._ctx.mcp_manager.has_server(server_name)
        else:
            self._mcp_available = False

        logger.debug(f"MCP availability for {self._provider.value}: {self._mcp_available}")
        return self._mcp_available

    async def initialize(self) -> BackendResult:
        """Initialize MCP backend (check availability)."""
        result = BackendResult(operation="init")

        if not await self.is_available():
            result.success = False
            result.errors.append(
                f"MCP server not available for {self._provider.value}. "
                f"Consider installing {MCP_SERVERS.get(self._provider, {}).get('package', 'MCP package')}"
            )
        else:
            result.success = True
            result.stdout = f"MCP backend ready for {self._provider.value}"

        result.finalize()
        return result

    async def plan(
        self,
        specs: list[InstanceSpec],
        provider: ProviderType,
    ) -> BackendResult:
        """
        Generate plan for MCP operations.

        MCP doesn't have native planning, so we simulate it.
        """
        result = BackendResult(operation="plan")

        if not await self.is_available():
            raise BackendNotAvailableError(
                f"MCP not available for {provider.value}",
                backend=BackendType.MCP,
                operation="plan",
            )

        # Store specs for apply
        self._planned_specs = specs

        # Simulate plan output
        result.success = True
        result.output_data = {
            "to_create": len(specs),
            "to_update": 0,
            "to_delete": 0,
            "resources": [f"{provider.value}_instance.{s.name}" for s in specs],
        }
        result.stdout = f"Plan: {len(specs)} instance(s) to create via MCP"

        for spec in specs:
            result.stdout += f"\n  + {provider.value}_instance.{spec.name}"

        result.finalize()
        return result

    async def apply(self) -> BackendResult:
        """Apply planned changes via MCP."""
        result = BackendResult(operation="apply")

        if not self._planned_specs:
            result.success = False
            result.errors.append("No plan to apply. Run plan first.")
            result.finalize()
            return result

        try:
            for spec in self._planned_specs:
                instance_result = await self._create_instance_via_mcp(spec)
                if instance_result:
                    result.resources_created.append(f"{self._provider.value}_instance.{spec.name}")
                    self._created_resources.append(instance_result)
                else:
                    result.errors.append(f"Failed to create {spec.name}")

            result.success = len(result.errors) == 0
            result.output_data = {
                "instances": self._created_resources,
            }

            # Store rollback data
            result.rollback_data = {
                "created_resources": self._created_resources,
                "provider": self._provider.value,
            }

        except Exception as e:
            result.success = False
            result.errors.append(str(e))

        result.finalize()
        return result

    async def destroy(self, resource_ids: list[str] | None = None) -> BackendResult:
        """Destroy resources via MCP."""
        result = BackendResult(operation="destroy")

        try:
            # Use provided IDs or created resources
            if resource_ids is not None:
                to_destroy = resource_ids
            else:
                to_destroy = [
                    str(r.get("instance_id"))
                    for r in self._created_resources
                    if r.get("instance_id") is not None
                ]

            for resource_id in to_destroy:
                success = await self._terminate_instance_via_mcp(resource_id)
                if success:
                    result.resources_deleted.append(resource_id)
                else:
                    result.errors.append(f"Failed to destroy {resource_id}")

            result.success = len(result.errors) == 0

        except Exception as e:
            result.success = False
            result.errors.append(str(e))

        result.finalize()
        return result

    async def rollback(self, rollback_data: dict[str, Any]) -> BackendResult:
        """Rollback by destroying created resources."""
        resource_ids = [
            r.get("instance_id")
            for r in rollback_data.get("created_resources", [])
            if r.get("instance_id")
        ]
        return await self.destroy(resource_ids)

    async def _create_instance_via_mcp(self, spec: InstanceSpec) -> dict[str, Any] | None:
        """Create instance using MCP tool call."""
        if not hasattr(self._ctx, "mcp_manager") or not self._ctx.mcp_manager:
            logger.warning("MCP manager not available")
            return None

        server_config = MCP_SERVERS.get(self._provider, {})
        tool_name = server_config.get("tools", {}).get("create_instance")

        if not tool_name:
            logger.warning(f"No create tool configured for {self._provider.value}")
            return None

        # Build tool arguments based on provider
        tool_args = self._build_create_args(spec)

        try:
            # Call MCP tool
            server_name = f"{self._provider.value}-mcp"
            response = await self._ctx.mcp_manager.call_tool(server_name, tool_name, tool_args)

            if response and response.get("success"):
                return {
                    "instance_id": response.get("instance_id") or response.get("id"),
                    "name": spec.name,
                    "status": "pending",
                    "raw_response": response,
                }

        except Exception as e:
            logger.error(f"MCP create instance failed: {e}")

        return None

    async def _terminate_instance_via_mcp(self, instance_id: str) -> bool:
        """Terminate instance using MCP tool call."""
        if not hasattr(self._ctx, "mcp_manager") or not self._ctx.mcp_manager:
            return False

        server_config = MCP_SERVERS.get(self._provider, {})
        tool_name = server_config.get("tools", {}).get("terminate_instance") or server_config.get(
            "tools", {}
        ).get("delete_instance")

        if not tool_name:
            return False

        try:
            server_name = f"{self._provider.value}-mcp"
            # Build arguments based on provider API
            args: dict[str, Any] = (
                {"instance_ids": [instance_id]}
                if self._provider == ProviderType.AWS
                else {"instance_id": instance_id}
            )
            response = await self._ctx.mcp_manager.call_tool(
                server_name,
                tool_name,
                args,
            )
            return bool(response and response.get("success"))

        except Exception as e:
            logger.error(f"MCP terminate instance failed: {e}")
            return False

    def _build_create_args(self, spec: InstanceSpec) -> dict[str, Any]:
        """Build MCP tool arguments for instance creation."""
        config = spec.to_provider_config(self._provider)

        if self._provider == ProviderType.AWS:
            return {
                "ImageId": config.get("ami"),
                "InstanceType": config.get("instance_type"),
                "MinCount": 1,
                "MaxCount": 1,
                "SubnetId": config.get("subnet_id"),
                "SecurityGroupIds": config.get("vpc_security_group_ids"),
                "KeyName": config.get("key_name"),
                "TagSpecifications": [
                    {
                        "ResourceType": "instance",
                        "Tags": [{"Key": "Name", "Value": spec.name}]
                        + [{"Key": k, "Value": v} for k, v in (spec.tags or {}).items()],
                    }
                ],
            }

        elif self._provider == ProviderType.GCP:
            return {
                "name": spec.name,
                "machineType": config.get("machine_type"),
                "sourceImage": config.get("source_image"),
                "zone": config.get("zone"),
                "diskSizeGb": config.get("boot_disk_size_gb"),
            }

        elif self._provider == ProviderType.AZURE:
            return {
                "name": spec.name,
                "vmSize": config.get("vm_size"),
                "imageReference": config.get("source_image_reference"),
                "osDiskSizeGB": config.get("os_disk_size_gb"),
            }

        return config
