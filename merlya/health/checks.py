"""
Merlya Health Checks.

Provides comprehensive health checks for Merlya components.
This module has been refactored into specialized sub-modules for better maintainability.
"""

from __future__ import annotations

# Re-export health check types
from merlya.core.types import CheckStatus, HealthCheck

from .connectivity import check_llm_provider, check_web_search
from .connectivity import ping_claude as _ping_claude
from .connectivity import ping_generic as _ping_generic
from .connectivity import ping_google as _ping_google
from .connectivity import ping_ollama as _ping_ollama
from .connectivity import ping_openai as _ping_openai
from .infrastructure import check_keyring, check_ssh_available
from .mcp_checks import check_mcp_servers
from .service_checks import check_parser_service, check_session_manager
from .startup import run_startup_checks
from .startup_health import StartupHealth

# Re-export all health check functions for backward compatibility
from .system_checks import check_disk_space, check_ram

__all__ = [
    "CheckStatus",
    "HealthCheck",
    "StartupHealth",
    "_ping_claude",
    "_ping_generic",
    "_ping_google",
    "_ping_ollama",
    "_ping_openai",
    "check_disk_space",
    "check_keyring",
    "check_llm_provider",
    "check_mcp_servers",
    "check_parser_service",
    "check_ram",
    "check_session_manager",
    "check_ssh_available",
    "check_web_search",
    "run_startup_checks",
]
