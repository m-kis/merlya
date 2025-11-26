"""
Plan Manager - Intelligent plan generation and optimization.

Like Claude Code, generates optimal execution plans adaptively.

Responsibilities:
- Generate execution plans from processed requests
- Validate plan safety and feasibility
- Optimize plans for efficiency
- Handle plan adaptations based on feedback
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from athena_ai.domains.orchestration.request_processor import ProcessedRequest
from athena_ai.utils.logger import logger


class StepType(Enum):
    """Types of execution steps."""
    GATHER_CONTEXT = "gather_context"
    QUERY_DATA = "query_data"
    EXECUTE_COMMAND = "execute_command"
    GENERATE_CODE = "generate_code"
    VALIDATE = "validate"
    ROLLBACK = "rollback"


@dataclass
class ExecutionStep:
    """
    Single step in execution plan.

    Like Claude Code's step-by-step approach.
    """
    id: str
    type: StepType
    description: str
    tool: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)  # Step IDs this depends on
    risk_level: str = "low"  # low, medium, high
    reversible: bool = True
    estimated_duration_ms: int = 1000

    def __repr__(self):
        return f"Step({self.id}: {self.description})"


@dataclass
class ExecutionPlan:
    """
    Complete execution plan.

    Like Claude Code, structured and adaptable.
    """
    request_id: str
    steps: List[ExecutionStep]
    metadata: Dict[str, Any] = field(default_factory=dict)
    total_estimated_duration_ms: int = 0
    max_risk_level: str = "low"
    requires_confirmation: bool = False

    def __repr__(self):
        return f"Plan({len(self.steps)} steps, risk={self.max_risk_level})"


class PlanManager:
    """
    Intelligent plan manager.

    Like Claude Code, generates optimal plans adaptively.

    Design:
    - SoC: Focused on plan management only
    - KISS: Simple step composition with smart ordering
    - DDD: Core domain service
    """

    def __init__(self, llm_router=None):
        """
        Initialize plan manager.

        Args:
            llm_router: LLM router for intelligent plan generation
        """
        self.llm_router = llm_router

    async def generate_plan(
        self,
        processed_request: ProcessedRequest,
        context: Optional[Dict[str, Any]] = None
    ) -> ExecutionPlan:
        """
        Generate execution plan from processed request.

        Like Claude Code, creates intelligent, context-aware plans.

        Args:
            processed_request: Processed user request
            context: Current context

        Returns:
            Execution plan
        """
        logger.info(f"Generating plan for: {processed_request.intent}")

        steps = []

        # Step 1: Gather context (if needed)
        if processed_request.context_needed:
            steps.append(self._create_context_gathering_step(processed_request.context_needed))

        # Step 2: Generate request-specific steps
        request_steps = await self._generate_request_steps(processed_request, context)
        steps.extend(request_steps)

        # Step 3: Add validation step (if needed)
        if processed_request.request_type.value in ['action', 'generation']:
            steps.append(self._create_validation_step())

        # Create plan
        plan = ExecutionPlan(
            request_id=f"req_{id(processed_request)}",
            steps=steps
        )

        # Calculate metadata
        plan.total_estimated_duration_ms = sum(s.estimated_duration_ms for s in steps)
        plan.max_risk_level = self._calculate_max_risk(steps)
        plan.requires_confirmation = plan.max_risk_level in ['medium', 'high']

        logger.info(f"Generated plan: {plan}")
        return plan

    def _create_context_gathering_step(self, context_needed: List[str]) -> ExecutionStep:
        """Create step to gather needed context."""
        return ExecutionStep(
            id="step_context",
            type=StepType.GATHER_CONTEXT,
            description=f"Gather context: {', '.join(context_needed)}",
            tool="get_infrastructure_context",
            params={"scope": context_needed},
            risk_level="low",
            estimated_duration_ms=2000
        )

    async def _generate_request_steps(
        self,
        processed_request: ProcessedRequest,
        context: Optional[Dict[str, Any]]
    ) -> List[ExecutionStep]:
        """
        Generate steps specific to request type.

        Uses heuristics + optional LLM enhancement.
        """
        steps = []

        # Query requests
        if processed_request.request_type.value == "query":
            steps.append(ExecutionStep(
                id="step_query",
                type=StepType.QUERY_DATA,
                description=processed_request.intent,
                tool="query_data",
                params={
                    "query": processed_request.original_query,
                    "entities": processed_request.entities
                },
                risk_level="low",
                estimated_duration_ms=1000
            ))

        # Action requests
        elif processed_request.request_type.value == "action":
            # Determine action command
            action_command = self._extract_action_command(processed_request)

            steps.append(ExecutionStep(
                id="step_action",
                type=StepType.EXECUTE_COMMAND,
                description=f"Execute: {action_command}",
                tool="execute_command",
                params={
                    "command": action_command,
                    "targets": processed_request.entities.get('hosts', [])
                },
                dependencies=["step_context"],  # Needs context first
                risk_level=self._assess_action_risk(action_command),
                reversible=self._is_reversible(action_command),
                estimated_duration_ms=5000
            ))

        # Generation requests
        elif processed_request.request_type.value == "generation":
            generation_type = self._detect_generation_type(processed_request)

            steps.append(ExecutionStep(
                id="step_generate",
                type=StepType.GENERATE_CODE,
                description=f"Generate {generation_type}",
                tool=f"generate_{generation_type}",
                params=processed_request.parameters,
                risk_level="low",  # Generation is low risk
                estimated_duration_ms=3000
            ))

        # Analysis/troubleshooting requests
        elif processed_request.request_type.value in ["analysis", "troubleshooting"]:
            # Multi-step analysis
            steps.extend(self._create_analysis_steps(processed_request))

        return steps

    def _create_validation_step(self) -> ExecutionStep:
        """Create validation step."""
        return ExecutionStep(
            id="step_validate",
            type=StepType.VALIDATE,
            description="Validate execution results",
            tool="validate_results",
            dependencies=["step_action", "step_generate"],  # After main actions
            risk_level="low",
            estimated_duration_ms=1000
        )

    def _extract_action_command(self, processed_request: ProcessedRequest) -> str:
        """Extract action command from request."""
        # Simple extraction - can be enhanced
        return processed_request.intent

    def _detect_generation_type(self, processed_request: ProcessedRequest) -> str:
        """Detect what to generate (terraform, ansible, etc.)."""
        query_lower = processed_request.original_query.lower()

        if 'terraform' in query_lower:
            return 'terraform'
        elif 'ansible' in query_lower:
            return 'ansible'
        elif 'docker' in query_lower:
            return 'dockerfile'
        else:
            return 'code'

    def _create_analysis_steps(self, processed_request: ProcessedRequest) -> List[ExecutionStep]:
        """Create multi-step analysis plan."""
        return [
            ExecutionStep(
                id="step_collect_data",
                type=StepType.GATHER_CONTEXT,
                description="Collect diagnostic data",
                tool="collect_diagnostics",
                params=processed_request.entities,
                risk_level="low",
                estimated_duration_ms=3000
            ),
            ExecutionStep(
                id="step_analyze",
                type=StepType.QUERY_DATA,
                description="Analyze collected data",
                tool="analyze_data",
                dependencies=["step_collect_data"],
                risk_level="low",
                estimated_duration_ms=2000
            )
        ]

    def _assess_action_risk(self, action_command: str) -> str:
        """
        Assess risk level of action.

        Like Claude Code, evaluates potential impact.
        """
        action_lower = action_command.lower()

        # High risk patterns
        high_risk_patterns = ['delete', 'remove', 'drop', 'truncate', 'rm -rf', 'shutdown', 'reboot']
        if any(pattern in action_lower for pattern in high_risk_patterns):
            return 'high'

        # Medium risk patterns
        medium_risk_patterns = ['restart', 'stop', 'kill', 'update', 'modify', 'change']
        if any(pattern in action_lower for pattern in medium_risk_patterns):
            return 'medium'

        # Default to low risk
        return 'low'

    def _is_reversible(self, action_command: str) -> bool:
        """Check if action is reversible."""
        action_lower = action_command.lower()

        # Irreversible actions
        irreversible_patterns = ['delete', 'remove', 'drop', 'truncate', 'rm']
        if any(pattern in action_lower for pattern in irreversible_patterns):
            return False

        # Most actions are reversible
        return True

    def _calculate_max_risk(self, steps: List[ExecutionStep]) -> str:
        """Calculate maximum risk level across all steps."""
        risk_levels = {'low': 0, 'medium': 1, 'high': 2}
        max_risk = 0

        for step in steps:
            risk_value = risk_levels.get(step.risk_level, 0)
            max_risk = max(max_risk, risk_value)

        # Convert back to string
        for level, value in risk_levels.items():
            if value == max_risk:
                return level

        return 'low'

    def validate_plan(self, plan: ExecutionPlan) -> Dict[str, Any]:
        """
        Validate plan safety and feasibility.

        Returns validation result with errors if any.
        """
        errors = []
        warnings = []

        # Check for circular dependencies
        if self._has_circular_dependencies(plan.steps):
            errors.append("Circular dependencies detected in plan")

        # Check for missing dependencies
        step_ids = {step.id for step in plan.steps}
        for step in plan.steps:
            for dep_id in step.dependencies:
                if dep_id not in step_ids:
                    errors.append(f"Step {step.id} depends on missing step {dep_id}")

        # Warn on high risk without confirmation
        if plan.max_risk_level == 'high' and not plan.requires_confirmation:
            warnings.append("High risk plan should require confirmation")

        return {
            'is_valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings
        }

    def _has_circular_dependencies(self, steps: List[ExecutionStep]) -> bool:
        """Check for circular dependencies using DFS."""
        # Build dependency graph
        graph = {step.id: step.dependencies for step in steps}

        def has_cycle(node, visited, rec_stack):
            visited.add(node)
            rec_stack.add(node)

            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    if has_cycle(neighbor, visited, rec_stack):
                        return True
                elif neighbor in rec_stack:
                    return True

            rec_stack.remove(node)
            return False

        visited = set()
        rec_stack = set()

        for step in steps:
            if step.id not in visited:
                if has_cycle(step.id, visited, rec_stack):
                    return True

        return False

    def optimize_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        """
        Optimize plan for efficiency.

        Like Claude Code, finds opportunities for parallelization and shortcuts.
        """
        # Identify steps that can run in parallel
        parallel_opportunities = self._find_parallel_opportunities(plan.steps)

        # Reorder steps for optimal execution
        optimized_steps = self._reorder_steps(plan.steps, parallel_opportunities)

        # Update plan
        plan.steps = optimized_steps
        plan.total_estimated_duration_ms = self._estimate_parallel_duration(optimized_steps)

        logger.debug(f"Optimized plan: {len(parallel_opportunities)} parallel opportunities found")
        return plan

    def _find_parallel_opportunities(self, steps: List[ExecutionStep]) -> List[List[str]]:
        """Find steps that can run in parallel."""
        # Steps with no dependencies can run in parallel
        # Steps with same dependencies can run in parallel
        parallel_groups = []

        # Group by dependency set
        from collections import defaultdict
        dependency_groups = defaultdict(list)

        for step in steps:
            dep_key = tuple(sorted(step.dependencies))
            dependency_groups[dep_key].append(step.id)

        # Groups with multiple steps can run in parallel
        for group in dependency_groups.values():
            if len(group) > 1:
                parallel_groups.append(group)

        return parallel_groups

    def _reorder_steps(
        self,
        steps: List[ExecutionStep],
        parallel_opportunities: List[List[str]]
    ) -> List[ExecutionStep]:
        """Reorder steps for optimal execution."""
        # Topological sort based on dependencies
        # For now, keep original order (can be enhanced)
        return steps

    def _estimate_parallel_duration(self, steps: List[ExecutionStep]) -> int:
        """Estimate duration considering parallel execution."""
        # Simple estimation - can be made more sophisticated
        return sum(step.estimated_duration_ms for step in steps) // 2  # Assume 50% parallelization
