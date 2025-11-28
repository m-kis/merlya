"""
CI/CD command handlers for Athena REPL.

Handles: /cicd, /debug-workflow, /ci-status, /ci-trigger, /ci-analyze
"""


from rich.panel import Panel
from rich.table import Table

from athena_ai.repl.ui import console, print_error, print_info, print_success, print_warning


class CICDCommandHandler:
    """Handles CI/CD-related slash commands."""

    def __init__(self, repl):
        """Initialize with reference to the main REPL instance."""
        self.repl = repl
        self._platform_manager = None
        self._learning_engine = None

    @property
    def platform_manager(self):
        """Lazy-load platform manager."""
        if self._platform_manager is None:
            from athena_ai.ci import CIPlatformManager
            self._platform_manager = CIPlatformManager()
        return self._platform_manager

    @property
    def learning_engine(self):
        """Lazy-load learning engine."""
        if self._learning_engine is None:
            from athena_ai.ci import CILearningEngine
            self._learning_engine = CILearningEngine()
        return self._learning_engine

    def handle_cicd(self, args: list) -> bool:
        """
        Main CI/CD command. Usage:
            /cicd              - Show CI/CD status and available platforms
            /cicd status       - Show recent runs
            /cicd workflows    - List workflows
            /cicd runs [N]     - List last N runs (default 10)
            /cicd analyze <id> - Analyze a specific run
            /cicd trigger <wf> - Trigger a workflow
            /cicd cancel <id>  - Cancel a run
            /cicd retry <id>   - Retry a failed run
        """
        if not args:
            return self._show_cicd_overview()

        subcommand = args[0].lower()
        sub_args = args[1:]

        handlers = {
            "status": self._handle_status,
            "workflows": self._handle_workflows,
            "runs": self._handle_runs,
            "analyze": self._handle_analyze,
            "trigger": self._handle_trigger,
            "cancel": self._handle_cancel,
            "retry": self._handle_retry,
            "permissions": self._handle_permissions,
        }

        handler = handlers.get(subcommand)
        if handler:
            return handler(sub_args)
        else:
            print_error(f"Unknown subcommand: {subcommand}")
            self._show_cicd_help()
            return True

    def handle_debug_workflow(self, args: list) -> bool:
        """
        Debug a CI/CD workflow failure. Usage:
            /debug-workflow           - Debug most recent failed run
            /debug-workflow <run_id>  - Debug specific run
        """
        platform = self._get_platform()
        if not platform:
            return True

        run_id = args[0] if args else None

        # Get the run to debug
        if run_id:
            run = platform.get_run(run_id)
            if not run:
                print_error(f"Run {run_id} not found")
                return True
        else:
            # Get most recent failed run
            runs = platform.list_runs(limit=10)
            failed_runs = [r for r in runs if r.is_failed]
            if not failed_runs:
                print_info("No recent failed runs found")
                return True
            run = failed_runs[0]

        # Get logs
        with console.status("[cyan]Fetching logs...[/cyan]", spinner="dots"):
            logs = platform.get_run_logs(run.id, failed_only=True)

        # Analyze with learning engine
        with console.status("[cyan]Analyzing failure...[/cyan]", spinner="dots"):
            insights = self.learning_engine.get_insights(
                run,
                logs,
                platform=self.platform_manager._detected[0].platform.value if self.platform_manager._detected else "unknown",
            )

        # Display results
        self._display_debug_results(run, insights)
        return True

    def _show_cicd_overview(self) -> bool:
        """Show CI/CD overview."""
        detected = self.platform_manager.detect_platforms()

        if not detected:
            print_warning("No CI/CD platforms detected")
            print_info("Tip: Make sure you have workflow files or CLI tools installed")
            return True

        # Platform detection table
        table = Table(title="Detected CI/CD Platforms", show_header=True)
        table.add_column("Platform", style="cyan")
        table.add_column("Source", style="dim")
        table.add_column("Confidence", style="green")
        table.add_column("Status")

        for d in detected:
            platform = self.platform_manager.get_platform(d.platform)
            status = "[green]Ready[/green]" if platform and platform.is_available() else "[yellow]Limited[/yellow]"

            table.add_row(
                d.platform.value,
                d.detection_source,
                f"{d.confidence:.0%}",
                status,
            )

        console.print(table)

        # Quick status of best platform
        platform, detection = self.platform_manager.get_best_platform()
        if platform:
            console.print()
            runs = platform.list_runs(limit=3)
            if runs:
                self._display_runs_mini(runs, f"Recent runs ({detection.platform.value})")

        return True

    def _handle_status(self, args: list) -> bool:
        """Show CI/CD status."""
        platform = self._get_platform()
        if not platform:
            return True

        # Get recent runs
        runs = platform.list_runs(limit=5)

        if not runs:
            print_info("No recent runs found")
            return True

        # Summary
        failed = sum(1 for r in runs if r.is_failed)
        running = sum(1 for r in runs if r.is_running)
        success = len(runs) - failed - running

        console.print(Panel(
            f"[green]Success: {success}[/green]  "
            f"[red]Failed: {failed}[/red]  "
            f"[yellow]Running: {running}[/yellow]",
            title="CI/CD Status",
        ))

        self._display_runs_table(runs)
        return True

    def _handle_workflows(self, args: list) -> bool:
        """List workflows."""
        platform = self._get_platform()
        if not platform:
            return True

        with console.status("[cyan]Fetching workflows...[/cyan]", spinner="dots"):
            workflows = platform.list_workflows()

        if not workflows:
            print_info("No workflows found")
            return True

        table = Table(title="Workflows", show_header=True)
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="white")
        table.add_column("Path", style="dim")
        table.add_column("State")

        for wf in workflows:
            state_style = "green" if wf.state == "active" else "yellow"
            table.add_row(
                str(wf.id),
                wf.name,
                wf.path or "-",
                f"[{state_style}]{wf.state}[/{state_style}]",
            )

        console.print(table)
        return True

    def _handle_runs(self, args: list) -> bool:
        """List recent runs."""
        platform = self._get_platform()
        if not platform:
            return True

        limit = int(args[0]) if args else 10

        with console.status("[cyan]Fetching runs...[/cyan]", spinner="dots"):
            runs = platform.list_runs(limit=limit)

        if not runs:
            print_info("No runs found")
            return True

        self._display_runs_table(runs)
        return True

    def _handle_analyze(self, args: list) -> bool:
        """Analyze a specific run."""
        if not args:
            print_error("Usage: /cicd analyze <run_id>")
            return True

        platform = self._get_platform()
        if not platform:
            return True

        run_id = args[0]

        with console.status("[cyan]Analyzing run...[/cyan]", spinner="dots"):
            run = platform.get_run(run_id)
            if not run:
                print_error(f"Run {run_id} not found")
                return True

            logs = platform.get_run_logs(run_id, failed_only=True)
            insights = self.learning_engine.get_insights(
                run,
                logs,
                platform=self.platform_manager._detected[0].platform.value if self.platform_manager._detected else "unknown",
            )

        self._display_debug_results(run, insights)
        return True

    def _handle_trigger(self, args: list) -> bool:
        """Trigger a workflow."""
        if not args:
            print_error("Usage: /cicd trigger <workflow_id> [--ref <branch>]")
            return True

        platform = self._get_platform()
        if not platform:
            return True

        workflow_id = args[0]
        ref = "main"

        # Parse --ref flag
        if "--ref" in args:
            ref_idx = args.index("--ref")
            if ref_idx + 1 < len(args):
                ref = args[ref_idx + 1]

        try:
            with console.status(f"[cyan]Triggering workflow {workflow_id}...[/cyan]", spinner="dots"):
                run = platform.trigger_workflow(workflow_id, ref=ref)

            print_success(f"Workflow triggered! Run ID: {run.id}")
            if run.url:
                console.print(f"  URL: [link={run.url}]{run.url}[/link]")

        except Exception as e:
            print_error(f"Failed to trigger workflow: {e}")

        return True

    def _handle_cancel(self, args: list) -> bool:
        """Cancel a running workflow."""
        if not args:
            print_error("Usage: /cicd cancel <run_id>")
            return True

        platform = self._get_platform()
        if not platform:
            return True

        run_id = args[0]

        if platform.cancel_run(run_id):
            print_success(f"Run {run_id} cancelled")
        else:
            print_error(f"Failed to cancel run {run_id}")

        return True

    def _handle_retry(self, args: list) -> bool:
        """Retry a failed run."""
        if not args:
            print_error("Usage: /cicd retry <run_id> [--full]")
            return True

        platform = self._get_platform()
        if not platform:
            return True

        run_id = args[0]
        failed_only = "--full" not in args

        try:
            with console.status(f"[cyan]Retrying run {run_id}...[/cyan]", spinner="dots"):
                run = platform.retry_run(run_id, failed_only=failed_only)

            print_success(f"Run retried! New run ID: {run.id}")
            if run.url:
                console.print(f"  URL: [link={run.url}]{run.url}[/link]")

        except Exception as e:
            print_error(f"Failed to retry run: {e}")

        return True

    def _handle_permissions(self, args: list) -> bool:
        """Check CI/CD permissions."""
        platform = self._get_platform()
        if not platform:
            return True

        with console.status("[cyan]Checking permissions...[/cyan]", spinner="dots"):
            report = platform.check_permissions()

        # Display report
        table = Table(title="CI/CD Permissions", show_header=True)
        table.add_column("Check", style="cyan")
        table.add_column("Status")

        auth_status = "[green]Yes[/green]" if report.authenticated else "[red]No[/red]"
        table.add_row("Authenticated", auth_status)

        read_status = "[green]Yes[/green]" if report.can_read else "[red]No[/red]"
        table.add_row("Can Read", read_status)

        write_status = "[green]Yes[/green]" if report.can_write else "[yellow]Unknown[/yellow]"
        table.add_row("Can Write", write_status)

        admin_status = "[green]Yes[/green]" if report.can_admin else "[dim]No[/dim]"
        table.add_row("Admin Access", admin_status)

        console.print(table)

        if report.permissions:
            console.print(f"\n[green]Granted:[/green] {', '.join(report.permissions)}")

        if report.missing_permissions:
            console.print(f"[yellow]Missing:[/yellow] {', '.join(report.missing_permissions)}")

        return True

    def _get_platform(self):
        """Get best available platform."""
        platform = self.platform_manager.get_platform()
        if not platform:
            print_error("No CI/CD platform available")
            print_info("Tip: Install gh CLI or configure a CI platform")
            return None
        return platform

    def _display_runs_table(self, runs: list) -> None:
        """Display runs in a table."""
        table = Table(show_header=True)
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="white", max_width=40)
        table.add_column("Status")
        table.add_column("Branch", style="dim")
        table.add_column("Time", style="dim")

        for run in runs:
            # Status with color
            if run.is_failed:
                status = "[red]Failed[/red]"
            elif run.is_running:
                status = "[yellow]Running[/yellow]"
            else:
                status = f"[green]{run.conclusion or 'Success'}[/green]"

            # Time
            time_str = ""
            if run.created_at:
                time_str = run.created_at.strftime("%Y-%m-%d %H:%M")

            table.add_row(
                str(run.id),
                run.name[:40],
                status,
                run.branch or "-",
                time_str,
            )

        console.print(table)

    def _display_runs_mini(self, runs: list, title: str) -> None:
        """Display runs in a compact format."""
        lines = []
        for run in runs[:3]:
            if run.is_failed:
                icon = "❌"
            elif run.is_running:
                icon = "⏳"
            else:
                icon = "✅"
            lines.append(f"{icon} {run.name[:30]} ({run.id})")

        console.print(Panel("\n".join(lines), title=title))

    def _display_debug_results(self, run, insights) -> None:
        """Display debugging results."""

        # Header
        console.print(Panel(
            f"[bold]{run.name}[/bold]\n"
            f"ID: {run.id}  Branch: {run.branch}",
            title="Debugging Run",
            border_style="red" if run.is_failed else "yellow",
        ))

        # Error classification
        console.print(f"\n[bold]Error Type:[/bold] {insights.error_type.value}")
        console.print(f"[bold]Confidence:[/bold] {insights.confidence:.0%}")

        # Summary
        console.print(f"\n[bold]Summary:[/bold]\n{insights.summary}")

        # Suggestions
        if insights.suggestions:
            console.print("\n[bold]Suggestions:[/bold]")
            for i, suggestion in enumerate(insights.suggestions, 1):
                console.print(f"  {i}. {suggestion}")

        # Learned fix
        if insights.learned_fix:
            console.print(f"\n[bold green]Learned Fix:[/bold green]\n  {insights.learned_fix}")

        # Similar incidents
        if insights.similar_incidents:
            console.print(f"\n[bold]Similar Past Incidents:[/bold] {len(insights.similar_incidents)}")
            for inc in insights.similar_incidents[:2]:
                console.print(f"  - {inc.get('title', 'Unknown')}")
                if inc.get('solution'):
                    console.print(f"    Solution: {inc['solution'][:100]}")

        # Patterns
        if insights.pattern_matches:
            console.print("\n[bold yellow]Patterns Detected:[/bold yellow]")
            for pattern in insights.pattern_matches:
                console.print(f"  ⚠️ {pattern}")

    def _show_cicd_help(self) -> None:
        """Show CI/CD help."""
        help_text = """
[bold]CI/CD Commands:[/bold]

  /cicd              Show overview and detected platforms
  /cicd status       Show recent run status
  /cicd workflows    List available workflows
  /cicd runs [N]     List last N runs (default 10)
  /cicd analyze <id> Analyze a specific run
  /cicd trigger <wf> Trigger a workflow
  /cicd cancel <id>  Cancel a running workflow
  /cicd retry <id>   Retry a failed run
  /cicd permissions  Check available permissions

  /debug-workflow [id]  Debug a workflow failure
"""
        console.print(help_text)
