"""
Entity Extractor Service - DDD Domain Service.

Extracts structured entities from natural language queries:
- target_host: hostname/server mentioned (VALIDATED against real inventory)
- service: service mentioned (mysql, nginx, etc.)
- intent: what the user wants (analyze, check, info, etc.)

CRITICAL SECURITY: This module uses HostRegistry for STRICT validation.
We NEVER return a hostname that doesn't exist in real inventory.
This prevents LLM hallucination attacks.
"""

import json
import re
from typing import Any, Dict, List, Optional

from merlya.context.host_registry import get_host_registry
from merlya.utils.logger import logger


class EntityExtractor:
    """
    Domain Service for extracting entities from natural language queries.

    SECURITY: All hostnames are validated against the HostRegistry.
    Invalid/hallucinated hostnames are REJECTED with suggestions.
    """

    # Special return values
    CLARIFICATION_NEEDED = "__CLARIFICATION_NEEDED__"
    HOST_NOT_FOUND = "__HOST_NOT_FOUND__"

    def __init__(self, llm_router, context_manager):
        """
        Initialize Entity Extractor.

        Args:
            llm_router: LLM router for intelligent extraction
            context_manager: Context manager for inventory access
        """
        self.llm_router = llm_router
        self.context_manager = context_manager
        self._host_registry = get_host_registry()

    def extract_entities(self, query: str) -> Dict[str, Any]:
        """
        Use LLM to intelligently understand intent and extract entities from query.

        IMPORTANT: The target_host extracted here is NOT yet validated.
        Use extract_target_from_context() for validated hostnames.

        Args:
            query: User's natural language query

        Returns:
            Dictionary with extracted entities and intent
        """
        # Build list of valid hosts to constrain LLM
        valid_hosts = self._host_registry.hostnames[:50]
        hosts_hint = ", ".join(valid_hosts[:20]) if valid_hosts else "none loaded"

        prompt = f"""You are an expert at analyzing infrastructure queries and extracting key information.

Analyze this user query and extract the following information:

Query: "{query}"

IMPORTANT: For target_host, ONLY extract hostnames that appear to be server names.
Available hosts in inventory (partial list): {hosts_hint}

Extract these elements and respond with VALID JSON ONLY (no markdown, no explanation):
{{
    "intent": "what the user wants (analyze, check, status, troubleshoot, info, read, etc.)",
    "target_host": "the hostname/server mentioned (null if none or unclear)",
    "service": "the service/concept mentioned (mysql, nginx, backup, etc., null if none)",
    "action_type": "system_analysis|service_check|info_request|troubleshooting|file_read",
    "file_path": "absolute file path if user asks about file content (null if none)"
}}

Examples:
- "a quoi sert le serveur preprodlb ?" → {{"intent": "info_request", "target_host": "preprodlb", "service": null, "action_type": "info_request", "file_path": null}}
- "analyze mysql on unifyqarcdb" → {{"intent": "analyze", "target_host": "unifyqarcdb", "service": "mysql", "action_type": "system_analysis", "file_path": null}}
- "liste les serveurs mongodb" → {{"intent": "list", "target_host": null, "service": "mongodb", "action_type": "info_request", "file_path": null}}

RESPOND WITH VALID JSON ONLY:"""

        # Try Ollama local first (fast, free, private)
        try:
            import requests

            models = ["qwen2.5:0.5b", "smollm2:1.7b", "phi3:mini"]

            for model in models:
                try:
                    response = requests.post(
                        "http://localhost:11434/api/generate",
                        json={
                            "model": model,
                            "prompt": prompt,
                            "stream": False,
                            "options": {
                                "temperature": 0,
                                "num_predict": 150,
                                "num_ctx": 2048
                            }
                        },
                        timeout=5
                    )

                    if response.status_code == 200:
                        ollama_response = response.json().get("response", "").strip()

                        response_clean = ollama_response
                        if response_clean.startswith("```"):
                            lines = response_clean.split("\n")
                            response_clean = "\n".join([line for line in lines if not line.startswith("```")])
                        if response_clean.startswith("json"):
                            response_clean = response_clean[4:].strip()

                        entities = json.loads(response_clean)
                        logger.debug(f"Ollama ({model}) extracted entities: {entities}")
                        return entities

                except Exception:
                    continue

            logger.debug("Ollama not available, falling back to main LLM")

        except Exception as e:
            logger.debug(f"Ollama extraction skipped: {e}")

        # Fallback to main LLM router
        try:
            response = self.llm_router.generate(
                prompt=prompt,
                system_prompt="You are an expert at extracting structured information. Respond with valid JSON only.",
                task="extraction"
            )

            response_clean = response.strip()
            if response_clean.startswith("```"):
                lines = response_clean.split("\n")
                response_clean = "\n".join([line for line in lines if not line.startswith("```")])
            if response_clean.startswith("json"):
                response_clean = response_clean[4:].strip()

            entities = json.loads(response_clean)
            logger.debug(f"LLM extracted entities: {entities}")
            return entities

        except Exception as e:
            logger.warning(f"LLM entity extraction failed: {e}")
            return {
                "intent": None,
                "target_host": None,
                "service": None,
                "action_type": None
            }

    def extract_target_from_context(self, context: Dict[str, Any]) -> Optional[str]:
        """
        Extract and VALIDATE target host from context.

        SECURITY CRITICAL: Returns ONLY validated hostnames.
        If the extracted hostname is not in inventory:
        - Returns HOST_NOT_FOUND with suggestions stored in context
        - NEVER returns an unvalidated hostname

        Args:
            context: Accumulated execution context

        Returns:
            - Validated hostname if found in registry
            - CLARIFICATION_NEEDED if conversational reference without memory
            - HOST_NOT_FOUND if hostname not in inventory (suggestions in context)
            - None if no hostname could be extracted
        """
        # Ensure registry is loaded
        if self._host_registry.is_empty():
            self._host_registry.load_all_sources()

        # Check if already validated in context
        if context.get("_validated_target_host"):
            return context["_validated_target_host"]

        # Try to validate from previous results
        if "target_host" in context:
            target = context["target_host"]
            if target and target not in [self.CLARIFICATION_NEEDED, self.HOST_NOT_FOUND]:
                validation = self._host_registry.validate(target)
                if validation.is_valid:
                    context["_validated_target_host"] = validation.host.hostname
                    return validation.host.hostname

        # Check step results
        for key, value in context.items():
            if key.startswith("step_") and isinstance(value, dict):
                if "target" in value:
                    target = value["target"]
                    validation = self._host_registry.validate(target)
                    if validation.is_valid:
                        context["_validated_target_host"] = validation.host.hostname
                        return validation.host.hostname

        # Extract from original query
        if "original_query" not in context:
            logger.warning("No original_query in context")
            return None

        query = context["original_query"]
        query_lower = query.lower()

        # STRATEGY 1: Use LLM to extract potential hostname
        entities = self.extract_entities(query)
        extracted_host = entities.get("target_host")

        if extracted_host:
            # CRITICAL: Validate against registry
            validation = self._host_registry.validate(extracted_host)

            if validation.is_valid:
                logger.info(f"✓ Host validated: {extracted_host} → {validation.host.hostname}")
                context["_validated_target_host"] = validation.host.hostname
                return validation.host.hostname
            else:
                # SECURITY: Do NOT return invalid hostname
                logger.warning(f"✗ Host NOT in inventory: {extracted_host}")
                context["_host_validation_failed"] = True
                context["_invalid_hostname"] = extracted_host
                context["_host_suggestions"] = validation.suggestions

                if validation.suggestions:
                    logger.info(f"  Suggestions: {[h for h, _ in validation.suggestions[:3]]}")

                return self.HOST_NOT_FOUND

        # STRATEGY 2: Check for conversational references
        conversational_patterns = [
            r'\b(ce|cette)\s+(serveur|machine|host)\b',
            r'\b(this|that)\s+(server|machine|host)\b',
            r'\bsur (ce|celui-ci)\b',
            r'\bon (this|it)\b',
        ]

        has_conversational_ref = any(
            re.search(pattern, query_lower)
            for pattern in conversational_patterns
        )

        if has_conversational_ref:
            logger.debug("Detected conversational reference")

            memory = context.get("conversation_memory", {})
            last_host = memory.get("last_target_host")

            if last_host:
                validation = self._host_registry.validate(last_host)
                if validation.is_valid:
                    logger.info(f"✓ Conversational reference resolved: {last_host}")
                    context["_validated_target_host"] = validation.host.hostname
                    return validation.host.hostname

            return self.CLARIFICATION_NEEDED

        # STRATEGY 3: Direct inventory lookup from query words
        words = query_lower.split()
        for word in words:
            word_clean = word.strip(",.;?:'\"")
            if len(word_clean) < 3:
                continue

            validation = self._host_registry.validate(word_clean)
            if validation.is_valid:
                logger.info(f"✓ Direct match found: {word_clean} → {validation.host.hostname}")
                context["_validated_target_host"] = validation.host.hostname
                return validation.host.hostname

        # STRATEGY 4: Pattern-based extraction with validation
        potential_hosts = self._extract_potential_hosts(query_lower)

        for potential in potential_hosts:
            validation = self._host_registry.validate(potential)
            if validation.is_valid:
                logger.info(f"✓ Pattern match validated: {potential} → {validation.host.hostname}")
                context["_validated_target_host"] = validation.host.hostname
                return validation.host.hostname

        # No valid host found - check if there were unvalidated extractions
        if potential_hosts:
            validation = self._host_registry.validate(potential_hosts[0])
            if validation.suggestions:
                context["_host_validation_failed"] = True
                context["_invalid_hostname"] = potential_hosts[0]
                context["_host_suggestions"] = validation.suggestions
                logger.warning(f"✗ Host NOT in inventory: {potential_hosts[0]}")
                return self.HOST_NOT_FOUND

        # Check conversation memory as last resort
        memory = context.get("conversation_memory", {})
        if memory.get("last_target_host"):
            last = memory["last_target_host"]
            validation = self._host_registry.validate(last)
            if validation.is_valid:
                logger.info(f"✓ Using memory host: {last}")
                context["_validated_target_host"] = validation.host.hostname
                return validation.host.hostname

        logger.debug("No target host could be extracted")
        return None

    def _extract_potential_hosts(self, query: str) -> List[str]:
        """Extract potential hostnames from query using patterns (not validated)."""
        potential = []

        # English patterns
        for pattern in [" on ", " for ", " from "]:
            if pattern in query:
                parts = query.split(pattern)
                if len(parts) > 1:
                    hostname = parts[1].split()[0].strip(",.;:")
                    if len(hostname) > 2:
                        potential.append(hostname)

        # French patterns
        for pattern in ["serveur ", "sur ", "de ", "du "]:
            if pattern in query:
                idx = query.rfind(pattern) + len(pattern)
                remainder = query[idx:]
                if remainder:
                    hostname = remainder.split()[0].strip(",.;?:")
                    skip_words = ["le", "la", "les", "un", "une", "des", "de", "du", "a", "est", "et", "the", "an"]
                    if hostname not in skip_words and len(hostname) > 2:
                        potential.append(hostname)

        # After server keywords
        words = query.split()
        server_keywords = ["serveur", "server", "host", "machine"]

        for i, word in enumerate(words):
            if word.strip(",.;?:") in server_keywords and i + 1 < len(words):
                next_word = words[i + 1].strip(",.;?:")
                skip_words = ["le", "la", "les", "un", "une", "des", "de", "du", "the", "a", "an"]
                if next_word in skip_words and i + 2 < len(words):
                    next_word = words[i + 2].strip(",.;?:")

                if len(next_word) > 2 and next_word.replace("-", "").replace("_", "").isalnum():
                    potential.append(next_word)

        # Deduplicate
        seen = set()
        result = []
        for h in potential:
            if h.lower() not in seen:
                seen.add(h.lower())
                result.append(h)

        return result

    def get_host_suggestions(self, context: Dict[str, Any]) -> Optional[str]:
        """
        Get formatted suggestions for invalid hostname.

        Call this when extract_target_from_context returns HOST_NOT_FOUND.
        """
        if not context.get("_host_validation_failed"):
            return None

        invalid = context.get("_invalid_hostname", "unknown")
        suggestions = context.get("_host_suggestions", [])

        if not suggestions:
            return f"❌ L'hôte '{invalid}' n'existe pas dans l'inventaire et aucun hôte similaire n'a été trouvé."

        lines = [f"❌ L'hôte '{invalid}' n'existe pas dans l'inventaire."]
        lines.append("")
        lines.append("Vouliez-vous dire:")
        for hostname, score in suggestions[:5]:
            lines.append(f"  • {hostname} ({score:.0%} correspondance)")

        return "\n".join(lines)

    def extract_service_from_context(self, context: Dict[str, Any]) -> Optional[str]:
        """Extract service name from context."""
        if "service_name" in context:
            return context["service_name"]

        if "original_query" not in context:
            return None

        query = context["original_query"]

        entities = self.extract_entities(query)
        if entities.get("service"):
            return entities["service"]

        query_lower = query.lower()
        services = [
            "mysql", "mariadb", "postgres", "postgresql", "mongodb", "mongo",
            "nginx", "apache", "httpd", "redis", "memcached",
            "elasticsearch", "kafka", "rabbitmq", "haproxy",
            "docker", "kubernetes", "k8s",
            "backup", "monitoring", "logs", "security"
        ]

        for service in services:
            if service in query_lower:
                return service

        return None

    def list_available_hosts(
        self,
        environment: Optional[str] = None,
        pattern: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List available hosts from registry."""
        hosts = self._host_registry.filter(environment=environment, pattern=pattern)

        return [
            {
                "hostname": h.hostname,
                "ip": h.ip_address,
                "environment": h.environment,
                "groups": h.groups,
                "source": h.source.value,
            }
            for h in hosts
        ]

    def get_registry_stats(self) -> Dict[str, Any]:
        """Get host registry statistics."""
        return self._host_registry.get_stats()
