"""
Fast Path Optimization Module.

Detects simple queries and executes them directly, bypassing multi-agent orchestration.
This reduces response time from ~5 minutes to ~30-60 seconds for common operations.

Uses semantic similarity (sentence-transformers) for intelligent query detection,
falling back to keyword patterns when embeddings are unavailable.

Bottlenecks addressed:
1. Intent classification LLM call (10-20s) → Embeddings (100ms)
2. Multi-agent orchestration (2-3min) → Direct tool call
3. Synthesis LLM call (10-20s) → Simple formatting
"""
import asyncio
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from merlya.utils.logger import logger

# Optional imports for embeddings
try:
    from merlya.triage.smart_classifier.embedding_cache import (
        HAS_EMBEDDINGS,
        EmbeddingCache,
        get_embedding_cache,
    )
except ImportError:
    HAS_EMBEDDINGS = False
    EmbeddingCache = None  # type: ignore
    get_embedding_cache = None  # type: ignore

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore

# Hostname validation pattern (RFC 1123)
VALID_HOSTNAME_PATTERN = re.compile(
    r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?'
    r'(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
)

# Timeout for tool execution (seconds)
TOOL_EXECUTION_TIMEOUT = 120


class FastPathType(Enum):
    """Types of fast-path operations."""
    SCAN_HOST = "scan_host"
    LIST_HOSTS = "list_hosts"
    LIST_SERVICES = "list_services"
    CHECK_HOST = "check_host"
    HOST_INFO = "host_info"
    NONE = "none"  # No fast path, use full orchestration


@dataclass
class FastPathMatch:
    """Result of fast path pattern matching."""
    path_type: FastPathType
    hostname: Optional[str] = None
    username: Optional[str] = None
    environment: Optional[str] = None
    pattern: Optional[str] = None
    confidence: float = 0.0
    original_query: str = ""


class FastPathDetector:
    """
    Detects simple queries that can bypass full orchestration.

    Uses semantic similarity with sentence-transformers for intelligent detection,
    with keyword fallback when embeddings are unavailable.

    Patterns detected:
    - "scan @host" / "scan moi @host"
    - "services on @host" / "quels services sur @host"
    - "list hosts" / "liste des hosts"
    - "check @host" / "vérifie @host"
    """

    # Minimum confidence threshold for fast path activation
    MIN_CONFIDENCE = 0.65  # Lower threshold to catch more queries

    # Reference patterns for semantic matching
    # Each pattern type has examples in both English and French
    REFERENCE_PATTERNS: Dict[FastPathType, List[str]] = {
        FastPathType.SCAN_HOST: [
            # English - varied formulations
            "scan the server",
            "scan this host",
            "scan my server and show services",
            "what services are running on the server",
            "show me the services on host",
            "check what's running on the machine",
            "scan host for services",
            "what is running on the server",
            "get services from server",
            "scan server with username",
            "scan host with user",
            # French - varied formulations
            "scan moi le serveur",
            "scanne le host",
            "scan moi le serveur avec mon username",
            "scan moi le serveur quels sont les services",
            "quels sont les services sur le serveur",
            "montre moi les services de la machine",
            "quels services tournent sur le host",
            "liste les services du serveur",
            "qu'est-ce qui tourne sur cette machine",
            "quels sont les services rendu par cette machine",
            "quels services sont rendus par le serveur",
        ],
        FastPathType.LIST_HOSTS: [
            # English
            "list all hosts",
            "list hosts",
            "show me the servers",
            "what hosts are available",
            "list my servers",
            "show available machines",
            "what servers do I have",
            "list production hosts",
            "show staging servers",
            # French
            "liste les hosts",
            "montre moi les serveurs",
            "quels hosts sont disponibles",
            "liste mes serveurs",
            "quels sont mes serveurs",
            "affiche les machines disponibles",
            "liste les serveurs de production",
        ],
        FastPathType.CHECK_HOST: [
            # English
            "check if server is up",
            "is the host alive",
            "ping the server",
            "verify host status",
            "check server health",
            "check the server",
            "verify server",
            # French
            "vérifie si le serveur est up",
            "verifie si le serveur est up",
            "le host est-il en vie",
            "ping le serveur",
            "vérifie l'état du host",
            "verifie le host",
            "verifie le serveur",
            "check le serveur",
        ],
    }

    def __init__(self, credentials_manager=None):
        """
        Initialize fast path detector.

        Args:
            credentials_manager: Optional credentials manager for @variable resolution
        """
        self._credentials = credentials_manager
        self._use_embeddings = HAS_EMBEDDINGS
        self._embedding_cache: Optional["EmbeddingCache"] = None
        self._reference_embeddings: Dict[FastPathType, Any] = {}

        if self._use_embeddings and get_embedding_cache is not None:
            try:
                self._embedding_cache = get_embedding_cache()
                self._precompute_reference_embeddings()
                logger.info("⚡ FastPath: Using semantic detection (embeddings)")
            except Exception as e:
                logger.warning(f"⚠️ FastPath: Embeddings init failed, using keywords: {e}")
                self._use_embeddings = False
        else:
            logger.info("⚡ FastPath: Using keyword detection (no embeddings)")

    def _precompute_reference_embeddings(self) -> None:
        """Precompute embeddings for reference patterns."""
        if not self._embedding_cache or np is None:
            return

        for path_type, patterns in self.REFERENCE_PATTERNS.items():
            try:
                embeddings = self._embedding_cache.get_embeddings_batch(patterns)
                self._reference_embeddings[path_type] = np.array(embeddings)
            except Exception as e:
                logger.warning(f"Failed to compute embeddings for {path_type}: {e}")

    def detect(self, query: str) -> FastPathMatch:
        """
        Detect if query matches a fast path pattern.

        Uses semantic similarity when available, falls back to keywords.

        Args:
            query: User's query (may contain @variables)

        Returns:
            FastPathMatch with detected type and parameters
        """
        # Extract hostname and username before semantic matching
        hostname = self._extract_hostname(query)
        username = self._extract_username(query)

        if self._use_embeddings and self._embedding_cache:
            match = self._detect_semantic(query, hostname, username)
        else:
            match = self._detect_keyword(query, hostname, username)

        if match.path_type != FastPathType.NONE:
            logger.info(
                f"⚡ Fast path detected: {match.path_type.value} "
                f"(host={match.hostname}, user={match.username}, conf={match.confidence:.2f})"
            )

        return match

    def _detect_semantic(
        self, query: str, hostname: Optional[str], username: Optional[str]
    ) -> FastPathMatch:
        """Detect fast path using semantic similarity."""
        if not self._embedding_cache or np is None:
            return FastPathMatch(path_type=FastPathType.NONE, original_query=query)

        try:
            # Get query embedding
            query_clean = self._clean_query_for_embedding(query)
            query_embedding = self._embedding_cache.get_embedding(query_clean)
            query_norm = np.linalg.norm(query_embedding)

            if query_norm == 0:
                return FastPathMatch(path_type=FastPathType.NONE, original_query=query)

            # Find best matching path type
            best_type = FastPathType.NONE
            best_score = 0.0

            for path_type, ref_embeddings in self._reference_embeddings.items():
                if len(ref_embeddings) == 0:
                    continue

                # Cosine similarity
                ref_norms = np.linalg.norm(ref_embeddings, axis=1)
                valid_mask = ref_norms > 0
                if not np.any(valid_mask):
                    continue

                similarities = np.dot(ref_embeddings[valid_mask], query_embedding) / (
                    ref_norms[valid_mask] * query_norm
                )
                max_sim = float(np.max(similarities))

                if max_sim > best_score:
                    best_score = max_sim
                    best_type = path_type

            # Check if confidence meets threshold
            if best_score >= self.MIN_CONFIDENCE:
                # For semantic detection, extract environment for LIST_HOSTS
                environment = None
                if best_type == FastPathType.LIST_HOSTS:
                    environment = self._extract_environment(query)

                return FastPathMatch(
                    path_type=best_type,
                    hostname=hostname,
                    username=username,
                    environment=environment,
                    confidence=best_score,
                    original_query=query,
                )

            # Below threshold - fall back to keyword detection
            return self._detect_keyword(query, hostname, username)

        except Exception as e:
            logger.warning(f"Semantic detection failed: {e}")
            # Fallback to keyword detection
            return self._detect_keyword(query, hostname, username)

    def _detect_keyword(
        self, query: str, hostname: Optional[str], username: Optional[str]
    ) -> FastPathMatch:
        """Detect fast path using keyword patterns (fallback)."""
        query_lower = query.lower().strip()

        # Scan patterns - match common scan-related queries
        scan_patterns = [
            r"scan\s+(?:me\s+)?(?:the\s+)?@?\w",
            r"scann?e?\s+(?:moi\s+)?(?:le\s+)?@?\w",
            r"what.{0,50}?(?:service|running).{0,50}?(?:on\s+)?@?\w",
            r"(?:list|show)\s+services?\s+(?:on\s+)?@?\w",
            r"quels?\s+(?:sont\s+)?(?:les\s+)?services?",
        ]
        for pattern in scan_patterns:
            if re.search(pattern, query_lower, re.IGNORECASE):
                return FastPathMatch(
                    path_type=FastPathType.SCAN_HOST,
                    hostname=hostname,
                    username=username,
                    confidence=0.80,
                    original_query=query,
                )

        # List hosts patterns - more permissive
        list_patterns = [
            r"^list\s+(?:all\s+)?(?:\w+\s+)?hosts?$",
            r"^show\s+(?:all\s+)?(?:\w+\s+)?hosts?$",
            r"^(?:quels?\s+)?(?:sont\s+)?(?:les\s+)?(?:hosts?|serveurs?)$",
            r"^list\s+(?:\w+\s+)?servers?$",
            r"^show\s+(?:\w+\s+)?servers?$",
        ]
        for pattern in list_patterns:
            if re.search(pattern, query_lower, re.IGNORECASE):
                return FastPathMatch(
                    path_type=FastPathType.LIST_HOSTS,
                    environment=self._extract_environment(query_lower),
                    confidence=0.85,
                    original_query=query,
                )

        # Check patterns - include more variations
        check_patterns = [
            r"^check\s+@?\w",
            r"v[ée]rifi(?:e|er)?\s+@?\w",
            r"status\s+(?:of\s+)?@?\w",
            r"^ping\s+@?\w",
        ]
        for pattern in check_patterns:
            if re.search(pattern, query_lower, re.IGNORECASE):
                return FastPathMatch(
                    path_type=FastPathType.CHECK_HOST,
                    hostname=hostname,
                    username=username,
                    confidence=0.75,
                    original_query=query,
                )

        return FastPathMatch(path_type=FastPathType.NONE, original_query=query)

    def _clean_query_for_embedding(self, query: str) -> str:
        """Clean query for embedding by removing @variables and normalizing."""
        # Remove @variable references (keep semantic meaning)
        cleaned = re.sub(r"@[\w\-]+", "server", query)
        # Normalize whitespace
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _validate_hostname(self, hostname: str) -> bool:
        """Validate hostname according to RFC 1123."""
        if not hostname or len(hostname) > 253:
            return False
        # Allow IP addresses as well
        if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', hostname):
            return True
        return bool(VALID_HOSTNAME_PATTERN.match(hostname))

    def _extract_hostname(self, query: str) -> Optional[str]:
        """Extract hostname from query."""
        # Match @variable patterns
        patterns = [
            r"@([\w\-\.]+)",  # @hostname
            r"(?:host|server|machine)\s+['\"]?([\w\-\.]+)['\"]?",  # host myserver
            r"(?:sur|on|de)\s+['\"]?([\w\-\.]+)['\"]?",  # sur myserver
        ]

        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                hostname = match.group(1)
                # Skip common non-hostname words
                if hostname.lower() in ("the", "le", "la", "un", "une", "my", "mon", "ma"):
                    continue
                # Resolve @variable if credentials manager available
                resolved = self._resolve_variable(hostname)
                # Validate hostname to prevent injection
                if not self._validate_hostname(resolved):
                    logger.warning("⚠️ Invalid hostname format rejected")
                    continue
                return resolved

        return None

    def _extract_username(self, query: str) -> Optional[str]:
        """Extract username from query if present."""
        patterns = [
            r"user(?:name)?\s*(?:is|[:=]|à utiliser|c'est)\s*@?([\w\-]+)",
            r"(?:as|avec)\s+user\s+@?([\w\-]+)",
            r"@([\w\-]+)-user",  # Pattern like @myserver-user
        ]

        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                username = match.group(1)
                return self._resolve_variable(username)

        return None

    def _extract_environment(self, query: str) -> Optional[str]:
        """Extract environment filter from query."""
        env_patterns = [
            (r"\b(prod(?:uction)?)\b", "production"),
            (r"\b(stag(?:ing)?)\b", "staging"),
            (r"\b(dev(?:elopment)?)\b", "development"),
        ]
        for pattern, env in env_patterns:
            if re.search(pattern, query, re.IGNORECASE):
                return env
        return None

    def _resolve_variable(self, value: str) -> str:
        """Resolve @variable to its actual value if credentials manager available."""
        if not value:
            return value

        clean_value = value.lstrip("@")

        if self._credentials:
            try:
                resolved = self._credentials.get_variable(clean_value)
                if resolved:
                    # Never log resolved credential values
                    logger.debug(f"📝 Resolved @{clean_value} → [REDACTED]")
                    return resolved
            except Exception as e:
                logger.debug(f"Variable resolution failed for {clean_value}: {e}")

        return clean_value


class FastPathExecutor:
    """
    Executes fast path operations directly.

    Bypasses multi-agent orchestration for simple, well-defined operations.
    """

    def __init__(
        self,
        tools: Dict[str, Callable[..., Any]],
        credentials_manager=None,
    ):
        """
        Initialize fast path executor.

        Args:
            tools: Dictionary of available tools (name -> callable)
            credentials_manager: Optional credentials manager
        """
        self._tools = tools
        self._credentials = credentials_manager

    async def execute(self, match: FastPathMatch) -> Optional[str]:
        """
        Execute a fast path operation.

        Args:
            match: FastPathMatch from detector

        Returns:
            Result string if fast path executed, None if should fall back to orchestration
        """
        if match.path_type == FastPathType.NONE:
            return None

        try:
            if match.path_type == FastPathType.SCAN_HOST:
                return await self._execute_scan_host(match)
            elif match.path_type == FastPathType.LIST_HOSTS:
                return await self._execute_list_hosts(match)
            elif match.path_type == FastPathType.CHECK_HOST:
                return await self._execute_check_host(match)
            else:
                logger.warning(f"⚠️ Unhandled fast path type: {match.path_type}")
                return None

        except Exception as e:
            logger.error(f"❌ Fast path execution failed: {e}")
            return None

    async def _execute_scan_host(self, match: FastPathMatch) -> Optional[str]:
        """Execute scan_host fast path."""
        if not match.hostname:
            logger.warning("⚠️ scan_host fast path: no hostname detected")
            return None

        scan_host = self._tools.get("scan_host")
        if not scan_host:
            logger.warning("⚠️ scan_host tool not available")
            return None

        logger.info(f"⚡ Fast path: scan_host({match.hostname}, user={match.username})")

        try:
            # Execute in thread with timeout to avoid blocking event loop
            if match.username:
                result = await asyncio.wait_for(
                    asyncio.to_thread(scan_host, match.hostname, match.username),
                    timeout=TOOL_EXECUTION_TIMEOUT
                )
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(scan_host, match.hostname),
                    timeout=TOOL_EXECUTION_TIMEOUT
                )
            return result
        except asyncio.TimeoutError:
            logger.error(f"⏱️ scan_host timed out after {TOOL_EXECUTION_TIMEOUT}s")
            return None
        except Exception as e:
            logger.error(f"❌ scan_host execution failed: {e}")
            return None

    async def _execute_list_hosts(self, match: FastPathMatch) -> Optional[str]:
        """Execute list_hosts fast path."""
        list_hosts = self._tools.get("list_hosts")
        if not list_hosts:
            logger.warning("⚠️ list_hosts tool not available")
            return None

        logger.info(f"⚡ Fast path: list_hosts(environment={match.environment})")

        try:
            env = match.environment or "all"
            # Execute in thread with timeout to avoid blocking event loop
            result = await asyncio.wait_for(
                asyncio.to_thread(list_hosts, environment=env),
                timeout=TOOL_EXECUTION_TIMEOUT
            )
            return result
        except asyncio.TimeoutError:
            logger.error(f"⏱️ list_hosts timed out after {TOOL_EXECUTION_TIMEOUT}s")
            return None
        except Exception as e:
            logger.error(f"❌ list_hosts execution failed: {e}")
            return None

    async def _execute_check_host(self, match: FastPathMatch) -> Optional[str]:
        """Execute check_host fast path (uses scan_host)."""
        if not match.hostname:
            return None

        scan_host = self._tools.get("scan_host")
        if not scan_host:
            logger.warning("⚠️ scan_host tool not available")
            return None

        logger.info(f"⚡ Fast path: check_host({match.hostname})")

        try:
            # Execute in thread with timeout to avoid blocking event loop
            result = await asyncio.wait_for(
                asyncio.to_thread(scan_host, match.hostname),
                timeout=TOOL_EXECUTION_TIMEOUT
            )
            return result
        except asyncio.TimeoutError:
            logger.error(f"⏱️ check_host timed out after {TOOL_EXECUTION_TIMEOUT}s")
            return None
        except Exception as e:
            logger.error(f"❌ check_host execution failed: {e}")
            return None
