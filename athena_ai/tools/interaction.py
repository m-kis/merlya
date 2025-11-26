"""
User interaction and learning tools.
"""
from typing import Annotated, Optional

from athena_ai.tools.base import get_tool_context, validate_host
from athena_ai.utils.logger import logger


def ask_user(
    question: Annotated[str, "Question to ask the user"]
) -> str:
    """
    Ask the user a question.

    Use when you need clarification, a decision, or missing information.

    Args:
        question: The question

    Returns:
        User's response
    """
    logger.info(f"Tool: ask_user '{question}'")

    print(f"\n❓ [bold cyan]Athena asks:[/bold cyan] {question}")
    try:
        response = input("   > ")
        return f"User response: {response}"
    except (KeyboardInterrupt, EOFError):
        return "User cancelled input."


def remember_skill(
    trigger: Annotated[str, "The problem (e.g. 'how to restart mongo')"],
    solution: Annotated[str, "The solution (e.g. 'systemctl restart mongod')"],
    context: Annotated[str, "Optional tags (e.g. 'linux production')"] = ""
) -> str:
    """
    Teach Athena a new skill (problem-solution pair).

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

    # Ask the user
    print(f"\n❓ [bold cyan]Athena asks:[/bold cyan] {question}")
    try:
        response = input("   > ").strip().lower()
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
