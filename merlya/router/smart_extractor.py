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

Respond in JSON format matching the schema."""


class SmartExtractor:
    """
    LLM-based semantic extractor for user requests.

    Uses the fast model (Haiku/GPT-4-mini) to understand user intent
    instead of brittle regex patterns.
    """

    # Timeout for extraction calls
    EXTRACTION_TIMEOUT = 10.0

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
        # Always run regex first for host detection (fast and reliable)
        regex_result = self._extract_with_regex(user_input)

        # Try LLM-based extraction for intent classification
        if await self._ensure_initialized() and self._agent:
            try:
                llm_result = await asyncio.wait_for(
                    self._extract_with_llm(user_input),
                    timeout=self.EXTRACTION_TIMEOUT,
                )
                if llm_result:
                    # Merge: Use regex hosts if LLM missed them (LLM often misses custom hostnames)
                    if regex_result.entities.hosts and not llm_result.entities.hosts:
                        logger.debug(
                            f"📋 Merging regex hosts {regex_result.entities.hosts} into LLM result"
                        )
                        llm_result.entities.hosts = regex_result.entities.hosts
                    return llm_result
            except TimeoutError:
                logger.warning(f"⚠️ SmartExtractor timed out after {self.EXTRACTION_TIMEOUT}s")
            except Exception as e:
                logger.warning(f"⚠️ SmartExtractor failed: {e}")

        # Fallback to regex-based extraction
        logger.debug("📋 Using regex extraction")
        return regex_result

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

    def _extract_with_regex(self, user_input: str) -> SmartExtractionResult:
        """Fallback regex-based extraction."""
        import re

        entities = ExtractedEntities()
        text = user_input

        # Extract @mentions as hosts
        host_mentions = re.findall(r"@([a-zA-Z][a-zA-Z0-9_.-]*)", text)
        if host_mentions:
            entities.hosts.extend(host_mentions)

        # Extract IPs
        ips = re.findall(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", text)
        if ips:
            entities.hosts.extend(ips)

        # Common words to filter out (not hostnames)
        common_words = {
            "the",
            "le",
            "la",
            "les",
            "all",
            "tous",
            "toutes",
            "my",
            "mon",
            "ma",
            "mes",
            "this",
            "that",
            "these",
            "those",
            "ce",
            "cette",
            "ces",
            "cet",
            "server",
            "serveur",
            "host",
            "hôte",
            "machine",
            "instance",
            "disk",
            "disque",
            "memory",
            "mémoire",
            "cpu",
            "load",
            "charge",
            "space",
            "espace",
            "usage",
            "file",
            "fichier",
            "log",
            "logs",
            "process",
            "service",
            "container",
            "pod",
            "node",
            "cluster",
            "and",
            "or",
            "et",
            "ou",
            "with",
            "avec",
            "for",
            "pour",
            "prod",
            "production",
            "staging",
            "dev",
            "development",
            "test",
        }

        # Extract hosts after prepositions (extended patterns)
        host_preposition_patterns = [
            r"\b(?:on|sur|from|to|at|de)\s+([a-zA-Z][a-zA-Z0-9_.-]*)",
            r"\b(?:serveur|server|host|machine|hôte|instance)\s+([a-zA-Z][a-zA-Z0-9_.-]*)",
        ]
        for pattern in host_preposition_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for h in matches:
                if h.lower() not in common_words and h not in entities.hosts:
                    entities.hosts.append(h)

        # Detect standalone hostnames (alphanumeric with numbers/hyphens, looks like a server)
        # Pattern: word with at least one digit or hyphen, typical server naming
        standalone_host_pattern = (
            r"\b([a-zA-Z][a-zA-Z0-9]*(?:[-_][a-zA-Z0-9]+)+|[a-zA-Z]+\d+[a-zA-Z0-9]*)\b"
        )
        standalone_hosts = re.findall(standalone_host_pattern, text)
        for h in standalone_hosts:
            if h.lower() not in common_words and h not in entities.hosts:
                entities.hosts.append(h)

        # Extract paths
        paths = re.findall(r"(/[a-zA-Z0-9_./-]+)", text)
        if paths:
            entities.paths = list(set(paths))

        # Extract ports
        ports = re.findall(r":(\d{2,5})\b", text)
        if ports:
            entities.ports = [int(p) for p in ports if 1 <= int(p) <= 65535]

        # Extract services (known list)
        services_pattern = (
            r"\b(nginx|apache|mysql|postgres|redis|mongo|docker|k8s|kubernetes|systemd)\b"
        )
        services = re.findall(services_pattern, text, re.IGNORECASE)
        if services:
            entities.services = list({s.lower() for s in services})

        # Extract environment
        if re.search(r"\b(prod|production)\b", text, re.IGNORECASE):
            entities.environment = "production"
        elif re.search(r"\b(staging|preprod|stage)\b", text, re.IGNORECASE):
            entities.environment = "staging"
        elif re.search(r"\b(dev|development|local)\b", text, re.IGNORECASE):
            entities.environment = "development"
        elif re.search(r"\b(test|testing|qa|uat)\b", text, re.IGNORECASE):
            entities.environment = "testing"

        # Extract jump host
        jump_match = re.search(
            r"\b(?:via|through|en passant par)\s+@?([a-zA-Z][a-zA-Z0-9_.-]*)",
            text,
            re.IGNORECASE,
        )
        if jump_match:
            entities.jump_host = jump_match.group(1)

        # Extract IaC tools (v0.9.0)
        iac_tools_pattern = (
            r"\b(terraform|ansible|pulumi|cloudformation|cfn|arm|helm|kubectl|k8s|"
            r"docker-compose|vagrant|packer|opentofu)\b"
        )
        iac_tools = re.findall(iac_tools_pattern, text, re.IGNORECASE)
        if iac_tools:
            # Normalize: cfn → cloudformation, k8s → kubernetes
            normalized = []
            for tool in {t.lower() for t in iac_tools}:
                if tool == "cfn":
                    normalized.append("cloudformation")
                elif tool == "k8s":
                    normalized.append("kubernetes")
                else:
                    normalized.append(tool)
            entities.iac_tools = list(set(normalized))

        # Extract cloud provider
        provider_patterns = {
            "aws": r"\b(aws|amazon|ec2|s3|rds|lambda|cloudwatch)\b",
            "gcp": r"\b(gcp|google\s*cloud|gce|gke|bigquery)\b",
            "azure": r"\b(azure|microsoft\s*cloud|aks|cosmos)\b",
            "ovh": r"\b(ovh|ovhcloud)\b",
            "proxmox": r"\b(proxmox|pve)\b",
            "vmware": r"\b(vmware|vsphere|vcenter|esxi)\b",
            "digitalocean": r"\b(digitalocean|do\s+droplet)\b",
            "openstack": r"\b(openstack|nova|neutron)\b",
        }
        for provider, pattern in provider_patterns.items():
            if re.search(pattern, text, re.IGNORECASE):
                entities.cloud_provider = provider
                break

        # Extract infrastructure resources
        resource_patterns = (
            r"\b(vm|vms|instance|instances|server|servers|machine|machines|"
            r"vpc|subnet|subnets|security[- ]?group|load[- ]?balancer|lb|elb|alb|nlb|"
            r"database|db|rds|aurora|dynamo|bucket|s3|blob|storage|volume|disk|ebs|"
            r"cluster|node|nodes|deployment|pod|pods|namespace|"
            r"network|firewall|nat|gateway|route[- ]?table|"
            r"lambda|function|api[- ]?gateway|cdn|cloudfront)\b"
        )
        resources = re.findall(resource_patterns, text, re.IGNORECASE)
        if resources:
            entities.infrastructure_resources = list({r.lower() for r in resources})

        # Extract IaC operation type
        # PROVISION patterns (creating new)
        provision_patterns = [
            r"\b(provision|provisionner|créer?|create|spin\s+up|allocate)\b.*"
            r"\b(vm|instance|server|serveur|machine|infra|infrastructure|resource|ressource)",
            r"\b(terraform|ansible|pulumi)\s+(apply|run)\b.*\b(new|nouveau)",
            r"\b(deploy|déployer)\s+(new|nouvelle?|infrastructure|infra)\b",
            r"\bnew\s+(vm|instance|server|serveur|machine|infrastructure)\b",
        ]
        # UPDATE patterns (modifying existing)
        update_patterns = [
            r"\b(update|mettre\s+[àa]\s+jour|upgrade|modifier|scale|resize)\b.*"
            r"\b(vm|instance|server|serveur|machine|infra|resource|ressource)",
            r"\b(apply|appliquer)\s+(changes?|modifications?|config)\b",
            r"\b(augment|réduire|increase|decrease)\s+(cpu|ram|memory|disk|replicas|capacity)\b",
            r"\b(scale|resize)\s+(up|down|out|in)\b",
            r"\bmodify\s+(instance|vm|server|serveur|resource)\b",
        ]
        # DESTROY patterns
        destroy_patterns = [
            r"\b(destroy|détruire|teardown|deprovision|supprimer)\b.*"
            r"\b(vm|instance|server|serveur|machine|infra|infrastructure|resource|ressource)",
            r"\bterraform\s+destroy\b",
            r"\b(delete|remove)\s+(all\s+)?(infrastructure|infra|resources?|ressources?)\b",
        ]
        # PLAN patterns (read-only preview)
        plan_patterns = [
            r"\bterraform\s+(plan|validate|fmt|show)\b",
            r"\bansible[- ]playbook\s+.*--check\b",
            r"\b(dry[- ]?run|preview|what[- ]?if)\b",
            r"\bkubectl\s+(diff|get|describe)\b",
        ]

        text_lower_iac = text.lower()
        if any(re.search(p, text_lower_iac) for p in destroy_patterns):
            entities.iac_operation = "destroy"
        elif any(re.search(p, text_lower_iac) for p in plan_patterns):
            entities.iac_operation = "plan"
        elif any(re.search(p, text_lower_iac) for p in update_patterns):
            entities.iac_operation = "update"
        elif (
            any(re.search(p, text_lower_iac) for p in provision_patterns)
            # Fallback: IaC tool + apply/run/execute = provision
            or (entities.iac_tools and re.search(r"\b(apply|run|execute)\b", text_lower_iac))
        ):
            entities.iac_operation = "provision"

        # Classify intent (simple heuristic)
        text_lower = text.lower()

        # CHANGE indicators
        change_patterns = [
            r"\b(restart|redémarrer|stop|start|deploy|install|update|fix|configure)\b",
            r"\b(create|delete|remove|modify|enable|disable|kill)\b",
            r"\b(répare|supprime|installe|démarre|arrête)\b",
        ]
        change_score = sum(1 for p in change_patterns if re.search(p, text_lower))

        # DIAGNOSTIC indicators
        diag_patterns = [
            r"\b(check|verify|show|list|get|view|analyze|monitor|debug|diagnose)\b",
            r"\b(vérifie|affiche|montre|analyse|surveille)\b",
            r"^(what|why|how|when|where|quoi|comment|pourquoi)\b",
            r"\?$",
        ]
        diag_score = sum(1 for p in diag_patterns if re.search(p, text_lower))

        # IaC operation strongly influences intent (v0.9.0)
        if entities.iac_operation in ("provision", "update", "destroy"):
            change_score += 3  # Strong CHANGE signal
        elif entities.iac_operation == "plan":
            diag_score += 3  # Plan is read-only

        # Determine intent
        if change_score > diag_score:
            center = "CHANGE"
            confidence = min(0.6 + change_score * 0.1, 0.9)
        else:
            center = "DIAGNOSTIC"
            confidence = min(0.6 + diag_score * 0.1, 0.9)

        # Check destructive (includes IaC destroy operations)
        destructive_patterns = (
            r"\b(rm\s+-rf|delete|drop|truncate|format|kill\s+-9|shutdown|reboot)\b"
        )
        is_destructive = bool(re.search(destructive_patterns, text_lower))

        # IaC destroy is always destructive (v0.9.0)
        if entities.iac_operation == "destroy":
            is_destructive = True

        # Determine severity (v0.9.0 - IaC-aware)
        severity = self._determine_severity(entities, is_destructive)

        intent = IntentClassification(
            center=center,
            confidence=confidence,
            is_destructive=is_destructive,
            severity=severity,
            reasoning="Regex fallback classification",
        )

        return SmartExtractionResult(
            entities=entities,
            intent=intent,
            raw_input=user_input,
        )

    def _determine_severity(self, entities: ExtractedEntities, is_destructive: bool) -> str:
        """
        Determine severity based on entities and operation type.

        Severity levels:
        - critical: Production + destructive, or destroy in production
        - high: Production operations, destroy in non-prod, urgent fixes
        - medium: Staging/dev operations, routine updates
        - low: Plan/preview, information requests

        v0.9.0: IaC-aware severity determination.
        """
        env = entities.environment
        iac_op = entities.iac_operation

        # Critical: destroy in production OR any destructive in production
        if env == "production" and (iac_op == "destroy" or is_destructive):
            return "critical"

        # High: destroy anywhere, or production modifications
        if iac_op == "destroy":
            return "high"
        if env == "production" and iac_op in ("provision", "update"):
            return "high"

        # Medium: staging operations or provision/update in dev
        if env == "staging" and iac_op in ("provision", "update", "destroy"):
            return "medium"
        if iac_op in ("provision", "update"):
            return "medium"

        # Low: plan operations or unknown
        if iac_op == "plan":
            return "low"

        # Fallback: destructive commands are high, otherwise low
        return "high" if is_destructive else "low"

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
