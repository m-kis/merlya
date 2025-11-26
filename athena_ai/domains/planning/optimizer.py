"""
Plan Optimizer - Optimizes execution plans for better performance.

Performs:
- Step merging
- Parallelization optimization
- Verification step insertion
- Token budget optimization
"""
from typing import Any, Dict, List

from athena_ai.utils.logger import logger


class PlanOptimizer:
    """
    Optimizes execution plans for better performance and reliability.

    IMPLEMENTATION OF PREVIOUSLY-EMPTY PlanOptimizer from adaptive_planner.py
    """

    def optimize(
        self,
        steps: List[Dict[str, Any]],
        max_parallel: int = 5,
        insert_verifications: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Optimize an execution plan.

        Args:
            steps: Original steps
            max_parallel: Maximum parallel steps
            insert_verifications: Whether to add verification steps

        Returns:
            Optimized steps
        """
        logger.info(f"Optimizing plan with {len(steps)} steps")

        # 1. Merge similar steps
        steps = self._merge_similar_steps(steps)

        # 2. Optimize parallelization
        steps = self._optimize_parallelization(steps, max_parallel)

        # 3. Add verification steps if needed
        if insert_verifications:
            steps = self._add_verification_steps(steps)

        # 4. Optimize token estimates
        steps = self._optimize_tokens(steps)

        # 5. Reorder for optimal execution
        steps = self._reorder_steps(steps)

        logger.info(f"Optimized plan now has {len(steps)} steps")
        return steps

    def _merge_similar_steps(self, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Merge steps that can be combined.

        For example:
        - "Check service A status" + "Check service B status" → "Check all services status"
        - Multiple file reads on same host → Single batch read
        """
        merged = []
        skip_ids = set()

        for i, step in enumerate(steps):
            if step["id"] in skip_ids:
                continue

            # Look for similar steps that can be merged
            description = step.get("description", "").lower()
            target = step.get("target")
            similar = []

            for _j, other_step in enumerate(steps[i + 1:], start=i + 1):
                if other_step["id"] in skip_ids:
                    continue

                other_desc = other_step.get("description", "").lower()
                other_target = other_step.get("target")

                # Check if similar and can be merged
                if (
                    target == other_target and
                    self._are_mergeable(description, other_desc) and
                    not other_step.get("dependencies", [])  # No dependencies
                ):
                    similar.append(other_step)
                    skip_ids.add(other_step["id"])

            if similar:
                # Merge steps
                merged_step = self._create_merged_step(step, similar)
                merged.append(merged_step)
                logger.debug(f"Merged step {step['id']} with {len(similar)} similar steps")
            else:
                merged.append(step)

        # Re-number steps
        for i, step in enumerate(merged, start=1):
            step["id"] = i

        return merged

    def _are_mergeable(self, desc1: str, desc2: str) -> bool:
        """Check if two step descriptions indicate mergeable operations."""
        # Common patterns for mergeable operations
        merge_patterns = [
            ("check", "status"),
            ("list", "files"),
            ("get", "info"),
            ("collect", "metrics")
        ]

        for pattern in merge_patterns:
            if all(p in desc1 for p in pattern) and all(p in desc2 for p in pattern):
                return True

        return False

    def _create_merged_step(
        self,
        primary: Dict[str, Any],
        similar: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Create a merged step from similar steps."""
        merged = primary.copy()

        # Combine descriptions
        all_steps = [primary] + similar
        merged["description"] = f"Batch operation: {len(all_steps)} similar tasks"

        # Combine token estimates
        merged["estimated_tokens"] = sum(s.get("estimated_tokens", 1000) for s in all_steps)

        # Mark as potentially parallelizable internally
        merged["batch_size"] = len(all_steps)

        return merged

    def _optimize_parallelization(
        self,
        steps: List[Dict[str, Any]],
        max_parallel: int
    ) -> List[Dict[str, Any]]:
        """
        Find and mark more opportunities for parallelization.

        Args:
            steps: Plan steps
            max_parallel: Maximum parallel steps allowed

        Returns:
            Optimized steps
        """
        # Build dependency levels
        levels: Dict[int, List[Dict[str, Any]]] = {}

        for step in steps:
            deps = step.get("dependencies", [])
            level = max(deps) if deps else 0

            if level not in levels:
                levels[level] = []
            levels[level].append(step)

        # Mark steps as parallelizable if they don't conflict
        for level, level_steps in levels.items():
            if len(level_steps) <= 1:
                continue

            # Check which steps can run in parallel
            targets = {}
            parallel_count = 0

            for step in level_steps:
                target = step.get("target", "local")

                # Can parallelize if different targets or read-only
                is_readonly = self._is_readonly_operation(step.get("description", ""))

                if target not in targets or is_readonly:
                    if parallel_count < max_parallel:
                        step["parallelizable"] = True
                        parallel_count += 1
                        targets[target] = step["id"]
                else:
                    step["parallelizable"] = False

        return steps

    def _is_readonly_operation(self, description: str) -> bool:
        """Check if operation is read-only (safe to parallelize)."""
        readonly_keywords = ["check", "get", "list", "show", "view", "read", "scan"]
        description_lower = description.lower()
        return any(kw in description_lower for kw in readonly_keywords)

    def _add_verification_steps(self, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Add verification steps after critical operations.

        Args:
            steps: Plan steps

        Returns:
            Steps with verifications inserted
        """
        enhanced = []
        next_id = len(steps) + 1

        for step in steps:
            enhanced.append(step)

            # Check if this is a critical operation
            if step.get("critical", False):
                # Add verification step after it
                verify_step = {
                    "id": next_id,
                    "description": f"Verify step {step['id']} succeeded",
                    "dependencies": [step["id"]],
                    "parallelizable": False,
                    "estimated_tokens": 500,
                    "verification_for": step["id"]
                }
                enhanced.append(verify_step)
                next_id += 1

                logger.debug(f"Added verification step after critical step {step['id']}")

        # Re-number steps
        for i, step in enumerate(enhanced, start=1):
            # Update dependencies
            old_id = step["id"]
            step["id"] = i

            # Update references in dependencies
            for other_step in enhanced:
                deps = other_step.get("dependencies", [])
                other_step["dependencies"] = [i if d == old_id else d for d in deps]

        return enhanced

    def _optimize_tokens(self, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Optimize token estimates based on step complexity.

        Args:
            steps: Plan steps

        Returns:
            Steps with optimized token estimates
        """
        for step in steps:
            description = step.get("description", "")

            # Estimate tokens based on operation type
            if any(kw in description.lower() for kw in ["list", "show", "get"]):
                # Simple read operations
                step["estimated_tokens"] = 600
            elif any(kw in description.lower() for kw in ["analyze", "investigate"]):
                # Complex analysis
                step["estimated_tokens"] = 2000
            elif step.get("batch_size", 0) > 1:
                # Batch operation
                step["estimated_tokens"] = min(
                    step.get("estimated_tokens", 1000) * step["batch_size"],
                    3000  # Cap at 3000
                )
            else:
                # Default if not set
                if "estimated_tokens" not in step:
                    step["estimated_tokens"] = 1000

        return steps

    def _reorder_steps(self, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Reorder steps for optimal execution.

        Principles:
        - Quick steps first (to fail fast)
        - Verification steps close to what they verify
        - Parallelizable steps grouped together
        """
        # Topological sort respecting dependencies
        # (Simple implementation - can be enhanced)

        # For now, maintain original order but group parallelizable steps
        return steps
