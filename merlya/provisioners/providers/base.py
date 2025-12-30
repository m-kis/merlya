"""
Merlya Provisioners - Cloud Provider Base.

Abstract interfaces for provider-agnostic infrastructure operations.

v0.9.0: Initial implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


class ProviderType(str, Enum):
    """Supported cloud provider types."""

    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"
    OVH = "ovh"
    DIGITALOCEAN = "digitalocean"
    PROXMOX = "proxmox"
    VMWARE = "vmware"


class InstanceStatus(str, Enum):
    """Instance status values."""

    PENDING = "pending"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    TERMINATED = "terminated"
    UNKNOWN = "unknown"


class InstanceSpec(BaseModel):
    """
    Provider-agnostic instance specification.

    Used to define desired state for VM/instance creation.
    """

    name: str = Field(description="Instance name")
    cpu_cores: int = Field(default=1, ge=1, description="Number of CPU cores")
    memory_gb: int = Field(default=1, ge=1, description="Memory in GB")
    disk_gb: int = Field(default=20, ge=1, description="Root disk size in GB")
    image: str = Field(description="Image ID or name (e.g., ami-xxx, ubuntu-22.04)")
    region: str | None = Field(default=None, description="Region/zone for deployment")
    network: str | None = Field(default=None, description="Network/VPC ID")
    subnet: str | None = Field(default=None, description="Subnet ID")
    security_groups: list[str] = Field(default_factory=list, description="Security group IDs")
    public_ip: bool = Field(default=False, description="Assign public IP")
    ssh_key_name: str | None = Field(default=None, description="SSH key name")
    user_data: str | None = Field(default=None, description="Cloud-init user data")
    tags: dict[str, str] = Field(default_factory=dict, description="Resource tags")
    extra: dict[str, Any] = Field(default_factory=dict, description="Provider-specific options")

    def to_provider_config(self, provider: ProviderType) -> dict[str, Any]:
        """Convert to provider-specific configuration."""
        # Base config that's common across providers
        config: dict[str, Any] = {
            "name": self.name,
            "tags": self.tags,
        }

        if provider == ProviderType.AWS:
            config.update(self._to_aws_config())
        elif provider == ProviderType.GCP:
            config.update(self._to_gcp_config())
        elif provider == ProviderType.AZURE:
            config.update(self._to_azure_config())
        elif provider == ProviderType.PROXMOX:
            config.update(self._to_proxmox_config())
        else:
            # Generic mapping
            config.update(
                {
                    "cpu": self.cpu_cores,
                    "memory": self.memory_gb,
                    "disk": self.disk_gb,
                    "image": self.image,
                }
            )

        # Merge extra provider-specific options
        config.update(self.extra)
        return config

    def _to_aws_config(self) -> dict[str, Any]:
        """Convert to AWS EC2 configuration."""
        # Map cpu/memory to instance type
        instance_type = self._aws_instance_type()
        return {
            "instance_type": instance_type,
            "ami": self.image,
            "vpc_security_group_ids": self.security_groups or None,
            "subnet_id": self.subnet,
            "key_name": self.ssh_key_name,
            "associate_public_ip_address": self.public_ip,
            "user_data": self.user_data,
            "root_block_device": {"volume_size": self.disk_gb},
        }

    def _to_gcp_config(self) -> dict[str, Any]:
        """Convert to GCP Compute Engine configuration."""
        machine_type = self._gcp_machine_type()
        return {
            "machine_type": machine_type,
            "source_image": self.image,
            "zone": self.region,
            "network": self.network,
            "subnetwork": self.subnet,
            "boot_disk_size_gb": self.disk_gb,
        }

    def _to_azure_config(self) -> dict[str, Any]:
        """Convert to Azure VM configuration."""
        vm_size = self._azure_vm_size()
        return {
            "vm_size": vm_size,
            "source_image_reference": self.image,
            "os_disk_size_gb": self.disk_gb,
            "network_interface_ids": [],
        }

    def _to_proxmox_config(self) -> dict[str, Any]:
        """Convert to Proxmox VM configuration."""
        return {
            "cores": self.cpu_cores,
            "memory": self.memory_gb * 1024,  # Proxmox uses MB
            "disk": f"{self.disk_gb}G",
            "clone": self.image,  # Template to clone
            "network_bridge": self.network or "vmbr0",
        }

    def _aws_instance_type(self) -> str:
        """Map cpu/memory to AWS instance type."""
        # Simple mapping - could be more sophisticated
        if self.cpu_cores <= 1 and self.memory_gb <= 1:
            return "t3.micro"
        if self.cpu_cores <= 2 and self.memory_gb <= 4:
            return "t3.medium"
        if self.cpu_cores <= 4 and self.memory_gb <= 8:
            return "t3.large"
        if self.cpu_cores <= 8 and self.memory_gb <= 16:
            return "t3.xlarge"
        return "t3.2xlarge"

    def _gcp_machine_type(self) -> str:
        """Map cpu/memory to GCP machine type."""
        if self.cpu_cores <= 1 and self.memory_gb <= 1:
            return "e2-micro"
        if self.cpu_cores <= 2 and self.memory_gb <= 4:
            return "e2-medium"
        if self.cpu_cores <= 4 and self.memory_gb <= 8:
            return "e2-standard-4"
        return "e2-standard-8"

    def _azure_vm_size(self) -> str:
        """Map cpu/memory to Azure VM size."""
        if self.cpu_cores <= 1 and self.memory_gb <= 1:
            return "Standard_B1s"
        if self.cpu_cores <= 2 and self.memory_gb <= 4:
            return "Standard_B2s"
        if self.cpu_cores <= 4 and self.memory_gb <= 8:
            return "Standard_D4s_v3"
        return "Standard_D8s_v3"


class Instance(BaseModel):
    """
    Provider-agnostic instance representation.

    Represents a running or existing VM/instance.
    """

    id: str = Field(description="Provider instance ID")
    name: str = Field(description="Instance name")
    provider: ProviderType = Field(description="Cloud provider")
    status: InstanceStatus = Field(default=InstanceStatus.UNKNOWN)
    public_ip: str | None = Field(default=None)
    private_ip: str | None = Field(default=None)
    region: str | None = Field(default=None)
    created_at: datetime | None = Field(default=None)
    spec: InstanceSpec | None = Field(default=None, description="Original spec if known")
    provider_metadata: dict[str, Any] = Field(default_factory=dict, description="Raw provider data")
    tags: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_aws(cls, data: dict[str, Any]) -> Instance:
        """Create Instance from AWS EC2 describe-instances response."""
        status_map = {
            "pending": InstanceStatus.PENDING,
            "running": InstanceStatus.RUNNING,
            "stopping": InstanceStatus.STOPPING,
            "stopped": InstanceStatus.STOPPED,
            "terminated": InstanceStatus.TERMINATED,
        }

        tags = {t["Key"]: t["Value"] for t in data.get("Tags", [])}
        name = tags.get("Name", data.get("InstanceId", ""))

        return cls(
            id=data.get("InstanceId", ""),
            name=name,
            provider=ProviderType.AWS,
            status=status_map.get(data.get("State", {}).get("Name", ""), InstanceStatus.UNKNOWN),
            public_ip=data.get("PublicIpAddress"),
            private_ip=data.get("PrivateIpAddress"),
            region=data.get("Placement", {}).get("AvailabilityZone"),
            created_at=data.get("LaunchTime"),
            provider_metadata=data,
            tags=tags,
        )

    @classmethod
    def from_gcp(cls, data: dict[str, Any]) -> Instance:
        """Create Instance from GCP Compute Engine response."""
        status_map = {
            "PROVISIONING": InstanceStatus.PENDING,
            "STAGING": InstanceStatus.PENDING,
            "RUNNING": InstanceStatus.RUNNING,
            "STOPPING": InstanceStatus.STOPPING,
            "TERMINATED": InstanceStatus.STOPPED,
        }

        # Extract IPs from network interfaces
        public_ip = None
        private_ip = None
        for nic in data.get("networkInterfaces", []):
            private_ip = nic.get("networkIP")
            for access in nic.get("accessConfigs", []):
                if access.get("natIP"):
                    public_ip = access["natIP"]
                    break

        return cls(
            id=str(data.get("id", "")),
            name=data.get("name", ""),
            provider=ProviderType.GCP,
            status=status_map.get(data.get("status", ""), InstanceStatus.UNKNOWN),
            public_ip=public_ip,
            private_ip=private_ip,
            region=data.get("zone", "").split("/")[-1] if data.get("zone") else None,
            created_at=data.get("creationTimestamp"),
            provider_metadata=data,
            tags=data.get("labels", {}),
        )


class ProviderCapabilities(BaseModel):
    """Capabilities supported by a cloud provider."""

    # Instance operations
    can_create: bool = True
    can_update: bool = True
    can_delete: bool = True
    can_start_stop: bool = True
    can_resize: bool = True
    # Snapshots require provider-specific APIs; default to False unless implemented.
    can_snapshot: bool = False

    # Networking
    supports_vpc: bool = True
    supports_security_groups: bool = True
    supports_public_ip: bool = True
    supports_private_networking: bool = True

    # Storage
    supports_block_storage: bool = True
    # Object storage (e.g., S3) is not part of the core provider interface.
    supports_object_storage: bool = False

    # Advanced
    supports_auto_scaling: bool = False
    supports_load_balancing: bool = False
    supports_dns: bool = False

    # Backend availability
    has_mcp_support: bool = False
    has_terraform_support: bool = True
    has_sdk_support: bool = False


class AbstractCloudProvider(ABC):
    """
    Abstract base class for cloud provider implementations.

    Provides a unified interface for infrastructure operations
    across different cloud providers.
    """

    def __init__(self, ctx: SharedContext) -> None:
        """
        Initialize the cloud provider.

        Args:
            ctx: Shared context with config, secrets, etc.
        """
        self._ctx = ctx

    @property
    @abstractmethod
    def provider_type(self) -> ProviderType:
        """Return the provider type."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the provider display name."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Return provider capabilities."""
        ...

    @abstractmethod
    async def validate_credentials(self) -> tuple[bool, str | None]:
        """
        Validate that credentials are configured and valid.

        Returns:
            Tuple of (success, error_message).
        """
        ...

    @abstractmethod
    async def list_instances(self, filters: dict[str, Any] | None = None) -> list[Instance]:
        """
        List instances with optional filters.

        Args:
            filters: Provider-specific filters.

        Returns:
            List of Instance objects.
        """
        ...

    @abstractmethod
    async def get_instance(self, instance_id: str) -> Instance | None:
        """
        Get a specific instance by ID.

        Args:
            instance_id: Provider instance ID.

        Returns:
            Instance if found, None otherwise.
        """
        ...

    @abstractmethod
    async def create_instance(self, spec: InstanceSpec) -> Instance:
        """
        Create a new instance.

        Args:
            spec: Instance specification.

        Returns:
            Created Instance.

        Raises:
            ProviderError: If creation fails.
        """
        ...

    @abstractmethod
    async def update_instance(self, instance_id: str, updates: dict[str, Any]) -> Instance:
        """
        Update an existing instance.

        Args:
            instance_id: Provider instance ID.
            updates: Fields to update.

        Returns:
            Updated Instance.
        """
        ...

    @abstractmethod
    async def delete_instance(self, instance_id: str) -> bool:
        """
        Delete/terminate an instance.

        Args:
            instance_id: Provider instance ID.

        Returns:
            True if deleted successfully.
        """
        ...

    @abstractmethod
    async def start_instance(self, instance_id: str) -> Instance:
        """Start a stopped instance."""
        ...

    @abstractmethod
    async def stop_instance(self, instance_id: str) -> Instance:
        """Stop a running instance."""
        ...

    async def reboot_instance(self, instance_id: str) -> Instance:
        """
        Reboot an instance.

        Default implementation does stop then start.
        """
        await self.stop_instance(instance_id)
        return await self.start_instance(instance_id)

    async def wait_for_status(
        self,
        instance_id: str,
        target_status: InstanceStatus,
        timeout_seconds: int = 300,
        poll_interval: int = 5,
    ) -> Instance | None:
        """
        Wait for an instance to reach a target status.

        Args:
            instance_id: Provider instance ID.
            target_status: Status to wait for.
            timeout_seconds: Maximum wait time.
            poll_interval: Seconds between polls.

        Returns:
            Instance if status reached, None if timeout.
        """
        import asyncio

        start = datetime.now(UTC)
        while (datetime.now(UTC) - start).total_seconds() < timeout_seconds:
            instance = await self.get_instance(instance_id)
            if instance and instance.status == target_status:
                return instance
            await asyncio.sleep(poll_interval)
        return None


class ProviderError(Exception):
    """Base exception for provider errors."""

    def __init__(
        self,
        message: str,
        provider: ProviderType | None = None,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.operation = operation
        self.details = details or {}


class CredentialsError(ProviderError):
    """Raised when credentials are missing or invalid."""

    pass


class ResourceNotFoundError(ProviderError):
    """Raised when a resource is not found."""

    pass


class QuotaExceededError(ProviderError):
    """Raised when provider quota is exceeded."""

    pass
