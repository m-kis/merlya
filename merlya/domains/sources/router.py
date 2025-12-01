"""
Intelligent Router - Routes user queries to optimal data source.

This is the "intelligence" layer that decides:
- Should we query a database or SSH scan?
- Which data source has the best information?
- How to translate the user query to the source's query language?
"""
import re
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from merlya.domains.sources.connectors import SourceMetadata, SourceType
from merlya.domains.sources.discovery import SourceDiscovery
from merlya.domains.sources.registry import SourceRegistry
from merlya.utils.logger import logger


class QueryIntent(Enum):
    """User query intent classification."""
    INVENTORY_LIST = "inventory_list"  # List servers, hosts, devices
    INVENTORY_FILTER = "inventory_filter"  # Filter by criteria (env, role, etc.)
    INVENTORY_COUNT = "inventory_count"  # Count resources
    SYSTEM_STATUS = "system_status"  # Check status (requires SSH)
    CONFIG_READ = "config_read"  # Read configuration files
    CONFIG_EDIT = "config_edit"  # Edit configuration
    UNKNOWN = "unknown"


class IntelligentRouter:
    """
    Routes user queries to the optimal data source.

    Intelligence flow:
    1. Classify query intent (inventory vs runtime vs config)
    2. Check available sources (registry)
    3. Route to best source:
       - Inventory queries → Database
       - Runtime queries → SSH/API
       - Config queries → SSH
    4. Translate query to source's language (SQL, MongoDB, etc.)
    5. Execute and return results
    """

    def __init__(self, env: str = "dev", auto_discover: bool = False):
        """
        Initialize intelligent router.

        Args:
            env: Environment name
            auto_discover: Auto-discover sources on init (default: False, lazy discovery)
        """
        self.env = env
        self.registry = SourceRegistry(env=env)
        self.discovery = SourceDiscovery()

        # Auto-discover sources if explicitly requested AND (registry is empty or expired)
        if auto_discover and (not self.registry.list_sources() or self.registry.is_cache_expired()):
            logger.info("Running source discovery...")
            try:
                discovered = self.discovery.discover_all()
                for source in discovered:
                    self.registry.register(source)
            except Exception as e:
                logger.warning(f"Source discovery failed (will use lazy discovery): {e}")

    def route_query(self, user_query: str) -> Tuple[str, Dict[str, Any]]:
        """
        Route user query to optimal data source and return execution plan.

        Args:
            user_query: User's natural language query

        Returns:
            Tuple of (source_name, query_plan)
            query_plan contains: {
                "source": SourceMetadata,
                "intent": QueryIntent,
                "query": str (SQL, MongoDB query, SSH command, etc.),
                "params": dict,
                "fallback": Optional fallback plan
            }
        """
        # Step 1: Classify intent
        intent = self._classify_intent(user_query)
        logger.debug(f"Classified query intent: {intent.value}")

        # Step 2: Determine best source based on intent
        source = self._select_source(intent, user_query)

        if not source:
            # No suitable source found, fallback to SSH scanning
            logger.warning("No suitable data source found, falling back to SSH scan")
            fallback_plan = self._build_fallback_plan(user_query, intent)
            return "ssh_fallback", fallback_plan

        # Step 3: Translate query to source's language
        query_plan = self._translate_query(user_query, source, intent)

        logger.info(f"Routing query to {source.name} ({source.source_type.value})")

        return source.name, query_plan

    def execute_query(self, source_name: str, query_plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Execute query plan against data source.

        Args:
            source_name: Name of source to query
            query_plan: Query plan from route_query()

        Returns:
            Query results as list of dicts
        """
        try:
            # Get connector
            connector = self.registry.get_connector(source_name)
            if not connector:
                raise ValueError(f"No connector for source: {source_name}")

            # Execute query
            with connector:
                results = connector.query(
                    query_plan["query"],
                    query_plan.get("params")
                )

            logger.info(f"Query returned {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Query execution failed: {e}")

            # Try fallback if available
            if "fallback" in query_plan and query_plan["fallback"]:
                logger.info("Attempting fallback plan...")
                return self._execute_fallback(query_plan["fallback"])

            raise

    def _classify_intent(self, user_query: str) -> QueryIntent:
        """
        Classify user query intent.

        Args:
            user_query: User's query

        Returns:
            QueryIntent classification
        """
        query_lower = user_query.lower()

        # Inventory list patterns
        inventory_list_patterns = [
            r'\b(list|show|get|give|donne)\s+(all|tous|les)?\s*(server|host|machine|node|device)',
            r'\bserver.*list\b',
            r'\bhost.*list\b',
            r'\binventory\b',
            r'\bquel.*serveur',
            r'\bcombien.*serveur',
        ]

        for pattern in inventory_list_patterns:
            if re.search(pattern, query_lower):
                # Check if it's a count query
                if re.search(r'\b(count|combien|nombre)\b', query_lower):
                    return QueryIntent.INVENTORY_COUNT
                # Check if it's a filter query
                elif re.search(r'\b(preprod|prod|staging|dev|web|db|mongo|mysql|redis)\b', query_lower):
                    return QueryIntent.INVENTORY_FILTER
                else:
                    return QueryIntent.INVENTORY_LIST

        # Status patterns (requires SSH)
        status_patterns = [
            r'\b(status|state|running|uptime|check)\b',
            r'\bdisk\s+space\b',
            r'\bmemory\s+usage\b',
            r'\bcpu\s+usage\b',
            r'\bservice.*running\b',
        ]

        for pattern in status_patterns:
            if re.search(pattern, query_lower):
                return QueryIntent.SYSTEM_STATUS

        # Config patterns
        config_patterns = [
            r'\bconfig',
            r'\b(nginx|apache|mysql|mongodb)\.conf\b',
            r'\bedit.*file\b',
            r'\bupdate.*config\b',
        ]

        for pattern in config_patterns:
            if re.search(pattern, query_lower):
                if re.search(r'\b(edit|update|modify|change)\b', query_lower):
                    return QueryIntent.CONFIG_EDIT
                else:
                    return QueryIntent.CONFIG_READ

        return QueryIntent.UNKNOWN

    def _select_source(self, intent: QueryIntent, user_query: str) -> Optional[SourceMetadata]:
        """
        Select best data source for query intent.

        Args:
            intent: Classified intent
            user_query: User's query

        Returns:
            Best source or None
        """
        # Inventory queries: Use database if available
        if intent in [QueryIntent.INVENTORY_LIST, QueryIntent.INVENTORY_FILTER, QueryIntent.INVENTORY_COUNT]:
            # Try to find best inventory source
            inventory_source = self.discovery.get_best_source_for_inventory()
            if inventory_source:
                return inventory_source

            # Check registry for inventory sources
            sources = self.registry.list_sources()
            inventory_sources = [s for s in sources if s.capabilities and "inventory" in s.capabilities]

            if inventory_sources:
                # Prioritize databases over APIs
                db_sources = [s for s in inventory_sources if s.source_type in [
                    SourceType.POSTGRESQL, SourceType.MYSQL, SourceType.MONGODB
                ]]
                if db_sources:
                    return sorted(db_sources, key=lambda s: s.confidence, reverse=True)[0]
                else:
                    return sorted(inventory_sources, key=lambda s: s.confidence, reverse=True)[0]

        # Status queries: Need SSH (return None to fallback)
        elif intent == QueryIntent.SYSTEM_STATUS:
            # Could support API sources that provide status (Netbox, etc.)
            api_sources = self.registry.get_sources_by_type(SourceType.API)
            if api_sources:
                return api_sources[0]
            return None

        # Config queries: Need SSH (return None to fallback)
        elif intent in [QueryIntent.CONFIG_READ, QueryIntent.CONFIG_EDIT]:
            return None

        return None

    def _translate_query(
        self,
        user_query: str,
        source: SourceMetadata,
        intent: QueryIntent
    ) -> Dict[str, Any]:
        """
        Translate user query to source's query language.

        Args:
            user_query: User's natural language query
            source: Target source
            intent: Query intent

        Returns:
            Query plan dict
        """
        query_lower = user_query.lower()

        # Extract filters from query
        filters = self._extract_filters(query_lower)

        # Build query based on source type
        if source.source_type == SourceType.POSTGRESQL:
            return self._build_postgres_query(filters, intent)
        elif source.source_type == SourceType.MYSQL:
            return self._build_mysql_query(filters, intent)
        elif source.source_type == SourceType.MONGODB:
            return self._build_mongodb_query(filters, intent)
        elif source.source_type == SourceType.API:
            return self._build_api_query(filters, intent)
        else:
            raise ValueError(f"Unsupported source type: {source.source_type}")

    def _extract_filters(self, query_lower: str) -> Dict[str, str]:
        """
        Extract filters from user query.

        Args:
            query_lower: Lowercased query

        Returns:
            Dict of filters (env, role, service, etc.)
        """
        filters = {}

        # Environment filter
        env_patterns = {
            "prod": r'\b(prod|production)\b',
            "preprod": r'\bpreprod\b',
            "staging": r'\bstaging\b',
            "dev": r'\b(dev|development)\b',
        }
        for env, pattern in env_patterns.items():
            if re.search(pattern, query_lower):
                filters["environment"] = env
                break

        # Role/Service filter
        role_patterns = {
            "web": r'\bweb\b',
            "db": r'\b(db|database)\b',
            "cache": r'\b(cache|redis)\b',
            "mongo": r'\b(mongo|mongodb)\b',
            "mysql": r'\bmysql\b',
            "postgres": r'\b(postgres|postgresql)\b',
        }
        for role, pattern in role_patterns.items():
            if re.search(pattern, query_lower):
                filters["role"] = role
                break

        return filters

    def _build_postgres_query(self, filters: Dict[str, str], intent: QueryIntent) -> Dict[str, Any]:
        """Build PostgreSQL query from filters."""
        # Try common table names
        table_names = ["hosts", "servers", "inventory", "assets", "devices"]

        # Build WHERE clause
        where_clauses = []
        params = {}

        if "environment" in filters:
            where_clauses.append("environment = %(environment)s OR env = %(environment)s")
            params["environment"] = filters["environment"]

        if "role" in filters:
            where_clauses.append("role = %(role)s OR service = %(role)s OR type = %(role)s")
            params["role"] = filters["role"]

        where_str = " AND ".join(where_clauses) if where_clauses else "1=1"

        # Build SELECT based on intent
        if intent == QueryIntent.INVENTORY_COUNT:
            query = f"SELECT COUNT(*) as count FROM {table_names[0]} WHERE {where_str}"
        else:
            query = f"SELECT * FROM {table_names[0]} WHERE {where_str} LIMIT 100"

        return {
            "source": None,  # Will be filled by caller
            "intent": intent,
            "query": query,
            "params": params,
            "fallback": self._build_fallback_plan("", intent)
        }

    def _build_mysql_query(self, filters: Dict[str, str], intent: QueryIntent) -> Dict[str, Any]:
        """Build MySQL query (same as PostgreSQL for basic queries)."""
        return self._build_postgres_query(filters, intent)

    def _build_mongodb_query(self, filters: Dict[str, str], intent: QueryIntent) -> Dict[str, Any]:
        """Build MongoDB query from filters."""
        # Build query document
        query_doc: Dict[str, Any] = {}

        if "environment" in filters:
            query_doc["$or"] = [
                {"environment": filters["environment"]},
                {"env": filters["environment"]}
            ]

        if "role" in filters:
            if "$or" in query_doc:
                # Combine with AND
                query_doc = {
                    "$and": [
                        query_doc,
                        {"$or": [
                            {"role": filters["role"]},
                            {"service": filters["role"]},
                            {"type": filters["role"]}
                        ]}
                    ]
                }
            else:
                query_doc["$or"] = [
                    {"role": filters["role"]},
                    {"service": filters["role"]},
                    {"type": filters["role"]}
                ]

        # Collection names to try
        collection = "hosts"  # Default

        params: Any
        if intent == QueryIntent.INVENTORY_COUNT:
            query = f"{collection}.aggregate"
            params = [{"$match": query_doc}, {"$count": "count"}]
        else:
            query = f"{collection}.find"
            params = query_doc

        return {
            "source": None,
            "intent": intent,
            "query": query,
            "params": params,
            "fallback": self._build_fallback_plan("", intent)
        }

    def _build_api_query(self, filters: Dict[str, str], intent: QueryIntent) -> Dict[str, Any]:
        """Build API query from filters."""
        # For Netbox/Nautobot style APIs
        endpoint = "/dcim/devices"  # Common endpoint

        # Build query params
        params = {}
        if "environment" in filters:
            params["tag"] = filters["environment"]
        if "role" in filters:
            params["role"] = filters["role"]

        return {
            "source": None,
            "intent": intent,
            "query": endpoint,
            "params": params,
            "fallback": self._build_fallback_plan("", intent)
        }

    def _build_fallback_plan(self, user_query: str, intent: QueryIntent) -> Dict[str, Any]:
        """Build fallback plan (SSH scan)."""
        return {
            "type": "ssh_scan",
            "intent": intent,
            "query": user_query
        }

    def _execute_fallback(self, fallback_plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute fallback plan (SSH scan)."""
        logger.warning("Executing fallback: SSH scan")
        # This would delegate to existing Discovery.scan_remote_hosts()
        # For now, return empty to avoid circular dependency
        return []
