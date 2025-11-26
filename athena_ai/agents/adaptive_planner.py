"""
Adaptive Plan Generator: Creates execution plans for ANY request using LLM reasoning.

Unlike pattern-based planners, this uses LLM to dynamically generate
appropriate plans for any type of request.
"""
import json
from typing import Any, Dict, List

from athena_ai.agents.request_classifier import RequestComplexity
from athena_ai.utils.logger import logger


class AdaptivePlanGenerator:
    """
    Generates execution plans dynamically using LLM reasoning.

    This planner can handle ANY request type by asking the LLM
    to decompose it into logical steps.
    """

    def __init__(self, llm_router):
        """
        Initialize adaptive planner.

        Args:
            llm_router: LiteLLM router for plan generation
        """
        self.llm = llm_router

    def generate_plan(
        self,
        request: str,
        complexity: RequestComplexity,
        max_steps: int = 10,
        context_summary: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Generate an execution plan using LLM reasoning.

        Args:
            request: User's request
            complexity: Request complexity
            max_steps: Maximum number of steps
            context_summary: Brief context

        Returns:
            List of step dictionaries
        """
        logger.info(f"Generating adaptive plan for: {request}")

        # Build prompt for plan generation
        prompt = self._build_planning_prompt(
            request,
            complexity,
            max_steps,
            context_summary
        )

        try:
            # Generate plan using LLM
            response = self._call_llm_for_plan(prompt)

            # Parse response into steps
            steps = self._parse_plan_response(response)

            # Validate and adjust plan
            steps = self._validate_plan(steps, max_steps)

            logger.info(f"Generated plan with {len(steps)} steps")
            return steps

        except Exception as e:
            logger.error(f"Plan generation failed: {e}")
            # Fallback to simple 3-step plan
            return self._fallback_plan(request)

    def _build_planning_prompt(
        self,
        request: str,
        complexity: RequestComplexity,
        max_steps: int,
        context_summary: str
    ) -> str:
        """
        Build prompt for LLM plan generation.

        Args:
            request: User request
            complexity: Complexity level
            max_steps: Maximum steps allowed
            context_summary: Context

        Returns:
            Planning prompt
        """
        prompt = f"""You are an expert DevOps/SRE planner. Your task is to decompose a user request into a structured execution plan.

USER REQUEST: "{request}"

COMPLEXITY: {complexity.value}
MAX STEPS: {max_steps}

{f"CONTEXT: {context_summary}" if context_summary else ""}

INSTRUCTIONS:
1. Break down the request into {3 if complexity == RequestComplexity.SIMPLE else 5 if complexity == RequestComplexity.MEDIUM else 8} logical steps
2. Each step should be:
   - Clear and actionable (what to do, not how)
   - Independent or with minimal dependencies
   - Achievable in < 30 seconds
   - Verifiable (clear success/failure)

3. Steps should follow this general pattern:
   - VERIFY prerequisites (connectivity, permissions, etc.)
   - GATHER required information
   - EXECUTE main actions
   - ANALYZE results
   - SYNTHESIZE findings

4. Consider parallelization:
   - Mark steps that can run in parallel
   - Identify dependencies between steps

5. Each step needs:
   - id: Sequential number (1, 2, 3, ...)
   - description: Clear description (max 80 chars)
   - dependencies: List of step IDs this depends on (empty array if none)
   - parallelizable: true if can run in parallel with other steps
   - estimated_tokens: Estimated tokens for this step (500-2000)

RESPOND WITH VALID JSON ONLY (no markdown, no explanation):
{{
  "steps": [
    {{
      "id": 1,
      "description": "Verify host connectivity and permissions",
      "dependencies": [],
      "parallelizable": false,
      "estimated_tokens": 500
    }},
    {{
      "id": 2,
      "description": "Collect system metrics and service status",
      "dependencies": [1],
      "parallelizable": false,
      "estimated_tokens": 800
    }}
  ]
}}"""

        return prompt

    def _call_llm_for_plan(self, prompt: str) -> str:
        """
        Call LLM to generate plan.

        Args:
            prompt: Planning prompt

        Returns:
            LLM response
        """
        try:
            # Call LLM with task-specific model selection for planning
            logger.info("Generating plan using LLM (intelligent planning enabled)")
            response = self.llm.generate(
                prompt=prompt,
                system_prompt="You are an expert DevOps/SRE planner. Generate ONLY valid JSON responses without any markdown formatting or explanations.",
                task="planning"  # Uses fast model optimized for planning tasks
            )

            return response

        except Exception as e:
            logger.error(f"LLM call failed: {e}, falling back to heuristic plan")
            # Fallback to heuristic plan on LLM failure
            return self._generate_fallback_response(prompt)

    def _generate_fallback_response(self, prompt: str) -> str:
        """
        Generate fallback response when LLM unavailable.

        This uses heuristics to create a reasonable plan.

        Args:
            prompt: Original prompt

        Returns:
            JSON string with plan
        """
        # Extract request from prompt
        lines = prompt.split("\n")
        request = ""
        for line in lines:
            if line.startswith("USER REQUEST:"):
                request = line.replace("USER REQUEST:", "").strip(' "')
                break

        # Generate generic plan
        steps = [
            {
                "id": 1,
                "description": "Verify prerequisites and gather context",
                "dependencies": [],
                "parallelizable": False,
                "estimated_tokens": 600
            },
            {
                "id": 2,
                "description": f"Execute main task: {request[:50]}...",
                "dependencies": [1],
                "parallelizable": False,
                "estimated_tokens": 1500
            },
            {
                "id": 3,
                "description": "Synthesize findings and generate report",
                "dependencies": [2],
                "parallelizable": False,
                "estimated_tokens": 1000
            }
        ]

        return json.dumps({"steps": steps})

    def _parse_plan_response(self, response: str) -> List[Dict[str, Any]]:
        """
        Parse LLM response into step list.

        Args:
            response: JSON response from LLM

        Returns:
            List of steps
        """
        try:
            # Try to parse as JSON
            if "```json" in response:
                # Extract JSON from markdown code block
                start = response.find("```json") + 7
                end = response.find("```", start)
                json_str = response[start:end].strip()
            elif "```" in response:
                # Extract from generic code block
                start = response.find("```") + 3
                end = response.find("```", start)
                json_str = response[start:end].strip()
            else:
                json_str = response.strip()

            data = json.loads(json_str)

            if "steps" in data:
                return data["steps"]
            elif isinstance(data, list):
                return data
            else:
                raise ValueError("Invalid plan format")

        except Exception as e:
            logger.error(f"Failed to parse plan response: {e}")
            logger.debug(f"Response was: {response[:500]}")
            raise

    def _validate_plan(self, steps: List[Dict[str, Any]], max_steps: int) -> List[Dict[str, Any]]:
        """
        Validate and adjust plan.

        Args:
            steps: List of steps
            max_steps: Maximum allowed steps

        Returns:
            Validated steps
        """
        # Ensure we don't exceed max steps
        if len(steps) > max_steps:
            logger.warning(f"Plan has {len(steps)} steps, trimming to {max_steps}")
            steps = steps[:max_steps]

        # Validate each step has required fields
        for i, step in enumerate(steps):
            # Ensure ID is sequential
            if step.get("id") != i + 1:
                step["id"] = i + 1

            # Ensure description exists
            if not step.get("description"):
                step["description"] = f"Step {i + 1}"

            # Ensure dependencies is a list
            if "dependencies" not in step:
                step["dependencies"] = []
            elif not isinstance(step["dependencies"], list):
                step["dependencies"] = []

            # Ensure parallelizable is boolean
            if "parallelizable" not in step:
                step["parallelizable"] = False

            # Ensure estimated_tokens exists
            if "estimated_tokens" not in step:
                step["estimated_tokens"] = 1000

            # Validate dependencies refer to existing steps
            valid_deps = [d for d in step["dependencies"] if d < step["id"]]
            step["dependencies"] = valid_deps

        return steps

    def _fallback_plan(self, request: str) -> List[Dict[str, Any]]:
        """
        Create a simple fallback plan when generation fails.

        Args:
            request: Original request

        Returns:
            Simple 3-step plan
        """
        logger.info("Using fallback plan")

        return [
            {
                "id": 1,
                "description": "Gather necessary information and context",
                "dependencies": [],
                "parallelizable": False,
                "estimated_tokens": 800
            },
            {
                "id": 2,
                "description": f"Execute: {request[:60]}",
                "dependencies": [1],
                "parallelizable": False,
                "estimated_tokens": 1500
            },
            {
                "id": 3,
                "description": "Synthesize results and provide summary",
                "dependencies": [2],
                "parallelizable": False,
                "estimated_tokens": 1000
            }
        ]


class PlanOptimizer:
    """
    Optimizes generated plans for better execution.

    This can:
    - Merge redundant steps
    - Reorder steps for better parallelization
    - Adjust token estimates
    - Add verification steps
    """

    def optimize(self, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Optimize an execution plan.

        Args:
            steps: Original steps

        Returns:
            Optimized steps
        """
        # For now, just return as-is
        # Future: implement actual optimizations
        return steps

    def _merge_similar_steps(self, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Merge steps that can be combined."""
        # TODO: Implement
        return steps

    def _optimize_parallelization(self, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Find more opportunities for parallelization."""
        # TODO: Implement
        return steps

    def _add_verification_steps(self, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Add verification steps after critical operations."""
        # TODO: Implement
        return steps
