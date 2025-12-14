"""
Merlya Router - Handler.

Handles user messages with fast path, skill, and LLM agent routing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from merlya.agent import MerlyaAgent
    from merlya.agent.main import AgentResponse
    from merlya.core.context import SharedContext
    from merlya.router.classifier import RouterResult
    from merlya.router.intent_classifier import AgentMode
else:
    from merlya.router.intent_classifier import AgentMode

# Constants
# Minimum confidence score (0.0-1.0) to route to skill instead of LLM agent.
# Set to 0.88 to avoid false positives - skills should only trigger when confident
# Lower values cause skills like service_check to trigger for config queries
# A score of 0.87 for "config cloudflared" -> service_check shows embeddings can be wrong
SKILL_CONFIDENCE_THRESHOLD = 0.88

# Note: Timeout is now handled by SubagentOrchestrator with ActivityTimeout
# which provides intelligent idle-based timeout detection

# Patterns indicating sensitive variable names (case-insensitive)
SENSITIVE_NAME_PATTERNS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "auth",
    "credential",
    "private",
    "key",
)

# Redacted placeholder for sensitive values
REDACTED_PLACEHOLDER = "********"


def _is_sensitive_variable(name: str) -> bool:
    """Check if a variable name suggests sensitive content."""
    name_lower = name.lower()
    return any(pattern in name_lower for pattern in SENSITIVE_NAME_PATTERNS)


def _mask_value(value: str, reveal_chars: int = 4) -> str:
    """Mask a value, optionally revealing a few characters."""
    if len(value) <= reveal_chars:
        return REDACTED_PLACEHOLDER
    return value[:reveal_chars] + REDACTED_PLACEHOLDER


_EXECUTION_TOOL_CATEGORIES = {"system", "files", "security", "docker", "kubernetes"}
_NO_TARGET_TOOL_CATEGORIES = {"web_search"}
_LOCAL_TARGET_ALIASES = {
    "local",
    "localhost",
    "ici",
    "en local",
    "ma machine",
    "mon poste",
    "this machine",
    "my machine",
    "locally",
}


def _normalize_target_input(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _needs_target_clarification(route_result: RouterResult) -> bool:
    """Return True if request likely requires execution but no host is specified.

    Security-first: never assume a default remote target.
    """
    if route_result.entities.get("hosts"):
        return False

    tools_set = set(route_result.tools or [])
    if tools_set & _NO_TARGET_TOOL_CATEGORIES:
        return False

    # Only prompt when the router believes we're in an execution-oriented mode.
    if route_result.mode not in {AgentMode.DIAGNOSTIC, AgentMode.REMEDIATION}:
        return False

    return bool(tools_set & _EXECUTION_TOOL_CATEGORIES)


async def _find_similar_inventory_hosts(ctx: SharedContext, query: str) -> list[str]:
    """Find similar inventory host names for suggestions (no DNS/local resolution)."""
    try:
        all_hosts = await ctx.hosts.get_all()
    except Exception:
        return []

    q = query.lower()
    matches: list[str] = []
    for host in all_hosts:
        name = getattr(host, "name", "")
        if not isinstance(name, str):
            continue
        nl = name.lower()
        if q in nl or nl in q:
            matches.append(name)
    return matches[:5]


async def _clarify_target(
    ctx: SharedContext,
    user_input: str,
) -> tuple[str, str | None] | None:
    """Ask the user to choose a target: local or an inventory host name.

    Returns:
        Tuple of (target_type, host_name) where:
        - ("local", None) for local execution
        - ("remote", "<exact-inventory-name>") for remote execution
        None if the user cancels/does not provide a valid target after retries.
    """
    max_attempts = 3
    for _ in range(max_attempts):
        answer = await ctx.ui.prompt(ctx.t("prompts.target_required", request=user_input))
        norm = _normalize_target_input(answer)
        if not norm:
            continue

        if norm in _LOCAL_TARGET_ALIASES:
            return "local", None

        candidate = answer.strip()
        if candidate.startswith("@"):
            candidate = candidate[1:].strip()

        if not candidate:
            continue

        host = await ctx.hosts.get_by_name(candidate)
        if host:
            # Enforce exact inventory name (case-preserving) even if user input differs.
            return "remote", host.name

        suggestions = await _find_similar_inventory_hosts(ctx, candidate)
        ctx.ui.warning(ctx.t("errors.host.not_found", name=candidate))
        if suggestions:
            ctx.ui.muted(ctx.t("errors.host.similar_hosts", hosts=", ".join(suggestions)))
        ctx.ui.muted(ctx.t("commands.help.usage_hint") + " /hosts")

    return None


@dataclass
class HandlerResponse:
    """Response from a handler.

    Attributes:
        message: Response message (markdown formatted).
        actions_taken: List of actions taken.
        suggestions: Optional suggestions for follow-up.
        handled_by: Which handler processed the request.
        raw_data: Any additional structured data.
    """

    message: str
    actions_taken: list[str] | None = None
    suggestions: list[str] | None = None
    handled_by: str = "unknown"
    raw_data: dict[str, Any] | None = None

    @classmethod
    def from_agent_response(cls, response: AgentResponse) -> HandlerResponse:
        """Create from AgentResponse."""
        return cls(
            message=response.message,
            actions_taken=response.actions_taken,
            suggestions=response.suggestions,
            handled_by="agent",
        )


async def handle_user_message(
    ctx: SharedContext,
    agent: MerlyaAgent,
    user_input: str,
    route_result: RouterResult,
) -> HandlerResponse:
    """
    Handle a user message with routing to fast path, skill, or agent.

    This is the main entry point for processing user input after routing.

    Flow:
    1. If fast_path detected -> handle_fast_path()
    2. If skill matched with high confidence -> handle_skill_flow()
    3. Otherwise -> run agent (handle_agent())

    Args:
        ctx: Shared context.
        agent: Merlya agent instance.
        user_input: Original user input.
        route_result: Result from intent router.

    Returns:
        HandlerResponse with the result.
    """
    # 1. Fast path - simple DB queries, no LLM
    if route_result.is_fast_path:
        logger.debug(f"⚡ Using fast path: {route_result.fast_path}")
        return await handle_fast_path(ctx, route_result)

    # 1.5 Clarify target for ambiguous execution requests (security-first).
    if _needs_target_clarification(route_result):
        target = await _clarify_target(ctx, user_input)
        if not target:
            return HandlerResponse(
                message=ctx.t("agent.action_cancelled"),
                handled_by="clarifier",
            )
        kind, chosen_host = target
        if kind == "local":
            clarified_input = (
                "LOCAL EXECUTION CONTEXT: this request targets the local machine. "
                "Use bash for commands; do NOT use ssh_execute.\n\n"
                + user_input
            )
            return await handle_agent(ctx, agent, clarified_input, route_result)

        if chosen_host:
            route_result.entities.setdefault("hosts", [])
            route_result.entities["hosts"] = [chosen_host]
            user_input = f"On @{chosen_host}: {user_input}"

    # 2. Skill flow - skill matched with good confidence
    if route_result.is_skill_match and route_result.skill_confidence >= SKILL_CONFIDENCE_THRESHOLD:
        logger.debug(f"🎯 Using skill flow: {route_result.skill_match}")
        response = await handle_skill_flow(ctx, user_input, route_result)
        if response:
            return response
        # Fall through to agent if skill execution failed

    # 3. Default: LLM agent
    logger.debug("🤖 Using agent flow")
    return await handle_agent(ctx, agent, user_input, route_result)


async def handle_fast_path(
    ctx: SharedContext,
    route_result: RouterResult,
) -> HandlerResponse:
    """
    Handle fast path intents - simple operations without LLM.

    Supported intents:
    - host.list: List all hosts from inventory
    - host.details: Get details for a specific host
    - group.list: List host groups/tags
    - skill.list: List available skills
    - var.list: List variables
    - var.get: Get a variable value

    Args:
        ctx: Shared context.
        route_result: Router result with fast_path set.

    Returns:
        HandlerResponse with formatted result.
    """
    intent = route_result.fast_path
    args = route_result.fast_path_args

    try:
        if intent == "host.list":
            return await _handle_host_list(ctx)

        elif intent == "host.details":
            target = args.get("target")
            if target:
                return await _handle_host_details(ctx, target)
            # If no target, fall back to list
            return await _handle_host_list(ctx)

        elif intent == "group.list":
            return await _handle_group_list(ctx)

        elif intent == "skill.list":
            return await _handle_skill_list(ctx)

        elif intent == "var.list":
            return await _handle_var_list(ctx)

        elif intent == "var.get":
            target = args.get("target")
            if target:
                return await _handle_var_get(ctx, target)
            return await _handle_var_list(ctx)

        else:
            logger.warning(f"⚠️ Unknown fast path intent: {intent}")
            return HandlerResponse(
                message=f"Unknown fast path intent: {intent}",
                handled_by="fast_path",
            )

    except Exception as e:
        logger.error(f"❌ Fast path error: {e}")
        return HandlerResponse(
            message=f"Error processing request: {e}",
            handled_by="fast_path",
        )


async def handle_skill_flow(
    ctx: SharedContext,
    user_input: str,
    route_result: RouterResult,
) -> HandlerResponse | None:
    """
    Handle skill-based execution flow.

    Args:
        ctx: Shared context.
        user_input: Original user input.
        route_result: Router result with skill_match set.

    Returns:
        HandlerResponse or None if skill execution should fall back to agent.
    """
    try:
        from merlya.skills.executor import SkillExecutor
        from merlya.skills.registry import get_registry

        registry = get_registry()
        if not route_result.skill_match:
            return None
        skill = registry.get(route_result.skill_match)

        if not skill:
            logger.warning(f"⚠️ Skill not found: {route_result.skill_match}")
            return None

        # Get hosts from entities
        hosts = route_result.entities.get("hosts", [])

        # Host validation - enforce requirements before execution
        # 1. If skill requires hosts (max_hosts > 0) and none provided:
        #    - Allow localhost default only if max_hosts == 1 AND localhost_safe is True
        #    - Otherwise, require explicit host specification
        if not hosts and skill.max_hosts > 0:
            # Only allow implicit localhost for single-host, localhost-safe skills
            if skill.max_hosts == 1 and skill.localhost_safe:
                hosts = ["localhost"]
                logger.debug(f"🏠 Using localhost for localhost-safe skill: {skill.name}")
            else:
                # Require explicit hosts - explain why
                if skill.max_hosts > 1:
                    reason = "This skill supports multiple hosts and requires explicit target specification."
                else:
                    reason = "This skill is not marked as localhost-safe and requires explicit host specification."

                return HandlerResponse(
                    message=f"**Skill: {skill.name}**\n\n"
                    f"{skill.description or 'No description available.'}\n\n"
                    f"⚠️ {reason}\n\n"
                    f"Please specify target hosts using @hostname syntax.",
                    handled_by="skill",
                    suggestions=[f"Try: @hostname {user_input}"],
                )

        # Get policy manager if available
        policy_manager = getattr(ctx, "policy_manager", None)

        # Create executor
        executor = SkillExecutor(
            context=ctx,
            policy_manager=policy_manager,
        )

        # Execute skill - timeout is handled by SubagentOrchestrator with ActivityTimeout
        # which provides intelligent idle-based timeout detection (not just absolute time)
        try:
            result = await executor.execute(
                skill=skill,
                hosts=hosts,
                task=user_input,
            )
        except TimeoutError as e:
            # Timeout message now includes reason (idle vs max)
            timeout_msg = str(e) if str(e) else "unknown timeout"
            logger.error(f"❌ Skill execution timeout: {skill.name} - {timeout_msg}")
            return HandlerResponse(
                message=f"**Skill: {skill.name}**\n\n❌ Execution timed out: {timeout_msg}",
                handled_by="skill",
                actions_taken=[f"skill:{skill.name}:timeout"],
            )

        # Format response
        message_parts = [
            f"**Skill: {skill.name}**",
            "",
            result.to_summary(),
        ]

        # Add detailed results if partial success or failure
        if result.status.value != "success":
            message_parts.append("")
            message_parts.append("### Details")
            for hr in result.host_results:
                status_emoji = "✅" if hr.success else "❌"
                message_parts.append(
                    f"- {status_emoji} **{hr.host}**: {hr.output or hr.error or 'No output'}"
                )

        return HandlerResponse(
            message="\n".join(message_parts),
            actions_taken=[f"skill:{skill.name}"],
            handled_by="skill",
            raw_data={
                "skill_result": result.model_dump() if hasattr(result, "model_dump") else None
            },
        )

    except ImportError as e:
        logger.debug(f"Skills module not available: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Skill execution error: {e}")
        return None


async def handle_agent(
    _ctx: SharedContext,
    agent: MerlyaAgent,
    user_input: str,
    route_result: RouterResult,
) -> HandlerResponse:
    """
    Handle via LLM agent (default path).

    Args:
        ctx: Shared context.
        agent: Merlya agent instance.
        user_input: Original user input.
        route_result: Router result.

    Returns:
        HandlerResponse with agent response.
    """
    response = await agent.run(user_input, route_result)
    return HandlerResponse.from_agent_response(response)


# ==============================================================================
# Fast Path Handlers
# ==============================================================================


async def _handle_host_list(ctx: SharedContext) -> HandlerResponse:
    """List all hosts from inventory."""
    hosts = await ctx.hosts.get_all()

    if not hosts:
        return HandlerResponse(
            message="No hosts in inventory. Use `/scan` to discover hosts.",
            handled_by="fast_path",
            suggestions=["/scan", "/host add <name> --address <ip>"],
        )

    # Group by health_status
    online = [h for h in hosts if h.health_status == "healthy"]
    offline = [h for h in hosts if h.health_status == "unreachable"]
    unknown = [h for h in hosts if h.health_status not in ("healthy", "unreachable")]

    lines = ["## Host Inventory", ""]

    if online:
        lines.append(f"### Online ({len(online)})")
        for h in online[:20]:  # Limit display
            tags = f" `{', '.join(h.tags)}`" if h.tags else ""
            lines.append(f"- ✅ **@{h.name}** ({h.hostname}){tags}")
        if len(online) > 20:
            lines.append(f"  ... and {len(online) - 20} more")
        lines.append("")

    if offline:
        lines.append(f"### Offline ({len(offline)})")
        for h in offline[:10]:
            lines.append(f"- ❌ **@{h.name}** ({h.hostname})")
        if len(offline) > 10:
            lines.append(f"  ... and {len(offline) - 10} more")
        lines.append("")

    if unknown:
        lines.append(f"### Unknown ({len(unknown)})")
        for h in unknown[:5]:
            lines.append(f"- ❓ **@{h.name}** ({h.hostname})")
        if len(unknown) > 5:
            lines.append(f"  ... and {len(unknown) - 5} more")

    lines.append("")
    lines.append(f"**Total: {len(hosts)} hosts**")

    return HandlerResponse(
        message="\n".join(lines),
        handled_by="fast_path",
        raw_data={"total": len(hosts), "online": len(online), "offline": len(offline)},
    )


async def _handle_host_details(ctx: SharedContext, hostname: str) -> HandlerResponse:
    """Get details for a specific host."""
    # Try to find host (case-insensitive)
    hosts = await ctx.hosts.get_all()
    host = None
    for h in hosts:
        if h.name.lower() == hostname.lower():
            host = h
            break

    if not host:
        return HandlerResponse(
            message=f"Host **@{hostname}** not found in inventory.",
            handled_by="fast_path",
            suggestions=[
                "Use `/hosts` to see all hosts",
                f"Try `/host add {hostname} --address <ip>`",
            ],
        )

    # Format details
    status_icon = (
        "✅ Online"
        if host.health_status == "healthy"
        else "❌ Offline"
        if host.health_status == "unreachable"
        else "❓ Unknown"
    )
    lines = [
        f"## Host: @{host.name}",
        "",
        f"- **Address**: {host.hostname}",
        f"- **Port**: {host.port or 22}",
        f"- **User**: {host.username or 'default'}",
        f"- **Status**: {status_icon}",
    ]

    if host.tags:
        lines.append(f"- **Tags**: {', '.join(host.tags)}")

    if host.os_info:
        lines.append(f"- **OS**: {host.os_info}")

    if host.last_seen:
        lines.append(f"- **Last Seen**: {host.last_seen}")

    if host.metadata and host.metadata.get("notes"):
        lines.append("")
        lines.append("### Notes")
        lines.append(str(host.metadata["notes"]))

    return HandlerResponse(
        message="\n".join(lines),
        handled_by="fast_path",
        raw_data={"host": host.model_dump() if hasattr(host, "model_dump") else None},
    )


async def _handle_group_list(ctx: SharedContext) -> HandlerResponse:
    """List host groups/tags."""
    hosts = await ctx.hosts.get_all()

    # Collect all tags
    tags: dict[str, list[str]] = {}
    for host in hosts:
        for tag in host.tags:
            if tag not in tags:
                tags[tag] = []
            tags[tag].append(host.name)

    if not tags:
        return HandlerResponse(
            message="No groups/tags defined. Add tags to hosts with `/host edit <name> --tags tag1,tag2`.",
            handled_by="fast_path",
        )

    lines = ["## Host Groups", ""]

    for tag, members in sorted(tags.items()):
        lines.append(f"### {tag} ({len(members)} hosts)")
        for name in members[:5]:
            lines.append(f"- @{name}")
        if len(members) > 5:
            lines.append(f"  ... and {len(members) - 5} more")
        lines.append("")

    return HandlerResponse(
        message="\n".join(lines),
        handled_by="fast_path",
        raw_data={"groups": {k: len(v) for k, v in tags.items()}},
    )


async def _handle_skill_list(_ctx: SharedContext) -> HandlerResponse:
    """List available skills."""
    try:
        from merlya.skills.registry import get_registry

        registry = get_registry()
        skills = registry.get_all()

        if not skills:
            return HandlerResponse(
                message="No skills registered. Use `/skill create` to create a custom skill.",
                handled_by="fast_path",
                suggestions=["/skill create", "/skill load"],
            )

        builtin = [s for s in skills if s.builtin]
        user = [s for s in skills if not s.builtin]

        lines = ["## Available Skills", ""]

        if builtin:
            lines.append(f"### Built-in ({len(builtin)})")
            for s in builtin:
                desc = (
                    s.description[:50] + "..."
                    if s.description and len(s.description) > 50
                    else s.description or ""
                )
                lines.append(f"- **{s.name}** v{s.version}: {desc}")
            lines.append("")

        if user:
            lines.append(f"### User-defined ({len(user)})")
            for s in user:
                desc = (
                    s.description[:50] + "..."
                    if s.description and len(s.description) > 50
                    else s.description or ""
                )
                lines.append(f"- **{s.name}** v{s.version}: {desc}")
            lines.append("")

        lines.append(f"**Total: {len(skills)} skills**")

        return HandlerResponse(
            message="\n".join(lines),
            handled_by="fast_path",
            raw_data={"total": len(skills), "builtin": len(builtin), "user": len(user)},
        )

    except ImportError:
        return HandlerResponse(
            message="Skills module not available.",
            handled_by="fast_path",
        )


async def _handle_var_list(ctx: SharedContext) -> HandlerResponse:
    """List all variables."""
    variables = await ctx.variables.get_all()

    if not variables:
        return HandlerResponse(
            message="No variables defined. Use `/var set <name> <value>` to create one.",
            handled_by="fast_path",
            suggestions=["/var set MY_VAR value"],
        )

    lines = ["## Variables", ""]

    for var in variables:
        is_sensitive = _is_sensitive_variable(var.name)
        if is_sensitive:
            value_preview = _mask_value(var.value)
            lines.append(f"- **@{var.name}**: `{value_preview}` _(sensitive)_")
        else:
            # Truncate long values for display
            value_preview = var.value[:30] + "..." if len(var.value) > 30 else var.value
            lines.append(f"- **@{var.name}**: `{value_preview}`")

    lines.append("")
    lines.append(f"**Total: {len(variables)} variables**")

    return HandlerResponse(
        message="\n".join(lines),
        handled_by="fast_path",
        raw_data={"count": len(variables)},
    )


async def _handle_var_get(ctx: SharedContext, name: str) -> HandlerResponse:
    """Get a specific variable value."""
    var = await ctx.variables.get(name)

    if not var:
        return HandlerResponse(
            message=f"Variable **@{name}** not found.",
            handled_by="fast_path",
            suggestions=[f"/var set {name} <value>"],
        )

    is_sensitive = _is_sensitive_variable(var.name)

    if is_sensitive:
        display_value = _mask_value(var.value)
        message = f"**@{var.name}** = `{display_value}` _(sensitive)_"
        raw_data: dict[str, Any] = {"name": var.name, "sensitive": True}
    else:
        message = f"**@{var.name}** = `{var.value}`"
        raw_data = {"name": var.name, "value": var.value, "sensitive": False}

    return HandlerResponse(
        message=message,
        handled_by="fast_path",
        raw_data=raw_data,
    )
