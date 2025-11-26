"""
PlannerAgent: Decomposes complex tasks into executable steps.

The planner analyzes user requests and creates structured execution plans
that minimize context size and maximize clarity.
"""
from typing import List, Dict, Any
import json
from athena_ai.utils.logger import logger


class PlannerAgent:
    """
    Agent responsible for task decomposition and planning.
    """

    def __init__(self, llm_client):
        """
        Initialize planner with LLM client.

        Args:
            llm_client: LiteLLM or similar client for planning
        """
        self.llm = llm_client

    def create_plan(self, request: str, context_summary: str = "") -> List[Dict[str, Any]]:
        """
        Create an execution plan for a user request.

        Args:
            request: User's request
            context_summary: Brief context (< 500 tokens)

        Returns:
            List of step dictionaries
        """
        logger.info(f"Planning for request: {request}")

        # Detect task type
        task_type = self._detect_task_type(request)
        logger.debug(f"Detected task type: {task_type}")

        # Generate plan using LLM
        if task_type == "service_analysis":
            plan = self._plan_service_analysis(request, context_summary)
        elif task_type == "troubleshooting":
            plan = self._plan_troubleshooting(request, context_summary)
        elif task_type == "monitoring":
            plan = self._plan_monitoring(request, context_summary)
        elif task_type == "deployment":
            plan = self._plan_deployment(request, context_summary)
        else:
            plan = self._plan_generic(request, context_summary)

        logger.info(f"Created plan with {len(plan)} steps")
        return plan

    def _detect_task_type(self, request: str) -> str:
        """
        Detect the type of task from the request.

        Args:
            request: User request

        Returns:
            Task type string
        """
        request_lower = request.lower()

        # Service analysis keywords
        if any(keyword in request_lower for keyword in [
            "analyze", "analysis", "full analysis", "check service", "inspect"
        ]):
            return "service_analysis"

        # Troubleshooting keywords
        if any(keyword in request_lower for keyword in [
            "why", "bug", "not working", "error", "issue", "problem", "debug"
        ]):
            return "troubleshooting"

        # Monitoring keywords
        if any(keyword in request_lower for keyword in [
            "monitor", "watch", "cpu", "memory", "disk", "metrics", "status"
        ]):
            return "monitoring"

        # Deployment keywords
        if any(keyword in request_lower for keyword in [
            "deploy", "install", "configure", "setup", "provision"
        ]):
            return "deployment"

        return "generic"

    def _plan_service_analysis(self, request: str, context: str) -> List[Dict[str, Any]]:
        """
        Plan for comprehensive service analysis.

        Example: "make full analysis of mysql service on unifyqarcdb"
        """
        # Extract service name and host from request
        service = self._extract_service_name(request)
        host = self._extract_host_name(request)

        logger.debug(f"Service analysis: {service} on {host}")

        steps = [
            {
                "id": 1,
                "description": f"Verify host '{host}' exists and test SSH connectivity",
                "dependencies": [],
                "parallelizable": False,
                "estimated_tokens": 500
            },
            {
                "id": 2,
                "description": f"Identify {service} service and get basic status",
                "dependencies": [1],
                "parallelizable": False,
                "estimated_tokens": 800
            },
            {
                "id": 3,
                "description": f"Collect {service} configuration",
                "dependencies": [2],
                "parallelizable": True,
                "estimated_tokens": 1200
            },
            {
                "id": 4,
                "description": f"Analyze {service} logs (error, slow query, etc.)",
                "dependencies": [2],
                "parallelizable": True,
                "estimated_tokens": 1500
            },
            {
                "id": 5,
                "description": f"Check {service} performance metrics",
                "dependencies": [2],
                "parallelizable": True,
                "estimated_tokens": 1000
            },
            {
                "id": 6,
                "description": f"Analyze {service} data and disk usage",
                "dependencies": [2],
                "parallelizable": True,
                "estimated_tokens": 800
            },
            {
                "id": 7,
                "description": "Check system resources (CPU, RAM, disk)",
                "dependencies": [2],
                "parallelizable": True,
                "estimated_tokens": 600
            },
            {
                "id": 8,
                "description": f"Verify {service} backup status",
                "dependencies": [2],
                "parallelizable": True,
                "estimated_tokens": 600
            },
            {
                "id": 9,
                "description": "Synthesize findings and generate comprehensive report",
                "dependencies": [3, 4, 5, 6, 7, 8],
                "parallelizable": False,
                "estimated_tokens": 2000
            }
        ]

        return steps

    def _plan_troubleshooting(self, request: str, context: str) -> List[Dict[str, Any]]:
        """
        Plan for troubleshooting issues.

        Example: "why is nginx not working on prod001"
        """
        service = self._extract_service_name(request)
        host = self._extract_host_name(request)

        steps = [
            {
                "id": 1,
                "description": f"Check if host '{host}' is accessible",
                "dependencies": [],
                "parallelizable": False,
                "estimated_tokens": 400
            },
            {
                "id": 2,
                "description": f"Check {service} service status",
                "dependencies": [1],
                "parallelizable": False,
                "estimated_tokens": 500
            },
            {
                "id": 3,
                "description": f"Analyze {service} error logs (last 100 lines)",
                "dependencies": [2],
                "parallelizable": True,
                "estimated_tokens": 1500
            },
            {
                "id": 4,
                "description": f"Check {service} configuration validity",
                "dependencies": [2],
                "parallelizable": True,
                "estimated_tokens": 800
            },
            {
                "id": 5,
                "description": "Check system resources (disk space, memory)",
                "dependencies": [2],
                "parallelizable": True,
                "estimated_tokens": 600
            },
            {
                "id": 6,
                "description": "Check network connectivity (ports, firewall)",
                "dependencies": [2],
                "parallelizable": True,
                "estimated_tokens": 700
            },
            {
                "id": 7,
                "description": "Identify root cause and propose solutions",
                "dependencies": [3, 4, 5, 6],
                "parallelizable": False,
                "estimated_tokens": 1500
            }
        ]

        return steps

    def _plan_monitoring(self, request: str, context: str) -> List[Dict[str, Any]]:
        """
        Plan for monitoring tasks.

        Example: "which machines have CPU > 80%"
        """
        steps = [
            {
                "id": 1,
                "description": "Load inventory and identify target hosts",
                "dependencies": [],
                "parallelizable": False,
                "estimated_tokens": 600
            },
            {
                "id": 2,
                "description": "Collect metrics from all hosts (parallel)",
                "dependencies": [1],
                "parallelizable": True,
                "estimated_tokens": 1500
            },
            {
                "id": 3,
                "description": "Filter and sort results by criteria",
                "dependencies": [2],
                "parallelizable": False,
                "estimated_tokens": 800
            },
            {
                "id": 4,
                "description": "Present findings in organized format",
                "dependencies": [3],
                "parallelizable": False,
                "estimated_tokens": 600
            }
        ]

        return steps

    def _plan_deployment(self, request: str, context: str) -> List[Dict[str, Any]]:
        """
        Plan for deployment tasks.

        Example: "deploy nginx config to all web servers"
        """
        steps = [
            {
                "id": 1,
                "description": "Validate deployment prerequisites",
                "dependencies": [],
                "parallelizable": False,
                "estimated_tokens": 600
            },
            {
                "id": 2,
                "description": "Backup existing configurations",
                "dependencies": [1],
                "parallelizable": True,
                "estimated_tokens": 800
            },
            {
                "id": 3,
                "description": "Deploy to staging/test environment first",
                "dependencies": [2],
                "parallelizable": False,
                "estimated_tokens": 1000
            },
            {
                "id": 4,
                "description": "Verify deployment on staging",
                "dependencies": [3],
                "parallelizable": False,
                "estimated_tokens": 800
            },
            {
                "id": 5,
                "description": "Request user confirmation for production deployment",
                "dependencies": [4],
                "parallelizable": False,
                "estimated_tokens": 400
            },
            {
                "id": 6,
                "description": "Deploy to production hosts",
                "dependencies": [5],
                "parallelizable": True,
                "estimated_tokens": 1500
            },
            {
                "id": 7,
                "description": "Verify production deployment",
                "dependencies": [6],
                "parallelizable": False,
                "estimated_tokens": 1000
            }
        ]

        return steps

    def _plan_generic(self, request: str, context: str) -> List[Dict[str, Any]]:
        """
        Plan for generic tasks using LLM.

        This creates a simple 3-step plan for tasks that don't match specific patterns.
        """
        steps = [
            {
                "id": 1,
                "description": "Gather necessary context and information",
                "dependencies": [],
                "parallelizable": False,
                "estimated_tokens": 800
            },
            {
                "id": 2,
                "description": "Execute required actions",
                "dependencies": [1],
                "parallelizable": False,
                "estimated_tokens": 1500
            },
            {
                "id": 3,
                "description": "Analyze results and provide response",
                "dependencies": [2],
                "parallelizable": False,
                "estimated_tokens": 1000
            }
        ]

        return steps

    def _extract_service_name(self, request: str) -> str:
        """
        Extract service name from request.

        Args:
            request: User request

        Returns:
            Service name or 'service'
        """
        request_lower = request.lower()

        # Common service names
        services = [
            "nginx", "apache", "httpd", "mysql", "mariadb", "postgres", "postgresql",
            "mongodb", "redis", "memcached", "elasticsearch", "rabbitmq", "kafka",
            "docker", "kubernetes", "k8s", "tomcat", "jenkins", "gitlab"
        ]

        for service in services:
            if service in request_lower:
                return service

        # Try to extract from "service X" pattern
        if " service " in request_lower:
            parts = request_lower.split(" service ")
            if len(parts) > 1:
                # Get word before "service"
                words_before = parts[0].split()
                if words_before:
                    return words_before[-1]

        return "service"

    def _extract_host_name(self, request: str) -> str:
        """
        Extract host name from request.

        Args:
            request: User request

        Returns:
            Host name or 'host'
        """
        # Look for common patterns: "on X", "from X", "at X"
        for prep in ["on ", "from ", "at "]:
            if prep in request.lower():
                parts = request.lower().split(prep)
                if len(parts) > 1:
                    # Get first word after preposition
                    words_after = parts[1].split()
                    if words_after:
                        # Clean up punctuation
                        host = words_after[0].strip(",.;:!?")
                        if host:
                            return host

        return "host"


class SimplePlanner:
    """
    Simplified planner that doesn't use LLM (fallback).
    """

    def create_simple_plan(self, request: str) -> List[Dict[str, Any]]:
        """
        Create a simple 3-step plan without LLM.

        Args:
            request: User request

        Returns:
            Simple plan
        """
        return [
            {
                "id": 1,
                "description": "Understand request and gather context",
                "dependencies": [],
                "parallelizable": False,
                "estimated_tokens": 800
            },
            {
                "id": 2,
                "description": f"Execute: {request}",
                "dependencies": [1],
                "parallelizable": False,
                "estimated_tokens": 1500
            },
            {
                "id": 3,
                "description": "Analyze and present results",
                "dependencies": [2],
                "parallelizable": False,
                "estimated_tokens": 1000
            }
        ]
