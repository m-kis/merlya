"""
Connectivity logic for Athena.
Determines the best way to connect to a host (Direct vs Jump Host).
"""
import socket
from dataclasses import dataclass
from typing import Optional

from athena_ai.memory.persistent_store import KnowledgeStore
from athena_ai.utils.logger import logger


@dataclass
class ConnectionStrategy:
    method: str  # 'direct' or 'jump'
    jump_host: Optional[str] = None

class ConnectivityPlanner:
    """
    Plans how to connect to a target host.
    """

    def __init__(self, knowledge_store: KnowledgeStore = None):
        self.knowledge_store = knowledge_store or KnowledgeStore()

    def is_port_open(self, host: str, port: int = 22, timeout: int = 2) -> bool:
        """Check if a port is reachable directly."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except:
            return False

    def get_connection_strategy(self, target_host: str, target_ip: str = None) -> ConnectionStrategy:
        """
        Determine how to connect to the target.
        """
        # 1. Try direct connection first (fastest check)
        # If we have an IP, use it. If not, resolve or use hostname.
        check_target = target_ip if target_ip and target_ip != "unknown" else target_host

        if self.is_port_open(check_target):
            logger.debug(f"Direct connection to {target_host} is possible")
            return ConnectionStrategy(method='direct')

        # 2. Check for known routes in KnowledgeStore
        # We need the IP to check CIDR matches
        if not target_ip or target_ip == "unknown":
            # Try to resolve if we don't have IP
            try:
                target_ip = socket.gethostbyname(target_host)
            except:
                pass

        if target_ip:
            gateway = self.knowledge_store.get_route_for_host(target_ip)
            if gateway:
                logger.info(f"Found route to {target_host} ({target_ip}) via {gateway}")
                return ConnectionStrategy(method='jump', jump_host=gateway)

        # 3. Default to direct (let it fail naturally if no route found)
        return ConnectionStrategy(method='direct')
