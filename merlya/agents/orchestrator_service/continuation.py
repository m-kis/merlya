"""
Task Continuation Logic.

Determines whether the agent should continue autonomously or return control
to the user. Uses semantic analysis to detect:
1. Task completion signals
2. User corrections that require continuation
3. Incomplete tasks requiring more work
"""
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class ContinuationDecision(Enum):
    """Decision about whether to continue or pause."""
    CONTINUE = "continue"  # Continue working on the task
    PAUSE = "pause"        # Return control to user
    COMPLETE = "complete"  # Task is fully complete


@dataclass
class ContinuationContext:
    """Context for continuation decision."""
    decision: ContinuationDecision
    reason: str
    next_action: Optional[str] = None  # Suggested next action if continuing


class ContinuationDetector:
    """
    Detects whether to continue task execution or return control to user.

    Analyzes:
    1. User responses to agent questions
    2. Agent output for completion signals
    3. Error corrections from user
    """

    # Patterns indicating user wants to continue with correction
    CORRECTION_PATTERNS = [
        r"(?:c'est|c est)\s*(?:pas|non)\s*(?:la|le)\s+(?:bonne?|bon)\s+(?:machine|host|serveur)",
        r"(?:la|le)\s+(?:bonne?|bon)\s+(?:machine|host|serveur)\s+(?:c'est|est)\s+(\w+)",
        r"(?:non|no),?\s*(?:c'est|c est|it's|its)\s+(\w+)",
        r"(?:use|utilise)\s+(\w+)\s+(?:instead|plutôt|plutot)",
        r"(?:wrong|mauvais)\s+(?:host|machine|server)",
        r"(?:should be|devrait être)\s+(\w+)",
        r"^(\w+)\s*$",  # Single word response after disambiguation
    ]

    # Patterns indicating task is complete
    COMPLETION_PATTERNS = [
        r"✅\s*(?:task|tâche)?\s*(?:completed?|terminée?|done|fini)",
        r"(?:voilà|voila|here(?:'s| is)|that's)\s+(?:the|your|le|la)",
        r"(?:summary|résumé|recap)",
        r"(?:in conclusion|en conclusion|pour conclure)",
    ]

    # Patterns indicating more work needed
    CONTINUATION_PATTERNS = [
        r"(?:now|maintenant)\s+(?:i'll|je vais|let me|i will)",
        r"(?:next|ensuite|puis),?\s+(?:i'll|je vais|let me|i will)",
        r"(?:continuing|je continue)",
        r"(?:retrying|je réessaie)\s+(?:with|avec)",
        r"(?:switching|je passe)\s+(?:to|à)\s+(\w+)",
        r"(?:let me)\s+(?:check|verify|look|see|try)",
    ]

    # Patterns indicating error/failure
    ERROR_PATTERNS = [
        r"❌\s*(?:error|erreur|failed|échoué)",
        r"(?:permission|access)\s+denied",
        r"(?:not found|introuvable)",
        r"(?:could not|impossible de|cannot)\s+(?:connect|execute|access)",
    ]

    def __init__(self):
        self._compiled_patterns = {
            'correction': [re.compile(p, re.IGNORECASE) for p in self.CORRECTION_PATTERNS],
            'completion': [re.compile(p, re.IGNORECASE) for p in self.COMPLETION_PATTERNS],
            'continuation': [re.compile(p, re.IGNORECASE) for p in self.CONTINUATION_PATTERNS],
            'error': [re.compile(p, re.IGNORECASE) for p in self.ERROR_PATTERNS],
        }

    def analyze_user_response(
        self,
        user_response: str,
        agent_question: Optional[str] = None,
        original_task: Optional[str] = None
    ) -> ContinuationContext:
        """
        Analyze user response to determine if agent should continue.

        Args:
            user_response: User's response text
            agent_question: The question the agent asked (if any)
            original_task: The original task being worked on

        Returns:
            ContinuationContext with decision and reason
        """
        response_lower = user_response.lower().strip()

        # 1. Check for explicit continuation signals
        if response_lower in ['yes', 'oui', 'y', 'o', 'continue', 'ok', 'go ahead', 'vas-y', 'proceed']:
            return ContinuationContext(
                decision=ContinuationDecision.CONTINUE,
                reason="User confirmed to continue"
            )

        # 2. Check for explicit stop signals
        if response_lower in ['no', 'non', 'n', 'stop', 'cancel', 'abort', 'annuler', 'arrête', 'arrete']:
            return ContinuationContext(
                decision=ContinuationDecision.PAUSE,
                reason="User requested to stop"
            )

        # 3. Check for correction patterns (user is correcting an error)
        correction_match = self._detect_correction(user_response)
        if correction_match:
            return ContinuationContext(
                decision=ContinuationDecision.CONTINUE,
                reason=f"User provided correction: {correction_match}",
                next_action=f"Use {correction_match} instead and continue with the original task"
            )

        # 4. If user provides a single hostname-like word after a host question
        if agent_question and self._is_host_disambiguation_question(agent_question):
            if re.match(r'^[\w\-\.]+$', response_lower) and len(response_lower) >= 3:
                return ContinuationContext(
                    decision=ContinuationDecision.CONTINUE,
                    reason=f"User specified hostname: {user_response}",
                    next_action=f"Use hostname '{user_response}' and continue"
                )

        # 5. Default: treat as new input, pause for processing
        return ContinuationContext(
            decision=ContinuationDecision.PAUSE,
            reason="User provided new input"
        )

    def analyze_agent_output(
        self,
        agent_output: str,
        original_task: Optional[str] = None
    ) -> ContinuationContext:
        """
        Analyze agent output to determine task state.

        Args:
            agent_output: The agent's output text
            original_task: The original task

        Returns:
            ContinuationContext with decision and reason
        """
        # 1. Check for completion patterns
        for pattern in self._compiled_patterns['completion']:
            if pattern.search(agent_output):
                return ContinuationContext(
                    decision=ContinuationDecision.COMPLETE,
                    reason="Agent indicated task completion"
                )

        # 2. Check for continuation patterns (agent is continuing)
        for pattern in self._compiled_patterns['continuation']:
            match = pattern.search(agent_output)
            if match:
                return ContinuationContext(
                    decision=ContinuationDecision.CONTINUE,
                    reason="Agent is continuing work",
                    next_action=match.group(1) if match.groups() else None
                )

        # 3. Check for errors that might need user input
        for pattern in self._compiled_patterns['error']:
            if pattern.search(agent_output):
                # Error detected - check if agent asked a question
                if '?' in agent_output or 'ask_user' in agent_output.lower():
                    return ContinuationContext(
                        decision=ContinuationDecision.PAUSE,
                        reason="Agent encountered error and needs user input"
                    )
                # Error without question - continue to handle it
                return ContinuationContext(
                    decision=ContinuationDecision.CONTINUE,
                    reason="Agent encountered error, should handle it"
                )

        # 4. Default: assume task is complete if no continuation signals
        return ContinuationContext(
            decision=ContinuationDecision.COMPLETE,
            reason="No continuation signals detected"
        )

    def _detect_correction(self, text: str) -> Optional[str]:
        """
        Detect if text contains a correction and extract the corrected value.

        Returns:
            Corrected value if found, None otherwise
        """
        for pattern in self._compiled_patterns['correction']:
            match = pattern.search(text)
            if match:
                # Try to extract the corrected value from groups
                if match.groups():
                    for group in match.groups():
                        if group:
                            return group.strip()
                # Pattern matched but no capture group - just return True indicator
                return "correction detected"
        return None

    def _is_host_disambiguation_question(self, question: str) -> bool:
        """Check if the question is about host disambiguation."""
        question_lower = question.lower()
        host_keywords = ['host', 'server', 'machine', 'hostname', 'serveur']
        question_keywords = ['which', 'quel', 'quelle', 'specify', 'précisez', 'choose', 'choisir']

        has_host = any(kw in question_lower for kw in host_keywords)
        has_question = any(kw in question_lower for kw in question_keywords)

        return has_host and has_question

    def should_continue_after_tool_response(
        self,
        tool_response: str,
        original_task: str
    ) -> Tuple[bool, str]:
        """
        Determine if the agent should continue after a tool response.

        Args:
            tool_response: Response from a tool (e.g., ask_user)
            original_task: The original user task

        Returns:
            (should_continue, reason)
        """
        # Check if the response is from ask_user and contains a correction
        if "User response:" in tool_response:
            user_part = tool_response.split("User response:", 1)[1].strip()
            ctx = self.analyze_user_response(user_part, original_task=original_task)

            if ctx.decision == ContinuationDecision.CONTINUE:
                return True, ctx.reason

        return False, "No continuation needed"


# Singleton
_detector: Optional[ContinuationDetector] = None


def get_continuation_detector() -> ContinuationDetector:
    """Get the global ContinuationDetector instance."""
    global _detector
    if _detector is None:
        _detector = ContinuationDetector()
    return _detector


def should_continue(
    user_response: str,
    agent_question: Optional[str] = None,
    original_task: Optional[str] = None
) -> ContinuationContext:
    """
    Convenience function to check if agent should continue.

    Args:
        user_response: User's response
        agent_question: Question that prompted the response
        original_task: Original task being worked on

    Returns:
        ContinuationContext with decision
    """
    return get_continuation_detector().analyze_user_response(
        user_response, agent_question, original_task
    )
