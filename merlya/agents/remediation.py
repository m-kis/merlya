"""
Enhanced Remediation Agent with Self-Healing Capabilities.

Provides 3 operational modes:
- CONSERVATIVE: Suggest only, human approves all actions
- SEMI_AUTO: Auto-execute safe commands, ask for risky ones
- SENTINEL: Full auto with safeguards (for monitoring/alerting scenarios)
"""

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from merlya.agents.base import BaseAgent
from merlya.knowledge import get_knowledge_manager
from merlya.remediation.rollback import RollbackManager
from merlya.utils.logger import logger


class RemediationMode(Enum):
    """Remediation execution modes."""
    CONSERVATIVE = "conservative"  # Suggest only, human approves
    SEMI_AUTO = "semi_auto"        # Auto-execute safe, ask for risky
    SENTINEL = "sentinel"          # Full auto with safeguards


@dataclass
class RemediationResult:
    """Result of a remediation attempt."""
    success: bool
    mode: RemediationMode
    actions_suggested: List[Dict[str, Any]]
    actions_executed: List[Dict[str, Any]]
    actions_skipped: List[Dict[str, Any]]
    rollbacks_created: List[Dict[str, Any]]
    confidence: float
    source: str  # "pattern", "incident", "llm"
    error: Optional[str] = None


class RemediationAgent(BaseAgent):
    """
    Intelligent remediation agent with self-healing capabilities.

    Modes:
        CONSERVATIVE: All actions require human approval.
                     Best for production environments with strict change control.

        SEMI_AUTO: Safe actions (read-only, status checks) execute automatically.
                  Risky actions (restarts, modifications) require approval.
                  Good balance between automation and safety.

        SENTINEL: Full automation with safeguards.
                 Uses rollback capabilities for risky actions.
                 Best for automated monitoring/alerting scenarios.
    """

    # Safe commands that can be auto-executed in SEMI_AUTO mode
    SAFE_COMMAND_PATTERNS = [
        "systemctl status", "service status",
        "ps ", "top", "htop",
        "df ", "du ", "free",
        "ls ", "cat ", "tail ", "head ", "grep ",
        "docker ps", "docker logs", "docker inspect",
        "kubectl get", "kubectl describe", "kubectl logs",
        "ping ", "curl ", "wget ", "nc -z",
        "SELECT ", "SHOW ", "DESCRIBE ", "EXPLAIN ",
    ]

    # High-risk commands that require extra confirmation even in SENTINEL mode
    HIGH_RISK_PATTERNS = [
        "rm -rf", "rm -r /", "dd if=", "mkfs",
        "DROP TABLE", "DROP DATABASE", "TRUNCATE",
        "shutdown", "reboot", "halt", "init 0",
        ":(){:|:&};:", "chmod -R 777",
    ]

    def __init__(
        self,
        context_manager,
        mode: RemediationMode = RemediationMode.CONSERVATIVE,
        approval_callback: Optional[Callable[[Dict], bool]] = None,
    ):
        """
        Initialize RemediationAgent.

        Args:
            context_manager: Context manager for environment info
            mode: Remediation mode (CONSERVATIVE, SEMI_AUTO, SENTINEL)
            approval_callback: Optional callback for approval requests
                              Signature: (action_dict) -> bool
                              If None, uses console prompt
        """
        super().__init__(context_manager)
        self.name = "RemediationAgent"
        self.mode = mode
        self.rollback_manager = RollbackManager()
        self.knowledge = get_knowledge_manager()
        self.approval_callback = approval_callback or self._default_approval

    def _default_approval(self, action: Dict) -> bool:
        """Default approval via console prompt."""
        cmd = action.get("command", "unknown")
        action_type = action.get("type", "shell")
        risk = action.get("risk_level", "unknown")

        print("\n❓​ Approval Required:")
        print(f"   Command: {cmd}")
        print(f"   Type: {action_type}")
        print(f"   Risk: {risk}")

        try:
            response = input("   Execute? (y/N): ").strip().lower()
            return response == 'y'
        except (KeyboardInterrupt, EOFError):
            return False

    def set_mode(self, mode: RemediationMode):
        """Change the remediation mode."""
        old_mode = self.mode
        self.mode = mode
        logger.info(f"RemediationAgent mode changed: {old_mode.value} -> {mode.value}")

    def run(  # type: ignore[override]
        self,
        task: str,
        target: str = "local",
        confirm: bool = False,
        dry_run: bool = False,
        incident_id: Optional[str] = None,
        symptoms: Optional[List[str]] = None,
        service: Optional[str] = None,
    ) -> RemediationResult:
        """
        Execute remediation based on mode.

        Args:
            task: Description of what needs to be remediated
            target: Target host or 'local'
            confirm: Force confirmation for all actions (overrides mode)
            dry_run: Plan but don't execute
            incident_id: Optional incident ID for context
            symptoms: Observed symptoms
            service: Affected service name

        Returns:
            RemediationResult with actions and outcomes
        """
        logger.info(f"RemediationAgent [{self.mode.value}] starting: {task}")

        # 1. Get remediation suggestion from knowledge base
        remediation = self._get_remediation_plan(
            task=task,
            incident_id=incident_id,
            symptoms=symptoms,
            service=service,
            target=target,
        )

        if not remediation or not remediation.get("commands"):
            logger.info("No existing remediation found, using LLM to generate plan")
            remediation = self._generate_llm_plan(task, target)

        if not remediation:
            return RemediationResult(
                success=False,
                mode=self.mode,
                actions_suggested=[],
                actions_executed=[],
                actions_skipped=[],
                rollbacks_created=[],
                confidence=0.0,
                source="none",
                error="Could not generate remediation plan",
            )

        # 2. Prepare actions with risk assessment
        actions = self._prepare_actions(remediation)
        source = remediation.get("source", "llm")
        confidence = remediation.get("confidence", 0.5)

        if dry_run:
            return RemediationResult(
                success=True,
                mode=self.mode,
                actions_suggested=actions,
                actions_executed=[],
                actions_skipped=actions,
                rollbacks_created=[],
                confidence=confidence,
                source=source,
            )

        # 3. Execute based on mode
        executed = []
        skipped = []
        rollbacks = []

        for action in actions:
            should_execute, reason = self._should_execute(action, confirm)

            if not should_execute:
                action["skip_reason"] = reason
                skipped.append(action)
                logger.info(f"Skipped action: {action.get('command')} ({reason})")
                continue

            # Prepare rollback if needed
            if action.get("risk_level") != "low":
                rollback = self.rollback_manager.prepare_rollback(
                    target,
                    action.get("type", "shell"),
                    action.get("details", {}),
                )
                if rollback.get("type") != "none":
                    rollbacks.append(rollback)

            # Execute
            result = self.executor.execute(
                target,
                action["command"],
                confirm=self.mode == RemediationMode.CONSERVATIVE,
            )

            action["result"] = result
            executed.append(action)

            if not result.get("success"):
                logger.error(f"Action failed: {action['command']}")
                # In SENTINEL mode, attempt auto-rollback
                if self.mode == RemediationMode.SENTINEL and rollbacks:
                    logger.info("Initiating auto-rollback...")
                    self._execute_rollbacks(rollbacks, target)
                break

        # 4. Record outcome for learning
        self._record_outcome(
            task=task,
            actions=executed,
            success=all(a.get("result", {}).get("success") for a in executed),
            service=service,
        )

        return RemediationResult(
            success=all(a.get("result", {}).get("success") for a in executed),
            mode=self.mode,
            actions_suggested=actions,
            actions_executed=executed,
            actions_skipped=skipped,
            rollbacks_created=rollbacks,
            confidence=confidence,
            source=source,
        )

    def _get_remediation_plan(
        self,
        task: str,
        incident_id: Optional[str],
        symptoms: Optional[List[str]],
        service: Optional[str],
        target: str,
    ) -> Optional[Dict[str, Any]]:
        """Get remediation from knowledge base."""
        try:
            return self.knowledge.get_remediation_for_incident(
                incident_id=incident_id,
                symptoms=symptoms,
                service=service,
                title=task,
            )
        except Exception as e:
            logger.warning(f"Knowledge lookup failed: {e}")
            return None

    def _generate_llm_plan(self, task: str, target: str) -> Optional[Dict[str, Any]]:
        """Generate remediation plan using LLM."""
        context = self.context_manager.get_context()

        prompt = f"""
Task: {task}
Target: {target}
Context: {json.dumps(context.get('local', {}), indent=2)}

Generate remediation actions as JSON list.
Each action: {{"command": "...", "type": "shell"|"edit_file", "details": {{}}}}

Focus on safe, reversible actions. Prefer restarts over reinstalls.
Return ONLY valid JSON list.
"""
        system_prompt = "You are an expert SRE. Return only raw JSON, no explanation."

        try:
            response = self.llm.generate(prompt, system_prompt)
            response = response.replace("```json", "").replace("```", "").strip()
            actions = json.loads(response)

            return {
                "commands": [a.get("command") for a in actions if a.get("command")],
                "actions": actions,
                "confidence": 0.5,
                "source": "llm",
            }
        except Exception as e:
            logger.error(f"LLM plan generation failed: {e}")
            return None

    def _prepare_actions(self, remediation: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Prepare actions with risk assessment."""
        actions = remediation.get("actions", [])

        # If we only have commands, convert to action format
        if not actions and remediation.get("commands"):
            actions = [
                {"command": cmd, "type": "shell", "details": {}}
                for cmd in remediation["commands"]
            ]

        # Assess risk for each action
        for action in actions:
            cmd = action.get("command", "")
            action["risk_level"] = self._assess_risk(cmd)

        return actions

    def _assess_risk(self, command: str) -> str:
        """Assess the risk level of a command."""
        cmd_lower = command.lower()

        # High risk
        for pattern in self.HIGH_RISK_PATTERNS:
            if pattern.lower() in cmd_lower:
                return "high"

        # Safe (low risk)
        for pattern in self.SAFE_COMMAND_PATTERNS:
            if pattern.lower() in cmd_lower:
                return "low"

        # Default to medium
        return "medium"

    def _should_execute(self, action: Dict, force_confirm: bool) -> tuple:
        """
        Determine if action should execute based on mode.

        Returns:
            (should_execute, reason) tuple
        """
        risk = action.get("risk_level", "medium")
        cmd = action.get("command", "")

        # High risk always blocked in CONSERVATIVE and SEMI_AUTO
        if risk == "high" and self.mode != RemediationMode.SENTINEL:
            return False, "high_risk_blocked"

        # CONSERVATIVE: Always require approval
        if self.mode == RemediationMode.CONSERVATIVE or force_confirm:
            if self.approval_callback(action):
                return True, "approved"
            return False, "denied"

        # SEMI_AUTO: Auto-execute safe, ask for others
        if self.mode == RemediationMode.SEMI_AUTO:
            if risk == "low":
                return True, "auto_safe"
            if self.approval_callback(action):
                return True, "approved"
            return False, "denied"

        # SENTINEL: Execute with safeguards
        if self.mode == RemediationMode.SENTINEL:
            if risk == "high":
                # Even SENTINEL asks for high-risk
                logger.warning(f"High-risk action in SENTINEL mode: {cmd}")
                if self.approval_callback(action):
                    return True, "approved_high_risk"
                return False, "high_risk_denied"
            return True, "auto_sentinel"

        return False, "unknown_mode"

    def _execute_rollbacks(self, rollbacks: List[Dict], target: str):
        """Execute rollback actions in reverse order."""
        for rollback in reversed(rollbacks):
            rollback_cmd = rollback.get("command")
            if rollback_cmd:
                logger.info(f"Executing rollback: {rollback_cmd}")
                self.executor.execute(target, rollback_cmd, confirm=False)

    def _record_outcome(
        self,
        task: str,
        actions: List[Dict],
        success: bool,
        service: Optional[str],
    ):
        """Record remediation outcome for learning."""
        try:
            if success and actions:
                # Extract commands that worked
                commands = [a["command"] for a in actions if a.get("result", {}).get("success")]

                # Log successful remediation pattern
                logger.info(f"Successful remediation recorded: {len(commands)} commands")

                # Future: Add to pattern learner
                # self.knowledge.patterns.add_pattern(...)
        except Exception as e:
            logger.warning(f"Failed to record outcome: {e}")


def get_remediation_agent(
    context_manager,
    mode: str = "conservative",
) -> RemediationAgent:
    """
    Factory function for RemediationAgent.

    Args:
        context_manager: Context manager instance
        mode: Mode string ("conservative", "semi_auto", "sentinel")

    Returns:
        Configured RemediationAgent
    """
    mode_map = {
        "conservative": RemediationMode.CONSERVATIVE,
        "semi_auto": RemediationMode.SEMI_AUTO,
        "semi-auto": RemediationMode.SEMI_AUTO,
        "sentinel": RemediationMode.SENTINEL,
    }

    remediation_mode = mode_map.get(mode.lower(), RemediationMode.CONSERVATIVE)

    return RemediationAgent(
        context_manager=context_manager,
        mode=remediation_mode,
    )
