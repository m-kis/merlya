"""
Response extraction and synthesis utilities.

Handles extracting responses from autogen TaskResult and generating
syntheses from tool outputs.
"""

import re
from typing import TYPE_CHECKING, Any, Callable, List

from merlya.utils.logger import logger

if TYPE_CHECKING:
    from autogen_agentchat.base import TaskResult

# Optional imports
try:
    from autogen_agentchat.messages import FunctionExecutionResult
    HAS_AUTOGEN = True
except ImportError:
    HAS_AUTOGEN = False
    FunctionExecutionResult = None  # type: ignore


def extract_content(content: Any) -> str:
    """
    Extract string content from autogen message content.

    Handles FunctionExecutionResult, lists, dicts, and strings.
    """
    if content is None:
        return ""

    # Handle FunctionExecutionResult (autogen 0.7+ tool results)
    if FunctionExecutionResult is not None and isinstance(content, FunctionExecutionResult):
        return str(content.content) if content.content else ""

    # Handle list of content items
    if isinstance(content, list):
        parts = []
        for item in content:
            if FunctionExecutionResult is not None and isinstance(item, FunctionExecutionResult):
                parts.append(str(item.content) if item.content else "")
            elif isinstance(item, dict):
                parts.append(str(item.get('text', item)))
            else:
                parts.append(str(item))
        return "\n".join(parts)

    # Handle dict content
    if isinstance(content, dict):
        return str(content.get('text', content))

    # Already a string
    if isinstance(content, str):
        return content

    # Fallback: convert to string
    return str(content)


def filter_chain_of_thought(content: str) -> str:
    """
    Filter out chain-of-thought reasoning from agent response.

    The agent sometimes outputs its internal reasoning before the final answer.
    This includes:
    - Lines starting with "A:" (agent's internal thoughts)
    - Internal markers like "Mode:", "Response Format:", "TOOL RESTRICTION:"
    - Meta-commentary about the task

    We want to extract only the final report/response for the user.
    """
    # If content starts with markdown header, it's likely the final response
    if content.startswith('#'):
        return content

    # Detect chain-of-thought patterns
    cot_markers = [
        r'^A:\s',  # Agent internal response marker
        r'Mode:\s*(QUERY|ACTION|STANDARD)',
        r'Response Format:',
        r'TOOL RESTRICTION:',
        r'Task is complete:',
        r'No more tools needed',
        r"I've already gathered",
        r'Key findings:',
        r'Translated:',
    ]

    has_cot = any(re.search(pattern, content, re.MULTILINE | re.IGNORECASE)
                  for pattern in cot_markers)

    if not has_cot:
        return content

    # Try to extract the final report (usually starts with # heading)
    # Look for markdown report starting with "# " (heading)
    report_match = re.search(r'^(#{1,2}\s+.+?)(?=\n\n[A-Z]|$)', content, re.MULTILINE | re.DOTALL)
    if report_match:
        # Find the full report section starting from the first heading
        heading_pos = content.find(report_match.group(0))
        if heading_pos != -1:
            return content[heading_pos:].strip()

    # Alternative: split on double newline before heading
    parts = re.split(r'\n\n(?=#\s)', content)
    if len(parts) > 1:
        # Return everything from the first heading onwards
        for part in parts:
            if part.startswith('#'):
                return part.strip()

    # If no clear heading found, try to find report after CoT section
    # Look for common report starters
    report_starters = [
        r'\n#{1,3}\s+\w+.*Report',  # "# ... Report"
        r'\n#{1,3}\s+Summary',       # "# Summary"
        r'\n#{1,3}\s+Findings',      # "# Findings"
        r'\n#{1,3}\s+Results',       # "# Results"
    ]

    for pattern in report_starters:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            return content[match.start():].strip()

    # Last resort: return content as-is if it's not too long
    # (long content with CoT markers should be filtered)
    if len(content) > 2000 and has_cot:
        logger.warning("⚠️ Long response with CoT detected but no clear report found")
        # Try to return just the last substantial section
        sections = content.split('\n\n')
        # Find sections that look like final content (not meta-commentary)
        final_sections = []
        capture = False
        for section in sections:
            if section.startswith('#') or capture:
                capture = True
                final_sections.append(section)
        if final_sections:
            return '\n\n'.join(final_sections).strip()

    return content


def collect_tool_outputs(result: "TaskResult") -> List[str]:
    """Collect all tool execution outputs from the conversation.

    Includes:
    - Tool results starting with SUCCESS/ERROR
    - Report content from save_report (contains the actual report)
    """
    outputs = []

    for msg in result.messages:
        raw_content = getattr(msg, 'content', '')
        if not raw_content:
            continue

        # Extract actual string content from autogen objects
        content = extract_content(raw_content)
        if not content:
            continue

        # Collect tool results - multiple patterns
        # Pattern 1: Execute command format "✅ SUCCESS" / "❌ ERROR"
        if content.startswith("✅ SUCCESS") or content.startswith("❌ ERROR"):
            # Extract just the output part, not the status prefix
            if "\nOutput:" in content:
                output_part = content.split("\nOutput:", 1)[1].strip()
                if output_part and len(output_part) < 2000:  # Limit size
                    outputs.append(output_part)
            continue

        # Pattern 2: scan_host and other host tools output (✅ Host, ❌ Host)
        if content.startswith(("✅ Host", "❌ Host", "❌ BLOCKED", "❌ Scan")):
            if len(content) < 5000:  # Reasonable size for scan results
                outputs.append(content)
            continue

        # Pattern 3: List/inventory tools (📋)
        if content.startswith("📋 ") and "\n" in content:
            if len(content) < 5000:
                outputs.append(content)
            continue

        # Collect save_report outputs (contains the actual report content)
        # These end with "📄 *Report saved to:" and contain the report content
        if "📄 *Report saved to:" in content:
            # This is a report - extract content before the footer
            report_parts = content.split("---\n📄 *Report saved to:")
            if report_parts and report_parts[0].strip():
                report_content = report_parts[0].strip()
                # Limit size but keep more for reports (they're meant to be displayed)
                if len(report_content) < 10000:
                    outputs.append(report_content)
                else:
                    outputs.append(report_content[:10000] + "\n... (truncated)")

    return outputs


def extract_response(result: "TaskResult") -> str:
    """Extract response from TaskResult.

    Handles multiple message types and ensures we never return empty responses.
    If no clear synthesis is found, returns empty string to trigger synthesis generation.
    """
    if not result.messages:
        return "✅ Task completed."

    # Debug: Log all messages to understand structure
    logger.debug(f"TaskResult has {len(result.messages)} messages")
    for i, msg in enumerate(result.messages):
        msg_type = type(msg).__name__
        raw_content = getattr(msg, 'content', None)
        content_type = type(raw_content).__name__ if raw_content else 'None'
        logger.debug(f"  [{i}] {msg_type}: content_type={content_type}")

    # Collect all potential response content (not just last message)
    candidate_responses = []

    # Get last message from the assistant (not tool results)
    for msg in reversed(result.messages):
        # Check for TextMessage or similar final response types
        msg_type = type(msg).__name__

        # Skip tool-related messages
        if msg_type in ('ToolCallRequestEvent', 'ToolCallExecutionEvent', 'ToolCallSummaryMessage'):
            continue

        raw_content = getattr(msg, 'content', '')
        if not raw_content:
            continue

        # Extract actual string content from autogen objects
        content = extract_content(raw_content)
        if not content:
            continue

        # Skip tool call results (they start with SUCCESS/ERROR or are raw output)
        if content.startswith("✅ SUCCESS") or content.startswith("❌ ERROR"):
            continue

        # Clean up TERMINATE from response
        content = content.strip()

        # Remove TERMINATE from end (with possible trailing whitespace/newlines)
        if content.endswith("TERMINATE"):
            content = content[:-9].rstrip()

        # Also handle case where TERMINATE is on its own line at the end
        lines = content.split('\n')
        while lines and lines[-1].strip() == "TERMINATE":
            lines.pop()
        content = '\n'.join(lines).strip()

        # Skip if content is ONLY "TERMINATE" or empty after cleaning
        if not content or content == "TERMINATE":
            continue

        # Filter chain-of-thought: extract only the final report/response
        # Chain-of-thought often starts with "A:" or contains internal markers
        content = filter_chain_of_thought(content)
        if not content:
            continue

        # We found a valid response
        if content:
            candidate_responses.append(content)
            # Return first valid response (most recent)
            return content

    # If we found no valid response content, signal for synthesis
    # Return empty string so caller can generate synthesis
    if not candidate_responses:
        return ""

    return "✅ Task completed."


async def generate_synthesis(
    user_query: str,
    tool_outputs: List[str],
    client_factory: Callable[[str], Any]
) -> str:
    """Generate a synthesis from tool outputs using the LLM.

    If tool_outputs contains a full report (from save_report), return it directly
    without re-synthesizing to avoid losing content.
    """
    # Check if we have a large report - return it directly (it's already formatted)
    for output in tool_outputs:
        # Reports from save_report are typically > 500 chars and markdown formatted
        if len(output) > 500 and (output.startswith("##") or output.startswith("#") or "**" in output[:100]):
            logger.debug("📄 Returning report content directly (no synthesis needed)")
            return output

    # Combine outputs (limit total size)
    combined = "\n---\n".join(tool_outputs[:5])  # Max 5 outputs
    if len(combined) > 4000:
        combined = combined[:4000] + "\n... (truncated)"

    synthesis_prompt = f"""Based on the following command outputs, provide a clear, concise answer to the user's question.

User question: {user_query}

Command outputs:
{combined}

Instructions:
- Answer the user's question directly
- Summarize key findings
- Use markdown formatting
- Be concise but complete
- Include any recommendations if relevant

Provide your synthesis now:"""

    try:
        # Use the model client to generate synthesis
        from autogen_core import CancellationToken

        response = await client_factory("synthesis").create(
            messages=[{"role": "user", "content": synthesis_prompt}],
            cancellation_token=CancellationToken(),
        )

        if response and response.content:
            return response.content
    except Exception:
        # Fallback: return a basic summary
        return f"## Résumé\n\nCommandes exécutées avec succès.\n\n### Données collectées:\n```\n{combined[:1000]}\n```"

    return "✅ Task completed."
