"""
Knowledge System for Athena.

Provides:
- FalkorDB graph database for knowledge storage
- Incident memory and pattern learning
- CVE monitoring
- Hybrid storage with SQLite
- Unified knowledge management facade
"""

from .schema import NodeType, RelationType, GRAPH_SCHEMA
from .falkordb_client import FalkorDBClient, FalkorDBConfig, get_falkordb_client
from .storage_manager import StorageManager, AuditEntry, SessionRecord
from .incident_memory import IncidentMemory, Incident, SimilarityMatch
from .pattern_learner import PatternLearner, Pattern, PatternMatch
from .cve_monitor import CVEMonitor, CVE, VulnerabilityCheck
from .ops_knowledge_manager import OpsKnowledgeManager, get_knowledge_manager
from .web_search import WebSearchEngine, SearchResult, SearchResponse, get_web_search_engine

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
