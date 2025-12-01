"""
AutoGen tools for interacting with the Knowledge Graph (FalkorDB).
Wraps OpsKnowledgeManager functionality.
"""
from typing import Annotated

from athena_ai.knowledge.ops_knowledge_manager import get_knowledge_manager
from athena_ai.utils.logger import logger

# Initialize manager
_knowledge_manager = get_knowledge_manager()

def record_incident(
    title: Annotated[str, "Short summary of the incident"],
    priority: Annotated[str, "Priority level (P0, P1, P2, P3)"],
    service: Annotated[str, "Affected service name (e.g. mongodb, nginx)"],
    symptoms: Annotated[str, "Comma-separated list of symptoms"],
    description: Annotated[str, "Detailed description"] = "",
    environment: Annotated[str, "Environment (prod, staging, dev)"] = "prod",
    host: Annotated[str, "Affected hostname"] = ""
) -> str:
    """
    Record a new incident in the Knowledge Graph.

    Use this when you detect a problem that needs to be tracked.

    Args:
        title: Incident title
        priority: Priority
        service: Service name
        symptoms: Symptoms list
        description: Description
        environment: Environment
        host: Hostname

    Returns:
        Incident ID
    """
    logger.info(f"Knowledge Tool: record_incident '{title}'")

    symptom_list = [s.strip() for s in symptoms.split(",") if s.strip()]

    incident_id = _knowledge_manager.record_incident(
        title=title,
        priority=priority,
        description=description,
        environment=environment,
        service=service,
        host=host,
        symptoms=symptom_list
    )

    return f"✅ Incident recorded: {incident_id}"

def search_knowledge(
    query: Annotated[str, "Search query (symptoms or keywords)"],
    service: Annotated[str, "Filter by service"] = "",
    limit: Annotated[int, "Max results"] = 3
) -> str:
    """
    Search the Knowledge Graph for similar past incidents or patterns.

    Use this to find how similar problems were solved in the past.

    Args:
        query: Search text
        service: Optional service filter
        limit: Max results

    Returns:
        Summary of findings
    """
    logger.info(f"Knowledge Tool: search_knowledge '{query}'")

    # 1. Search Patterns
    patterns = _knowledge_manager.match_patterns(
        text=query,
        service=service,
        limit=limit
    )

    # 2. Search Incidents
    # Extract potential symptoms from query (simplified)
    symptoms = [query]
    incidents = _knowledge_manager.find_similar_incidents(
        symptoms=symptoms,
        service=service,
        limit=limit
    )

    output = []

    if patterns:
        output.append("🧠 **Matching Patterns:**")
        for p in patterns:
            output.append(f"- **{p.pattern.name}** ({int(p.score * 100)}% confidence)")
            output.append(f"  Solution: {p.pattern.suggested_solution}")
            if p.pattern.suggested_commands:
                output.append(f"  Commands: `{' && '.join(p.pattern.suggested_commands)}`")
        output.append("")

    if incidents:
        output.append("📜 **Similar Past Incidents:**")
        for match in incidents:
            inc = match.incident
            output.append(f"- **{inc.title}** ({inc.id})")
            if inc.solution:
                output.append(f"  Solution: {inc.solution}")
            if inc.commands_executed:
                cmds = inc.commands_executed
                if isinstance(cmds, list):
                    output.append(f"  Commands: `{' && '.join(cmds)}`")
        output.append("")

    if not output:
        return "❌ No relevant knowledge found."

    return "\n".join(output)

def get_solution_suggestion(
    symptoms: Annotated[str, "Comma-separated symptoms"],
    service: Annotated[str, "Service name"],
    environment: Annotated[str, "Environment"] = ""
) -> str:
    """
    Get an AI/Graph-based solution suggestion.

    Args:
        symptoms: Symptoms
        service: Service
        environment: Environment

    Returns:
        Suggested solution
    """
    logger.info(f"Knowledge Tool: get_solution_suggestion for {service}")

    symptom_list = [s.strip() for s in symptoms.split(",") if s.strip()]

    suggestion = _knowledge_manager.get_suggestion(
        symptoms=symptom_list,
        service=service,
        environment=environment
    )

    if suggestion:
        conf = int(suggestion['confidence'] * 100)
        src = suggestion['source']
        sol = suggestion['solution']
        cmds = suggestion.get('commands', [])

        out = f"💡 **Suggestion ({conf}% confidence from {src}):**\n\n{sol}"
        if cmds:
            out += f"\n\nSuggested Commands:\n```bash\n{chr(10).join(cmds)}\n```"
        return out

    return "❌ No high-confidence suggestion found."

def graph_stats() -> str:
    """
    Get statistics about the Knowledge Graph.

    Returns:
        Stats summary
    """
    stats = _knowledge_manager.get_stats()

    falkor = stats.get('storage', {}).get('falkordb', {})
    connected = falkor.get('connected', False)

    if not connected:
        return "⚠️ FalkorDB is NOT connected. Using SQLite fallback."

    nodes = falkor.get('total_nodes', 0)
    rels = falkor.get('total_relationships', 0)
    graph_name = falkor.get('graph_name', 'unknown')

    return f"✅ **Knowledge Graph Status:**\n- Graph: `{graph_name}`\n- Nodes: {nodes}\n- Relationships: {rels}\n- Status: Online"
