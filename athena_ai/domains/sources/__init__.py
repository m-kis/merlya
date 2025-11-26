"""
Intelligent Source Discovery and Routing.

Provides the "intelligence" to:
- Auto-discover data sources on localhost (PostgreSQL, MySQL, MongoDB, APIs)
- Intelligently route queries to the optimal source
- Translate user queries to source-specific query languages

This eliminates manual filtering and enables true intelligent infrastructure
management.
"""
from athena_ai.domains.sources.discovery import SourceDiscovery
from athena_ai.domains.sources.registry import SourceRegistry
from athena_ai.domains.sources.router import IntelligentRouter, QueryIntent

__all__ = [
    "SourceDiscovery",
    "SourceRegistry",
    "IntelligentRouter",
    "QueryIntent",
]
