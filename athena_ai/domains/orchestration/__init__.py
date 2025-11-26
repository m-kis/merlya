"""
Orchestration Domain - Intelligent request processing.

Following DDD principles, this domain handles:
- Request understanding and classification
- Intelligent routing and strategy selection
- Plan generation and validation
- Execution coordination

Like Claude Code, the orchestrator is intelligent and adaptive.
"""

from athena_ai.domains.orchestration.execution_coordinator import ExecutionCoordinator
from athena_ai.domains.orchestration.intelligence_engine import IntelligenceEngine
from athena_ai.domains.orchestration.plan_manager import PlanManager
from athena_ai.domains.orchestration.request_processor import RequestProcessor

__all__ = [
    'RequestProcessor',
    'PlanManager',
    'ExecutionCoordinator',
    'IntelligenceEngine'
]
