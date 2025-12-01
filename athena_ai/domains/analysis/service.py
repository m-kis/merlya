"""
Analysis Service - DDD Domain Service.

Orchestrates system analysis by:
- Extracting entities from context
- Determining investigation strategy
- Executing diagnostic commands
- Collecting and formatting results
"""
from typing import Any, Callable, Dict, Optional

from athena_ai.utils.logger import logger


class AnalysisService:
    """
    Domain Service for orchestrating system analysis workflows.

    Coordinates entity extraction, investigation strategy,
    and command execution.
    """

    def __init__(self, entity_extractor, investigation_service):
        """
        Initialize Analysis Service.

        Args:
            entity_extractor: EntityExtractor instance
            investigation_service: InvestigationService instance
        """
        self.entity_extractor = entity_extractor
        self.investigation_service = investigation_service

    def execute_analysis(
        self,
        context: Dict[str, Any],
        command_executor: Callable
    ) -> Dict[str, Any]:
        """
        Execute complete analysis workflow.

        Steps:
        1. Extract target host and service from context
        2. Validate inputs
        3. Determine investigation strategy
        4. Generate appropriate commands
        5. Execute commands and collect results

        Args:
            context: Execution context with query and infrastructure info
            command_executor: Function to execute commands (target, command, reason)

        Returns:
            {
                "success": bool,
                "message": str,
                "output": {"analysis_results": [...], "target": str},
                "error": str (if failed)
            }
        """
        try:
            # Step 1: Extract entities
            target_host = self.entity_extractor.extract_target_from_context(context)
            service_name = self.entity_extractor.extract_service_from_context(context)
            original_query = context.get("original_query", "")

            # Step 2: Validate inputs
            validation_error = self._validate_inputs(target_host)
            if validation_error:
                return validation_error

            # Step 3-4: Determine strategy and generate commands
            commands_list, reasons = self._generate_commands(
                service_name, target_host, original_query
            )

            # Step 5: Execute commands and collect results
            results = self._execute_commands(
                commands_list, reasons, target_host, command_executor
            )

            return {
                "success": True,
                "message": f"Analysis completed on {target_host}",
                "output": {"analysis_results": results, "target": target_host}
            }

        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Analysis execution failed"
            }

    def _validate_inputs(self, target_host: str) -> Optional[Dict[str, Any]]:
        """
        Validate analysis inputs.

        Args:
            target_host: Extracted target hostname

        Returns:
            Error dict if validation fails, None if valid
        """
        if target_host == "__CLARIFICATION_NEEDED__":
            return {
                "success": False,
                "error": "CLARIFICATION_NEEDED",
                "message": "Cannot proceed without clarifying target host"
            }

        if not target_host:
            return {
                "success": False,
                "message": "No target host specified for analysis",
                "error": "Missing target host"
            }

        return None

    def _generate_commands(
        self,
        service_name: str,
        target_host: str,
        original_query: str
    ) -> tuple:
        """
        Generate commands and reasons based on investigation strategy.

        Args:
            service_name: Service to investigate (or None)
            target_host: Target hostname
            original_query: Original user query

        Returns:
            (commands_list, reasons_list)
        """
        strategy = self.investigation_service.get_investigation_strategy(service_name)

        if strategy == "direct":
            # DIRECT SERVICE: Use simple systemctl commands
            logger.info(f"Detected direct service: {service_name}")
            commands_list = self.investigation_service.get_direct_service_commands(service_name)
            reasons = [
                f"Check {service_name} service status",
                f"Verify {service_name} process"
            ]
        elif strategy == "concept":
            # CONCEPT: Use intelligent investigation
            logger.info(f"Detected concept requiring investigation: {service_name}")
            commands_list = self.investigation_service.generate_investigation_commands(
                service_name, target_host, original_query
            )
            reasons = [f"Investigate {service_name}" for _ in commands_list]
        else:
            # GENERIC: No specific service/concept
            logger.info("No specific service detected, using generic analysis")
            commands_list = self.investigation_service.get_generic_commands()
            reasons = [
                "Check system uptime and load",
                "Check disk usage"
            ]

        return commands_list, reasons

    def _execute_commands(
        self,
        commands_list: list,
        reasons: list,
        target_host: str,
        command_executor: Callable
    ) -> list:
        """
        Execute commands and collect results.

        Args:
            commands_list: List of commands to execute
            reasons: List of reasons (one per command)
            target_host: Target hostname
            command_executor: Function to execute commands

        Returns:
            List of result dicts with command and result
        """
        results = []
        for command, reason in zip(commands_list, reasons, strict=False):
            logger.info(f"Executing analysis command: {command}")
            result = command_executor(
                target=target_host,
                command=command,
                reason=reason
            )
            results.append({
                "command": command,
                "result": result[:500]  # Truncate to avoid bloat
            })
        return results
