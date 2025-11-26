"""
Base Orchestrator - Common foundation for all orchestrators.

Follows DRY principle by extracting all common initialization and utilities.
FalkorDB is used as long-term memory for incidents, patterns, and knowledge.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from athena_ai.context.manager import ContextManager
from athena_ai.executors.action_executor import ActionExecutor
from athena_ai.knowledge.storage_manager import StorageManager
from athena_ai.llm.litellm_router import LiteLLMRouter
from athena_ai.mcp.manager import MCPManager
from athena_ai.memory.session import SessionManager
from athena_ai.security.credentials import CredentialManager
from athena_ai.security.permissions import PermissionManager
from athena_ai.security.risk_assessor import RiskAssessor
from athena_ai.utils.logger import logger


class BaseOrchestrator(ABC):
    """
    Base class for all orchestrators.

    Provides common initialization and utilities following DRY principle.
    All orchestrators should inherit from this base class.

    Design Principles:
    - DRY: Single source of truth for common dependencies
    - SoC: Separates initialization from business logic
    - LoD: Dependencies are injected, not deeply coupled
    """

    def __init__(self, env: str = "dev", language: str = "en"):
        """
        Initialize base orchestrator with common dependencies.

        Args:
            env: Environment name (dev, staging, prod)
            language: Response language (en, fr)
        """
        self.env = env
        self.language = language

        # Core dependencies - shared by all orchestrators
        logger.info(f"Initializing orchestrator for {env} (language: {language})")

        # Storage manager (SQLite + FalkorDB) - hybrid persistence
        # FalkorDB is used as long-term memory (Docker auto-started if needed)
        self.storage = StorageManager(enable_falkordb=True)
        self._init_long_term_memory()

        self.llm_router = LiteLLMRouter()
        self.context_manager = ContextManager(env=env)
        self.executor = ActionExecutor()
        self.risk_assessor = RiskAssessor()
        self.credentials = CredentialManager(storage_manager=self.storage)
        self.permissions = PermissionManager(executor=self.executor)
        self.session = SessionManager(env=env)
        self.mcp_manager = MCPManager()

        logger.debug("Base orchestrator initialized")

    @abstractmethod
    async def process_request(
        self,
        user_query: str,
        auto_confirm: bool = False,
        dry_run: bool = False,
        **kwargs
    ) -> str:
        """
        Process user request - must be implemented by subclasses.

        Args:
            user_query: User's request
            auto_confirm: Auto-confirm critical actions
            dry_run: Preview only, don't execute
            **kwargs: Additional parameters

        Returns:
            Response string
        """
        pass

    def _get_context(self) -> Dict[str, Any]:
        """
        Get current context information.

        Returns:
            Context dictionary
        """
        return {
            "environment": self.env,
            "language": self.language,
            "infrastructure": self.context_manager.get_context()
        }

    def _log_request(self, query: str, response: str, execution_time_ms: int = 0):
        """
        Log request to session manager.

        Args:
            query: User query
            response: Response
            execution_time_ms: Execution time in milliseconds
        """
        if self.session.current_session_id:
            self.session.log_query(
                query=query,
                response=response,
                execution_time_ms=execution_time_ms
            )

    # =========================================================================
    # Long-Term Memory (FalkorDB)
    # =========================================================================

    def _init_long_term_memory(self) -> None:
        """
        Initialize FalkorDB as long-term memory.

        Connects to FalkorDB (auto-starts Docker container if needed).
        Gracefully degrades to SQLite-only if FalkorDB is unavailable.
        """
        try:
            if self.storage.connect_falkordb():
                logger.info("FalkorDB connected - long-term memory enabled")
                # Sync any unsynced data from SQLite
                synced = self.storage.sync_to_falkordb()
                if synced.get("incidents", 0) > 0:
                    logger.info(f"Synced {synced['incidents']} incidents to FalkorDB")
            else:
                logger.warning(
                    "FalkorDB not available - using SQLite-only mode. "
                    "Run 'docker run -d -p 6379:6379 falkordb/falkordb' to enable."
                )
        except Exception as e:
            logger.warning(f"FalkorDB init failed: {e} - continuing with SQLite-only")

    @property
    def has_long_term_memory(self) -> bool:
        """Check if long-term memory (FalkorDB) is available."""
        return self.storage.falkordb_available

    def store_incident(self, incident: Dict[str, Any]) -> str:
        """
        Store an incident in long-term memory.

        Stored in both SQLite (always) and FalkorDB (if available).

        Args:
            incident: Incident data with title, description, priority, etc.

        Returns:
            Incident ID
        """
        return self.storage.store_incident(incident)

    def find_similar_incidents(
        self,
        symptoms: Optional[List[str]] = None,
        service: Optional[str] = None,
        environment: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict]:
        """
        Find similar past incidents from long-term memory.

        Uses FalkorDB graph queries if available, falls back to SQLite.

        Args:
            symptoms: List of symptom descriptions
            service: Service name
            environment: Environment (prod, staging, dev)
            limit: Maximum number of results

        Returns:
            List of similar incidents
        """
        return self.storage.find_similar_incidents(
            symptoms=symptoms,
            service=service,
            environment=environment,
            limit=limit
        )

    def get_memory_stats(self) -> Dict[str, Any]:
        """
        Get statistics about long-term memory.

        Returns:
            Dict with SQLite and FalkorDB stats
        """
        return self.storage.get_stats()
