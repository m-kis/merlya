"""
Validation logic for LLM parser.
"""
import json
import re
from typing import List, Optional, Tuple

from merlya.utils.logger import logger

from ...models import ParsedHost


def _find_balanced_json_array(text: str) -> Optional[str]:
    """
    Find the first balanced JSON array in text using bracket matching.

    This is safer than greedy regex as it properly handles nested structures
    and won't over-capture when multiple arrays exist in the response.

    Args:
        text: Text that may contain a JSON array

    Returns:
        The first balanced JSON array substring, or None if not found
    """
    start_idx = text.find('[')
    if start_idx == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False

    for i, char in enumerate(text[start_idx:], start=start_idx):
        if escape_next:
            escape_next = False
            continue

        if char == '\\' and in_string:
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == '[':
            depth += 1
        elif char == ']':
            depth -= 1
            if depth == 0:
                return text[start_idx:i + 1]

    return None


def validate_llm_response(response: str) -> Tuple[List[ParsedHost], List[str]]:
    """
    Strictly validate LLM response and extract host data.

    This function performs rigorous validation of the LLM response to ensure:
    1. The response contains valid JSON
    2. The JSON is an array (not an object or primitive)
    3. Each element has required fields with correct types
    4. No unexpected text or injection artifacts are present

    Args:
        response: Raw text response from the LLM

    Returns:
        Tuple of (list of validated ParsedHost objects, list of validation errors)
    """
    hosts: List[ParsedHost] = []
    errors: List[str] = []

    if not response or not response.strip():
        errors.append("LLM_EMPTY_RESPONSE: LLM returned empty response")
        return hosts, errors

    # Strip whitespace and check for pure JSON response
    cleaned_response = response.strip()

    # Check for markdown code blocks and extract content
    code_block_match = re.match(r'^```(?:json)?\s*\n?(.*?)\n?```\s*$', cleaned_response, re.DOTALL)
    if code_block_match:
        cleaned_response = code_block_match.group(1).strip()
        logger.debug("Extracted JSON from markdown code block")

    # First, try to parse the entire response as JSON directly
    # This handles clean responses without unnecessary extraction
    try:
        data = json.loads(cleaned_response)
        if isinstance(data, list):
            logger.debug("Parsed entire response as JSON array directly")
            # Skip to validation below
        else:
            # Response parsed but isn't a list - will be caught in validation
            pass
    except json.JSONDecodeError:
        # Response isn't pure JSON, try to extract JSON array
        data = None

        # Try bracket-matching to find the first balanced JSON array
        json_substring = _find_balanced_json_array(cleaned_response)

        if json_substring:
            # Log preamble/postamble warnings
            json_start = cleaned_response.find(json_substring)
            preamble = cleaned_response[:json_start].strip()
            postamble = cleaned_response[json_start + len(json_substring):].strip()

            if preamble:
                preamble_display = preamble[:100] + "..." if len(preamble) > 100 else preamble
                errors.append(
                    f"LLM_UNEXPECTED_PREAMBLE: Response contained unexpected text before JSON: "
                    f"'{preamble_display}'. This may indicate injection artifacts."
                )
                logger.warning(f"LLM response has unexpected preamble: {preamble_display}")

            if postamble:
                postamble_display = postamble[:100] + "..." if len(postamble) > 100 else postamble
                errors.append(
                    f"LLM_UNEXPECTED_POSTAMBLE: Response contained unexpected text after JSON: "
                    f"'{postamble_display}'. This may indicate injection artifacts."
                )
                logger.warning(f"LLM response has unexpected postamble: {postamble_display}")

            try:
                data = json.loads(json_substring)
            except json.JSONDecodeError as e:
                errors.append(f"LLM_JSON_PARSE_ERROR: Failed to parse extracted JSON: {e}")
                logger.error(f"JSON parse error on extracted substring: {e}. Content: {json_substring[:500]}...")
                return hosts, errors
        else:
            errors.append(
                "LLM_NO_JSON_ARRAY: Response does not contain a valid JSON array. "
                "This may indicate a prompt injection attempt or malformed response."
            )
            logger.error(f"LLM response missing JSON array. Response preview: {cleaned_response[:200]}...")
            return hosts, errors

    # Validate structure - must be a list
    if not isinstance(data, list):
        errors.append(
            f"LLM_INVALID_STRUCTURE: Expected JSON array, got {type(data).__name__}. "
            "This may indicate a prompt injection attempt."
        )
        logger.error(f"LLM returned non-array JSON: {type(data).__name__}")
        return hosts, errors

    # Validate and extract each host entry
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"LLM_INVALID_ITEM: Item at index {idx} is not an object")
            continue

        # Validate required field: hostname
        hostname = item.get("hostname")

        # Handle None explicitly
        if hostname is None:
            errors.append(f"LLM_MISSING_HOSTNAME: Item at index {idx} missing required 'hostname' field")
            continue

        # Convert non-strings to string if possible, skip if not convertible
        if not isinstance(hostname, str):
            # Try to convert numbers or other primitives to string
            if isinstance(hostname, (int, float)):
                hostname = str(hostname)
                errors.append(f"LLM_HOSTNAME_CONVERTED: Item at index {idx} had numeric hostname, converted to string")
            else:
                errors.append(f"LLM_INVALID_HOSTNAME: Item at index {idx} has non-string hostname type {type(hostname).__name__}")
                continue

        # Skip empty strings after conversion
        if not hostname.strip():
            errors.append(f"LLM_EMPTY_HOSTNAME: Item at index {idx} has empty hostname")
            continue

        # Validate hostname doesn't contain injection artifacts
        if any(marker in hostname.lower() for marker in ['injection', 'ignore', 'instruction', 'system:']):
            errors.append(
                f"LLM_SUSPICIOUS_HOSTNAME: Item at index {idx} has suspicious hostname that may "
                f"indicate injection: '{hostname[:50]}'"
            )
            logger.warning(f"Suspicious hostname detected: {hostname}")
            continue

        # Validate optional fields with type checking
        ip_address = item.get("ip_address")
        if ip_address is not None and not isinstance(ip_address, str):
            ip_address = None
            errors.append(f"LLM_INVALID_IP: Item at index {idx} has non-string ip_address, ignoring")

        environment = item.get("environment")
        if environment is not None and not isinstance(environment, str):
            environment = None
            errors.append(f"LLM_INVALID_ENV: Item at index {idx} has non-string environment, ignoring")

        groups = item.get("groups")

        # Coerce groups to a list
        if groups is None:
            groups = []
        elif isinstance(groups, str):
            # Wrap single string value in a list (stripped, only if non-empty after strip)
            stripped = groups.strip()
            groups = [stripped] if stripped else []
        elif not isinstance(groups, list):
            errors.append(f"LLM_INVALID_GROUPS: Item at index {idx} has non-array groups type {type(groups).__name__}, using empty")
            groups = []
        else:
            # Filter to only non-empty string group names, stripped
            groups = [g.strip() for g in groups if isinstance(g, str) and g.strip()]

        metadata = item.get("metadata")

        # Coerce metadata to a dict
        if metadata is None:
            metadata = {}
        elif not isinstance(metadata, dict):
            errors.append(f"LLM_INVALID_METADATA: Item at index {idx} has non-object metadata type {type(metadata).__name__}, using empty")
            metadata = {}

        # Create validated host
        host = ParsedHost(
            hostname=hostname.lower().strip(),
            ip_address=ip_address.strip() if (ip_address and ip_address.strip()) else None,
            environment=environment.strip() if (environment and environment.strip()) else None,
            groups=groups,
            metadata=metadata,
        )
        hosts.append(host)

    logger.info(f"LLM response validated: {len(hosts)} hosts extracted, {len(errors)} validation issues")
    return hosts, errors
