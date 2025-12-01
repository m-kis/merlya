from typing import Any, Dict

import boto3

from merlya.utils.logger import logger


class AWSExecutor:
    def __init__(self, region: str = "us-east-1"):
        self.region = region
        # In a real app, we'd handle session/credentials more robustly
        self.ec2 = boto3.client('ec2', region_name=region)

    def list_instances(self) -> Dict[str, Any]:
        """List EC2 instances."""
        logger.info(f"Listing EC2 instances in {self.region}")
        try:
            response = self.ec2.describe_instances()
            instances = []
            for reservation in response.get('Reservations', []):
                for instance in reservation.get('Instances', []):
                    instances.append({
                        "id": instance.get('InstanceId'),
                        "type": instance.get('InstanceType'),
                        "state": instance.get('State', {}).get('Name'),
                        "public_ip": instance.get('PublicIpAddress'),
                        "tags": instance.get('Tags', [])
                    })
            return {"success": True, "instances": instances}
        except Exception as e:
            logger.error(f"Failed to list EC2 instances: {e}")
            return {"success": False, "error": str(e)}

    def start_instance(self, instance_id: str) -> Dict[str, Any]:
        """Start an EC2 instance."""
        logger.info(f"Starting instance {instance_id}")
        try:
            self.ec2.start_instances(InstanceIds=[instance_id])
            return {"success": True, "message": f"Instance {instance_id} starting"}
        except Exception as e:
            logger.error(f"Failed to start instance {instance_id}: {e}")
            return {"success": False, "error": str(e)}

    def stop_instance(self, instance_id: str) -> Dict[str, Any]:
        """Stop an EC2 instance."""
        logger.info(f"Stopping instance {instance_id}")
        try:
            self.ec2.stop_instances(InstanceIds=[instance_id])
            return {"success": True, "message": f"Instance {instance_id} stopping"}
        except Exception as e:
            logger.error(f"Failed to stop instance {instance_id}: {e}")
            return {"success": False, "error": str(e)}
