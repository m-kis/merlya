"""
Statistics command handler.

Handles: /stats [subcommand]
"""

from typing import TYPE_CHECKING, List

from rich.table import Table

from merlya.repl.ui import console, print_error, print_warning
from merlya.utils.stats_manager import get_stats_manager

if TYPE_CHECKING:
    from merlya.repl import MerlyaREPL


def _format_duration(ms: float) -> str:
    """Format duration in ms to human-readable string."""
    if ms < 1000:
        return f"{int(ms)}ms"
    elif ms < 60000:
        return f"{ms/1000:.1f}s"
    else:
        return f"{ms/60000:.1f}m"


def _format_rate(rate: float) -> str:
    """Format rate as percentage."""
    return f"{rate*100:.1f}%"


class StatsCommandHandler:
    """Handles statistics-related slash commands."""

    def __init__(self, repl: 'MerlyaREPL') -> None:
        """Initialize with reference to the main REPL instance."""
        self.repl = repl
        self.stats_manager = get_stats_manager()

    def handle_stats(self, args: List[str]) -> bool:
        """
        Handle /stats command.

        Subcommands:
            /stats              - Show dashboard summary
            /stats llm          - Show LLM statistics
            /stats queries      - Show query statistics
            /stats actions      - Show action statistics
            /stats embeddings   - Show embedding statistics
            /stats agents       - Show agent task statistics
            /stats session      - Show current session stats
            /stats cleanup [days] - Clean up old metrics
        """
        if not args:
            return self._show_dashboard()

        subcommand = args[0].lower()

        if subcommand == 'llm':
            return self._show_llm_stats(args[1:])
        elif subcommand == 'queries':
            return self._show_query_stats(args[1:])
        elif subcommand == 'actions':
            return self._show_action_stats(args[1:])
        elif subcommand == 'embeddings':
            return self._show_embedding_stats(args[1:])
        elif subcommand == 'agents':
            return self._show_agent_stats(args[1:])
        elif subcommand == 'session':
            return self._show_session_stats()
        elif subcommand == 'cleanup':
            return self._cleanup_metrics(args[1:])
        elif subcommand == 'help':
            return self._show_help()
        else:
            print_warning(f"Unknown subcommand: {subcommand}")
            return self._show_help()

    def _show_dashboard(self, hours: int = 24) -> bool:
        """Show comprehensive dashboard."""
        try:
            stats = self.stats_manager.get_dashboard(hours=hours)

            console.print("\n[bold cyan]📊 Merlya Statistics Dashboard[/bold cyan]")
            console.print(f"[dim]Period: Last {hours} hours | Generated: {stats['generated_at'][:19]}[/dim]\n")

            # Summary panel
            llm = stats.get('llm', {})
            queries = stats.get('queries', {})
            actions = stats.get('actions', {})
            embeddings = stats.get('embeddings', {})
            agents = stats.get('agent_tasks', {})

            # Create summary table
            summary_table = Table(title="Summary", show_header=True, header_style="bold")
            summary_table.add_column("Metric", style="cyan")
            summary_table.add_column("Count", justify="right")
            summary_table.add_column("Success Rate", justify="right")
            summary_table.add_column("Avg Time", justify="right")

            summary_table.add_row(
                "LLM Calls",
                str(llm.get('total_calls', 0)),
                _format_rate(llm.get('success_rate', 0)),
                _format_duration(llm.get('avg_response_time_ms', 0)),
            )
            summary_table.add_row(
                "Queries",
                str(queries.get('total_queries', 0)),
                _format_rate(queries.get('success_rate', 0)),
                _format_duration(queries.get('avg_total_time_ms', 0)),
            )
            summary_table.add_row(
                "Actions",
                str(actions.get('total_actions', 0)),
                _format_rate(actions.get('success_rate', 0)),
                _format_duration(actions.get('avg_duration_ms', 0)),
            )
            summary_table.add_row(
                "Embeddings",
                str(embeddings.get('total_calls', 0)),
                _format_rate(embeddings.get('success_rate', 0)),
                _format_duration(embeddings.get('avg_duration_ms', 0)),
            )
            summary_table.add_row(
                "Agent Tasks",
                str(agents.get('total_tasks', 0)),
                _format_rate(agents.get('success_rate', 0)),
                _format_duration(agents.get('avg_duration_ms', 0)),
            )

            console.print(summary_table)

            # Quick stats
            console.print("\n[bold]Quick Stats:[/bold]")
            console.print(f"  Total tokens used: [green]{llm.get('total_tokens', 0):,}[/green]")
            console.print(f"  Query p50/p95/p99: {_format_duration(queries.get('p50_time_ms', 0))} / "
                         f"{_format_duration(queries.get('p95_time_ms', 0))} / "
                         f"{_format_duration(queries.get('p99_time_ms', 0))}")
            console.print(f"  Total actions executed: [yellow]{actions.get('total_actions', 0)}[/yellow]")
            console.print(f"  Total LLM calls from agents: [cyan]{agents.get('total_llm_calls', 0)}[/cyan]")

            console.print("\n[dim]Use /stats <category> for detailed view (llm, queries, actions, embeddings, agents)[/dim]")
            return True

        except Exception as e:
            print_error(f"Failed to get dashboard: {e}")
            return True

    def _show_llm_stats(self, args: List[str]) -> bool:
        """Show LLM statistics."""
        try:
            hours = int(args[0]) if args else 24
            stats = self.stats_manager.get_llm_stats(hours=hours)

            console.print(f"\n[bold cyan]🤖 LLM Statistics[/bold cyan] (Last {hours}h)\n")

            # Overview
            console.print("[bold]Overview:[/bold]")
            console.print(f"  Total calls: [green]{stats.get('total_calls', 0)}[/green]")
            console.print(f"  Successful: {stats.get('successful_calls', 0)} ({_format_rate(stats.get('success_rate', 0))})")
            console.print(f"  Total tokens: [yellow]{stats.get('total_tokens', 0):,}[/yellow]")
            console.print(f"    - Prompt: {stats.get('total_prompt_tokens', 0):,}")
            console.print(f"    - Completion: {stats.get('total_completion_tokens', 0):,}")

            console.print("\n[bold]Response Times:[/bold]")
            console.print(f"  Average: [cyan]{_format_duration(stats.get('avg_response_time_ms', 0))}[/cyan]")
            console.print(f"  Min: {_format_duration(stats.get('min_response_time_ms', 0))}")
            console.print(f"  Max: {_format_duration(stats.get('max_response_time_ms', 0))}")

            # By provider
            by_provider = stats.get('by_provider', [])
            if by_provider:
                console.print("\n[bold]By Provider:[/bold]")
                provider_table = Table(show_header=True, header_style="bold")
                provider_table.add_column("Provider", style="cyan")
                provider_table.add_column("Calls", justify="right")
                provider_table.add_column("Tokens", justify="right")
                provider_table.add_column("Avg Time", justify="right")

                for p in by_provider:
                    provider_table.add_row(
                        p.get('provider', 'unknown'),
                        str(p.get('calls', 0)),
                        f"{p.get('tokens', 0):,}",
                        _format_duration(p.get('avg_time_ms', 0)),
                    )
                console.print(provider_table)

            # By model
            by_model = stats.get('by_model', [])
            if by_model:
                console.print("\n[bold]By Model (Top 5):[/bold]")
                model_table = Table(show_header=True, header_style="bold")
                model_table.add_column("Model", style="green")
                model_table.add_column("Calls", justify="right")
                model_table.add_column("Avg Time", justify="right")

                for m in by_model[:5]:
                    model_table.add_row(
                        m.get('model', 'unknown'),
                        str(m.get('calls', 0)),
                        _format_duration(m.get('avg_time_ms', 0)),
                    )
                console.print(model_table)

            return True

        except Exception as e:
            print_error(f"Failed to get LLM stats: {e}")
            return True

    def _show_query_stats(self, args: List[str]) -> bool:
        """Show query statistics."""
        try:
            hours = int(args[0]) if args else 24
            stats = self.stats_manager.get_query_stats(hours=hours)

            console.print(f"\n[bold cyan]❓ Query Statistics[/bold cyan] (Last {hours}h)\n")

            console.print("[bold]Overview:[/bold]")
            console.print(f"  Total queries: [green]{stats.get('total_queries', 0)}[/green]")
            console.print(f"  Successful: {stats.get('successful_queries', 0)} ({_format_rate(stats.get('success_rate', 0))})")
            console.print(f"  Total actions triggered: [yellow]{stats.get('total_actions', 0)}[/yellow]")

            console.print("\n[bold]Response Times:[/bold]")
            console.print(f"  Average: [cyan]{_format_duration(stats.get('avg_total_time_ms', 0))}[/cyan]")
            console.print(f"    - LLM time: {_format_duration(stats.get('avg_llm_time_ms', 0))}")
            console.print(f"    - Tool time: {_format_duration(stats.get('avg_tool_time_ms', 0))}")
            console.print(f"  Min: {_format_duration(stats.get('min_time_ms', 0))}")
            console.print(f"  Max: {_format_duration(stats.get('max_time_ms', 0))}")

            console.print("\n[bold]Percentiles:[/bold]")
            console.print(f"  p50: [green]{_format_duration(stats.get('p50_time_ms', 0))}[/green]")
            console.print(f"  p95: [yellow]{_format_duration(stats.get('p95_time_ms', 0))}[/yellow]")
            console.print(f"  p99: [red]{_format_duration(stats.get('p99_time_ms', 0))}[/red]")

            return True

        except Exception as e:
            print_error(f"Failed to get query stats: {e}")
            return True

    def _show_action_stats(self, args: List[str]) -> bool:
        """Show action statistics."""
        try:
            hours = int(args[0]) if args else 24
            stats = self.stats_manager.get_action_stats(hours=hours)

            console.print(f"\n[bold cyan]⚡ Action Statistics[/bold cyan] (Last {hours}h)\n")

            console.print("[bold]Overview:[/bold]")
            console.print(f"  Total actions: [green]{stats.get('total_actions', 0)}[/green]")
            console.print(f"  Successful: {stats.get('successful_actions', 0)} ({_format_rate(stats.get('success_rate', 0))})")

            console.print("\n[bold]Duration:[/bold]")
            console.print(f"  Average: [cyan]{_format_duration(stats.get('avg_duration_ms', 0))}[/cyan]")
            console.print(f"  Min: {_format_duration(stats.get('min_duration_ms', 0))}")
            console.print(f"  Max: {_format_duration(stats.get('max_duration_ms', 0))}")

            # By command type
            by_type = stats.get('by_command_type', [])
            if by_type:
                console.print("\n[bold]By Type:[/bold]")
                type_table = Table(show_header=True, header_style="bold")
                type_table.add_column("Type", style="cyan")
                type_table.add_column("Count", justify="right")
                type_table.add_column("Successful", justify="right")
                type_table.add_column("Avg Duration", justify="right")

                for t in by_type:
                    type_table.add_row(
                        t.get('command_type', 'unknown'),
                        str(t.get('count', 0)),
                        str(t.get('successful', 0)),
                        _format_duration(t.get('avg_duration_ms', 0)),
                    )
                console.print(type_table)

            # By risk level
            by_risk = stats.get('by_risk_level', [])
            if by_risk:
                console.print("\n[bold]By Risk Level:[/bold]")
                risk_table = Table(show_header=True, header_style="bold")
                risk_table.add_column("Risk", style="yellow")
                risk_table.add_column("Count", justify="right")
                risk_table.add_column("Successful", justify="right")

                for r in by_risk:
                    risk_table.add_row(
                        r.get('risk_level', 'unknown'),
                        str(r.get('count', 0)),
                        str(r.get('successful', 0)),
                    )
                console.print(risk_table)

            return True

        except Exception as e:
            print_error(f"Failed to get action stats: {e}")
            return True

    def _show_embedding_stats(self, args: List[str]) -> bool:
        """Show embedding statistics."""
        try:
            hours = int(args[0]) if args else 24
            stats = self.stats_manager.get_embedding_stats(hours=hours)

            console.print(f"\n[bold cyan]🧠 Embedding Statistics[/bold cyan] (Last {hours}h)\n")

            console.print("[bold]Overview:[/bold]")
            console.print(f"  Total calls: [green]{stats.get('total_calls', 0)}[/green]")
            console.print(f"  Successful: {stats.get('successful_calls', 0)} ({_format_rate(stats.get('success_rate', 0))})")
            console.print(f"  Total tokens: [yellow]{stats.get('total_tokens', 0):,}[/yellow]")
            console.print(f"  Total embeddings: {stats.get('total_embeddings', 0)}")

            console.print("\n[bold]Duration:[/bold]")
            console.print(f"  Average: [cyan]{_format_duration(stats.get('avg_duration_ms', 0))}[/cyan]")
            console.print(f"  Min: {_format_duration(stats.get('min_duration_ms', 0))}")
            console.print(f"  Max: {_format_duration(stats.get('max_duration_ms', 0))}")

            # By model
            by_model = stats.get('by_model', [])
            if by_model:
                console.print("\n[bold]By Model:[/bold]")
                model_table = Table(show_header=True, header_style="bold")
                model_table.add_column("Model", style="green")
                model_table.add_column("Calls", justify="right")
                model_table.add_column("Tokens", justify="right")
                model_table.add_column("Avg Duration", justify="right")

                for m in by_model:
                    model_table.add_row(
                        m.get('model', 'unknown'),
                        str(m.get('calls', 0)),
                        f"{m.get('tokens', 0):,}",
                        _format_duration(m.get('avg_duration_ms', 0)),
                    )
                console.print(model_table)

            # By purpose
            by_purpose = stats.get('by_purpose', [])
            if by_purpose:
                console.print("\n[bold]By Purpose:[/bold]")
                purpose_table = Table(show_header=True, header_style="bold")
                purpose_table.add_column("Purpose", style="cyan")
                purpose_table.add_column("Calls", justify="right")
                purpose_table.add_column("Avg Duration", justify="right")

                for p in by_purpose:
                    purpose_table.add_row(
                        p.get('purpose', 'unknown'),
                        str(p.get('calls', 0)),
                        _format_duration(p.get('avg_duration_ms', 0)),
                    )
                console.print(purpose_table)

            return True

        except Exception as e:
            print_error(f"Failed to get embedding stats: {e}")
            return True

    def _show_agent_stats(self, args: List[str]) -> bool:
        """Show agent task statistics."""
        try:
            hours = int(args[0]) if args else 24
            stats = self.stats_manager.get_agent_stats(hours=hours)

            console.print(f"\n[bold cyan]🤖 Agent Task Statistics[/bold cyan] (Last {hours}h)\n")

            console.print("[bold]Overview:[/bold]")
            console.print(f"  Total tasks: [green]{stats.get('total_tasks', 0)}[/green]")
            console.print(f"  Successful: {stats.get('successful_tasks', 0)} ({_format_rate(stats.get('success_rate', 0))})")
            console.print(f"  Total steps: [yellow]{stats.get('total_steps', 0)}[/yellow]")
            console.print(f"  Total LLM calls: [cyan]{stats.get('total_llm_calls', 0)}[/cyan]")

            console.print("\n[bold]Duration:[/bold]")
            console.print(f"  Average: [cyan]{_format_duration(stats.get('avg_duration_ms', 0))}[/cyan]")
            console.print(f"  Min: {_format_duration(stats.get('min_duration_ms', 0))}")
            console.print(f"  Max: {_format_duration(stats.get('max_duration_ms', 0))}")

            # By agent
            by_agent = stats.get('by_agent', [])
            if by_agent:
                console.print("\n[bold]By Agent:[/bold]")
                agent_table = Table(show_header=True, header_style="bold")
                agent_table.add_column("Agent", style="green")
                agent_table.add_column("Tasks", justify="right")
                agent_table.add_column("Successful", justify="right")
                agent_table.add_column("Avg Duration", justify="right")
                agent_table.add_column("LLM Calls", justify="right")

                for a in by_agent:
                    agent_table.add_row(
                        a.get('agent_name', 'unknown'),
                        str(a.get('tasks', 0)),
                        str(a.get('successful', 0)),
                        _format_duration(a.get('avg_duration_ms', 0)),
                        str(a.get('llm_calls', 0)),
                    )
                console.print(agent_table)

            # By task type
            by_task_type = stats.get('by_task_type', [])
            if by_task_type:
                console.print("\n[bold]By Task Type:[/bold]")
                task_table = Table(show_header=True, header_style="bold")
                task_table.add_column("Task Type", style="cyan")
                task_table.add_column("Count", justify="right")
                task_table.add_column("Successful", justify="right")
                task_table.add_column("Avg Duration", justify="right")

                for t in by_task_type:
                    task_table.add_row(
                        t.get('task_type', 'unknown'),
                        str(t.get('tasks', 0)),
                        str(t.get('successful', 0)),
                        _format_duration(t.get('avg_duration_ms', 0)),
                    )
                console.print(task_table)

            return True

        except Exception as e:
            print_error(f"Failed to get agent stats: {e}")
            return True

    def _show_session_stats(self) -> bool:
        """Show current session statistics."""
        try:
            session_id = self.repl.session_manager.current_session_id
            stats = self.stats_manager.get_session_stats(session_id)

            console.print("\n[bold cyan]📊 Session Statistics[/bold cyan]\n")
            console.print(f"  Session ID: [green]{stats.get('session_id', 'unknown')}[/green]")
            console.print(f"  Total queries: {stats.get('total_queries', 0)}")
            console.print(f"  Successful: {stats.get('successful_queries', 0)}")
            console.print(f"  Total time: [cyan]{_format_duration(stats.get('total_time_ms', 0))}[/cyan]")
            console.print(f"  LLM time: {_format_duration(stats.get('total_llm_time_ms', 0))}")
            console.print(f"  Actions executed: [yellow]{stats.get('total_actions', 0)}[/yellow]")

            if stats.get('first_query'):
                console.print(f"  First query: {stats['first_query'][:19]}")
            if stats.get('last_query'):
                console.print(f"  Last query: {stats['last_query'][:19]}")

            return True

        except Exception as e:
            print_error(f"Failed to get session stats: {e}")
            return True

    def _cleanup_metrics(self, args: List[str]) -> bool:
        """Clean up old metrics."""
        try:
            days = int(args[0]) if args else 30
            deleted = self.stats_manager.cleanup(days=days)
            console.print(f"[green]✅ Cleaned up {deleted} metrics older than {days} days[/green]")
            return True
        except Exception as e:
            print_error(f"Failed to cleanup metrics: {e}")
            return True

    def _show_help(self) -> bool:
        """Show help for stats command."""
        console.print("\n[bold]📊 Statistics Commands[/bold]\n")
        console.print("  [cyan]/stats[/cyan]              - Show dashboard summary")
        console.print("  [cyan]/stats llm[/cyan] [hours]  - Show LLM statistics")
        console.print("  [cyan]/stats queries[/cyan] [h]  - Show query statistics")
        console.print("  [cyan]/stats actions[/cyan] [h]  - Show action statistics")
        console.print("  [cyan]/stats embeddings[/cyan]   - Show embedding statistics")
        console.print("  [cyan]/stats agents[/cyan] [h]   - Show agent task statistics")
        console.print("  [cyan]/stats session[/cyan]      - Show current session stats")
        console.print("  [cyan]/stats cleanup[/cyan] [d]  - Clean up metrics older than d days")
        console.print("\n[dim]Default period is 24 hours. Cleanup default is 30 days.[/dim]")
        return True
