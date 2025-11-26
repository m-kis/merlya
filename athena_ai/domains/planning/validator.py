"""
Plan Validator - Validates execution plans before execution.

Checks for:
- Circular dependencies
- Missing dependencies
- Resource availability
- Permission requirements
- Risk assessment
"""
from typing import List, Dict, Any, Set, Tuple, Optional
from athena_ai.utils.logger import logger


class ValidationError:
    """Validation error with severity."""

    def __init__(self, severity: str, message: str, step_id: Optional[int] = None):
        self.severity = severity  # "error", "warning", "info"
        self.message = message
        self.step_id = step_id

    def __str__(self) -> str:
        prefix = {
            "error": "❌",
            "warning": "⚠️ ",
            "info": "ℹ️ "
        }.get(self.severity, "")

        if self.step_id:
            return f"{prefix} Step {self.step_id}: {self.message}"
        return f"{prefix} {self.message}"


class PlanValidator:
    """
    Validates execution plans for correctness and feasibility.

    Performs comprehensive validation before execution.
    """

    def validate(
        self,
        steps: List[Dict[str, Any]],
        available_tools: Optional[Set[str]] = None
    ) -> Tuple[bool, List[ValidationError]]:
        """
        Validate a plan.

        Args:
            steps: List of plan steps
            available_tools: Set of available tool names

        Returns:
            (is_valid, list of errors/warnings)
        """
        errors = []

        # 1. Validate structure
        errors.extend(self._validate_structure(steps))

        # 2. Check for circular dependencies
        errors.extend(self._check_circular_dependencies(steps))

        # 3. Validate dependencies exist
        errors.extend(self._validate_dependencies(steps))

        # 4. Check parallelization conflicts
        errors.extend(self._check_parallelization(steps))

        # 5. Validate tool availability
        if available_tools:
            errors.extend(self._validate_tools(steps, available_tools))

        # 6. Risk assessment
        errors.extend(self._assess_risks(steps))

        # Check if any critical errors
        has_errors = any(e.severity == "error" for e in errors)

        return (not has_errors, errors)

    def _validate_structure(self, steps: List[Dict[str, Any]]) -> List[ValidationError]:
        """Validate basic plan structure."""
        errors = []

        if not steps:
            errors.append(ValidationError("error", "Plan is empty"))
            return errors

        # Check for required fields
        for step in steps:
            step_id = step.get("id")

            if step_id is None:
                errors.append(ValidationError("error", "Step missing 'id' field"))
                continue

            if "description" not in step:
                errors.append(ValidationError(
                    "warning",
                    "Step missing 'description'",
                    step_id
                ))

            if "dependencies" not in step:
                errors.append(ValidationError(
                    "info",
                    "Step missing 'dependencies' (assuming none)",
                    step_id
                ))

        # Check for duplicate IDs
        ids = [s.get("id") for s in steps if "id" in s]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            errors.append(ValidationError(
                "error",
                f"Duplicate step IDs: {duplicates}"
            ))

        # Check for sequential IDs
        expected_ids = list(range(1, len(steps) + 1))
        actual_ids = sorted(ids)
        if actual_ids != expected_ids:
            errors.append(ValidationError(
                "warning",
                f"Step IDs not sequential (expected {expected_ids}, got {actual_ids})"
            ))

        return errors

    def _check_circular_dependencies(self, steps: List[Dict[str, Any]]) -> List[ValidationError]:
        """
        Check for circular dependencies using DFS.

        Args:
            steps: Plan steps

        Returns:
            List of validation errors
        """
        errors = []

        # Build dependency graph
        graph = {step["id"]: step.get("dependencies", []) for step in steps}

        # DFS to detect cycles
        visited = set()
        rec_stack = set()

        def has_cycle(node: int, path: List[int]) -> bool:
            visited.add(node)
            rec_stack.add(node)

            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    if has_cycle(neighbor, path + [node]):
                        return True
                elif neighbor in rec_stack:
                    # Found cycle
                    cycle = path + [node, neighbor]
                    errors.append(ValidationError(
                        "error",
                        f"Circular dependency detected: {' -> '.join(map(str, cycle))}"
                    ))
                    return True

            rec_stack.remove(node)
            return False

        for node in graph:
            if node not in visited:
                has_cycle(node, [])

        return errors

    def _validate_dependencies(self, steps: List[Dict[str, Any]]) -> List[ValidationError]:
        """Validate that all dependencies reference existing steps."""
        errors = []

        step_ids = {step["id"] for step in steps}

        for step in steps:
            step_id = step["id"]
            dependencies = step.get("dependencies", [])

            for dep_id in dependencies:
                # Check dependency exists
                if dep_id not in step_ids:
                    errors.append(ValidationError(
                        "error",
                        f"References non-existent step {dep_id}",
                        step_id
                    ))

                # Check dependency is before this step
                if dep_id >= step_id:
                    errors.append(ValidationError(
                        "error",
                        f"Depends on future step {dep_id}",
                        step_id
                    ))

        return errors

    def _check_parallelization(self, steps: List[Dict[str, Any]]) -> List[ValidationError]:
        """
        Check for parallelization conflicts.

        Steps marked as parallelizable should not have conflicting resource access.
        """
        errors = []

        # Find parallelizable steps at each level
        levels: Dict[int, List[Dict[str, Any]]] = {}

        for step in steps:
            if not step.get("parallelizable", False):
                continue

            # Determine level (max dependency depth)
            deps = step.get("dependencies", [])
            level = max(deps) if deps else 0

            if level not in levels:
                levels[level] = []
            levels[level].append(step)

        # Check for resource conflicts within each level
        for level, parallel_steps in levels.items():
            targets = {}
            for step in parallel_steps:
                target = step.get("target", "local")
                if target in targets:
                    # Potential conflict
                    errors.append(ValidationError(
                        "warning",
                        f"Steps {targets[target]} and {step['id']} may conflict on target '{target}'",
                        step["id"]
                    ))
                else:
                    targets[target] = step["id"]

        return errors

    def _validate_tools(
        self,
        steps: List[Dict[str, Any]],
        available_tools: Set[str]
    ) -> List[ValidationError]:
        """Validate that required tools are available."""
        errors = []

        for step in steps:
            tool_name = step.get("tool")
            if tool_name and tool_name not in available_tools:
                errors.append(ValidationError(
                    "error",
                    f"Required tool '{tool_name}' not available",
                    step["id"]
                ))

        return errors

    def _assess_risks(self, steps: List[Dict[str, Any]]) -> List[ValidationError]:
        """
        Assess risks in the plan.

        Args:
            steps: Plan steps

        Returns:
            List of risk warnings
        """
        errors = []

        # High-risk operations
        high_risk_keywords = ["delete", "drop", "remove", "destroy", "terminate"]
        medium_risk_keywords = ["restart", "stop", "kill", "shutdown"]

        for step in steps:
            description = step.get("description", "").lower()

            # Check for high-risk operations
            if any(kw in description for kw in high_risk_keywords):
                errors.append(ValidationError(
                    "warning",
                    f"High-risk operation detected: {step.get('description')}",
                    step["id"]
                ))
                # Mark step as critical for snapshot creation
                step["critical"] = True

            # Check for medium-risk operations
            elif any(kw in description for kw in medium_risk_keywords):
                errors.append(ValidationError(
                    "info",
                    f"Medium-risk operation: {step.get('description')}",
                    step["id"]
                ))

        # Check for missing verification steps
        has_verify = any("verify" in step.get("description", "").lower() for step in steps)
        if not has_verify and len(steps) > 2:
            errors.append(ValidationError(
                "info",
                "Plan has no verification steps"
            ))

        return errors
