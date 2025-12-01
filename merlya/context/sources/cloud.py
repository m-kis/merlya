from typing import List

from merlya.context.sources.base import BaseSource, Host, InventorySource
from merlya.utils.logger import logger


class AWSSource(BaseSource):
    """Source for AWS EC2 instances."""

    def load(self) -> List[Host]:
        hosts = []
        try:
            import boto3

            ec2 = boto3.client('ec2')
            response = ec2.describe_instances(
                Filters=[{'Name': 'instance-state-name', 'Values': ['running']}]
            )

            for reservation in response['Reservations']:
                for instance in reservation['Instances']:
                    # Get Name tag
                    name = None
                    for tag in instance.get('Tags', []):
                        if tag['Key'] == 'Name':
                            name = tag['Value']
                            break

                    if not name:
                        name = instance['InstanceId']

                    # Get environment from tags
                    env = None
                    for tag in instance.get('Tags', []):
                        if tag['Key'].lower() in ['environment', 'env']:
                            env = tag['Value']
                            break

                    hosts.append(Host(
                        hostname=name,
                        ip_address=instance.get('PrivateIpAddress'),
                        source=InventorySource.CLOUD_AWS,
                        environment=env,
                        metadata={
                            'instance_id': instance['InstanceId'],
                            'instance_type': instance['InstanceType'],
                            'availability_zone': instance['Placement']['AvailabilityZone'],
                        }
                    ))

            logger.info(f"Loaded {len(hosts)} hosts from AWS EC2")
            return hosts

        except ImportError:
            logger.debug("boto3 not installed, skipping AWS")
            return []
        except Exception as e:
            logger.warning(f"Failed to load AWS hosts: {e}")
            return []


class GCPSource(BaseSource):
    """Source for GCP Compute Engine instances."""

    def load(self) -> List[Host]:
        hosts = []
        try:
            from google.cloud import compute_v1

            client = compute_v1.InstancesClient()
            project = self.config.get("gcp_project")

            if not project:
                logger.debug("GCP project not configured")
                return []

            # List all zones and instances
            for zone in compute_v1.ZonesClient().list(project=project):
                for instance in client.list(project=project, zone=zone.name):
                    if instance.status != "RUNNING":
                        continue

                    ip = None
                    for interface in instance.network_interfaces:
                        if interface.network_i_p:
                            ip = interface.network_i_p
                            break

                    hosts.append(Host(
                        hostname=instance.name,
                        ip_address=ip,
                        source=InventorySource.CLOUD_GCP,
                        metadata={
                            'zone': zone.name,
                            'machine_type': instance.machine_type,
                        }
                    ))

            logger.info(f"Loaded {len(hosts)} hosts from GCP")
            return hosts

        except ImportError:
            logger.debug("google-cloud-compute not installed, skipping GCP")
            return []
        except Exception as e:
            logger.warning(f"Failed to load GCP hosts: {e}")
            return []
