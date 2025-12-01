"""
CI/CD Module for Merlya - Agnostic Multi-Platform Support.

This module provides platform-agnostic CI/CD integration for Merlya,
supporting GitHub Actions, GitLab CI, Jenkins, CircleCI, and more.

Key Design Principles:
- Agnostic: No hardcoded platform-specific flows
- Adaptive: Dynamically detects and uses available tools (CLI, MCP, API)
- Extensible: Add new platforms via registry pattern (OCP)
- Intelligent: Semantic error analysis via embeddings (reuses triage infrastructure)

Usage:
    from merlya.ci import CIPlatformManager, CIPlatformRegistry

    # Auto-detect and get platform
    manager = CIPlatformManager()
    platform = manager.get_platform()

    # List recent runs
    runs = platform.list_runs(limit=5)

    # Analyze failure
    analysis = platform.analyze_failure(run_id)
"""

from merlya.ci.adapters.base import BaseCIAdapter
from merlya.ci.adapters.github import GitHubCIAdapter
from merlya.ci.analysis.error_classifier import CIErrorClassifier
from merlya.ci.config import CIConfig
from merlya.ci.learning.engine import CILearningEngine
from merlya.ci.learning.memory_router import CIMemoryRouter
from merlya.ci.manager import CIPlatformManager
from merlya.ci.models import (
    CIErrorType,
    DetectedPlatform,
    FailureAnalysis,
    Job,
    PermissionReport,
    Run,
    RunLogs,
    Step,
    Workflow,
)
from merlya.ci.protocols import (
    CIClientProtocol,
    CIPlatformProtocol,
    CIPlatformType,
    RunStatus,
)
from merlya.ci.registry import (
    CIPlatformRegistry,
    get_ci_registry,
    register_builtin_platforms,
)

__all__ = [
    # Protocols
    "CIPlatformProtocol",
    "CIClientProtocol",
    "CIPlatformType",
    "RunStatus",
    # Models
    "Workflow",
    "Run",
    "Job",
    "Step",
    "RunLogs",
    "PermissionReport",
    "FailureAnalysis",
    "DetectedPlatform",
    # Config
    "CIConfig",
    # Registry
    "CIPlatformRegistry",
    "get_ci_registry",
    "register_builtin_platforms",
    # Adapters
    "BaseCIAdapter",
    "GitHubCIAdapter",
    # Manager
    "CIPlatformManager",
    # Analysis & Learning
    "CIErrorType",
    "CIErrorClassifier",
    "CILearningEngine",
    "CIMemoryRouter",
]
