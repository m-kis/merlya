"""
Merlya Pipelines Module.

Provides controlled execution pipelines for infrastructure changes.
Each pipeline follows: Plan -> Diff -> Summary -> HITL -> Apply -> Post-check -> Rollback
"""

from merlya.pipelines.ansible import AnsibleMode, AnsiblePipeline
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
from merlya.pipelines.kubernetes import KubernetesOperation, KubernetesPipeline
from merlya.pipelines.terraform import TerraformPipeline

__all__ = [
    "AbstractPipeline",
    "AnsibleMode",
    "AnsiblePipeline",
    "ApplyResult",
    "BashPipeline",
    "DiffResult",
    "KubernetesOperation",
    "KubernetesPipeline",
    "PipelineDeps",
    "PipelineResult",
    "PipelineStage",
    "PlanResult",
    "PostCheckResult",
    "RollbackResult",
    "TerraformPipeline",
]
