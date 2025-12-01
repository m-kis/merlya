"""
CI Client implementations for different access methods.

Supports CLI (gh, glab), MCP servers, and REST APIs.
"""

from merlya.ci.clients.base import BaseCIClient, CIClientError
from merlya.ci.clients.cli_client import CLIClient

__all__ = [
    "BaseCIClient",
    "CIClientError",
    "CLIClient",
]
