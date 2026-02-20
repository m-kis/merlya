"""
Merlya Router - Smart Extractor.

Uses the fast LLM model (Haiku/GPT-4-mini/Mistral-small) for semantic extraction
instead of brittle regex patterns.

This module handles:
- Entity extraction (hosts, services, paths, environments)
- Intent classification (DIAGNOSTIC vs CHANGE)
- Severity inference
- Destructive command detection

v0.8.0: Replaces pattern-based extraction with LLM-based semantic understanding.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from merlya.config import Config


class ExtractedEntities(BaseModel):
    """Entities extracted from user input."""

    hosts: list[str] = Field(default_factory=list, description="Host names or IPs mentioned")
    services: list[str] = Field(
        default_factory=list, description="Service names (nginx, mysql, etc.)"
    )
    paths: list[str] = Field(default_factory=list, description="File or directory paths")
    ports: list[int] = Field(default_factory=list, description="Port numbers")
    environment: str | None = Field(
        default=None, description="Environment (prod, staging, dev, test)"
    )
    jump_host: str | None = Field(default=None, description="Jump/bastion host if mentioned")

    # IaC-specific fields (v0.9.0)
    iac_tools: list[str] = Field(
        default_factory=list,
        description="IaC tools mentioned (terraform, ansible, pulumi, cloudformation)",
    )
    iac_operation: str | None = Field(
        default=None,
        description="IaC operation type: provision, update, destroy, plan",
    )
    cloud_provider: str | None = Field(
        default=None,
        description="Cloud provider: aws, gcp, azure, ovh, proxmox, vmware",
    )
    infrastructure_resources: list[str] = Field(
        default_factory=list,
        description="Infrastructure resources (vm, vpc, subnet, security-group, etc.)",
    )


class IntentClassification(BaseModel):
    """Classification of user intent."""

    center: str = Field(description="DIAGNOSTIC (read-only) or CHANGE (mutation)")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score")
    is_destructive: bool = Field(default=False, description="Whether the action is destructive")
    severity: str = Field(default="low", description="Severity: low, medium, high, critical")
    reasoning: str | None = Field(default=None, description="Brief explanation")
    needs_clarification: bool = Field(default=False, description="True if the request is missing critical context or target info")
    clarification_message: str | None = Field(default=None, description="Question to ask the user if clarification is needed")


class SmartExtractionResult(BaseModel):
    """Combined result of smart extraction."""

    entities: ExtractedEntities = Field(default_factory=ExtractedEntities)
    intent: IntentClassification = Field(
        default_factory=lambda: IntentClassification(center="DIAGNOSTIC", confidence=0.5)
    )
    raw_input: str = Field(description="Original user input")


# System prompt for the fast model
EXTRACTION_SYSTEM_PROMPT = """You are an infrastructure assistant analyzing user requests.
Extract entities and classify intent from the user's message.

## Entity Extraction Rules:
- **hosts**: Server names, hostnames, IPs (e.g., "pine64", "web-01", "192.168.1.7")
  - Include names after "on", "sur", "from", "to", "via", "through"
  - Include names prefixed with @ (e.g., @ansible → "ansible")
  - Do NOT include generic words like "server", "machine", "host" without a specific name
- **services**: Service names (nginx, apache, mysql, postgres, redis, docker, k8s, etc.)
- **paths**: Unix paths starting with /, ~/, or ./
- **ports**: Port numbers (e.g., :8080, port 443)
- **environment**: prod/production, staging/preprod, dev/development, test/qa
- **jump_host**: Bastion/jump host mentioned with "via", "through", "en passant par"

## Infrastructure-as-Code (IaC) Detection:
- **iac_tools**: IaC tools mentioned
  - terraform, ansible, pulumi, cloudformation, arm, helm, kubectl
- **iac_operation**: Type of IaC operation
  - **provision**: Create new infrastructure (create, provision, spin up, allocate, deploy new)
  - **update**: Modify existing resources (update, scale, resize, modify, increase, decrease, change)
  - **destroy**: Remove infrastructure (destroy, teardown, deprovision, delete infrastructure)
  - **plan**: Preview changes without applying (terraform plan, dry-run, preview)
- **cloud_provider**: Target cloud platform
  - aws, gcp, azure, ovh, proxmox, vmware, openstack, digitalocean
- **infrastructure_resources**: Cloud resources mentioned
  - vm, instance, server, vpc, subnet, security-group, load-balancer, database, rds, s3, bucket

## Intent Classification Rules:
- **DIAGNOSTIC**: Read-only operations
  - Check, verify, show, list, get, view, analyze, monitor, debug, diagnose
  - Logs viewing, status checks, disk/memory/CPU checks
  - Questions starting with what, why, how, when, where
  - terraform plan, terraform show, kubectl get, ansible --check

- **CHANGE**: State-modifying operations
  - Restart, stop, start, deploy, install, update, fix, configure
  - Create, delete, remove, modify, enable, disable
  - terraform apply, terraform destroy, ansible-playbook, kubectl apply
  - Provision new infrastructure, update existing resources, destroy infrastructure

## Severity Rules:
- **critical**: Production outage, data loss risk, security breach, destroy infrastructure in prod
- **high**: Service degradation, urgent fixes, provision/destroy in staging
- **medium**: Non-urgent issues, routine maintenance, updates in dev
- **low**: Information requests, minor issues, plan/preview operations

## Destructive Detection:
Mark as destructive if: rm -rf, delete, drop, truncate, format, kill -9, shutdown, reboot,
terraform destroy, destroy infrastructure, teardown, deprovision

## Agentic Clarity (Ambiguity Detection):
- If the user request is extremely vague, ambiguous, or lacks a critical target (e.g. "restart the server" but no server is specified or in context), set `needs_clarification` to true.
- If true, provide a concise `clarification_message` asking the user for the missing information in the same language as their prompt (e.g. "Which server would you like to restart?").

Respond in JSON format matching the schema."""


class SmartExtractor:
    """
    LLM-based semantic extractor for user requests.

    Uses the fast model (Haiku/GPT-4-mini) to understand user intent
    instead of brittle regex patterns.
    """

    # Timeout for extraction calls
    EXTRACTION_TIMEOUT = 20.0

    def __init__(self, config: Config) -> None:
        """
        Initialize the smart extractor.

        Args:
            config: Merlya configuration with model settings.
        """
        self.config = config
        self._model: str | None = None
        self._agent: Any = None
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def _ensure_initialized(self) -> bool:
        """Initialize the agent if not already done."""
        if self._initialized:
            return self._agent is not None

        async with self._init_lock:
            if self._initialized:
                return self._agent is not None

            try:
                from pydantic_ai import Agent

                # Get fast model from config
                self._model = f"{self.config.model.provider}:{self.config.model.get_fast_model()}"
                logger.debug(f"🧠 SmartExtractor initializing with model: {self._model}")

                self._agent = Agent(
                    self._model,
                    system_prompt=EXTRACTION_SYSTEM_PROMPT,
                    output_type=SmartExtractionResult,
                    retries=1,
                )
                self._initialized = True
                logger.info(f"✅ SmartExtractor ready with {self._model}")
                return True

            except Exception as e:
                logger.warning(f"⚠️ SmartExtractor initialization failed: {e}")
                self._initialized = True  # Mark as initialized to avoid retries
                return False

    async def extract(self, user_input: str) -> SmartExtractionResult:
        """
        Extract entities and classify intent from user input.

        Args:
            user_input: Raw user input text.

        Returns:
            SmartExtractionResult with entities and intent classification.
        """
        # Try LLM-based extraction
        if await self._ensure_initialized() and self._agent:
            try:
                llm_result = await asyncio.wait_for(
                    self._extract_with_llm(user_input),
                    timeout=self.EXTRACTION_TIMEOUT,
                )
                if llm_result:
                    return llm_result
            except TimeoutError:
                logger.warning(f"⚠️ SmartExtractor timed out after {self.EXTRACTION_TIMEOUT}s")
            except Exception as e:
                logger.warning(f"⚠️ SmartExtractor failed: {e}")

        # Fallback if LLM fails or times out
        logger.warning("📋 Returning empty extraction result due to LLM failure")
        return SmartExtractionResult(
            raw_input=user_input,
            intent=IntentClassification(
                center="DIAGNOSTIC",
                confidence=0.0,
                reasoning="LLM extraction failed, fallback triggered"
            )
        )

    async def _extract_with_llm(self, user_input: str) -> SmartExtractionResult | None:
        """Extract using LLM."""
        if not self._agent:
            return None

        prompt = f"""Analyze this user request and extract entities + classify intent:

"{user_input}"

Extract:
- hosts, services, paths, ports, environment, jump_host
- iac_tools (terraform, ansible, pulumi, cloudformation, helm, kubectl)
- iac_operation (provision, update, destroy, plan)
- cloud_provider (aws, gcp, azure, ovh, proxmox, vmware)
- infrastructure_resources (vm, vpc, subnet, security-group, etc.)

Classify as DIAGNOSTIC or CHANGE.
Determine severity and if destructive."""

        response = await self._agent.run(prompt)
        result = response.output

        # Ensure raw_input is set
        if isinstance(result, SmartExtractionResult):
            result.raw_input = user_input
            logger.debug(
                f"🎯 Extracted: hosts={result.entities.hosts}, "
                f"intent={result.intent.center} ({result.intent.confidence:.2f})"
            )
            return result

        return None



    @property
    def model(self) -> str | None:
        """Return the model being used."""
        return self._model

    @property
    def is_llm_available(self) -> bool:
        """Check if LLM extraction is available."""
        return self._agent is not None


# Singleton instance (lazy initialization)
_extractor: SmartExtractor | None = None


def get_smart_extractor(config: Config) -> SmartExtractor:
    """Get or create the smart extractor singleton."""
    global _extractor
    if _extractor is None:
        _extractor = SmartExtractor(config)
    return _extractor


def reset_smart_extractor() -> None:
    """Reset the extractor (for testing)."""
    global _extractor
    _extractor = None
