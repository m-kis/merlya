"""
Intelligence Engine - Adaptive learning and optimization.

Like Claude Code, learns from interactions to improve over time.

Responsibilities:
- Learn from execution patterns
- Optimize future requests based on history
- Provide intelligent suggestions
- Adapt to user preferences
"""
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from athena_ai.domains.orchestration.execution_coordinator import ExecutionResult
from athena_ai.domains.orchestration.plan_manager import ExecutionPlan
from athena_ai.domains.orchestration.request_processor import ProcessedRequest, RequestType
from athena_ai.utils.logger import logger


@dataclass
class LearningPattern:
    """
    Learned pattern from execution history.

    Like Claude Code's adaptive learning.
    """
    pattern_type: str  # request_type, common_entity, frequent_action
    pattern_value: str
    frequency: int = 1
    success_rate: float = 1.0
    avg_duration_ms: int = 0
    last_seen: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


class IntelligenceEngine:
    """
    Adaptive intelligence engine.

    Like Claude Code, learns and improves from experience.

    Features:
    - Pattern recognition from execution history
    - Performance optimization suggestions
    - User preference adaptation
    - Predictive prefetching

    Design:
    - SoC: Focused on learning and adaptation
    - DDD: Intelligence domain service
    - KISS: Simple pattern matching with incremental learning
    """

    def __init__(self, env: str = "dev", enable_learning: bool = True):
        """
        Initialize intelligence engine.

        Args:
            env: Environment name
            enable_learning: Enable adaptive learning
        """
        self.env = env
        self.enable_learning = enable_learning

        # Storage
        self.storage_path = Path.home() / ".athena" / env / "intelligence"
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # Learned patterns
        self.patterns: Dict[str, LearningPattern] = {}

        # Execution history (last 100 executions)
        self.execution_history: List[Dict[str, Any]] = []
        self.max_history = 100

        # Load existing knowledge
        self._load_knowledge()

        logger.info(f"IntelligenceEngine initialized (learning={'on' if enable_learning else 'off'})")

    def _load_knowledge(self):
        """Load learned patterns from storage."""
        knowledge_file = self.storage_path / "patterns.json"

        if knowledge_file.exists():
            try:
                with open(knowledge_file, 'r') as f:
                    data = json.load(f)

                self.patterns = {
                    k: LearningPattern(
                        pattern_type=v['pattern_type'],
                        pattern_value=v['pattern_value'],
                        frequency=v['frequency'],
                        success_rate=v['success_rate'],
                        avg_duration_ms=v['avg_duration_ms'],
                        last_seen=datetime.fromisoformat(v['last_seen'])
                    )
                    for k, v in data.get('patterns', {}).items()
                }

                logger.debug(f"Loaded {len(self.patterns)} learned patterns")
            except Exception as e:
                logger.warning(f"Failed to load knowledge: {e}")

    def _save_knowledge(self):
        """Save learned patterns to storage."""
        if not self.enable_learning:
            return

        knowledge_file = self.storage_path / "patterns.json"

        try:
            data = {
                'patterns': {
                    k: {
                        'pattern_type': v.pattern_type,
                        'pattern_value': v.pattern_value,
                        'frequency': v.frequency,
                        'success_rate': v.success_rate,
                        'avg_duration_ms': v.avg_duration_ms,
                        'last_seen': v.last_seen.isoformat(),
                        'metadata': v.metadata
                    }
                    for k, v in self.patterns.items()
                }
            }

            with open(knowledge_file, 'w') as f:
                json.dump(data, f, indent=2)

            logger.debug(f"Saved {len(self.patterns)} patterns")
        except Exception as e:
            logger.error(f"Failed to save knowledge: {e}")

    def learn_from_execution(
        self,
        request: ProcessedRequest,
        plan: ExecutionPlan,
        result: ExecutionResult
    ):
        """
        Learn from execution to improve future performance.

        Like Claude Code, adapts based on outcomes.

        Args:
            request: Original processed request
            plan: Execution plan
            result: Execution result
        """
        if not self.enable_learning:
            return

        # Record execution in history
        self.execution_history.append({
            'timestamp': datetime.now().isoformat(),
            'request_type': request.request_type.value,
            'complexity': request.complexity.value,
            'success': result.overall_status == 'success',
            'duration_ms': result.total_duration_ms,
            'steps': len(plan.steps)
        })

        # Keep only last N executions
        if len(self.execution_history) > self.max_history:
            self.execution_history = self.execution_history[-self.max_history:]

        # Learn patterns
        self._learn_request_type_pattern(request, result)
        self._learn_entity_patterns(request, result)
        self._learn_tool_patterns(plan, result)

        # Save knowledge
        self._save_knowledge()

        logger.debug(f"Learned from execution: {request.intent}")

    def _learn_request_type_pattern(self, request: ProcessedRequest, result: ExecutionResult):
        """Learn from request type patterns."""
        pattern_key = f"request_type:{request.request_type.value}"

        if pattern_key in self.patterns:
            pattern = self.patterns[pattern_key]
            pattern.frequency += 1
            # Update success rate (exponential moving average)
            success = 1.0 if result.overall_status == 'success' else 0.0
            pattern.success_rate = 0.9 * pattern.success_rate + 0.1 * success
            # Update avg duration
            pattern.avg_duration_ms = int(
                0.9 * pattern.avg_duration_ms + 0.1 * result.total_duration_ms
            )
            pattern.last_seen = datetime.now()
        else:
            self.patterns[pattern_key] = LearningPattern(
                pattern_type='request_type',
                pattern_value=request.request_type.value,
                success_rate=1.0 if result.overall_status == 'success' else 0.0,
                avg_duration_ms=result.total_duration_ms
            )

    def _learn_entity_patterns(self, request: ProcessedRequest, result: ExecutionResult):
        """Learn from entity patterns (environments, services, etc.)."""
        for entity_type, entity_value in request.entities.items():
            if isinstance(entity_value, list):
                for value in entity_value:
                    self._record_entity_pattern(entity_type, value, result)
            else:
                self._record_entity_pattern(entity_type, entity_value, result)

    def _record_entity_pattern(self, entity_type: str, entity_value: str, result: ExecutionResult):
        """Record single entity pattern."""
        pattern_key = f"entity:{entity_type}:{entity_value}"

        if pattern_key in self.patterns:
            pattern = self.patterns[pattern_key]
            pattern.frequency += 1
            pattern.last_seen = datetime.now()
        else:
            self.patterns[pattern_key] = LearningPattern(
                pattern_type='entity',
                pattern_value=f"{entity_type}={entity_value}",
                metadata={'entity_type': entity_type}
            )

    def _learn_tool_patterns(self, plan: ExecutionPlan, result: ExecutionResult):
        """Learn from tool usage patterns."""
        for step_result in result.step_results:
            if step_result.status.value == 'completed':
                pattern_key = f"tool:{step_result.step_id}"

                if pattern_key in self.patterns:
                    pattern = self.patterns[pattern_key]
                    pattern.frequency += 1
                    pattern.avg_duration_ms = int(
                        0.9 * pattern.avg_duration_ms + 0.1 * step_result.duration_ms
                    )
                else:
                    self.patterns[pattern_key] = LearningPattern(
                        pattern_type='tool',
                        pattern_value=step_result.step_id,
                        avg_duration_ms=step_result.duration_ms
                    )

    def get_suggestions(self, request: ProcessedRequest) -> List[str]:
        """
        Get intelligent suggestions based on learned patterns.

        Like Claude Code's contextual suggestions.

        Args:
            request: Processed request

        Returns:
            List of suggestions
        """
        suggestions = []

        # Suggest based on frequent patterns
        frequent_entities = self._get_frequent_entities()
        if frequent_entities and not request.entities:
            suggestions.append(
                f"💡 Common environments: {', '.join(frequent_entities[:3])}"
            )

        # Suggest based on request type history
        request_pattern = self.patterns.get(f"request_type:{request.request_type.value}")
        if request_pattern:
            if request_pattern.success_rate < 0.8:
                suggestions.append(
                    f"⚠️  This type of request has {request_pattern.success_rate*100:.0f}% success rate"
                )

            if request_pattern.avg_duration_ms > 10000:
                suggestions.append(
                    f"⏱️  This typically takes {request_pattern.avg_duration_ms/1000:.1f}s"
                )

        return suggestions

    def _get_frequent_entities(self, limit: int = 5) -> List[str]:
        """Get most frequently used entities."""
        entity_patterns = [
            p for p in self.patterns.values()
            if p.pattern_type == 'entity'
        ]

        # Sort by frequency
        entity_patterns.sort(key=lambda p: p.frequency, reverse=True)

        return [p.pattern_value.split('=')[1] for p in entity_patterns[:limit]]

    def predict_context_needed(self, request: ProcessedRequest) -> List[str]:
        """
        Predict what context will be needed.

        Like Claude Code, anticipates needs.

        Args:
            request: Processed request

        Returns:
            Predicted context items
        """
        # Based on request type and learned patterns
        predicted = set(request.context_needed)

        # Add from history
        similar_executions = [
            ex for ex in self.execution_history
            if ex['request_type'] == request.request_type.value
        ]

        if similar_executions:
            # Commonly needed context for this request type
            predicted.add('infrastructure_inventory')

            if request.request_type == RequestType.ACTION:
                predicted.add('permissions')
                predicted.add('current_state')

        return list(predicted)

    def optimize_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        """
        Optimize plan based on learned patterns.

        Like Claude Code, applies learned optimizations.

        Args:
            plan: Original plan

        Returns:
            Optimized plan
        """
        # Use learned average durations for better estimates
        for step in plan.steps:
            tool_pattern = self.patterns.get(f"tool:{step.id}")
            if tool_pattern and tool_pattern.avg_duration_ms > 0:
                step.estimated_duration_ms = tool_pattern.avg_duration_ms

        # Recalculate total
        plan.total_estimated_duration_ms = sum(s.estimated_duration_ms for s in plan.steps)

        return plan

    def get_analytics(self) -> Dict[str, Any]:
        """
        Get analytics on learned patterns.

        Like Claude Code's insights.

        Returns:
            Analytics dictionary
        """
        if not self.execution_history:
            return {'message': 'No execution history yet'}

        total_executions = len(self.execution_history)
        successful = sum(1 for ex in self.execution_history if ex['success'])
        avg_duration = sum(ex['duration_ms'] for ex in self.execution_history) / total_executions

        # Request type distribution
        request_types: defaultdict[str, int] = defaultdict(int)
        for ex in self.execution_history:
            request_types[ex['request_type']] += 1

        return {
            'total_executions': total_executions,
            'success_rate': successful / total_executions if total_executions > 0 else 0,
            'avg_duration_ms': int(avg_duration),
            'request_type_distribution': dict(request_types),
            'learned_patterns': len(self.patterns),
            'most_common_patterns': self._get_top_patterns(5)
        }

    def _get_top_patterns(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get top learned patterns by frequency."""
        patterns = sorted(
            self.patterns.values(),
            key=lambda p: p.frequency,
            reverse=True
        )[:limit]

        return [
            {
                'type': p.pattern_type,
                'value': p.pattern_value,
                'frequency': p.frequency,
                'success_rate': p.success_rate
            }
            for p in patterns
        ]
