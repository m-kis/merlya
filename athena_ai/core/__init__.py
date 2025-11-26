"""
Core Module for Athena.

Provides shared types, enums, and base classes used across the application.
Following DRY principle - centralized definitions to avoid duplicates.
"""

from .types import StepStatus, RequestComplexity
from .hooks import HookEvent, HookContext, HookManager, get_hook_manager

__all__ = [
    "StepStatus",
    "RequestComplexity",
    "HookEvent",
    "HookContext",
    "HookManager",
    "get_hook_manager",
]
