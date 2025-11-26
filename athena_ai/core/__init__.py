"""
Core Module for Athena.

Provides shared types, enums, and base classes used across the application.
Following DRY principle - centralized definitions to avoid duplicates.
"""

from .hooks import HookContext, HookEvent, HookManager, get_hook_manager
from .types import RequestComplexity, StepStatus

__all__ = [
    "StepStatus",
    "RequestComplexity",
    "HookEvent",
    "HookContext",
    "HookManager",
    "get_hook_manager",
]
