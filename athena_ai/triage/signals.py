"""
Signal detection for priority classification.

Multi-layer detection:
1. Keyword matching (fastest, < 5ms)
2. Context/environment analysis (< 10ms)
3. Pattern matching for severity amplifiers
"""

import re
from typing import Tuple, List, Set, Optional, Dict
from dataclasses import dataclass

from .priority import Priority


# ============================================================================
# KEYWORD DICTIONARIES
# ============================================================================

# P0: Production down, data loss, active security breach
P0_KEYWORDS: Set[str] = {
    # Production down
    "down", "outage", "unreachable", "not responding", "connection refused",
    "total failure", "complete outage", "site down", "prod down",
    "production down", "service unavailable", "503", "500 error",
    # Data loss
    "data loss", "data corruption", "database crash", "disk full",
    "raid failure", "backup failed", "replication broken", "data gone",
    # Active security breach
    "breach", "hacked", "compromised", "ransomware", "unauthorized access",
    "rootkit", "exfiltration", "intrusion detected",
}

# P1: Service degraded, security vulnerability, imminent failure
P1_KEYWORDS: Set[str] = {
    # Service degradation
    "degraded", "slow", "high latency", "timeout", "partial outage",
    "intermittent", "failing", "errors increasing", "error rate",
    "response time", "queue full", "backlog",
    # Security concerns
    "vulnerability", "cve", "security issue", "exposed", "leak",
    "suspicious activity", "brute force", "failed logins", "scan detected",
    # Imminent failure
    "disk almost full", "memory pressure", "oom", "swap thrashing",
    "certificate expiring", "ssl expire", "quota exceeded",
    "disk 9", "memory 9",  # disk 90%, memory 95%, etc.
}

# P2: Performance issues, non-critical failures
P2_KEYWORDS: Set[str] = {
    # Performance
    "performance", "optimize", "slow query", "high cpu", "memory usage",
    "load average", "io wait", "bottleneck", "throughput",
    # Non-critical failures
    "backup warning", "replica lag", "queue growing", "cache miss",
    "connection pool", "retry", "warning", "degradation",
    # Capacity
    "capacity", "scaling", "resources",
}

# P3 is the default - no specific keywords, everything else


# ============================================================================
# ENVIRONMENT AMPLIFIERS
# ============================================================================

ENVIRONMENT_PATTERNS: Dict[str, Dict] = {
    # Production - always amplify priority
    r"\bprod\b": {"multiplier": 1.5, "min_priority": Priority.P1, "env": "prod"},
    r"\bproduction\b": {"multiplier": 1.5, "min_priority": Priority.P1, "env": "prod"},
    r"\bprd\b": {"multiplier": 1.5, "min_priority": Priority.P1, "env": "prod"},
    r"\blive\b": {"multiplier": 1.5, "min_priority": Priority.P1, "env": "prod"},

    # Staging - moderate priority
    r"\bstaging\b": {"multiplier": 1.0, "min_priority": Priority.P2, "env": "staging"},
    r"\bstg\b": {"multiplier": 1.0, "min_priority": Priority.P2, "env": "staging"},
    r"\buat\b": {"multiplier": 1.0, "min_priority": Priority.P2, "env": "staging"},
    r"\bpreprod\b": {"multiplier": 1.0, "min_priority": Priority.P2, "env": "staging"},

    # Dev - lower priority
    r"\bdev\b": {"multiplier": 0.5, "min_priority": Priority.P3, "env": "dev"},
    r"\bdevelopment\b": {"multiplier": 0.5, "min_priority": Priority.P3, "env": "dev"},
    r"\blocal\b": {"multiplier": 0.3, "min_priority": Priority.P3, "env": "dev"},
    r"\btest\b": {"multiplier": 0.5, "min_priority": Priority.P3, "env": "test"},
}

# Impact amplifiers
IMPACT_PATTERNS: Dict[str, float] = {
    r"\ball users\b": 2.0,
    r"\beveryone\b": 2.0,
    r"\bcustomer": 1.5,
    r"\brevenue\b": 2.0,
    r"\bbusiness critical\b": 2.0,
    r"\bcritical\b": 1.5,
    r"\burgent\b": 1.3,
    r"\bemergency\b": 2.0,
    r"\basap\b": 1.5,
    r"\binternal\b": 0.8,
}


@dataclass
class SignalMatch:
    """A matched signal with its details."""
    keyword: str
    priority: Priority
    source: str  # "keyword", "environment", "impact", "pattern"


class SignalDetector:
    """
    Fast signal detection for priority classification.

    Uses pre-compiled patterns for speed.
    """

    def __init__(self):
        # Pre-compile environment patterns
        self._env_patterns = {
            re.compile(pattern, re.IGNORECASE): config
            for pattern, config in ENVIRONMENT_PATTERNS.items()
        }

        # Pre-compile impact patterns
        self._impact_patterns = {
            re.compile(pattern, re.IGNORECASE): multiplier
            for pattern, multiplier in IMPACT_PATTERNS.items()
        }

        # Lowercase keyword sets for fast lookup
        self._p0_keywords = {k.lower() for k in P0_KEYWORDS}
        self._p1_keywords = {k.lower() for k in P1_KEYWORDS}
        self._p2_keywords = {k.lower() for k in P2_KEYWORDS}

    def detect_keywords(self, text: str) -> Tuple[Priority, List[str], float]:
        """
        Detect priority from keywords in text.

        Returns:
            (priority, matched_signals, confidence)
        """
        text_lower = text.lower()
        signals = []
        confidence = 0.5  # Base confidence

        # Check P0 keywords
        p0_matches = [kw for kw in self._p0_keywords if kw in text_lower]
        if p0_matches:
            signals.extend([f"P0:{kw}" for kw in p0_matches[:3]])
            confidence = min(0.95, 0.7 + 0.1 * len(p0_matches))
            return Priority.P0, signals, confidence

        # Check P1 keywords
        p1_matches = [kw for kw in self._p1_keywords if kw in text_lower]
        if p1_matches:
            signals.extend([f"P1:{kw}" for kw in p1_matches[:3]])
            confidence = min(0.9, 0.6 + 0.1 * len(p1_matches))
            return Priority.P1, signals, confidence

        # Check P2 keywords
        p2_matches = [kw for kw in self._p2_keywords if kw in text_lower]
        if p2_matches:
            signals.extend([f"P2:{kw}" for kw in p2_matches[:3]])
            confidence = min(0.85, 0.5 + 0.1 * len(p2_matches))
            return Priority.P2, signals, confidence

        # Default to P3
        return Priority.P3, ["default"], 0.5

    def detect_environment(self, text: str) -> Tuple[Optional[str], float, Optional[Priority]]:
        """
        Detect environment context and get priority modifier.

        Returns:
            (environment_name, multiplier, min_priority)
        """
        text_lower = text.lower()

        for pattern, config in self._env_patterns.items():
            if pattern.search(text_lower):
                return (
                    config["env"],
                    config["multiplier"],
                    config["min_priority"],
                )

        return None, 1.0, None

    def detect_impact(self, text: str) -> float:
        """
        Detect impact amplifiers.

        Returns:
            multiplier (1.0 = no change, > 1.0 = higher priority)
        """
        text_lower = text.lower()
        max_multiplier = 1.0

        for pattern, multiplier in self._impact_patterns.items():
            if pattern.search(text_lower):
                max_multiplier = max(max_multiplier, multiplier)

        return max_multiplier

    def detect_host_or_service(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Try to extract host or service name from text.

        Returns:
            (host_name, service_name)
        """
        host = None
        service = None

        # Common service patterns
        service_patterns = [
            r"\b(nginx|apache|httpd|haproxy)\b",
            r"\b(mysql|postgres|postgresql|mongodb|mongod|redis|memcached)\b",
            r"\b(docker|kubernetes|k8s|containerd)\b",
            r"\b(sshd|ssh|systemd)\b",
            r"\b(elasticsearch|kibana|logstash|grafana|prometheus)\b",
        ]

        for pattern in service_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                service = match.group(1).lower()
                break

        # Host patterns (hostname-like strings)
        host_pattern = r"\b([a-zA-Z][\w-]*(?:\d+|prod|stg|dev)[\w-]*)\b"
        host_match = re.search(host_pattern, text)
        if host_match:
            potential_host = host_match.group(1)
            # Filter out common words
            if potential_host.lower() not in {"prod", "production", "staging", "dev"}:
                host = potential_host

        return host, service

    def detect_all(self, text: str) -> dict:
        """
        Run all detections and return comprehensive results.

        Returns:
            {
                "keyword_priority": Priority,
                "keyword_signals": List[str],
                "keyword_confidence": float,
                "environment": str | None,
                "env_multiplier": float,
                "env_min_priority": Priority | None,
                "impact_multiplier": float,
                "host": str | None,
                "service": str | None,
            }
        """
        kw_priority, kw_signals, kw_confidence = self.detect_keywords(text)
        env, env_mult, env_min = self.detect_environment(text)
        impact_mult = self.detect_impact(text)
        host, service = self.detect_host_or_service(text)

        return {
            "keyword_priority": kw_priority,
            "keyword_signals": kw_signals,
            "keyword_confidence": kw_confidence,
            "environment": env,
            "env_multiplier": env_mult,
            "env_min_priority": env_min,
            "impact_multiplier": impact_mult,
            "host": host,
            "service": service,
        }
