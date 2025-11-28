"""
CI/CD Module for Athena - Agnostic Multi-Platform Support.

This module provides platform-agnostic CI/CD integration for Athena,
supporting GitHub Actions, GitLab CI, Jenkins, CircleCI, and more.

Key Design Principles:
- Agnostic: No hardcoded platform-specific flows
- Adaptive: Dynamically detects and uses available tools (CLI, MCP, API)
- Extensible: Add new platforms via registry pattern (OCP)
- Intelligent: Semantic error analysis via embeddings (reuses triage infrastructure)

Usage:
    from athena_ai.ci import CIPlatformManager, CIPlatformRegistry

    # Auto-detect and get platform
    manager = CIPlatformManager()
    platform = manager.get_platform()

    # List recent runs
    runs = platform.list_runs(limit=5)

    # Analyze failure
    analysis = platform.analyze_failure(run_id)
"""

from athena_ai.ci.adapters.base import BaseCIAdapter
from athena_ai.ci.adapters.github import GitHubCIAdapter
from athena_ai.ci.analysis.error_classifier import CIErrorClassifier
from athena_ai.ci.config import CIConfig
from athena_ai.ci.learning.engine import CILearningEngine
from athena_ai.ci.learning.memory_router import CIMemoryRouter
from athena_ai.ci.manager import CIPlatformManager
from athena_ai.ci.models import (
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
from athena_ai.ci.protocols import (
    CIClientProtocol,
    CIPlatformProtocol,
    CIPlatformType,
    RunStatus,
)
from athena_ai.ci.registry import (
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
