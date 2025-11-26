"""
User interaction and learning tools.
"""
from typing import Annotated

from athena_ai.tools.base import get_tool_context
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
