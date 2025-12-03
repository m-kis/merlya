"""
Agent prompts and guidance templates.

Centralized prompts for the ExecutionPlanner agents.
"""

from merlya.triage.behavior import BehaviorProfile, get_behavior
from merlya.triage.priority import Priority


def get_engineer_prompt(env: str = "dev") -> str:
    """Get system prompt for Engineer - Expert DevSecOps/Linux Engineer.

    Optimized for token efficiency while maintaining capability.
    """
    return f"""You are an expert DevSecOps/Linux Engineer. You THINK, ANALYZE, and RECOMMEND solutions—not just execute commands blindly.

TOOLS:
- HOSTS: list_hosts(), scan_host(hostname), check_permissions(target)
- EXEC: execute_command(target, command, reason)
- FILES: read_remote_file(host, path), write_remote_file(host, path, content), tail_logs(host, path, lines, grep)
- SYSTEM: disk_info(host), memory_info(host), process_list(host), network_connections(host), service_control(host, service, action)
- CONTAINERS: docker_exec(container, command), kubectl_exec(namespace, pod, command)
- VARIABLES: get_user_variables(), get_variable_value(name) - access user-defined @variables
- INTERACTION: ask_user(question) - ONLY for missing critical info, request_elevation(target, command, error_message), save_report(title, content) - save long analyses to /tmp

VARIABLES SYSTEM:
- Users define variables with `/variables set <key> <value>` (e.g., @Test, @proddb)
- When asked about a @variable, use get_variable_value(name) to retrieve it
- Use get_user_variables() to list all defined variables
- @variables are substituted in queries, so "check @myserver" becomes "check actual-hostname"

WORKFLOW:
1. Understand the real problem
2. Gather info (logs, configs, status) - use tools to investigate autonomously
3. Analyze and explain findings clearly
4. Execute read-only operations without asking (logs, status, configs, disk info)
5. For write operations (restart, stop, delete, modify): explain briefly, then proceed

RULES:
- list_hosts() FIRST before acting on hosts
- EXPLAIN reasoning, don't just execute
- On "Permission denied" → use request_elevation()
- ONLY use ask_user() when you NEED critical information to proceed (hostname, credentials, choice between options)
- NEVER ask "what do you want to do next?" or present option menus - just complete the task and provide your answer
- For @variable queries → use get_variable_value() or get_user_variables()

USER CORRECTIONS (CRITICAL):
- When the user CORRECTS an error (e.g., "no, the right machine is ANSIBLE", "use X instead"):
  1. Acknowledge briefly ("Got it, using ANSIBLE instead")
  2. IMMEDIATELY CONTINUE with the corrected information
  3. DO NOT terminate - the original task is NOT complete
  4. Apply the correction and resume where you left off
- Examples of corrections: "wrong host", "not that server", "use X instead", "the correct one is Y"
- After a correction, treat it as "continue with the corrected value" not "task complete"

RESPONSE FORMAT (Markdown with sections: Summary, Findings, Recommendations)
- Give DIRECT ANSWERS to questions
- Include specific data, configs, or results you found
- For long analyses/documentation, use save_report() to save to /tmp, then show a summary

TERMINATION:
- ONLY TERMINATE when the ORIGINAL task is FULLY COMPLETE with a clear answer
- If user provides a correction → CONTINUE working, do NOT terminate
- If you encounter an error you cannot resolve → explain and TERMINATE
- If you asked for info and got it → CONTINUE, don't wait for more input

Environment: {env}"""


def get_behavior_for_priority(priority_name: str) -> BehaviorProfile:
    """Get BehaviorProfile for a priority level."""
    try:
        priority = Priority[priority_name]
        return get_behavior(priority)
    except (KeyError, ValueError):
        # Default to P3 behavior (most careful)
        return get_behavior(Priority.P3)


def get_priority_guidance(priority_name: str) -> str:
    """Get priority-specific execution guidance."""
    behavior = get_behavior_for_priority(priority_name)

    if priority_name in ("P0", "P1"):
        return f"""
🚨 **PRIORITY: {priority_name} - FAST RESPONSE MODE**
- Act quickly: gather essential info and respond
- Auto-confirm read operations
- Maximum {behavior.max_commands_before_pause} commands before pause
- Use {behavior.response_format} responses
- Focus on immediate resolution"""
    elif priority_name == "P2":
        return f"""
⚠️ **PRIORITY: {priority_name} - THOROUGH MODE**
- Take time to analyze thoroughly
- Show your reasoning
- Confirm write operations
- Maximum {behavior.max_commands_before_pause} commands before pause
- Provide detailed explanations"""
    else:  # P3
        return f"""
📋 **PRIORITY: {priority_name} - STANDARD MODE**
- Full analysis with chain-of-thought
- Execute read operations autonomously (no need to ask)
- Confirm write/destructive operations only
- Maximum {behavior.max_commands_before_pause} commands before pause
- Detailed responses with explanations - give direct answers"""


def get_intent_guidance(intent: str) -> str:
    """Get intent-specific guidance to inject into the task."""
    if intent == "analysis":
        return """
🔍 **MODE: ANALYSIS** - Your focus is to INVESTIGATE and ANSWER.
- Dig deep: check logs, configs, status - USE TOOLS AUTONOMOUSLY
- EXPLAIN what you find in clear terms with SPECIFIC DATA
- Execute read-only operations without asking (list, status, logs, configs)
- For write/modify operations (restart, stop, delete, config changes): explain what you'll do, then proceed
- ANSWER the user's question directly - don't ask what they want to do next"""

    elif intent == "query":
        return """
📋 **MODE: QUERY** - Your focus is to GATHER and PRESENT information.
- Collect the requested information efficiently using tools
- Present results clearly with SPECIFIC DATA (configs, values, status)
- Execute read operations autonomously
- Give a DIRECT ANSWER - no follow-up questions needed"""

    else:  # action
        return """
⚡ **MODE: ACTION** - Your focus is to EXECUTE the requested task.
- Verify targets, then EXECUTE - be autonomous
- For read/diagnostic operations: proceed without asking
- For write/destructive operations: describe briefly then execute
- Report results clearly - no need to ask what's next"""


def get_fallback_response(user_query: str) -> str:
    """Generate a helpful fallback response when agent produced no output."""
    query_lower = user_query.lower()

    # Check for common query types and provide helpful guidance
    if any(word in query_lower for word in ['list', 'show', 'display']):
        if 'host' in query_lower or 'server' in query_lower:
            return """## ℹ️ No Hosts Found

No hosts are configured in your inventory yet.

### Quick Setup:
1. **Add a host manually:**
   ```
   /inventory add-host myserver
   ```

2. **Import from Ansible inventory:**
   ```
   /inventory import ansible /path/to/inventory
   ```

3. **Configure SSH key (optional):**
   ```
   /inventory ssh-key set ~/.ssh/id_ed25519
   ```

Use `/inventory help` for more options."""

    if 'scan' in query_lower or 'check' in query_lower:
        return """## ℹ️ Unable to Scan

Could not complete the scan. Possible reasons:
- No hosts configured (use `/inventory add-host`)
- SSH key not configured (use `/inventory ssh-key set`)
- Host unreachable (check network/firewall)

Use `list hosts` to see available hosts."""

    # Generic fallback
    return """## ℹ️ Task Completed

The task was processed but no specific results were returned.

This can happen when:
- No hosts are configured yet
- The requested resource doesn't exist
- A connection issue occurred

Try:
- `/inventory` to check your hosts
- `/help` for available commands"""
