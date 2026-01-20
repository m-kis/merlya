"""
Merlya Commands - Metrics handlers.

Commands for viewing metrics and performance data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from merlya.commands.registry import CommandResult, command
from merlya.core.metrics import get_metrics_summary

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


@command("metrics", "Show metrics summary", "/metrics", aliases=["m"])
async def cmd_metrics(ctx: SharedContext, _args: list[str]) -> CommandResult:
    """
    Show in-memory metrics summary.

    Usage:
        /metrics

    Displays:
        - Command execution counts and status
        - SSH operation stats (count, avg duration, max duration)
        - LLM API call counts by provider/model
        - Pipeline execution counts and status
    """
    summary = get_metrics_summary()

    # If no metrics collected yet
    if "0 total" in summary or summary.count("\n") <= 2:
        ctx.ui.panel(
            "No metrics collected yet.\n\n"
            "Metrics are tracked automatically when you:\n"
            "  • Execute commands (SSH, bash, etc.)\n"
            "  • Make LLM calls\n"
            "  • Run pipelines",
            title="📊 Metrics",
            style="info",
        )
        return CommandResult(success=True, message="")

    # Display metrics
    ctx.ui.panel(summary, title="📊 Metrics Summary", style="success")

    return CommandResult(success=True, message="")
