"""
Base Orchestrator - Common foundation for all orchestrators.

Follows DRY principle by extracting all common initialization and utilities.
"""
from typing import Optional, Dict, Any
from abc import ABC, abstractmethod

from athena_ai.llm.litellm_router import LiteLLMRouter
from athena_ai.context.manager import ContextManager
from athena_ai.executors.action_executor import ActionExecutor
from athena_ai.security.risk_assessor import RiskAssessor
from athena_ai.security.credentials import CredentialManager
from athena_ai.security.permissions import PermissionManager
from athena_ai.memory.session import SessionManager
from athena_ai.mcp.manager import MCPManager
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

        self.llm_router = LiteLLMRouter()
        self.context_manager = ContextManager(env=env)
        self.executor = ActionExecutor()
        self.risk_assessor = RiskAssessor()
        self.credentials = CredentialManager()
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
