"""
LLM-based parser fallback.
"""
import json
import re
from typing import List, Tuple, Optional, Any

from athena_ai.utils.logger import logger
from ..models import ParsedHost


def parse_with_llm(
    content: str, llm_router: Any, content_limit: Optional[int] = 8000
) -> Tuple[List[ParsedHost], List[str], List[str]]:
    """Use LLM to parse non-standard format.

    Returns:
        Tuple of (hosts, errors, warnings)
    """
    hosts = []
    errors = []
    warnings = []

    if not llm_router:
        errors.append("LLM not available for parsing non-standard format")
        return hosts, errors, warnings

    # Apply truncation if configured
    original_length = len(content)
    content_to_parse = content
    truncation_notice = ""

    if content_limit and original_length > content_limit:
        content_to_parse = content[: content_limit]
        truncation_notice = (
            f"\n\nWARNING: CONTENT TRUNCATED - showing first "
            f"{content_limit:,} of {original_length:,} characters. "
            f"Some hosts may be omitted from this excerpt.\n"
        )
        warnings.append(
            f"LLM_CONTENT_TRUNCATED: Content was truncated from "
            f"{original_length:,} to {content_limit:,} characters. "
            f"Some host entries may have been omitted. "
            f"Adjust InventoryParser.LLM_CONTENT_LIMIT to change this limit."
        )
        logger.warning(
            f"Inventory content truncated for LLM parsing: "
            f"{original_length:,} -> {content_limit:,} chars"
        )

    prompt = f"""Analyze this inventory content and extract host information.
Return ONLY a JSON array with objects containing these fields:
- hostname (required): the server hostname
- ip_address (optional): IP address if present
- environment (optional): prod/staging/dev if determinable
- groups (optional): array of group names
- metadata (optional): any other relevant info as key-value pairs
{truncation_notice}
Content to parse:
```
{content_to_parse}
```

Return ONLY valid JSON, no explanations."""

    try:
        response = llm_router.generate(prompt, task="correction")

        # Extract JSON from response
        json_match = re.search(r'\[.*\]', response, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            for item in data:
                if isinstance(item, dict) and item.get("hostname"):
                    host = ParsedHost(
                        hostname=item["hostname"].lower(),
                        ip_address=item.get("ip_address"),
                        environment=item.get("environment"),
                        groups=item.get("groups", []),
                        metadata=item.get("metadata", {}),
                    )
                    hosts.append(host)
        else:
            errors.append("LLM did not return valid JSON")

    except Exception as e:
        errors.append(f"LLM parsing failed: {e}")

    return hosts, errors, warnings
