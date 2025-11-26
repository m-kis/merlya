"""
Request Processor - Intelligent request understanding.

Like Claude Code, understands user intent and context to route requests optimally.

Responsibilities:
- Parse and understand user requests
- Classify request complexity and type
- Extract entities and parameters
- Determine optimal processing strategy
"""
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum

from athena_ai.utils.logger import logger
from athena_ai.core import RequestComplexity


class RequestType(Enum):
    """Types of user requests."""
    QUERY = "query"  # Information request
    ACTION = "action"  # Execute something
    ANALYSIS = "analysis"  # Analyze/investigate
    GENERATION = "generation"  # Generate code/config
    TROUBLESHOOTING = "troubleshooting"  # Fix issues


@dataclass
class ProcessedRequest:
    """
    Processed request with understanding and metadata.

    Like Claude Code's request processing, captures full context.
    """
    original_query: str
    request_type: RequestType
    complexity: RequestComplexity
    intent: str
    entities: Dict[str, Any]
    parameters: Dict[str, Any]
    context_needed: List[str]
    suggested_strategy: str

    def __repr__(self):
        return (
            f"ProcessedRequest(type={self.request_type.value}, "
            f"complexity={self.complexity.value}, intent='{self.intent}')"
        )


class RequestProcessor:
    """
    Intelligent request processor.

    Like Claude Code, understands user intent to optimize processing.

    Design:
    - SoC: Focused only on request understanding
    - KISS: Simple heuristics + optional LLM enhancement
    - DDD: Part of Orchestration domain
    """

    def __init__(self, use_llm_enhancement: bool = True):
        """
        Initialize request processor.

        Args:
            use_llm_enhancement: Use LLM for better understanding
        """
        self.use_llm_enhancement = use_llm_enhancement
        self._init_patterns()

    def _init_patterns(self):
        """Initialize regex patterns for quick classification."""
        self.query_patterns = [
            r'\b(list|show|get|display|what|which|where|combien)\b',
            r'\?$'
        ]

        self.action_patterns = [
            r'\b(restart|stop|start|deploy|install|update|configure|set|create)\b',
            r'\b(execute|run|apply|enable|disable)\b'
        ]

        self.analysis_patterns = [
            r'\b(analyze|investigate|check|examine|diagnose|verify)\b',
            r'\b(why|how|explain|understand)\b'
        ]

        self.generation_patterns = [
            r'\b(generate|create|write|build)\s+(terraform|ansible|docker|code|script)\b'
        ]

        self.troubleshooting_patterns = [
            r'\b(fix|repair|solve|resolve|troubleshoot)\b',
            r'\b(error|problem|issue|broken|failed|not working)\b'
        ]

    def process(self, query: str, context: Optional[Dict[str, Any]] = None) -> ProcessedRequest:
        """
        Process user request to understand intent and requirements.

        Like Claude Code's intelligent understanding.

        Args:
            query: User query
            context: Optional context information

        Returns:
            Processed request with full understanding
        """
        query_lower = query.lower()

        # Classify request type
        request_type = self._classify_type(query_lower)

        # Determine complexity
        complexity = self._determine_complexity(query_lower, request_type)

        # Extract intent (main goal)
        intent = self._extract_intent(query, request_type)

        # Extract entities (hosts, services, etc.)
        entities = self._extract_entities(query_lower, context)

        # Extract parameters
        parameters = self._extract_parameters(query_lower)

        # Determine context needed
        context_needed = self._determine_context_needed(request_type, entities)

        # Suggest processing strategy
        suggested_strategy = self._suggest_strategy(request_type, complexity)

        processed = ProcessedRequest(
            original_query=query,
            request_type=request_type,
            complexity=complexity,
            intent=intent,
            entities=entities,
            parameters=parameters,
            context_needed=context_needed,
            suggested_strategy=suggested_strategy
        )

        logger.debug(f"Processed request: {processed}")
        return processed

    def _classify_type(self, query_lower: str) -> RequestType:
        """Classify request type using patterns."""
        import re

        # Check patterns in order of specificity
        for pattern in self.troubleshooting_patterns:
            if re.search(pattern, query_lower):
                return RequestType.TROUBLESHOOTING

        for pattern in self.generation_patterns:
            if re.search(pattern, query_lower):
                return RequestType.GENERATION

        for pattern in self.action_patterns:
            if re.search(pattern, query_lower):
                return RequestType.ACTION

        for pattern in self.analysis_patterns:
            if re.search(pattern, query_lower):
                return RequestType.ANALYSIS

        for pattern in self.query_patterns:
            if re.search(pattern, query_lower):
                return RequestType.QUERY

        # Default to query
        return RequestType.QUERY

    def _determine_complexity(self, query_lower: str, request_type: RequestType) -> RequestComplexity:
        """
        Determine request complexity.

        Simple heuristics:
        - Queries are usually simple
        - Actions and troubleshooting are moderate to complex
        - Analysis and generation depend on scope
        """
        # Count complexity indicators
        complexity_indicators = [
            'all', 'every', 'multiple', 'various', 'investigate', 'analyze',
            'troubleshoot', 'diagnose', 'complex', 'detailed'
        ]

        indicator_count = sum(1 for indicator in complexity_indicators if indicator in query_lower)

        # Length-based heuristic
        word_count = len(query_lower.split())

        # Classify
        if indicator_count == 0 and word_count < 10:
            return RequestComplexity.SIMPLE
        elif indicator_count >= 2 or word_count > 20:
            return RequestComplexity.COMPLEX
        else:
            return RequestComplexity.MODERATE

    def _extract_intent(self, query: str, request_type: RequestType) -> str:
        """
        Extract main intent/goal from query.

        Simple extraction for now, can be enhanced with LLM.
        """
        # Take first sentence as intent
        sentences = query.split('.')
        return sentences[0].strip() if sentences else query.strip()

    def _extract_entities(self, query_lower: str, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract entities (hosts, services, environments, etc.).

        Uses regex patterns + context.
        """
        import re

        entities = {}

        # Extract environment
        env_patterns = {
            'prod': r'\b(prod|production)\b',
            'preprod': r'\bpreprod\b',
            'staging': r'\bstaging\b',
            'dev': r'\b(dev|development)\b'
        }

        for env, pattern in env_patterns.items():
            if re.search(pattern, query_lower):
                entities['environment'] = env
                break

        # Extract services
        service_patterns = {
            'nginx': r'\bnginx\b',
            'mongodb': r'\b(mongo|mongodb)\b',
            'postgresql': r'\b(postgres|postgresql)\b',
            'mysql': r'\bmysql\b',
            'redis': r'\bredis\b',
            'docker': r'\bdocker\b'
        }

        for service, pattern in service_patterns.items():
            if re.search(pattern, query_lower):
                entities.setdefault('services', []).append(service)

        # Extract roles
        role_patterns = {
            'web': r'\bweb\b',
            'db': r'\b(db|database)\b',
            'cache': r'\bcache\b',
            'api': r'\bapi\b'
        }

        for role, pattern in role_patterns.items():
            if re.search(pattern, query_lower):
                entities['role'] = role
                break

        return entities

    def _extract_parameters(self, query_lower: str) -> Dict[str, Any]:
        """Extract parameters (numbers, flags, etc.)."""
        import re

        params = {}

        # Extract numbers
        numbers = re.findall(r'\b\d+\b', query_lower)
        if numbers:
            params['numbers'] = [int(n) for n in numbers]

        # Extract boolean flags
        if re.search(r'\b(force|skip|ignore)\b', query_lower):
            params['force'] = True

        if re.search(r'\b(dry-?run|test|preview)\b', query_lower):
            params['dry_run'] = True

        return params

    def _determine_context_needed(self, request_type: RequestType, entities: Dict[str, Any]) -> List[str]:
        """
        Determine what context is needed to process this request.

        Like Claude Code, identifies missing information.
        """
        needed = []

        # Always need basic infrastructure context
        needed.append('infrastructure_inventory')

        # Type-specific context
        if request_type in [RequestType.ACTION, RequestType.TROUBLESHOOTING]:
            needed.append('current_state')
            needed.append('permissions')

        if request_type == RequestType.ANALYSIS:
            needed.append('logs')
            needed.append('metrics')

        # Entity-specific context
        if 'services' in entities:
            needed.append('service_status')

        if 'environment' in entities:
            needed.append('environment_config')

        return needed

    def _suggest_strategy(self, request_type: RequestType, complexity: RequestComplexity) -> str:
        """
        Suggest processing strategy based on request characteristics.

        Strategies:
        - direct: Fast, single LLM call
        - smart: Smart orchestrator with domain services
        - enhanced: Full plan-validate-execute cycle
        """
        # Simple queries → direct
        if request_type == RequestType.QUERY and complexity == RequestComplexity.SIMPLE:
            return 'direct'

        # Complex analysis/troubleshooting → smart
        if request_type in [RequestType.ANALYSIS, RequestType.TROUBLESHOOTING]:
            if complexity == RequestComplexity.COMPLEX:
                return 'smart'

        # Actions and generations → enhanced (with preview)
        if request_type in [RequestType.ACTION, RequestType.GENERATION]:
            return 'enhanced'

        # Default to smart for moderate complexity
        return 'smart' if complexity != RequestComplexity.SIMPLE else 'direct'
