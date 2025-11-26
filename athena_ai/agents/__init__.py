"""
Intelligent orchestration using DDD architecture.

This package contains the Unified Orchestrator with Domain-Driven Design:
- Request Processing: Understands user intent
- Plan Management: Generates optimal execution plans
- Execution Coordination: Executes safely with rollback
- Intelligence Engine: Learns and adapts like Claude Code

Features:
- Claude Code-like intelligence
- Adaptive learning from execution history
- Multi-provider LLM support via LiteLLM (OpenRouter, Anthropic, OpenAI, Ollama)
- Safe execution with automatic rollback
- Modular DDD architecture
"""
from athena_ai.agents.ag2_orchestrator import Ag2Orchestrator
from athena_ai.agents.remediation import (
    RemediationAgent,
    RemediationMode,
    RemediationResult,
    get_remediation_agent,
)
from athena_ai.agents.sentinel import (
    Alert,
    AlertSeverity,
    CheckResult,
    HealthCheck,
    SentinelAgent,
    SentinelStatus,
    get_sentinel_agent,
)

# UnifiedOrchestrator has been replaced by Ag2Orchestrator
# for advanced multi-agent capabilities

__all__ = [
    "Ag2Orchestrator",
    # Remediation
    "RemediationAgent",
    "RemediationMode",
    "RemediationResult",
    "get_remediation_agent",
    # Sentinel
    "SentinelAgent",
    "SentinelStatus",
    "HealthCheck",
    "CheckResult",
    "Alert",
    "AlertSeverity",
    "get_sentinel_agent",
]
