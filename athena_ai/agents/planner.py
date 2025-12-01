"""
Unified Planner: Creates execution plans using Pattern or LLM strategies.

Consolidates PlannerAgent and AdaptivePlanGenerator into a single
configurable planner following DRY and Strategy pattern.
"""
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from athena_ai.utils.logger import logger

# =============================================================================
# Data Types
# =============================================================================

@dataclass
class PlanStep:
    """A single step in an execution plan."""
    id: int
    description: str
    dependencies: list[int] = field(default_factory=list)
    parallelizable: bool = False
    estimated_tokens: int = 1000

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "dependencies": self.dependencies,
            "parallelizable": self.parallelizable,
            "estimated_tokens": self.estimated_tokens,
        }


@dataclass
class Plan:
    """Complete execution plan."""
    title: str
    steps: list[PlanStep]
    task_type: str = "generic"
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def total_estimated_tokens(self) -> int:
        return sum(step.estimated_tokens for step in self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "steps": [s.to_dict() for s in self.steps],
            "task_type": self.task_type,
            "total_estimated_tokens": self.total_estimated_tokens,
        }


class TaskType(Enum):
    """Types of infrastructure tasks."""
    SERVICE_ANALYSIS = "service_analysis"
    TROUBLESHOOTING = "troubleshooting"
    MONITORING = "monitoring"
    DEPLOYMENT = "deployment"
    GENERIC = "generic"


# =============================================================================
# Planning Strategy Interface (Strategy Pattern)
# =============================================================================

class PlanningStrategy(ABC):
    """Abstract base for planning strategies."""

    @abstractmethod
    def create_plan(self, request: str, context: dict[str, Any] | None = None) -> Plan:
        """Create execution plan from request."""
        pass


# =============================================================================
# Pattern-Based Strategy (No LLM required)
# =============================================================================

class PatternStrategy(PlanningStrategy):
    """
    Pattern-based planning using keyword detection.

    Fast, works offline, good for common task types.
    """

    # Common service names for detection
    SERVICES = [
        "nginx", "apache", "httpd", "mysql", "mariadb", "postgres", "postgresql",
        "mongodb", "redis", "memcached", "elasticsearch", "rabbitmq", "kafka",
        "docker", "kubernetes", "k8s", "tomcat", "jenkins", "gitlab"
    ]

    def create_plan(self, request: str, context: dict[str, Any] | None = None) -> Plan:
        """Create plan using pattern matching."""
        task_type = self._detect_task_type(request)
        service = self._extract_service(request)
        host = self._extract_host(request)

        logger.debug(f"Pattern planning: {task_type.value} for {service} on {host}")

        match task_type:
            case TaskType.SERVICE_ANALYSIS:
                steps = self._plan_service_analysis(service, host)
            case TaskType.TROUBLESHOOTING:
                steps = self._plan_troubleshooting(service, host)
            case TaskType.MONITORING:
                steps = self._plan_monitoring()
            case TaskType.DEPLOYMENT:
                steps = self._plan_deployment()
            case _:
                steps = self._plan_generic(request)

        return Plan(
            title=f"{task_type.value.replace('_', ' ').title()}: {request[:50]}",
            steps=steps,
            task_type=task_type.value,
            context={"service": service, "host": host},
        )

    def _detect_task_type(self, request: str) -> TaskType:
        """Detect task type from keywords."""
        r = request.lower()

        if any(k in r for k in ["analyze", "analysis", "full analysis", "check service", "inspect"]):
            return TaskType.SERVICE_ANALYSIS
        if any(k in r for k in ["why", "bug", "not working", "error", "issue", "problem", "debug"]):
            return TaskType.TROUBLESHOOTING
        if any(k in r for k in ["monitor", "watch", "cpu", "memory", "disk", "metrics", "status"]):
            return TaskType.MONITORING
        if any(k in r for k in ["deploy", "install", "configure", "setup", "provision"]):
            return TaskType.DEPLOYMENT
        return TaskType.GENERIC

    def _extract_service(self, request: str) -> str:
        """Extract service name from request."""
        r = request.lower()
        for service in self.SERVICES:
            if service in r:
                return service
        return "service"

    def _extract_host(self, request: str) -> str:
        """Extract hostname from request."""
        for prep in ["on ", "from ", "at "]:
            if prep in request.lower():
                parts = request.lower().split(prep)
                if len(parts) > 1:
                    host = parts[1].split()[0].strip(",.;:!?")
                    if host:
                        return host
        return "host"

    def _plan_service_analysis(self, service: str, host: str) -> list[PlanStep]:
        """Plan for comprehensive service analysis."""
        return [
            PlanStep(1, f"Verify host '{host}' exists and test SSH", [], False, 500),
            PlanStep(2, f"Identify {service} service and get status", [1], False, 800),
            PlanStep(3, f"Collect {service} configuration", [2], True, 1200),
            PlanStep(4, f"Analyze {service} logs", [2], True, 1500),
            PlanStep(5, f"Check {service} performance metrics", [2], True, 1000),
            PlanStep(6, "Analyze disk usage", [2], True, 800),
            PlanStep(7, "Check system resources (CPU, RAM)", [2], True, 600),
            PlanStep(8, f"Verify {service} backup status", [2], True, 600),
            PlanStep(9, "Synthesize findings and generate report", [3, 4, 5, 6, 7, 8], False, 2000),
        ]

    def _plan_troubleshooting(self, service: str, host: str) -> list[PlanStep]:
        """Plan for troubleshooting issues."""
        return [
            PlanStep(1, f"Check if host '{host}' is accessible", [], False, 400),
            PlanStep(2, f"Check {service} service status", [1], False, 500),
            PlanStep(3, f"Analyze {service} error logs", [2], True, 1500),
            PlanStep(4, f"Check {service} configuration validity", [2], True, 800),
            PlanStep(5, "Check system resources (disk, memory)", [2], True, 600),
            PlanStep(6, "Check network connectivity", [2], True, 700),
            PlanStep(7, "Identify root cause and propose solutions", [3, 4, 5, 6], False, 1500),
        ]

    def _plan_monitoring(self) -> list[PlanStep]:
        """Plan for monitoring tasks."""
        return [
            PlanStep(1, "Load inventory and identify target hosts", [], False, 600),
            PlanStep(2, "Collect metrics from all hosts", [1], True, 1500),
            PlanStep(3, "Filter and sort results by criteria", [2], False, 800),
            PlanStep(4, "Present findings in organized format", [3], False, 600),
        ]

    def _plan_deployment(self) -> list[PlanStep]:
        """Plan for deployment tasks."""
        return [
            PlanStep(1, "Validate deployment prerequisites", [], False, 600),
            PlanStep(2, "Backup existing configurations", [1], True, 800),
            PlanStep(3, "Deploy to staging environment first", [2], False, 1000),
            PlanStep(4, "Verify staging deployment", [3], False, 800),
            PlanStep(5, "Request confirmation for production", [4], False, 400),
            PlanStep(6, "Deploy to production hosts", [5], True, 1500),
            PlanStep(7, "Verify production deployment", [6], False, 1000),
        ]

    def _plan_generic(self, request: str) -> list[PlanStep]:
        """Fallback plan for generic tasks."""
        return [
            PlanStep(1, "Gather necessary context and information", [], False, 800),
            PlanStep(2, f"Execute: {request[:60]}", [1], False, 1500),
            PlanStep(3, "Analyze results and provide response", [2], False, 1000),
        ]


# =============================================================================
# LLM-Based Strategy
# =============================================================================

class LLMStrategy(PlanningStrategy):
    """
    LLM-based planning for complex/unusual tasks.

    Uses LLM to dynamically generate appropriate plans.
    Falls back to pattern strategy on failure.
    """

    def __init__(self, llm_router, max_steps: int = 10):
        """
        Initialize LLM strategy.

        Args:
            llm_router: LiteLLM router for plan generation
            max_steps: Maximum steps in generated plan
        """
        self.llm = llm_router
        self.max_steps = max_steps
        self._fallback = PatternStrategy()

    def create_plan(self, request: str, context: dict[str, Any] | None = None) -> Plan:
        """Create plan using LLM reasoning."""
        try:
            prompt = self._build_prompt(request, context)
            response = self._call_llm(prompt)
            steps = self._parse_response(response)
            steps = self._validate_steps(steps)

            return Plan(
                title=f"Plan: {request[:50]}",
                steps=steps,
                task_type="llm_generated",
                context=context or {},
            )
        except Exception as e:
            logger.warning(f"LLM planning failed: {e}, using fallback")
            return self._fallback.create_plan(request, context)

    def _build_prompt(self, request: str, context: dict[str, Any] | None) -> str:
        """Build LLM prompt for plan generation."""
        context_str = f"\nCONTEXT: {context}" if context else ""

        return f"""You are an expert DevOps/SRE planner. Decompose this request into steps.

USER REQUEST: "{request}"
MAX STEPS: {self.max_steps}{context_str}

INSTRUCTIONS:
1. Break down into 3-8 logical steps
2. Each step should be clear, actionable, and verifiable
3. Consider parallelization where possible
4. Follow pattern: VERIFY → GATHER → EXECUTE → ANALYZE → SYNTHESIZE

RESPOND WITH VALID JSON ONLY:
{{
  "steps": [
    {{"id": 1, "description": "...", "dependencies": [], "parallelizable": false, "estimated_tokens": 500}}
  ]
}}"""

    def _call_llm(self, prompt: str) -> str:
        """Call LLM for plan generation."""
        return self.llm.generate(
            prompt=prompt,
            system_prompt="Generate ONLY valid JSON. No markdown, no explanation.",
            task="planning"
        )

    def _parse_response(self, response: str) -> list[PlanStep]:
        """Parse LLM response into steps."""
        # Extract JSON from possible markdown
        json_str = response
        if "```json" in response:
            start = response.find("```json") + 7
            end = response.find("```", start)
            json_str = response[start:end].strip()
        elif "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            json_str = response[start:end].strip()

        data = json.loads(json_str)
        steps_data = data.get("steps", data if isinstance(data, list) else [])

        return [
            PlanStep(
                id=s.get("id", i + 1),
                description=s.get("description", f"Step {i + 1}"),
                dependencies=s.get("dependencies", []),
                parallelizable=s.get("parallelizable", False),
                estimated_tokens=s.get("estimated_tokens", 1000),
            )
            for i, s in enumerate(steps_data)
        ]

    def _validate_steps(self, steps: list[PlanStep]) -> list[PlanStep]:
        """Validate and fix step list."""
        # Limit to max_steps
        steps = steps[:self.max_steps]

        # Fix IDs and dependencies
        for i, step in enumerate(steps):
            step.id = i + 1
            step.dependencies = [d for d in step.dependencies if d < step.id]

        return steps


# =============================================================================
# Unified Planner (Facade)
# =============================================================================

class PlannerMode(Enum):
    """Planner operating modes."""
    PATTERN = "pattern"  # Fast, offline, pattern-based
    LLM = "llm"          # Intelligent, requires LLM
    AUTO = "auto"        # Pattern for simple, LLM for complex


class Planner:
    """
    Unified Planner with configurable strategies.

    Examples:
        # Pattern-based (fast, offline)
        planner = Planner(mode=PlannerMode.PATTERN)

        # LLM-based (intelligent)
        planner = Planner(mode=PlannerMode.LLM, llm_router=router)

        # Auto-select based on complexity
        planner = Planner(mode=PlannerMode.AUTO, llm_router=router)
    """

    # Keywords that suggest complex tasks needing LLM
    COMPLEX_KEYWORDS = [
        "complex", "multiple", "all", "across", "migrate", "refactor",
        "optimize", "automate", "integrate", "custom"
    ]

    def __init__(
        self,
        mode: PlannerMode = PlannerMode.PATTERN,
        llm_router=None,
    ):
        self.mode = mode
        self._pattern_strategy = PatternStrategy()
        self._llm_strategy = LLMStrategy(llm_router) if llm_router else None

    def create_plan(self, request: str, context: dict[str, Any] | None = None) -> Plan:
        """
        Create execution plan for request.

        Args:
            request: User request
            context: Optional context dict

        Returns:
            Execution plan
        """
        strategy = self._select_strategy(request)
        logger.info(f"Creating plan with {strategy.__class__.__name__}")
        return strategy.create_plan(request, context)

    def _select_strategy(self, request: str) -> PlanningStrategy:
        """Select appropriate strategy based on mode and request."""
        match self.mode:
            case PlannerMode.PATTERN:
                return self._pattern_strategy
            case PlannerMode.LLM:
                if self._llm_strategy:
                    return self._llm_strategy
                logger.warning("LLM not available, falling back to pattern")
                return self._pattern_strategy
            case PlannerMode.AUTO:
                if self._is_complex(request) and self._llm_strategy:
                    return self._llm_strategy
                return self._pattern_strategy

    def _is_complex(self, request: str) -> bool:
        """Detect if request is complex enough to need LLM."""
        r = request.lower()
        return any(k in r for k in self.COMPLEX_KEYWORDS) or len(request) > 200


# =============================================================================
# Backward Compatibility Aliases
# =============================================================================

# Alias for old PlannerAgent
class PlannerAgent(Planner):
    """Backward compatibility alias for PlannerAgent."""

    def __init__(self, llm_client=None):
        super().__init__(
            mode=PlannerMode.PATTERN if not llm_client else PlannerMode.AUTO,
            llm_router=llm_client,
        )

    def create_plan(  # type: ignore[override]
        self, request: str, context_summary: str = ""
    ) -> list[dict[str, Any]]:
        """Create plan (returns list of dicts for compatibility)."""
        plan = super().create_plan(request, {"summary": context_summary})
        return [step.to_dict() for step in plan.steps]


# Alias for old AdaptivePlanGenerator
class AdaptivePlanGenerator(Planner):
    """Backward compatibility alias for AdaptivePlanGenerator."""

    def __init__(self, llm_router):
        super().__init__(mode=PlannerMode.LLM, llm_router=llm_router)

    def generate_plan(
        self,
        request: str,
        complexity=None,
        max_steps: int = 10,
        context_summary: str = ""
    ) -> list[dict[str, Any]]:
        """Generate plan (returns list of dicts for compatibility)."""
        plan = super().create_plan(request, {"summary": context_summary})
        return [step.to_dict() for step in plan.steps]


# Alias for SimplePlanner
class SimplePlanner:
    """Backward compatibility: simple pattern-based planner."""

    def __init__(self):
        self._planner = Planner(mode=PlannerMode.PATTERN)

    def create_simple_plan(self, request: str) -> list[dict[str, Any]]:
        plan = self._planner.create_plan(request)
        return [step.to_dict() for step in plan.steps]
