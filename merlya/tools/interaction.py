"""
User interaction and learning tools.
"""
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional

from merlya.tools.base import get_tool_context, validate_host
from merlya.utils.logger import logger


def get_user_variables(
    filter_type: Annotated[Optional[str], "Filter by type: 'host', 'config', 'secret', or None for all"] = None
) -> str:
    """
    Get user-defined variables from the session.

    Use this tool when the user asks about their variables, wants to see
    what variables are defined, or references a @variable.

    Args:
        filter_type: Optional type filter ('host', 'config', 'secret', or None for all)

    Returns:
        Formatted list of variables with their types and values (secrets are masked)
    """
    ctx = get_tool_context()
    logger.info(f"Tool: get_user_variables (filter_type={filter_type})")

    if not ctx.credentials:
        return "❌ Credential manager not available"

    try:
        from merlya.security.credentials import VariableType

        # Get all typed variables
        variables = ctx.credentials.list_variables_typed()

        if not variables:
            return "ℹ️ No user variables defined.\n\nUse `/variables set <key> <value>` to define a variable, then reference it with @key in your queries."

        # Filter by type if specified
        if filter_type:
            try:
                target_type = VariableType(filter_type.lower())
                variables = {
                    k: v for k, v in variables.items()
                    if v[1] == target_type
                }
                if not variables:
                    return f"ℹ️ No variables of type '{filter_type}' defined."
            except ValueError:
                return f"❌ Invalid type filter '{filter_type}'. Valid types: host, config, secret"

        # Format output
        output_lines = ["📋 **User Variables:**", ""]
        for key, (value, var_type) in sorted(variables.items()):
            # Mask secrets
            if var_type == VariableType.SECRET:
                display_value = "********"
            elif len(value) > 80:
                display_value = value[:40] + "..." + value[-35:]
            else:
                display_value = value

            type_emoji = {"host": "🖥️", "config": "⚙️", "secret": "🔐"}.get(var_type.value, "📌")
            output_lines.append(f"- **@{key}** ({type_emoji} {var_type.value}): `{display_value}`")

        output_lines.extend([
            "",
            "💡 Use @variable_name in your queries to substitute the value.",
            "   Example: 'check status on @prodserver'"
        ])

        return "\n".join(output_lines)

    except Exception as e:
        logger.error(f"Failed to get variables: {e}")
        return f"❌ Error retrieving variables: {e}"


def get_variable_value(
    variable_name: Annotated[str, "Name of the variable (without @)"]
) -> str:
    """
    Get the value of a specific user variable.

    Use this when the user asks about a specific variable like @Test.

    Args:
        variable_name: Name of the variable (without the @ prefix)

    Returns:
        The variable value and type, or error if not found
    """
    ctx = get_tool_context()
    logger.info(f"Tool: get_variable_value '{variable_name}'")

    if not ctx.credentials:
        return "❌ Credential manager not available"

    try:
        from merlya.security.credentials import VariableType

        # Clean up variable name (remove @ if present)
        clean_name = variable_name.lstrip('@')

        # Get variable value
        value = ctx.credentials.get_variable(clean_name)
        if value is None:
            # List available variables as suggestion
            available = list(ctx.credentials.list_variables().keys())
            if available:
                suggestions = ", ".join([f"@{v}" for v in available[:5]])
                return f"❌ Variable '@{clean_name}' not found.\n\nAvailable variables: {suggestions}"
            return f"❌ Variable '@{clean_name}' not found. No variables are defined yet."

        # Get type
        var_type = ctx.credentials.get_variable_type(clean_name)

        # Mask secrets
        if var_type == VariableType.SECRET:
            display_value = "********"
            return f"🔐 **@{clean_name}** (secret): `{display_value}`\n\n_Secret values are never displayed for security._"
        else:
            type_emoji = {"host": "🖥️", "config": "⚙️"}.get(var_type.value, "📌")
            return f"{type_emoji} **@{clean_name}** ({var_type.value}): `{value}`"

    except Exception as e:
        logger.error(f"Failed to get variable: {e}")
        return f"❌ Error retrieving variable: {e}"


def ask_user(
    question: Annotated[str, "Question to ask the user"]
) -> str:
    """
    Ask the user a question.

    Use when you need clarification, a decision, or missing information.

    Args:
        question: The question

    Returns:
        User's response with continuation instructions
    """
    from merlya.agents.orchestrator_service.continuation import (
        ContinuationDecision,
        get_continuation_detector,
    )

    ctx = get_tool_context()
    logger.info(f"Tool: ask_user '{question}'")

    # Print question with Rich formatting
    ctx.console.print(f"\n❓ [bold cyan]Merlya asks:[/bold cyan] {question}")
    # Use context's get_user_input which handles spinner pause
    try:
        response = ctx.get_user_input("   > ")

        # Analyze response to detect if it's a correction
        detector = get_continuation_detector()
        continuation = detector.analyze_user_response(response, agent_question=question)

        if continuation.decision == ContinuationDecision.CONTINUE:
            # User provided a correction or confirmation to continue
            if continuation.next_action:
                return (
                    f"User response: {response}\n\n"
                    f"**CORRECTION DETECTED**: {continuation.reason}\n"
                    f"**ACTION REQUIRED**: {continuation.next_action}\n\n"
                    f"⚠️ IMPORTANT: CONTINUE with the original task using this corrected information. "
                    f"Do NOT terminate until the original task is FULLY COMPLETE."
                )
            else:
                return (
                    f"User response: {response}\n\n"
                    f"**IMPORTANT**: Now continue with the original task using this information. "
                    f"Do NOT terminate until the task is fully complete."
                )
        else:
            # Normal response
            return (
                f"User response: {response}\n\n"
                f"**IMPORTANT**: Process this information and continue with the original task. "
                f"Do NOT terminate until the task is fully complete."
            )
    except (KeyboardInterrupt, EOFError):
        return "User cancelled input. Task aborted. TERMINATE."


def remember_skill(
    trigger: Annotated[str, "The problem (e.g. 'how to restart mongo')"],
    solution: Annotated[str, "The solution (e.g. 'systemctl restart mongod')"],
    context: Annotated[str, "Optional tags (e.g. 'linux production')"] = ""
) -> str:
    """
    Teach Merlya a new skill (problem-solution pair).

    Args:
        trigger: Problem description
        solution: The solution
        context: Optional tags

    Returns:
        Confirmation
    """
    ctx = get_tool_context()
    logger.info(f"Tool: remember_skill '{trigger}'")

    if ctx.context_memory and hasattr(ctx.context_memory, 'skill_store'):
        ctx.context_memory.skill_store.add_skill(trigger, solution, context)
        return f"✅ Learned: When '{trigger}', do '{solution}'"

    return "❌ Memory system not available"


def recall_skill(
    query: Annotated[str, "Search query for skills"]
) -> str:
    """
    Search learned skills.

    Args:
        query: Search query

    Returns:
        Matching skills
    """
    ctx = get_tool_context()
    logger.info(f"Tool: recall_skill '{query}'")

    if ctx.context_memory and hasattr(ctx.context_memory, 'skill_store'):
        summary = ctx.context_memory.skill_store.get_skill_summary(query)
        if summary:
            return summary
        return f"❌ No skills found for '{query}'"

    return "❌ Memory system not available"


def request_elevation(
    target: Annotated[str, "Target host where command failed"],
    command: Annotated[str, "The command that failed due to permissions"],
    error_message: Annotated[str, "The permission error message"],
    reason: Annotated[Optional[str], "Why elevation is needed"] = None
) -> str:
    """
    Request privilege escalation after a permission error.

    Use this tool when a command fails with "Permission denied" or similar.
    It asks the user for confirmation before retrying with elevated privileges.

    Args:
        target: Target host where the command failed
        command: The original command that failed
        error_message: The error message received
        reason: Optional explanation for the user

    Returns:
        Result of the elevated command, or denial message
    """
    ctx = get_tool_context()
    logger.info(f"Tool: request_elevation on {target} for '{command}'")

    # Validate host
    is_valid, message = validate_host(target)
    if not is_valid:
        return f"❌ BLOCKED: Invalid host '{target}'\n\n{message}"

    # Check if we have required dependencies
    if not ctx.permissions:
        return "❌ Permission manager not available"
    if not ctx.executor:
        return "❌ Command executor not available"

    # Detect elevation capabilities
    try:
        capabilities = ctx.permissions.detect_capabilities(target)
    except Exception as e:
        logger.warning(f"Failed to detect capabilities: {e}")
        return f"❌ Cannot detect elevation capabilities: {e}"

    # Check if elevation is possible
    elevation_method = capabilities.get('elevation_method')
    if not elevation_method or elevation_method == 'none':
        if capabilities.get('is_root'):
            return "❌ Already running as root - elevation not needed"
        return (
            "❌ No elevation method available on this host.\n"
            f"User: {capabilities.get('user')}\n"
            f"Sudo: {'Yes' if capabilities.get('has_sudo') else 'No'}\n"
            f"Su: {'Yes' if capabilities.get('has_su') else 'No'}"
        )

    # Format the question for the user
    method_desc = {
        'sudo': 'sudo (passwordless)',
        'sudo_with_password': 'sudo (may require password)',
        'su': 'su (switch to root)',
        'doas': 'doas',
    }.get(elevation_method, elevation_method)

    reason_text = f"\nReason: {reason}" if reason else ""
    question = (
        f"🔐 Permission denied for:\n"
        f"   Command: {command}\n"
        f"   Error: {error_message[:200]}\n"
        f"   Host: {target}\n"
        f"   Available method: {method_desc}{reason_text}\n\n"
        f"Do you want me to retry with elevated privileges? (yes/no)"
    )

    # Print question with Rich formatting
    ctx.console.print(f"\n❓ [bold cyan]Merlya asks:[/bold cyan] {question}")
    # Use context's get_user_input which handles spinner pause
    try:
        response = ctx.get_user_input("   > ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        return "❌ Elevation cancelled by user."

    # Check response
    if response not in ('yes', 'y', 'oui', 'o', 'да', '1'):
        return f"❌ Elevation declined by user (response: '{response}')"

    # Elevate and execute
    try:
        elevated_command = ctx.permissions.elevate_command(command, target)
        logger.info(f"Executing elevated command: {elevated_command}")
        result = ctx.executor.execute(target, elevated_command, confirm=True)
    except Exception as e:
        logger.warning(f"Elevated execution failed: {e}")
        return f"❌ Elevated execution failed: {e}"

    if result['success']:
        output = result.get('stdout') or "(no output)"
        return f"✅ SUCCESS (elevated with {method_desc})\n\nOutput:\n{output}"
    else:
        error = result.get('error') or result.get('stderr') or 'Unknown error'
        return f"❌ FAILED (even with elevation)\n\nError:\n{error}"


def _cleanup_old_reports(reports_dir: Path, max_age_days: int = 7) -> int:
    """
    Remove reports older than max_age_days.

    Args:
        reports_dir: Directory containing reports
        max_age_days: Maximum age in days before deletion

    Returns:
        Number of files deleted
    """
    deleted = 0
    cutoff = datetime.now().timestamp() - (max_age_days * 86400)
    try:
        for report in reports_dir.glob("*.md"):
            if report.stat().st_mtime < cutoff:
                report.unlink()
                deleted += 1
                logger.debug(f"Cleaned up old report: {report}")
    except Exception as e:
        logger.warning(f"Error during report cleanup: {e}")
    return deleted


def save_report(
    title: Annotated[str, "Report title (e.g., 'Infrastructure Analysis', 'HAProxy Config')"],
    content: Annotated[str, "Full report content in markdown format"],
    filename: Annotated[Optional[str], "Optional filename (without extension)"] = None
) -> str:
    """
    Save a detailed report to a file for the user to access later.

    Use this tool when you have generated a long analysis, documentation,
    or detailed findings that the user might want to reference later.

    The report is saved to /tmp/merlya_reports/ and the path is returned.
    Old reports (>7 days) are automatically cleaned up.

    Args:
        title: Report title (used in the file header)
        content: Full markdown content of the report
        filename: Optional custom filename (auto-generated if not provided)

    Returns:
        Path to the saved report file
    """
    import os

    # Constants
    MAX_REPORT_SIZE = 10 * 1024 * 1024  # 10 MB
    MAX_TITLE_LENGTH = 200
    MAX_FILENAME_LENGTH = 50
    CLEANUP_MAX_AGE_DAYS = 7

    ctx = get_tool_context()
    logger.info(f"Tool: save_report '{title[:50]}...'")

    # Input validation
    if not title or not title.strip():
        return "❌ Title cannot be empty"
    if not content or not content.strip():
        return "❌ Content cannot be empty"
    if len(title) > MAX_TITLE_LENGTH:
        return f"❌ Title too long (max {MAX_TITLE_LENGTH} characters)"

    try:
        # Create reports directory (configurable via env var)
        base_dir = os.getenv("MERLYA_REPORTS_DIR", str(Path(tempfile.gettempdir()) / "merlya_reports"))
        reports_dir = Path(base_dir)
        reports_dir.mkdir(exist_ok=True, parents=True)

        # Cleanup old reports (run periodically, not blocking)
        _cleanup_old_reports(reports_dir, CLEANUP_MAX_AGE_DAYS)

        # Generate safe filename (prevent path traversal)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if filename:
            # Remove path separators and parent directory references
            clean_name = filename.replace('/', '_').replace('\\', '_').replace('..', '_')
            safe_filename = "".join(c if c.isalnum() or c in "-_" else "_" for c in clean_name[:MAX_FILENAME_LENGTH])
            filepath = reports_dir / f"{safe_filename}_{timestamp}.md"
        else:
            safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in title[:30])
            filepath = reports_dir / f"report_{safe_title}_{timestamp}.md"

        # Verify resolved path is within reports_dir (prevent path traversal)
        if not str(filepath.resolve()).startswith(str(reports_dir.resolve())):
            logger.warning(f"Path traversal attempt detected: {filename}")
            return "❌ Invalid filename: path traversal detected"

        # Build full report with header
        full_content = f"""# {title}

**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**By:** Merlya Infrastructure Assistant

---

{content}

---
*Report generated by Merlya. Use `cat {filepath}` to view this report again.*
"""

        # Check file size before writing
        if len(full_content.encode('utf-8')) > MAX_REPORT_SIZE:
            return f"❌ Report too large ({len(full_content):,} bytes). Maximum size: {MAX_REPORT_SIZE:,} bytes"

        # Write file
        filepath.write_text(full_content, encoding="utf-8")
        logger.info(f"Report saved to {filepath}")

        # Notify user via console
        ctx.console.print(f"\n📄 [bold green]Report saved:[/bold green] {filepath}")

        return f"✅ Report saved to: {filepath}\n\nThe user can view it with: `cat {filepath}`"

    except OSError as e:
        logger.error(f"Failed to save report (filesystem error): {e}", exc_info=True)
        return f"❌ Failed to save report: {e} (Check disk space and permissions)"
    except Exception as e:
        logger.error(f"Failed to save report: {e}", exc_info=True)
        return f"❌ Failed to save report: {e}"
