"""
Predictive Scanning Service - DDD Domain Service.

Analyzes queries to predict likely target hosts and pre-scans them
in background to reduce initial response latency.
"""
import re
import threading
from typing import List, Optional, Dict, Any
from athena_ai.utils.logger import logger


class PredictiveScanningService:
    """
    Domain Service for predictive host scanning.

    Analyzes user queries to predict which hosts are likely to be needed,
    then triggers background scans to have results ready when needed.

    Features:
    - Pattern-based host prediction (fast, no LLM needed)
    - Background scanning to avoid blocking
    - Smart caching (leverages existing context manager cache)
    """

    def __init__(self, context_manager):
        """
        Initialize Predictive Scanning Service.

        Args:
            context_manager: ContextManager instance for scanning hosts
        """
        self.context_manager = context_manager

    def predict_and_scan(self, query: str) -> List[str]:
        """
        Predict likely hosts from query and trigger background scans.

        Args:
            query: User's query

        Returns:
            List of predicted host names that will be scanned
        """
        # Predict hosts from query
        predicted_hosts = self._predict_hosts_from_query(query)

        if not predicted_hosts:
            logger.debug("No hosts predicted from query")
            return []

        logger.info(f"Predicted {len(predicted_hosts)} hosts, triggering background scans")

        # Trigger scans in background thread (non-blocking)
        for host in predicted_hosts:
            threading.Thread(
                target=self._scan_host_background,
                args=(host,),
                daemon=True
            ).start()

        return predicted_hosts

    def _predict_hosts_from_query(self, query: str) -> List[str]:
        """
        Predict likely target hosts from query using pattern matching.

        Strategies:
        1. Direct hostname mention (e.g., "check unifyqarcdb")
        2. Service pattern matching (e.g., "backup" → *backup*, *bdd*)
        3. Environment keywords (e.g., "prod" → *prod*)

        Args:
            query: User's query

        Returns:
            List of predicted hostnames
        """
        query_lower = query.lower()
        inventory = self.context_manager.get_context().get("inventory", {})

        if not inventory:
            return []

        predicted = []

        # Strategy 1: Direct hostname mention
        # Look for exact or partial hostname matches
        for hostname in inventory.keys():
            hostname_lower = hostname.lower()
            # Check if hostname appears in query
            if hostname_lower in query_lower:
                predicted.append(hostname)
                logger.debug(f"Direct match: {hostname}")

        # Strategy 2: Service-based prediction
        service_patterns = {
            "backup": ["backup", "bdd", "db"],
            "database": ["db", "bdd", "sql", "mongo", "postgres", "mysql"],
            "cache": ["redis", "memcache", "cache"],
            "web": ["web", "nginx", "apache", "frontend"],
            "api": ["api", "backend"],
        }

        for service_keyword, patterns in service_patterns.items():
            if service_keyword in query_lower:
                # Find hosts matching these patterns
                for hostname in inventory.keys():
                    hostname_lower = hostname.lower()
                    if any(pattern in hostname_lower for pattern in patterns):
                        if hostname not in predicted:
                            predicted.append(hostname)
                            logger.debug(f"Service pattern match: {hostname} (service: {service_keyword})")

        # Strategy 3: Environment-based prediction
        env_keywords = ["prod", "preprod", "staging", "dev", "test"]
        for env_kw in env_keywords:
            if env_kw in query_lower:
                # Find hosts in this environment
                for hostname in inventory.keys():
                    if env_kw in hostname.lower():
                        if hostname not in predicted:
                            predicted.append(hostname)
                            logger.debug(f"Environment match: {hostname} (env: {env_kw})")

        # Limit to top 3 to avoid scanning too many hosts
        predicted = predicted[:3]

        return predicted

    def _scan_host_background(self, hostname: str):
        """
        Scan a host in background thread.

        Args:
            hostname: Hostname to scan
        """
        try:
            logger.debug(f"Background scan starting: {hostname}")
            self.context_manager.scan_host(hostname)
            logger.debug(f"Background scan completed: {hostname}")
        except Exception as e:
            logger.debug(f"Background scan failed for {hostname}: {e}")

    def get_scan_status(self, hostname: str) -> Optional[Dict[str, Any]]:
        """
        Check if a host has been scanned (from cache).

        Args:
            hostname: Hostname to check

        Returns:
            Scan info if available, None otherwise
        """
        remote_hosts = self.context_manager.get_context().get("remote_hosts", {})
        return remote_hosts.get(hostname)

    def is_host_scanned(self, hostname: str) -> bool:
        """
        Check if a host has already been scanned.

        Args:
            hostname: Hostname to check

        Returns:
            True if scan is available in cache
        """
        return self.get_scan_status(hostname) is not None
