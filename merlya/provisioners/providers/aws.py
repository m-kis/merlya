"""
Merlya Provisioners - AWS Cloud Provider.

AWS EC2 provider implementation with MCP-first approach.

v0.9.0: Initial implementation.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.provisioners.credentials import CredentialResolver
from merlya.provisioners.providers.base import (
    AbstractCloudProvider,
    CredentialsError,
    Instance,
    InstanceSpec,
    InstanceStatus,
    ProviderCapabilities,
    ProviderError,
    ProviderType,
    ResourceNotFoundError,
)

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


class AWSProvider(AbstractCloudProvider):
    """
    AWS EC2 cloud provider.

    Implements instance operations using boto3 SDK.
    MCP integration planned for future versions.

    Note: boto3 is synchronous; AWS API calls are executed via asyncio.to_thread()
    to avoid blocking the event loop.
    """

    def __init__(self, ctx: SharedContext) -> None:
        """Initialize AWS provider."""
        super().__init__(ctx)
        self._client: Any = None
        self._region: str | None = None
        self._credential_resolver = CredentialResolver.get_instance()

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.AWS

    @property
    def name(self) -> str:
        return "Amazon Web Services"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            can_create=True,
            can_update=True,
            can_delete=True,
            can_start_stop=True,
            can_resize=True,
            # TODO(PROV-AWS-001): Add EC2/EBS snapshot support (docs/tickets.md#prov-aws-001).
            can_snapshot=False,
            supports_vpc=True,
            supports_security_groups=True,
            supports_public_ip=True,
            supports_private_networking=True,
            supports_block_storage=True,
            # TODO(PROV-AWS-002): Add S3 object storage support (docs/tickets.md#prov-aws-002).
            supports_object_storage=False,
            # TODO(PROV-AWS-003): Add Auto Scaling Groups support (docs/tickets.md#prov-aws-003).
            supports_auto_scaling=False,
            # TODO(PROV-AWS-004): Add ELB/ALB/NLB support (docs/tickets.md#prov-aws-004).
            supports_load_balancing=False,
            # TODO(PROV-AWS-005): Add Route 53 DNS record management (docs/tickets.md#prov-aws-005).
            supports_dns=False,
            has_mcp_support=True,  # @aws-sdk/mcp available
            has_terraform_support=True,
            has_sdk_support=True,
        )

    async def _get_client(self) -> Any:
        """Get or create boto3 EC2 client."""
        if self._client is not None:
            return self._client

        try:
            import boto3
        except ImportError:
            raise ProviderError(
                "boto3 not installed. Run: pip install boto3",
                provider=ProviderType.AWS,
                operation="init",
            ) from None

        # Get credentials
        creds = self._credential_resolver.resolve("aws")
        if not creds.is_complete:
            raise CredentialsError(
                f"Missing AWS credentials: {creds.missing}",
                provider=ProviderType.AWS,
                operation="init",
            )

        # Get region
        self._region = creds.credentials.get("AWS_DEFAULT_REGION", "us-east-1")

        # Create client with credentials
        self._client = boto3.client(
            "ec2",
            region_name=self._region,
            aws_access_key_id=creds.credentials.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=creds.credentials.get("AWS_SECRET_ACCESS_KEY"),
            aws_session_token=creds.credentials.get("AWS_SESSION_TOKEN"),
        )

        logger.debug(f"AWS EC2 client created for region {self._region}")
        return self._client

    async def _ec2_call(self, method_name: str, /, **kwargs: Any) -> Any:
        """Run a boto3 EC2 client call off the event loop."""
        client = await self._get_client()
        method = getattr(client, method_name)
        return await asyncio.to_thread(method, **kwargs)

    async def validate_credentials(self) -> tuple[bool, str | None]:
        """Validate AWS credentials."""
        try:
            # Try a simple API call
            await self._ec2_call("describe_regions", DryRun=False)
            return True, None
        except CredentialsError as e:
            return False, str(e)
        except Exception as e:
            error_msg = str(e)
            if "AuthFailure" in error_msg or "InvalidClientTokenId" in error_msg:
                return False, "Invalid AWS credentials"
            if "ExpiredToken" in error_msg:
                return False, "AWS session token expired"
            return False, f"AWS validation failed: {error_msg}"

    async def list_instances(self, filters: dict[str, Any] | None = None) -> list[Instance]:
        """List EC2 instances."""
        # Convert filters to AWS format
        aws_filters = []
        if filters:
            supported_keys = {"status", "name"}
            for key, value in filters.items():
                if key == "status":
                    aws_filters.append({"Name": "instance-state-name", "Values": [value]})
                elif key == "name":
                    aws_filters.append({"Name": "tag:Name", "Values": [value]})
                elif key.startswith("tag:"):
                    aws_filters.append({"Name": key, "Values": [value]})
                elif key not in supported_keys:
                    logger.warning(f"Ignoring unsupported filter key: {key}")

        try:
            response = await self._ec2_call(
                "describe_instances", Filters=aws_filters if aws_filters else []
            )
        except Exception as e:
            raise ProviderError(
                f"Failed to list instances: {e}",
                provider=ProviderType.AWS,
                operation="list_instances",
            ) from e

        instances = []
        for reservation in response.get("Reservations", []):
            for instance_data in reservation.get("Instances", []):
                instances.append(Instance.from_aws(instance_data))

        logger.debug(f"Listed {len(instances)} AWS instances")
        return instances

    async def get_instance(self, instance_id: str) -> Instance | None:
        """Get a specific EC2 instance."""
        client = await self._get_client()

        try:
            response = await asyncio.to_thread(client.describe_instances, InstanceIds=[instance_id])
        except client.exceptions.ClientError as e:
            if "InvalidInstanceID" in str(e):
                return None
            raise ProviderError(
                f"Failed to get instance: {e}",
                provider=ProviderType.AWS,
                operation="get_instance",
            ) from e

        for reservation in response.get("Reservations", []):
            for instance_data in reservation.get("Instances", []):
                return Instance.from_aws(instance_data)

        return None

    async def create_instance(self, spec: InstanceSpec) -> Instance:
        """Create a new EC2 instance."""
        # Convert spec to AWS config
        config = spec.to_provider_config(ProviderType.AWS)

        # Build run_instances parameters
        params: dict[str, Any] = {
            "ImageId": config["ami"],
            "InstanceType": config["instance_type"],
            "MinCount": 1,
            "MaxCount": 1,
        }

        if config.get("subnet_id"):
            params["SubnetId"] = config["subnet_id"]

        if config.get("vpc_security_group_ids"):
            params["SecurityGroupIds"] = config["vpc_security_group_ids"]

        if config.get("key_name"):
            params["KeyName"] = config["key_name"]

        if config.get("user_data"):
            params["UserData"] = config["user_data"]

        # Tags
        tags = [{"Key": "Name", "Value": spec.name}]
        tags.extend([{"Key": k, "Value": v} for k, v in spec.tags.items()])
        params["TagSpecifications"] = [{"ResourceType": "instance", "Tags": tags}]

        # Block device for root disk
        if config.get("root_block_device"):
            params["BlockDeviceMappings"] = [
                {
                    "DeviceName": "/dev/xvda",
                    "Ebs": {
                        "VolumeSize": config["root_block_device"]["volume_size"],
                        "DeleteOnTermination": True,
                    },
                }
            ]

        try:
            response = await self._ec2_call("run_instances", **params)
        except Exception as e:
            raise ProviderError(
                f"Failed to create instance: {e}",
                provider=ProviderType.AWS,
                operation="create_instance",
                details={"spec": spec.model_dump()},
            ) from e

        instance_data = response["Instances"][0]
        instance = Instance.from_aws(instance_data)
        instance.spec = spec

        logger.info(f"Created AWS instance: {instance.id}")
        return instance

    async def update_instance(self, instance_id: str, updates: dict[str, Any]) -> Instance:
        """Update an EC2 instance."""
        # EC2 instance updates are limited
        # Most require stop -> modify -> start

        if "instance_type" in updates:
            # Must stop instance first
            current = await self.get_instance(instance_id)
            if current and current.status == InstanceStatus.RUNNING:
                await self.stop_instance(instance_id)
                await self.wait_for_status(instance_id, InstanceStatus.STOPPED)

            try:
                await self._ec2_call(
                    "modify_instance_attribute",
                    InstanceId=instance_id,
                    InstanceType={"Value": updates["instance_type"]},
                )
            except Exception as e:
                raise ProviderError(
                    f"Failed to modify instance type: {e}",
                    provider=ProviderType.AWS,
                    operation="update_instance",
                ) from e

            # Restart if was running
            if current and current.status == InstanceStatus.RUNNING:
                await self.start_instance(instance_id)

        if "tags" in updates:
            tags = [{"Key": k, "Value": v} for k, v in updates["tags"].items()]
            try:
                await self._ec2_call("create_tags", Resources=[instance_id], Tags=tags)
            except Exception as e:
                raise ProviderError(
                    f"Failed to update tags: {e}",
                    provider=ProviderType.AWS,
                    operation="update_instance",
                ) from e

        # Return updated instance
        instance = await self.get_instance(instance_id)
        if not instance:
            raise ResourceNotFoundError(
                f"Instance {instance_id} not found after update",
                provider=ProviderType.AWS,
                operation="update_instance",
            )
        return instance

    async def delete_instance(self, instance_id: str) -> bool:
        """Terminate an EC2 instance."""
        client = await self._get_client()

        try:
            await asyncio.to_thread(client.terminate_instances, InstanceIds=[instance_id])
            logger.info(f"Terminated AWS instance: {instance_id}")
            return True
        except client.exceptions.ClientError as e:
            if "InvalidInstanceID" in str(e):
                logger.warning(f"Instance {instance_id} not found for termination")
                return False
            raise ProviderError(
                f"Failed to terminate instance: {e}",
                provider=ProviderType.AWS,
                operation="delete_instance",
            ) from e

    async def start_instance(self, instance_id: str) -> Instance:
        """Start a stopped EC2 instance."""
        try:
            await self._ec2_call("start_instances", InstanceIds=[instance_id])
            logger.info(f"Started AWS instance: {instance_id}")
        except Exception as e:
            raise ProviderError(
                f"Failed to start instance: {e}",
                provider=ProviderType.AWS,
                operation="start_instance",
            ) from e

        instance = await self.get_instance(instance_id)
        if not instance:
            raise ResourceNotFoundError(
                f"Instance {instance_id} not found",
                provider=ProviderType.AWS,
                operation="start_instance",
            )
        return instance

    async def stop_instance(self, instance_id: str) -> Instance:
        """Stop a running EC2 instance."""
        try:
            await self._ec2_call("stop_instances", InstanceIds=[instance_id])
            logger.info(f"Stopped AWS instance: {instance_id}")
        except Exception as e:
            raise ProviderError(
                f"Failed to stop instance: {e}",
                provider=ProviderType.AWS,
                operation="stop_instance",
            ) from e

        instance = await self.get_instance(instance_id)
        if not instance:
            raise ResourceNotFoundError(
                f"Instance {instance_id} not found",
                provider=ProviderType.AWS,
                operation="stop_instance",
            )
        return instance

    async def list_images(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """
        List available AMIs.

        Useful for finding image IDs for instance creation.
        """
        aws_filters = []
        if filters:
            for key, value in filters.items():
                if key == "name":
                    aws_filters.append({"Name": "name", "Values": [f"*{value}*"]})
                elif key == "owner":
                    pass  # Handled separately
                else:
                    aws_filters.append({"Name": key, "Values": [value]})

        params: dict[str, Any] = {}
        if aws_filters:
            params["Filters"] = aws_filters
        if filters and "owner" in filters:
            params["Owners"] = [filters["owner"]]
        else:
            params["Owners"] = ["amazon", "self"]

        try:
            response = await self._ec2_call("describe_images", **params)
        except Exception as e:
            raise ProviderError(
                f"Failed to list images: {e}",
                provider=ProviderType.AWS,
                operation="list_images",
            ) from e

        images: list[dict[str, Any]] = response.get("Images", [])
        return images

    async def list_regions(self) -> list[str]:
        """List available AWS regions."""
        try:
            response = await self._ec2_call("describe_regions")
        except Exception as e:
            raise ProviderError(
                f"Failed to list regions: {e}",
                provider=ProviderType.AWS,
                operation="list_regions",
            ) from e

        return [r["RegionName"] for r in response.get("Regions", [])]
