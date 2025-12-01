"""
Knowledge System for Merlya.

Provides:
- FalkorDB graph database for knowledge storage
- Incident memory and pattern learning
- CVE monitoring
- Hybrid storage with SQLite
- Unified knowledge management facade
"""

from .cve_monitor import CVE, CVEMonitor, VulnerabilityCheck
from .falkordb_client import FalkorDBClient, FalkorDBConfig, get_falkordb_client
from .incident_memory import Incident, IncidentMemory, SimilarityMatch
from .ops_knowledge_manager import OpsKnowledgeManager, get_knowledge_manager
from .pattern_learner import Pattern, PatternLearner, PatternMatch
from .schema import GRAPH_SCHEMA, NodeType, RelationType
from .storage_manager import AuditEntry, SessionRecord, StorageManager
from .web_search import SearchResponse, SearchResult, WebSearchEngine, get_web_search_engine

__all__ = [
    # Schema
    "NodeType",
    "RelationType",
    "GRAPH_SCHEMA",
    # FalkorDB
    "FalkorDBClient",
    "FalkorDBConfig",
    "get_falkordb_client",
    # Storage
    "StorageManager",
    "AuditEntry",
    "SessionRecord",
    # Incidents
    "IncidentMemory",
    "Incident",
    "SimilarityMatch",
    # Patterns
    "PatternLearner",
    "Pattern",
    "PatternMatch",
    # CVE
    "CVEMonitor",
    "CVE",
    "VulnerabilityCheck",
    # Web Search
    "WebSearchEngine",
    "SearchResult",
    "SearchResponse",
    "get_web_search_engine",
    # Facade
    "OpsKnowledgeManager",
    "get_knowledge_manager",
]
