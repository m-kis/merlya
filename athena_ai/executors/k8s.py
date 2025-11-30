import os
from typing import Any, Dict, Optional

from kubernetes import client, config

from athena_ai.utils.logger import logger


class K8sExecutor:
    def __init__(self, kubeconfig: Optional[str] = None):
        try:
            if kubeconfig and os.path.exists(kubeconfig):
                config.load_kube_config(config_file=kubeconfig)
            else:
                config.load_kube_config() # Default location
            self.v1 = client.CoreV1Api()
        except Exception as e:
            logger.warning(f"Failed to load kubeconfig: {e}")
            self.v1 = None

    def list_pods(self, namespace: str = "default") -> Dict[str, Any]:
        """List pods in a namespace."""
        if not self.v1:
            return {"success": False, "error": "Kubeconfig not loaded"}

        logger.info(f"Listing pods in namespace {namespace}")
        try:
            pods = self.v1.list_namespaced_pod(namespace)
            pod_list = []
            for pod in pods.items:
                pod_list.append({
                    "name": pod.metadata.name,
                    "status": pod.status.phase,
                    "ip": pod.status.pod_ip,
                    "node": pod.spec.node_name
                })
            return {"success": True, "pods": pod_list}
        except Exception as e:
            logger.error(f"Failed to list pods: {e}")
            return {"success": False, "error": str(e)}

    def get_pod_logs(self, name: str, namespace: str = "default") -> Dict[str, Any]:
        """Get logs for a pod."""
        if not self.v1:
            return {"success": False, "error": "Kubeconfig not loaded"}

        logger.info(f"Getting logs for pod {name} in {namespace}")
        try:
            logs = self.v1.read_namespaced_pod_log(name, namespace)
            return {"success": True, "logs": logs}
        except Exception as e:
            logger.error(f"Failed to get pod logs: {e}")
            return {"success": False, "error": str(e)}
