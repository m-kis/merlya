"""
CI/CD tools for Merlya agents.

Provides tools for agents to interact with CI/CD platforms.
These tools are platform-agnostic and adapt to available platforms.
"""

from typing import Annotated, Optional

from merlya.utils.logger import logger

# Lazy-loaded singletons
_platform_manager = None
_learning_engine = None


def _get_platform_manager():
    """Get or create platform manager."""
    global _platform_manager
    if _platform_manager is None:
        from merlya.ci import CIPlatformManager
        _platform_manager = CIPlatformManager()
    return _platform_manager


def _get_learning_engine():
    """Get or create learning engine."""
    global _learning_engine
    if _learning_engine is None:
        from merlya.ci import CILearningEngine
        _learning_engine = CILearningEngine()
    return _learning_engine


def get_ci_status() -> str:
    """
    Get current CI/CD status and detected platforms.

    Returns:
        Summary of detected platforms and recent run status
    """
    logger.info("🔄 Tool: get_ci_status")

    manager = _get_platform_manager()
    detected = manager.detect_platforms()

    if not detected:
        return "❌ No CI/CD platforms detected. Make sure workflow files exist or CLI tools are installed."

    lines = ["📊 CI/CD STATUS", ""]

    # List detected platforms
    lines.append("Detected Platforms:")
    for d in detected:
        status = "✅" if manager.get_platform(d.platform) else "⚠️"
        lines.append(f"  {status} {d.platform.value} ({d.detection_source}, {d.confidence:.0%})")

    # Get recent runs from best platform
    platform = manager.get_platform()
    if platform:
        lines.append("")
        lines.append("Recent Runs:")

        try:
            runs = platform.list_runs(limit=5)
            for run in runs:
                if run.is_failed:
                    icon = "❌"
                elif run.is_running:
                    icon = "⏳"
                else:
                    icon = "✅"
                lines.append(f"  {icon} {run.name[:40]} ({run.id})")
        except Exception as e:
            lines.append(f"  ⚠️ Could not fetch runs: {e}")

    return "\n".join(lines)


def list_ci_workflows() -> str:
    """
    List all available CI/CD workflows.

    Returns:
        List of workflows with their IDs and status
    """
    logger.info("📋 Tool: list_ci_workflows")

    platform = _get_platform_manager().get_platform()
    if not platform:
        return "❌ No CI/CD platform available"

    try:
        workflows = platform.list_workflows()
    except Exception as e:
        return f"❌ Failed to list workflows: {e}"

    if not workflows:
        return "📋 No workflows found"

    lines = ["📋 WORKFLOWS", ""]
    for wf in workflows:
        state_icon = "🟢" if wf.state == "active" else "🟡"
        lines.append(f"  {state_icon} {wf.name}")
        lines.append(f"     ID: {wf.id}")
        if wf.path:
            lines.append(f"     Path: {wf.path}")
        lines.append("")

    return "\n".join(lines)


def list_ci_runs(
    limit: Annotated[int, "Maximum number of runs to list"] = 10,
    workflow_id: Annotated[Optional[str], "Filter by workflow ID"] = None,
) -> str:
    """
    List recent CI/CD runs.

    Args:
        limit: Maximum number of runs to return
        workflow_id: Optional workflow ID to filter by

    Returns:
        List of runs with their status
    """
    logger.info(f"📋 Tool: list_ci_runs (limit={limit}, workflow={workflow_id})")

    platform = _get_platform_manager().get_platform()
    if not platform:
        return "❌ No CI/CD platform available"

    try:
        runs = platform.list_runs(workflow_id=workflow_id, limit=limit)
    except Exception as e:
        return f"❌ Failed to list runs: {e}"

    if not runs:
        return "📋 No runs found"

    lines = ["📋 RECENT RUNS", ""]

    for run in runs:
        if run.is_failed:
            icon = "❌"
            status = "Failed"
        elif run.is_running:
            icon = "⏳"
            status = "Running"
        else:
            icon = "✅"
            status = run.conclusion or "Success"

        lines.append(f"{icon} {run.name}")
        lines.append(f"   ID: {run.id}")
        lines.append(f"   Status: {status}")
        lines.append(f"   Branch: {run.branch}")
        if run.created_at:
            lines.append(f"   Time: {run.created_at.strftime('%Y-%m-%d %H:%M')}")
        if run.url:
            lines.append(f"   URL: {run.url}")
        lines.append("")

    return "\n".join(lines)


def analyze_ci_failure(
    run_id: Annotated[str, "The run ID to analyze"],
) -> str:
    """
    Analyze why a CI/CD run failed.

    Args:
        run_id: The ID of the failed run

    Returns:
        Detailed analysis with error type, summary, and suggestions
    """
    logger.info(f"🔍 Tool: analyze_ci_failure (run_id={run_id})")

    manager = _get_platform_manager()
    platform = manager.get_platform()
    if not platform:
        return "❌ No CI/CD platform available"

    # Get run details
    try:
        run = platform.get_run(run_id)
        if not run:
            return f"❌ Run {run_id} not found"

        logs = platform.get_run_logs(run_id, failed_only=True)
    except Exception as e:
        return f"❌ Failed to fetch run details: {e}"

    # Analyze with learning engine
    engine = _get_learning_engine()
    detected = manager.detect_platforms()
    platform_name = detected[0].platform.value if detected else "unknown"

    insights = engine.get_insights(run, logs, platform=platform_name)

    # Format output
    lines = ["🔍 FAILURE ANALYSIS", ""]

    lines.append(f"Run: {run.name}")
    lines.append(f"ID: {run_id}")
    lines.append(f"Error Type: {insights.error_type.value}")
    lines.append(f"Confidence: {insights.confidence:.0%}")
    lines.append("")

    lines.append("Summary:")
    lines.append(f"  {insights.summary}")
    lines.append("")

    if insights.suggestions:
        lines.append("Suggestions:")
        for i, suggestion in enumerate(insights.suggestions, 1):
            lines.append(f"  {i}. {suggestion}")
        lines.append("")

    if insights.learned_fix:
        lines.append("💡 Learned Fix:")
        lines.append(f"  {insights.learned_fix}")
        lines.append("")

    if insights.similar_incidents:
        lines.append(f"📚 Similar Past Incidents: {len(insights.similar_incidents)}")
        for inc in insights.similar_incidents[:2]:
            lines.append(f"  - {inc.get('title', 'Unknown')}")
        lines.append("")

    if insights.pattern_matches:
        lines.append("⚠️ Detected Patterns:")
        for pattern in insights.pattern_matches:
            lines.append(f"  - {pattern}")

    return "\n".join(lines)


def trigger_ci_workflow(
    workflow_id: Annotated[str, "The workflow ID or name to trigger"],
    ref: Annotated[str, "Git ref (branch/tag) to run on"] = "main",
) -> str:
    """
    Trigger a CI/CD workflow.

    Args:
        workflow_id: The workflow to trigger
        ref: Git reference (branch or tag) to run on

    Returns:
        Result with new run ID
    """
    logger.info(f"🚀 Tool: trigger_ci_workflow (workflow={workflow_id}, ref={ref})")

    platform = _get_platform_manager().get_platform()
    if not platform:
        return "❌ No CI/CD platform available"

    try:
        run = platform.trigger_workflow(workflow_id, ref=ref)
        lines = [
            "✅ WORKFLOW TRIGGERED",
            "",
            f"Run ID: {run.id}",
            f"Workflow: {run.workflow_name or workflow_id}",
            f"Branch: {ref}",
        ]
        if run.url:
            lines.append(f"URL: {run.url}")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to trigger workflow: {e}"


def retry_ci_run(
    run_id: Annotated[str, "The run ID to retry"],
    failed_only: Annotated[bool, "Only retry failed jobs"] = True,
) -> str:
    """
    Retry a failed CI/CD run.

    Args:
        run_id: The run to retry
        failed_only: If True, only retry failed jobs

    Returns:
        Result with new run ID
    """
    logger.info(f"🔄 Tool: retry_ci_run (run_id={run_id}, failed_only={failed_only})")

    platform = _get_platform_manager().get_platform()
    if not platform:
        return "❌ No CI/CD platform available"

    try:
        run = platform.retry_run(run_id, failed_only=failed_only)
        lines = [
            "✅ RUN RETRIED",
            "",
            f"New Run ID: {run.id}",
            f"Mode: {'Failed jobs only' if failed_only else 'Full retry'}",
        ]
        if run.url:
            lines.append(f"URL: {run.url}")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to retry run: {e}"


def cancel_ci_run(
    run_id: Annotated[str, "The run ID to cancel"],
) -> str:
    """
    Cancel a running CI/CD workflow.

    Args:
        run_id: The run to cancel

    Returns:
        Success or failure message
    """
    logger.info(f"🛑 Tool: cancel_ci_run (run_id={run_id})")

    platform = _get_platform_manager().get_platform()
    if not platform:
        return "❌ No CI/CD platform available"

    try:
        if platform.cancel_run(run_id):
            return f"✅ Run {run_id} cancelled successfully"
        else:
            return f"❌ Failed to cancel run {run_id}"

    except Exception as e:
        return f"❌ Failed to cancel run: {e}"


def check_ci_permissions() -> str:
    """
    Check available CI/CD permissions and authentication status.

    Returns:
        Permission report showing what operations are available
    """
    logger.info("🔐 Tool: check_ci_permissions")

    platform = _get_platform_manager().get_platform()
    if not platform:
        return "❌ No CI/CD platform available"

    try:
        report = platform.check_permissions()
    except Exception as e:
        return f"❌ Failed to check permissions: {e}"

    lines = ["🔐 CI/CD PERMISSIONS", ""]

    auth_icon = "✅" if report.authenticated else "❌"
    lines.append(f"{auth_icon} Authenticated: {'Yes' if report.authenticated else 'No'}")

    read_icon = "✅" if report.can_read else "❌"
    lines.append(f"{read_icon} Can Read: {'Yes' if report.can_read else 'No'}")

    write_icon = "✅" if report.can_write else "⚠️"
    lines.append(f"{write_icon} Can Write: {'Yes' if report.can_write else 'Unknown'}")

    admin_icon = "✅" if report.can_admin else "➖"
    lines.append(f"{admin_icon} Admin Access: {'Yes' if report.can_admin else 'No'}")

    lines.append("")

    if report.permissions:
        lines.append("Granted Permissions:")
        for perm in report.permissions:
            lines.append(f"  ✅ {perm}")

    if report.missing_permissions:
        lines.append("")
        lines.append("Missing Permissions:")
        for perm in report.missing_permissions:
            lines.append(f"  ⚠️ {perm}")

    return "\n".join(lines)


def debug_most_recent_failure() -> str:
    """
    Find and analyze the most recent failed CI/CD run.

    Returns:
        Analysis of the most recent failure
    """
    logger.info("🔍 Tool: debug_most_recent_failure")

    platform = _get_platform_manager().get_platform()
    if not platform:
        return "❌ No CI/CD platform available"

    try:
        runs = platform.list_runs(limit=10)
        failed_runs = [r for r in runs if r.is_failed]

        if not failed_runs:
            return "✅ No recent failed runs found!"

        # Analyze the most recent failure
        return analyze_ci_failure(failed_runs[0].id)

    except Exception as e:
        return f"❌ Failed to find recent failures: {e}"


# Export tools for registration
CI_TOOLS = [
    get_ci_status,
    list_ci_workflows,
    list_ci_runs,
    analyze_ci_failure,
    trigger_ci_workflow,
    retry_ci_run,
    cancel_ci_run,
    check_ci_permissions,
    debug_most_recent_failure,
]
