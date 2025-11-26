"""
Request Classifier: Automatically analyzes requests and determines execution strategy.

This classifier decides:
- Request complexity (simple/medium/complex)
- Whether to use Chain of Thought
- Whether to show thinking process
- Whether prompt needs reformulation
"""
from typing import Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum
from athena_ai.utils.logger import logger
from athena_ai.core import RequestComplexity


class ExecutionStrategy(Enum):
    """Execution strategies."""
    DIRECT = "direct"           # Direct execution without CoT
    COT_SILENT = "cot_silent"   # CoT without showing thinking
    COT_VERBOSE = "cot_verbose" # CoT with visible thinking


@dataclass
class ClassificationResult:
    """
    Result of request classification.
    """
    complexity: RequestComplexity
    strategy: ExecutionStrategy
    show_thinking: bool
    needs_reformulation: bool
    estimated_steps: int
    estimated_duration: int  # seconds
    reasoning: str  # Why this classification
    suggested_prompt: str = None  # Reformulated prompt if needed


class RequestClassifier:
    """
    Intelligent classifier that analyzes requests and determines execution strategy.

    The classifier uses multiple signals:
    - Request length and structure
    - Keywords (analyze, debug, monitor, etc.)
    - Target scope (single host vs multiple)
    - Expected output complexity
    """

    def __init__(self):
        """Initialize classifier."""
        self.complexity_keywords = {
            RequestComplexity.SIMPLE: [
                "status", "check", "is", "what is", "show", "list",
                "get", "display", "current", "uptime"
            ],
            RequestComplexity.MODERATE: [
                "find", "search", "which", "where", "compare",
                "verify", "validate", "test", "monitor"
            ],
            RequestComplexity.COMPLEX: [
                "analyze", "analysis", "full analysis", "comprehensive",
                "investigate", "diagnose", "troubleshoot", "optimize",
                "benchmark", "audit", "review", "deep dive"
            ]
        }

        self.multi_target_keywords = [
            "all", "every", "each", "hosts", "servers", "machines",
            "across", "multiple"
        ]

        self.reformulation_triggers = [
            "make", "do", "perform", "execute", "run"  # Vague verbs
        ]

    def classify(self, request: str, context: Dict[str, Any] = None) -> ClassificationResult:
        """
        Classify a request and determine execution strategy.

        Args:
            request: User's request
            context: Optional context (inventory size, etc.)

        Returns:
            ClassificationResult with strategy and parameters
        """
        request_lower = request.lower()

        # Analyze complexity signals
        complexity = self._determine_complexity(request_lower)

        # Determine if multi-target
        is_multi_target = self._is_multi_target(request_lower)

        # Check if needs reformulation
        needs_reformulation = self._needs_reformulation(request_lower)

        # Estimate steps and duration
        estimated_steps = self._estimate_steps(complexity, is_multi_target)
        estimated_duration = self._estimate_duration(complexity, is_multi_target)

        # Determine execution strategy
        strategy, show_thinking = self._determine_strategy(
            complexity,
            estimated_steps,
            is_multi_target
        )

        # Generate reasoning
        reasoning = self._generate_reasoning(
            complexity,
            strategy,
            estimated_steps,
            is_multi_target
        )

        # Reformulate if needed
        suggested_prompt = None
        if needs_reformulation:
            suggested_prompt = self._reformulate_prompt(request, complexity)

        result = ClassificationResult(
            complexity=complexity,
            strategy=strategy,
            show_thinking=show_thinking,
            needs_reformulation=needs_reformulation,
            estimated_steps=estimated_steps,
            estimated_duration=estimated_duration,
            reasoning=reasoning,
            suggested_prompt=suggested_prompt
        )

        logger.info(
            f"Request classified: {complexity.value} | "
            f"Strategy: {strategy.value} | "
            f"Steps: {estimated_steps} | "
            f"Duration: ~{estimated_duration}s"
        )

        return result

    def _determine_complexity(self, request_lower: str) -> RequestComplexity:
        """
        Determine request complexity based on keywords.

        Args:
            request_lower: Lowercase request

        Returns:
            RequestComplexity
        """
        # Count matches for each complexity level
        scores = {
            RequestComplexity.SIMPLE: 0,
            RequestComplexity.MODERATE: 0,
            RequestComplexity.COMPLEX: 0
        }

        for complexity, keywords in self.complexity_keywords.items():
            for keyword in keywords:
                if keyword in request_lower:
                    scores[complexity] += 1

        # Return highest scoring complexity
        max_score = max(scores.values())
        if max_score == 0:
            # Default to medium if no keywords match
            return RequestComplexity.MODERATE

        for complexity, score in scores.items():
            if score == max_score:
                return complexity

        return RequestComplexity.MODERATE

    def _is_multi_target(self, request_lower: str) -> bool:
        """Check if request targets multiple hosts."""
        return any(keyword in request_lower for keyword in self.multi_target_keywords)

    def _needs_reformulation(self, request_lower: str) -> bool:
        """
        Check if request needs reformulation.

        Vague requests like "make analysis" should be reformulated to
        "Perform comprehensive analysis including: ..."
        """
        # Check for vague verbs
        has_vague_verb = any(
            request_lower.startswith(verb)
            for verb in self.reformulation_triggers
        )

        # Check for incomplete requests
        is_short = len(request_lower.split()) < 5

        # Check for missing specificity
        lacks_target = "on" not in request_lower and "of" not in request_lower

        return has_vague_verb or (is_short and lacks_target)

    def _estimate_steps(self, complexity: RequestComplexity, is_multi_target: bool) -> int:
        """
        Estimate number of steps required.

        Args:
            complexity: Request complexity
            is_multi_target: Whether request targets multiple hosts

        Returns:
            Estimated number of steps
        """
        base_steps = {
            RequestComplexity.SIMPLE: 2,    # e.g., get context → execute → done
            RequestComplexity.MODERATE: 4,    # e.g., verify → collect → analyze → present
            RequestComplexity.COMPLEX: 8    # e.g., verify → scan → config → logs → metrics → disk → backup → synthesize
        }

        steps = base_steps[complexity]

        # Multiply if multi-target
        if is_multi_target:
            steps = int(steps * 1.5)  # 50% more steps for multi-target

        return min(steps, 12)  # Cap at 12 steps

    def _estimate_duration(self, complexity: RequestComplexity, is_multi_target: bool) -> int:
        """
        Estimate execution duration in seconds.

        Args:
            complexity: Request complexity
            is_multi_target: Whether multi-target

        Returns:
            Estimated duration in seconds
        """
        base_duration = {
            RequestComplexity.SIMPLE: 5,
            RequestComplexity.MODERATE: 20,
            RequestComplexity.COMPLEX: 45
        }

        duration = base_duration[complexity]

        if is_multi_target:
            duration = int(duration * 2)  # Double for multi-target

        return duration

    def _determine_strategy(
        self,
        complexity: RequestComplexity,
        estimated_steps: int,
        is_multi_target: bool
    ) -> Tuple[ExecutionStrategy, bool]:
        """
        Determine execution strategy and whether to show thinking.

        Args:
            complexity: Request complexity
            estimated_steps: Number of steps
            is_multi_target: Multi-target flag

        Returns:
            (ExecutionStrategy, show_thinking)
        """
        # Simple requests: direct execution
        if complexity == RequestComplexity.SIMPLE and estimated_steps <= 2:
            return ExecutionStrategy.DIRECT, False

        # Medium requests: CoT silent if < 5 steps, verbose otherwise
        if complexity == RequestComplexity.MODERATE:
            if estimated_steps <= 4:
                return ExecutionStrategy.COT_SILENT, False
            else:
                return ExecutionStrategy.COT_VERBOSE, True

        # Complex requests: always CoT verbose with thinking
        if complexity == RequestComplexity.COMPLEX:
            return ExecutionStrategy.COT_VERBOSE, True

        # Multi-target always shows progress
        if is_multi_target:
            return ExecutionStrategy.COT_VERBOSE, True

        # Default: medium complexity with silent CoT
        return ExecutionStrategy.COT_SILENT, False

    def _generate_reasoning(
        self,
        complexity: RequestComplexity,
        strategy: ExecutionStrategy,
        estimated_steps: int,
        is_multi_target: bool
    ) -> str:
        """Generate explanation for classification decision."""
        reasons = []

        reasons.append(f"Complexity: {complexity.value}")
        reasons.append(f"Estimated steps: {estimated_steps}")

        if is_multi_target:
            reasons.append("Multi-target detected")

        reasons.append(f"Strategy: {strategy.value}")

        return " | ".join(reasons)

    def _reformulate_prompt(self, original: str, complexity: RequestComplexity) -> str:
        """
        Reformulate vague prompts into clear, actionable requests.

        Args:
            original: Original request
            complexity: Detected complexity

        Returns:
            Reformulated prompt
        """
        original_lower = original.lower()

        # Extract key components
        service = self._extract_service(original_lower)
        host = self._extract_host(original_lower)
        action = self._extract_action(original_lower)

        # Build reformulated prompt
        if complexity == RequestComplexity.COMPLEX:
            if service and host:
                return (
                    f"Perform comprehensive analysis of {service} service on {host}, including: "
                    f"service status, configuration, logs, performance metrics, "
                    f"resource usage, and backup status. Provide detailed findings and recommendations."
                )
            elif service:
                return (
                    f"Analyze {service} service comprehensively: check status, review configuration, "
                    f"examine logs for errors, monitor performance metrics, and verify backups."
                )

        elif complexity == RequestComplexity.MODERATE:
            if service and host:
                return f"Check {service} service status on {host} and analyze recent logs for issues."
            elif service:
                return f"Investigate {service} service: check status, review recent logs."

        # Simple: just clarify the action
        if service and host:
            return f"Check {service} status on {host}."
        elif service:
            return f"Check {service} status."

        # If we can't reformulate meaningfully, return original
        return original

    def _extract_service(self, text: str) -> str:
        """Extract service name from text."""
        services = [
            "nginx", "apache", "mysql", "mariadb", "postgres", "mongodb",
            "redis", "memcached", "elasticsearch", "kafka", "rabbitmq",
            "docker", "kubernetes", "tomcat"
        ]

        for service in services:
            if service in text:
                return service

        # Look for "service X" pattern
        if " service " in text:
            words = text.split(" service ")
            if len(words) > 1:
                before = words[0].split()
                if before:
                    return before[-1]

        return "service"

    def _extract_host(self, text: str) -> str:
        """Extract host name from text."""
        # Look for "on X" pattern
        if " on " in text:
            words = text.split(" on ")
            if len(words) > 1:
                after = words[1].split()
                if after:
                    return after[0].strip(",.;:")

        return None

    def _extract_action(self, text: str) -> str:
        """Extract action from text."""
        actions = {
            "analyze": "analysis",
            "check": "status check",
            "monitor": "monitoring",
            "troubleshoot": "troubleshooting",
            "debug": "debugging"
        }

        for verb, noun in actions.items():
            if verb in text:
                return noun

        return "operation"


class ClassifierCache:
    """
    Cache classification results for similar requests.

    Avoids re-classifying identical or very similar requests.
    """

    def __init__(self, max_size: int = 100):
        self.cache = {}
        self.max_size = max_size

    def get(self, request: str) -> ClassificationResult:
        """Get cached classification."""
        key = self._normalize_key(request)
        return self.cache.get(key)

    def put(self, request: str, result: ClassificationResult):
        """Cache a classification result."""
        key = self._normalize_key(request)

        # Evict oldest if at capacity
        if len(self.cache) >= self.max_size:
            oldest = next(iter(self.cache))
            del self.cache[oldest]

        self.cache[key] = result

    def _normalize_key(self, request: str) -> str:
        """Normalize request for cache key."""
        return request.lower().strip()
