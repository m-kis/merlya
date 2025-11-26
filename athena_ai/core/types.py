"""
Core Types and Enums for Athena.

Centralized type definitions to follow DRY principle.
All modules should import from here instead of defining their own.
"""

from enum import Enum


class StepStatus(Enum):
    """
    Status of a step in any execution context.

    Unified enum covering:
    - Chain of Thought (CoT) reasoning steps
    - Plan execution steps
    - Orchestration coordination steps

    Usage:
        from athena_ai.core import StepStatus

        step.status = StepStatus.RUNNING
    """
    # Common states
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"

    # CoT-specific states
    THINKING = "thinking"
    EXECUTING = "executing"

    # Rollback state
    ROLLED_BACK = "rolled_back"


class RequestComplexity(Enum):
    """
    Request complexity levels.

    Unified enum for classifying request complexity across:
    - Request processing
    - Request classification
    - Execution strategy selection

    Usage:
        from athena_ai.core import RequestComplexity

        if complexity == RequestComplexity.COMPLEX:
            use_cot = True
    """
    SIMPLE = "simple"      # Single-step, direct answer
    MODERATE = "moderate"  # Few steps, straightforward
    COMPLEX = "complex"    # Multiple steps, requires planning
