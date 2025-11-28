"""
Host Models.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class HostData:
    """Data container for host bulk imports."""

    hostname: str
    ip_address: Optional[str] = None
    aliases: Optional[List[str]] = None
    environment: Optional[str] = None
    groups: Optional[List[str]] = None
    role: Optional[str] = None
    service: Optional[str] = None
    ssh_port: Optional[int] = None
    metadata: Optional[Dict] = None
