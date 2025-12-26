"""
Merlya Pipelines Module.

Provides controlled execution pipelines for infrastructure changes.
Each pipeline follows: Plan -> Diff -> Summary -> HITL -> Apply -> Post-check -> Rollback
"""

from merlya.pipelines.base import (
    AbstractPipeline,
    ApplyResult,
    DiffResult,
    PipelineDeps,
    PipelineResult,
    PipelineStage,
    PlanResult,
    PostCheckResult,
    RollbackResult,
)
from merlya.pipelines.bash import BashPipeline

__all__ = [
    "AbstractPipeline",
    "ApplyResult",
    "BashPipeline",
    "DiffResult",
    "PipelineDeps",
    "PipelineResult",
    "PipelineStage",
    "PlanResult",
    "PostCheckResult",
    "RollbackResult",
]
