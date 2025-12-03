"""
Configuration for on-demand scanning.
"""
from dataclasses import dataclass, field
from typing import ClassVar, Dict


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

    # Timeouts (reduced for faster scanning)
    connect_timeout: float = 5.0  # seconds (was 10, reduced for faster failure)
    command_timeout: float = 30.0  # seconds (was 60, reduced for faster response)

    # SSH host key policy: "reject", "warning", or "auto_add"
    # "auto_add" should only be used in non-production/testing environments
    # Note: MERLYA_SSH_AUTO_ADD_HOSTS=1 env var overrides this in ssh_scanner._connect_ssh()
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

    # Valid SSH host key policies
    _VALID_SSH_POLICIES: ClassVar[frozenset[str]] = frozenset({"reject", "warning", "auto_add"})

    def __post_init__(self):
        """Validate configuration values."""
        # Validate parallelism
        if self.max_workers <= 0:
            raise ValueError(f"max_workers must be positive, got: {self.max_workers}")
        if self.batch_size <= 0:
            raise ValueError(f"batch_size must be positive, got: {self.batch_size}")

        # Validate rate limiting
        if self.requests_per_second <= 0:
            raise ValueError(f"requests_per_second must be positive, got: {self.requests_per_second}")
        if self.burst_size <= 0:
            raise ValueError(f"burst_size must be positive, got: {self.burst_size}")

        # Validate retry configuration
        if self.max_retries < 0:
            raise ValueError(f"max_retries must be non-negative, got: {self.max_retries}")
        if self.retry_base_delay <= 0:
            raise ValueError(f"retry_base_delay must be positive, got: {self.retry_base_delay}")
        if self.retry_max_delay <= 0:
            raise ValueError(f"retry_max_delay must be positive, got: {self.retry_max_delay}")
        if self.retry_base_delay > self.retry_max_delay:
            raise ValueError(
                f"retry_base_delay ({self.retry_base_delay}) cannot exceed "
                f"retry_max_delay ({self.retry_max_delay})"
            )

        # Validate timeouts
        if self.connect_timeout <= 0:
            raise ValueError(f"connect_timeout must be positive, got: {self.connect_timeout}")
        if self.command_timeout <= 0:
            raise ValueError(f"command_timeout must be positive, got: {self.command_timeout}")

        # Validate SSH policy
        if self.ssh_host_key_policy not in self._VALID_SSH_POLICIES:
            raise ValueError(
                f"ssh_host_key_policy must be one of {set(self._VALID_SSH_POLICIES)}, "
                f"got: {self.ssh_host_key_policy!r}"
            )

        # Validate cache TTL values
        for category, ttl in self.cache_ttl.items():
            if ttl <= 0:
                raise ValueError(f"cache_ttl[{category!r}] must be positive, got: {ttl}")
