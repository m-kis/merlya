"""
Chain of Thought (CoT) System for Multi-Agent Reasoning.

This module implements a step-by-step reasoning system that:
1. Decomposes complex tasks into manageable steps
2. Shows thinking process to the user
3. Executes steps sequentially or in parallel based on dependencies
4. Handles errors gracefully
5. Provides real-time feedback
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from athena_ai.core import StepStatus
from athena_ai.utils.logger import logger

console = Console()


@dataclass
class Step:
    """
    Represents a single step in the chain of thought.
    """
    id: int
    description: str
    dependencies: List[int] = field(default_factory=list)
    parallelizable: bool = False
    estimated_tokens: int = 1000
    status: StepStatus = StepStatus.PENDING
    thinking: Optional[str] = None
    action: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    duration: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "description": self.description,
            "dependencies": self.dependencies,
            "parallelizable": self.parallelizable,
            "estimated_tokens": self.estimated_tokens,
            "status": self.status.value,
            "thinking": self.thinking,
            "action": self.action,
            "result": self.result,
            "error": self.error,
            "duration": self.duration
        }


@dataclass
class Plan:
    """
    Represents a complete plan with multiple steps.
    """
    title: str
    steps: List[Step]
    total_estimated_tokens: int
    parallel_groups: List[List[int]] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)

    def get_step(self, step_id: int) -> Optional[Step]:
        """Get a step by ID."""
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    def get_executable_steps(self) -> List[Step]:
        """Get steps that can be executed now (dependencies met)."""
        executable = []
        for step in self.steps:
            if step.status != StepStatus.PENDING:
                continue

            # Check if all dependencies are completed
            deps_met = all(
                self.get_step(dep_id).status == StepStatus.COMPLETED
                for dep_id in step.dependencies
            )

            if deps_met:
                executable.append(step)

        return executable

    def is_complete(self) -> bool:
        """Check if all steps are completed or skipped."""
        return all(
            step.status in [StepStatus.COMPLETED, StepStatus.SKIPPED]
            for step in self.steps
        )

    def has_failures(self) -> bool:
        """Check if any step failed."""
        return any(step.status == StepStatus.FAILED for step in self.steps)


class ChainOfThought:
    """
    Chain of Thought executor that runs steps sequentially with feedback.
    """

    def __init__(self, show_thinking: bool = True, show_actions: bool = True):
        """
        Initialize Chain of Thought executor.

        Args:
            show_thinking: Show thinking process to user
            show_actions: Show actions being executed
        """
        self.show_thinking = show_thinking
        self.show_actions = show_actions
        self.console = console

    def create_plan(
        self,
        title: str,
        request: str,
        planner_fn: Callable[[str], List[Dict[str, Any]]]
    ) -> Plan:
        """
        Create an execution plan using a planner function.

        Args:
            title: Title of the plan
            request: User request
            planner_fn: Function that takes request and returns list of step dicts

        Returns:
            Plan object
        """
        logger.info(f"Creating plan for: {request}")

        with self.console.status("[bold green]Creating execution plan..."):
            step_dicts = planner_fn(request)

        # Convert to Step objects
        steps = []
        total_tokens = 0

        for step_dict in step_dicts:
            step = Step(
                id=step_dict["id"],
                description=step_dict["description"],
                dependencies=step_dict.get("dependencies", []),
                parallelizable=step_dict.get("parallelizable", False),
                estimated_tokens=step_dict.get("estimated_tokens", 1000)
            )
            steps.append(step)
            total_tokens += step.estimated_tokens

        # Identify parallel groups
        parallel_groups = self._identify_parallel_groups(steps)

        plan = Plan(
            title=title,
            steps=steps,
            total_estimated_tokens=total_tokens,
            parallel_groups=parallel_groups
        )

        self._display_plan(plan)

        return plan

    def _identify_parallel_groups(self, steps: List[Step]) -> List[List[int]]:
        """
        Identify groups of steps that can run in parallel.

        Args:
            steps: List of steps

        Returns:
            List of groups (each group is a list of step IDs)
        """
        groups = []
        current_group = []

        for step in steps:
            if step.parallelizable and not step.dependencies:
                # Can run in parallel with other similar steps
                if not current_group:
                    current_group.append(step.id)
                else:
                    # Check if this step has same dependencies as group
                    current_group.append(step.id)
            else:
                # Cannot parallelize, flush current group
                if len(current_group) > 1:
                    groups.append(current_group)
                current_group = []

        # Flush remaining group
        if len(current_group) > 1:
            groups.append(current_group)

        return groups

    def _display_plan(self, plan: Plan):
        """Display the execution plan to the user."""
        self.console.print()
        self.console.print(Panel.fit(
            f"[bold cyan]{plan.title}[/bold cyan]\n\n"
            f"[dim]Steps: {len(plan.steps)} | "
            f"Estimated tokens: {plan.total_estimated_tokens:,} | "
            f"Parallelizable groups: {len(plan.parallel_groups)}[/dim]",
            border_style="cyan"
        ))
        self.console.print()

        # Display steps
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Step", width=6)
        table.add_column("Description", width=60)
        table.add_column("Deps", width=8)

        for step in plan.steps:
            deps_str = ", ".join(str(d) for d in step.dependencies) if step.dependencies else "-"
            parallel_marker = "⚡" if step.parallelizable else ""
            table.add_row(
                f"{step.id} {parallel_marker}",
                step.description,
                deps_str
            )

        self.console.print(table)
        self.console.print()

    def execute_plan(
        self,
        plan: Plan,
        thinking_fn: Callable[[Step, Dict[str, Any]], str],
        action_fn: Callable[[Step, str, Dict[str, Any]], Dict[str, Any]]
    ) -> Plan:
        """
        Execute a plan step by step.

        Args:
            plan: Plan to execute
            thinking_fn: Function that generates thinking for a step
            action_fn: Function that executes the action for a step

        Returns:
            Updated plan with results
        """
        logger.info(f"Executing plan: {plan.title}")

        step_count = 0
        total_steps = len(plan.steps)

        while not plan.is_complete():
            executable_steps = plan.get_executable_steps()

            if not executable_steps:
                # No more executable steps but plan not complete
                # This means remaining steps have unmet dependencies (failed steps)
                logger.warning("Cannot proceed: remaining steps have failed dependencies")
                for step in plan.steps:
                    if step.status == StepStatus.PENDING:
                        step.status = StepStatus.SKIPPED
                        step.error = "Dependencies failed"
                break

            # Check if steps can run in parallel
            all_parallelizable = all(step.parallelizable for step in executable_steps)
            can_parallelize = len(executable_steps) > 1 and all_parallelizable

            if can_parallelize:
                # Execute steps in parallel using ThreadPoolExecutor
                logger.info(f"Executing {len(executable_steps)} steps in parallel")

                with ThreadPoolExecutor(max_workers=min(len(executable_steps), 4)) as executor:
                    # Submit all steps
                    future_to_step = {}
                    for step in executable_steps:
                        step_count += 1
                        future = executor.submit(
                            self._execute_step,
                            step,
                            step_count,
                            total_steps,
                            plan.context,
                            thinking_fn,
                            action_fn
                        )
                        future_to_step[future] = step

                    # Wait for completion
                    for future in as_completed(future_to_step):
                        step = future_to_step[future]
                        try:
                            success = future.result()
                            # Add step result to context
                            if success and step.result:
                                plan.context[f"step_{step.id}_result"] = step.result
                        except Exception as e:
                            logger.error(f"Parallel step {step.id} failed: {e}")
                            step.status = StepStatus.FAILED
                            step.error = str(e)
            else:
                # Execute steps sequentially
                for step in executable_steps:
                    step_count += 1
                    success = self._execute_step(
                        step,
                        step_count,
                        total_steps,
                        plan.context,
                        thinking_fn,
                        action_fn
                    )

                    # Add step result to context for next steps
                    if success and step.result:
                        plan.context[f"step_{step.id}_result"] = step.result

        self._display_summary(plan)

        return plan

    def _execute_step(
        self,
        step: Step,
        step_num: int,
        total_steps: int,
        context: Dict[str, Any],
        thinking_fn: Callable[[Step, Dict[str, Any]], str],
        action_fn: Callable[[Step, str, Dict[str, Any]], Dict[str, Any]]
    ) -> bool:
        """
        Execute a single step.

        Returns:
            True if step completed successfully, False otherwise
        """
        start_time = time.time()

        # Display step header
        self.console.print()
        self.console.print("━" * 80, style="cyan")
        self.console.print(
            f"[bold cyan]📍 Step {step_num}/{total_steps}:[/bold cyan] {step.description}"
        )

        try:
            # Phase 1: Thinking
            step.status = StepStatus.THINKING
            if self.show_thinking:
                self.console.print("[dim]💭 Thinking:[/dim]", end=" ")

            thinking = thinking_fn(step, context)
            step.thinking = thinking

            if self.show_thinking:
                # Wrap thinking text nicely
                thinking_lines = thinking.split("\n")
                for i, line in enumerate(thinking_lines):
                    if i == 0:
                        self.console.print(f"[italic]{line}[/italic]")
                    else:
                        self.console.print(f"           [italic]{line}[/italic]")

            # Phase 2: Execution
            step.status = StepStatus.EXECUTING
            if self.show_actions:
                self.console.print("[bold yellow]⚙️  Executing...[/bold yellow]")

            result = action_fn(step, thinking, context)
            step.result = result
            step.status = StepStatus.COMPLETED

            # Display result
            if result.get("success"):
                self.console.print(f"[bold green]✅ {result.get('message', 'Completed')}[/bold green]")

                # Show key outputs
                if "output" in result and result["output"]:
                    output = result["output"]
                    if isinstance(output, str):
                        # Limit output length
                        if len(output) > 500:
                            output = output[:500] + "..."
                        self.console.print(f"[dim]{output}[/dim]")
                    elif isinstance(output, dict):
                        for key, value in list(output.items())[:5]:  # Show first 5 keys
                            self.console.print(f"   [dim]- {key}: {value}[/dim]")
            else:
                raise Exception(result.get("error", "Unknown error"))

            step.duration = time.time() - start_time
            return True

        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = str(e)
            step.duration = time.time() - start_time

            self.console.print(f"[bold red]❌ Failed: {str(e)}[/bold red]")
            logger.error(f"Step {step.id} failed: {e}")

            return False

    def _display_summary(self, plan: Plan):
        """Display execution summary."""
        self.console.print()
        self.console.print("━" * 80, style="green")
        self.console.print()

        # Count statuses
        completed = sum(1 for s in plan.steps if s.status == StepStatus.COMPLETED)
        failed = sum(1 for s in plan.steps if s.status == StepStatus.FAILED)
        skipped = sum(1 for s in plan.steps if s.status == StepStatus.SKIPPED)

        # Summary table
        table = Table(show_header=False, box=None)
        table.add_column("Label", style="bold")
        table.add_column("Value")

        table.add_row("📊 Execution Summary", "")
        table.add_row("  Completed", f"[green]{completed}/{len(plan.steps)}[/green]")
        if failed > 0:
            table.add_row("  Failed", f"[red]{failed}[/red]")
        if skipped > 0:
            table.add_row("  Skipped", f"[yellow]{skipped}[/yellow]")

        total_duration = sum(s.duration for s in plan.steps)
        table.add_row("  Total time", f"{total_duration:.1f}s")

        self.console.print(table)
        self.console.print()

        # Show failed steps
        if failed > 0:
            self.console.print("[bold red]Failed Steps:[/bold red]")
            for step in plan.steps:
                if step.status == StepStatus.FAILED:
                    self.console.print(f"  • Step {step.id}: {step.description}")
                    self.console.print(f"    [dim]Error: {step.error}[/dim]")
