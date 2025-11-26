"""
Info Request Service - DDD Domain Service.

Responsible for executing INFO_REQUEST workflows.
"""
import re
from typing import Any, Dict, List

from rich.console import Console

from athena_ai.agents import autogen_tools
from athena_ai.utils.logger import logger

console = Console()


class InfoRequestService:
    """
    Domain Service for handling INFO_REQUEST workflows.

    Coordinates:
    - Scanning hosts for services
    - Parsing service information
    - Delegating to RoleInferenceService
    """

    def __init__(self, role_inference_service):
        """
        Initialize Info Request Service.

        Args:
            role_inference_service: RoleInferenceService instance
        """
        self.role_inference = role_inference_service

    def execute_workflow(self, target_host: str, context: Dict[str, Any]) -> str:
        """
        Execute info request workflow - explain server's role/purpose.

        Steps:
        1. Scan host to get services
        2. Parse services from scan
        3. Infer role using RoleInferenceService
        4. Generate explanation using RoleInferenceService

        Args:
            target_host: Target hostname
            context: Accumulated context

        Returns:
            Formatted explanation of server's role
        """
        logger.info(f"Executing INFO_REQUEST workflow for {target_host}")

        try:
            # Step 1: Scan host
            console.print()
            console.print("[bold]🔍 Scanning host...[/bold]")
            scan_result = autogen_tools.scan_host(target_host)

            # Step 2: Parse services
            services = self._parse_services_from_scan(scan_result)

            # Step 3: Infer role
            console.print("[bold]🧠 Analyzing server role...[/bold]")
            role_info = self.role_inference.infer_role(target_host, services)

            # Step 4: Extract uptime
            uptime_days = self._extract_uptime(scan_result)

            # Step 5: Generate explanation
            explanation = self.role_inference.generate_explanation(
                target_host,
                role_info,
                services,
                uptime_days
            )

            return explanation

        except Exception as e:
            logger.error(f"INFO_REQUEST workflow failed: {e}", exc_info=True)
            return f"❌ Impossible d'obtenir les informations sur {target_host}: {str(e)}"

    def _parse_services_from_scan(self, scan_result: str) -> List[str]:
        """
        Parse scan result to extract service names.

        Args:
            scan_result: Raw scan output

        Returns:
            List of detected service names
        """
        services = []
        if not scan_result:
            return services

        # Service keywords to look for
        service_keywords = [
            "mysql", "mariadb", "postgres", "mongodb",
            "nginx", "apache", "redis", "memcached",
            "haproxy", "traefik"
        ]

        lines = scan_result.split('\n')
        for line in lines:
            for service_name in service_keywords:
                if service_name in line.lower():
                    if service_name not in services:
                        services.append(service_name)

        return services

    def _extract_uptime(self, scan_result: str) -> int:
        """
        Extract uptime in days from scan result.

        Args:
            scan_result: Raw scan output

        Returns:
            Uptime in days, or None if not found
        """
        if not scan_result:
            return None

        uptime_match = re.search(r'(\d+)\s+days?', scan_result, re.IGNORECASE)
        if uptime_match:
            return int(uptime_match.group(1))

        return None
