"""
Configuration for on-demand scanning.
"""
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class ScanConfig:
    """Configuration for on-demand scanning."""

    # Parallelism
    max_workers: int = 10
    batch_size: int = 5

    # Rate limiting
    requests_per_second: float = 5.0
    burst_size: int = 10

    # Retry
    max_retries: int = 3
    retry_base_delay: float = 1.0  # seconds
    retry_max_delay: float = 30.0  # seconds

    # Timeouts
    connect_timeout: float = 10.0  # seconds
    command_timeout: float = 60.0  # seconds

    # SSH host key policy: "reject", "warning", or "auto_add"
    # "auto_add" should only be used in non-production/testing environments
    # Can be overridden by ATHENA_SSH_AUTO_ADD_HOSTS=1 env var
    ssh_host_key_policy: str = "warning"

    # Cache TTL (seconds)
    cache_ttl: Dict[str, int] = field(default_factory=lambda: {
        "basic": 300,       # 5 min - hostname, IP, connectivity
        "system": 1800,     # 30 min - OS, CPU, memory
        "services": 900,    # 15 min - running services
        "packages": 3600,   # 1 hour - installed packages
        "processes": 60,    # 1 min - process list
        "full": 600,        # 10 min - full scan
    })
