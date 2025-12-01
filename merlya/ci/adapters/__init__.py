"""
CI Platform Adapters.

Each adapter implements CIPlatformProtocol for a specific CI platform.
Adapters use clients (CLI, MCP, API) to interact with the platform.
"""

from merlya.ci.adapters.base import BaseCIAdapter
from merlya.ci.adapters.github import GitHubCIAdapter

__all__ = [
    "BaseCIAdapter",
    "GitHubCIAdapter",
]
