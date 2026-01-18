"""
Merlya Hosts - Host management.

Host resolution, enrichment, and inventory scanning.
"""

from merlya.hosts.resolver import HostNotFoundError, HostResolver, ResolvedHost
from merlya.hosts.target_resolver import (
    HostTargetResolver,
    ResolvedTarget,
    TargetType,
    is_local_target,
)

__all__ = [
    "HostNotFoundError",
    "HostResolver",
    "HostTargetResolver",
    "ResolvedHost",
    "ResolvedTarget",
    "TargetType",
    "is_local_target",
]
