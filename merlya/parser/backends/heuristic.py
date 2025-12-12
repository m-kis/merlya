"""
Merlya Parser - Heuristic backend using regex and patterns.

This is the lightweight backend (tier=lightweight) that uses
pattern matching and regex for text parsing. No external models required.

Security notes:
- All regex patterns are pre-compiled to avoid ReDoS
- Input is validated and truncated to MAX_INPUT_SIZE
- Patterns are designed to avoid catastrophic backtracking
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any

from loguru import logger

from merlya.parser.backends.base import ParserBackend
from merlya.parser.models import (
    CommandInput,
    CommandParsingResult,
    Environment,
    HostQueryInput,
    HostQueryParsingResult,
    IncidentInput,
    IncidentParsingResult,
    LogEntry,
    LogLevel,
    LogParsingResult,
    ParsedLog,
    Severity,
)

# Security: Maximum input size (10 MB)
MAX_INPUT_SIZE = 10 * 1024 * 1024

# Patterns for entity extraction (raw strings, compiled below)
_PATTERNS_RAW = {
    # Host patterns: @hostname, hostname.domain.com, IPs
    # Simplified patterns to avoid ReDoS (no nested quantifiers)
    "hosts": [
        r"@([a-zA-Z][a-zA-Z0-9_-]{0,63})",  # @hostname (max 64 chars)
        r"\b([a-zA-Z][a-zA-Z0-9-]{0,62}(?:\.[a-zA-Z0-9-]{1,63}){1,5})\b",  # hostname.domain (max 5 levels)
        r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b",  # IPv4
    ],
    # File paths (limited depth to avoid backtracking)
    "paths": [
        r"(/[a-zA-Z0-9_.-]{1,255}(?:/[a-zA-Z0-9_.-]{1,255}){0,20})",  # Unix paths
        r"(~/[a-zA-Z0-9_.-]{1,255}(?:/[a-zA-Z0-9_.-]{1,255}){0,20})",  # Home paths
        r"(\./[a-zA-Z0-9_.-]{1,255}(?:/[a-zA-Z0-9_.-]{1,255}){0,20})",  # Relative paths
    ],
    # Services (common patterns)
    "services": [
        r"\b(nginx|apache|httpd|mysql|postgres|mongodb|redis|elasticsearch)\b",
        r"\b(docker|kubernetes|k8s|systemd|journald)\b",
        r"\b(ssh|sshd|sftp|ftp|smtp|imap)\b",
        r"\b([a-zA-Z][a-zA-Z0-9_-]{0,63}\.service)\b",  # systemd services
    ],
    # Error indicators
    "errors": [
        r"(error|failed|failure|exception|crash|killed|timeout|refused)",
        r"(permission denied|access denied|unauthorized|forbidden)",
        r"(connection refused|connection reset|no route to host)",
        r"(out of memory|oom|disk full|no space left)",
    ],
    # Timestamps (various formats)
    "timestamps": [
        r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:?\d{2})?)",
        r"(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})",
        r"([A-Z][a-z]{2} \d{1,2} \d{2}:\d{2}:\d{2})",  # Syslog format
    ],
    # Secrets (@secret-name) - simplified pattern
    "secrets": [
        r"@([a-zA-Z][a-zA-Z0-9_-]{0,63}(?:-[a-zA-Z0-9_-]{1,63})+)",
    ],
}

# Pre-compile all patterns for performance and ReDoS protection
COMPILED_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    entity_type: [re.compile(p, re.IGNORECASE) for p in patterns]
    for entity_type, patterns in _PATTERNS_RAW.items()
}

# Environment detection patterns (pre-compiled)
_ENV_PATTERNS_RAW = {
    Environment.PRODUCTION: [r"\bprod\b", r"\bproduction\b", r"\bprd\b"],
    Environment.STAGING: [r"\bstaging\b", r"\bstage\b", r"\bstg\b", r"\bpreprod\b"],
    Environment.DEVELOPMENT: [r"\bdev\b", r"\bdevelopment\b", r"\blocal\b"],
    Environment.TESTING: [r"\btest\b", r"\btesting\b", r"\bqa\b", r"\buat\b"],
}
ENV_PATTERNS: dict[Environment, list[re.Pattern[str]]] = {
    env: [re.compile(p, re.IGNORECASE) for p in patterns]
    for env, patterns in _ENV_PATTERNS_RAW.items()
}

# Severity detection patterns (pre-compiled)
_SEVERITY_PATTERNS_RAW = {
    Severity.CRITICAL: [r"\bcritical\b", r"\bp0\b", r"\bsev0\b", r"\bdown\b", r"\boutage\b"],
    Severity.HIGH: [r"\bhigh\b", r"\bp1\b", r"\bsev1\b", r"\burgent\b", r"\bblocking\b"],
    Severity.MEDIUM: [r"\bmedium\b", r"\bp2\b", r"\bsev2\b", r"\bdegraded\b"],
    Severity.LOW: [r"\blow\b", r"\bp3\b", r"\bsev3\b", r"\bminor\b"],
}
SEVERITY_PATTERNS: dict[Severity, list[re.Pattern[str]]] = {
    sev: [re.compile(p, re.IGNORECASE) for p in patterns]
    for sev, patterns in _SEVERITY_PATTERNS_RAW.items()
}

# Log level patterns (pre-compiled)
_LOG_LEVEL_PATTERNS_RAW = {
    LogLevel.ERROR: [r"\berror\b", r"\berr\b", r"\bfatal\b", r"\bcrit\b"],
    LogLevel.WARNING: [r"\bwarn\b", r"\bwarning\b"],
    LogLevel.INFO: [r"\binfo\b", r"\bnotice\b"],
    LogLevel.DEBUG: [r"\bdebug\b"],
    LogLevel.TRACE: [r"\btrace\b", r"\bverbose\b"],
}
LOG_LEVEL_PATTERNS: dict[LogLevel, list[re.Pattern[str]]] = {
    level: [re.compile(p, re.IGNORECASE) for p in patterns]
    for level, patterns in _LOG_LEVEL_PATTERNS_RAW.items()
}

# Destructive command patterns (pre-compiled)
_DESTRUCTIVE_PATTERNS_RAW = [
    r"\brm\s+(-rf?|--recursive)",
    r"\bdrop\s+(database|table|index)",
    r"\bdelete\s+from\b",
    r"\btruncate\s+table\b",
    r"\bformat\b",
    r"\bmkfs\b",
    r"\bdd\s+[^\n]*of=",  # Simplified to avoid backtracking
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bkill\s+-9",
    r"\bsystemctl\s+(stop|disable|mask)",
]
DESTRUCTIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE) for p in _DESTRUCTIVE_PATTERNS_RAW
]


def _is_valid_ipv4(ip: str) -> bool:
    """Validate that an IPv4 address has all octets in range 0-255."""
    try:
        octets = ip.split(".")
        if len(octets) != 4:
            return False
        return all(0 <= int(octet) <= 255 for octet in octets)
    except (ValueError, AttributeError):
        return False


class HeuristicBackend(ParserBackend):
    """
    Heuristic parser backend using regex and patterns.

    This is the lightweight backend that requires no external models.
    Suitable for basic parsing when ONNX is not available.
    """

    def __init__(self) -> None:
        """Initialize the heuristic backend."""
        self._loaded = True  # No loading required
        logger.debug("🔧 HeuristicBackend initialized")

    @property
    def name(self) -> str:
        """Return the backend name."""
        return "heuristic"

    @property
    def is_loaded(self) -> bool:
        """Return True (always ready)."""
        return self._loaded

    async def load(self) -> bool:
        """Load (no-op for heuristic backend)."""
        return True

    def _validate_input(self, text: str) -> str:
        """Validate and sanitize input text."""
        if not text:
            return ""
        # Truncate if too large (security: prevent DoS)
        if len(text) > MAX_INPUT_SIZE:
            logger.warning(f"⚠️ Input truncated from {len(text)} to {MAX_INPUT_SIZE} bytes")
            text = text[:MAX_INPUT_SIZE]
        return text

    async def parse_incident(self, text: str) -> IncidentParsingResult:
        """Parse text as an incident description."""
        start_time = time.perf_counter()
        text = self._validate_input(text)

        entities = await self.extract_entities(text)
        text_lower = text.lower()

        # Detect environment
        environment = self._detect_environment(text_lower)

        # Detect severity
        severity = self._detect_severity(text_lower)

        # Extract symptoms (sentences with error indicators)
        symptoms = self._extract_symptoms(text)

        # Extract error messages (quoted or distinct error lines)
        error_messages = self._extract_error_messages(text)

        # Parse timestamps
        timestamps = self._parse_timestamps(entities.get("timestamps", []))

        # Build incident
        incident = IncidentInput(
            description=text[:500] if len(text) > 500 else text,
            severity=severity,
            environment=environment,
            affected_hosts=entities.get("hosts", []),
            affected_services=entities.get("services", []),
            symptoms=symptoms,
            error_messages=error_messages,
            timestamps=timestamps,
            paths=entities.get("paths", []),
            keywords=self._extract_keywords(text),
        )

        # Calculate confidence based on how much we extracted
        total_entities = sum(len(v) for v in entities.values())
        confidence = min(0.3 + (total_entities * 0.05), 0.8)  # Max 0.8 for heuristic

        # Calculate coverage (rough estimate based on pattern matches)
        coverage = min(len(error_messages) * 0.1 + len(symptoms) * 0.1 + 0.3, 0.9)

        parse_time = (time.perf_counter() - start_time) * 1000

        return IncidentParsingResult(
            incident=incident,
            confidence=confidence,
            coverage_ratio=coverage,
            has_unparsed_blocks=confidence < 0.6,
            truncated=len(text) > 500,
            total_lines=text.count("\n") + 1,
            backend_used=self.name,
            parse_time_ms=parse_time,
        )

    async def parse_log(self, text: str) -> LogParsingResult:
        """Parse text as log output."""
        start_time = time.perf_counter()
        text = self._validate_input(text)

        lines = text.strip().split("\n") if text else []
        entries: list[LogEntry] = []
        error_count = 0
        warning_count = 0
        sources: set[str] = set()
        key_errors: list[str] = []
        patterns_detected: set[str] = set()

        for i, line in enumerate(lines, 1):
            if not line.strip():
                continue

            entry = self._parse_log_line(line, i)
            entries.append(entry)

            if entry.level == LogLevel.ERROR:
                error_count += 1
                if len(key_errors) < 10:  # Limit key errors
                    key_errors.append(entry.message[:100])
            elif entry.level == LogLevel.WARNING:
                warning_count += 1

            if entry.source:
                sources.add(entry.source)

            # Detect common patterns
            line_lower = line.lower()
            if "connection refused" in line_lower:
                patterns_detected.add("connection_refused")
            if "timeout" in line_lower:
                patterns_detected.add("timeout")
            if "permission denied" in line_lower:
                patterns_detected.add("permission_denied")
            if "out of memory" in line_lower or "oom" in line_lower:
                patterns_detected.add("out_of_memory")

        # Find time range
        timestamps = [e.timestamp for e in entries if e.timestamp]
        time_start = min(timestamps) if timestamps else None
        time_end = max(timestamps) if timestamps else None

        parsed_log = ParsedLog(
            entries=entries,
            error_count=error_count,
            warning_count=warning_count,
            time_range_start=time_start,
            time_range_end=time_end,
            sources=list(sources),
            key_errors=key_errors,
            patterns_detected=list(patterns_detected),
        )

        # Calculate confidence
        parsed_count = len([e for e in entries if e.timestamp or e.level != LogLevel.INFO])
        confidence = min(0.3 + (parsed_count / max(len(entries), 1)) * 0.5, 0.8)

        parse_time = (time.perf_counter() - start_time) * 1000

        return LogParsingResult(
            parsed_log=parsed_log,
            confidence=confidence,
            coverage_ratio=parsed_count / max(len(lines), 1),
            has_unparsed_blocks=parsed_count < len(entries),
            truncated=False,
            total_lines=len(lines),
            backend_used=self.name,
            parse_time_ms=parse_time,
        )

    async def parse_host_query(self, text: str) -> HostQueryParsingResult:
        """Parse text as a host query."""
        start_time = time.perf_counter()
        text = self._validate_input(text)

        entities = await self.extract_entities(text)
        text_lower = text.lower()

        # Determine query type
        query_type = "list"
        if any(word in text_lower for word in ["details", "detail", "info", "information"]):
            query_type = "details"
        elif any(word in text_lower for word in ["status", "health", "check"]):
            query_type = "status"
        elif any(word in text_lower for word in ["count", "how many"]):
            query_type = "count"

        # Extract filters
        filters: dict[str, Any] = {}

        # Tag filters
        tag_match = re.search(r"tag[s]?\s*[=:]\s*([a-zA-Z0-9_,-]+)", text_lower)
        if tag_match:
            filters["tags"] = tag_match.group(1).split(",")

        # Status filters
        if "running" in text_lower or "online" in text_lower:
            filters["status"] = "running"
        elif "stopped" in text_lower or "offline" in text_lower:
            filters["status"] = "stopped"

        # Group patterns
        groups: list[str] = []
        group_match = re.search(r"group[s]?\s*[=:]\s*([a-zA-Z0-9_,-]+)", text_lower)
        if group_match:
            groups = group_match.group(1).split(",")

        query = HostQueryInput(
            target_hosts=entities.get("hosts", []),
            target_groups=groups,
            filters=filters,
            query_type=query_type,
            fields_requested=[],
        )

        confidence = 0.5 + (0.1 if entities.get("hosts") else 0) + (0.1 if filters else 0)

        parse_time = (time.perf_counter() - start_time) * 1000

        return HostQueryParsingResult(
            query=query,
            confidence=confidence,
            coverage_ratio=0.7,
            has_unparsed_blocks=False,
            backend_used=self.name,
            parse_time_ms=parse_time,
        )

    async def parse_command(self, text: str) -> CommandParsingResult:
        """Parse text as a command."""
        start_time = time.perf_counter()
        text = self._validate_input(text)

        entities = await self.extract_entities(text)

        # Extract target host
        target_host = entities.get("hosts", [None])[0] if entities.get("hosts") else None

        # Extract via/jump host
        via_host = None
        via_match = re.search(r"\bvia\s+@?(\w[\w.-]*)", text, re.IGNORECASE)
        if via_match:
            via_host = via_match.group(1)
            # Remove via host from target if same
            if target_host == via_host and len(entities.get("hosts", [])) > 1:
                target_host = entities["hosts"][1]

        # Extract the actual command (after "run", "execute", "launch", etc.)
        command = text
        cmd_match = re.search(
            r"(?:run|execute|launch|do|perform)\s+['\"]?(.+?)['\"]?\s*$",
            text,
            re.IGNORECASE,
        )
        if cmd_match:
            command = cmd_match.group(1)

        # Check if destructive (using pre-compiled patterns)
        is_destructive = any(pattern.search(command) for pattern in DESTRUCTIVE_PATTERNS)

        # Check if requires elevation
        requires_elevation = any(
            word in command.lower() for word in ["sudo", "su -", "doas", "/etc/", "/var/log/"]
        )

        # Extract secrets
        secrets = entities.get("secrets", [])

        cmd_input = CommandInput(
            command=command,
            target_host=target_host,
            via_host=via_host,
            requires_elevation=requires_elevation,
            is_destructive=is_destructive,
            secrets_referenced=secrets,
        )

        parse_time = (time.perf_counter() - start_time) * 1000

        return CommandParsingResult(
            command=cmd_input,
            confidence=0.6 + (0.1 if target_host else 0),
            coverage_ratio=0.8,
            has_unparsed_blocks=False,
            backend_used=self.name,
            parse_time_ms=parse_time,
        )

    async def extract_entities(self, text: str) -> dict[str, list[str]]:
        """Extract named entities from text using pre-compiled regex patterns."""
        entities: dict[str, list[str]] = {}

        for entity_type, compiled_patterns in COMPILED_PATTERNS.items():
            found: set[str] = set()
            for pattern in compiled_patterns:
                matches = pattern.findall(text)
                found.update(matches)

            if found:
                # Validate IPv4 addresses in hosts (reject octets > 255)
                if entity_type == "hosts":
                    found = {
                        h
                        for h in found
                        if not re.fullmatch(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", h)
                        or _is_valid_ipv4(h)
                    }
                if found:
                    entities[entity_type] = list(found)

        return entities

    def _detect_environment(self, text_lower: str) -> Environment:
        """Detect environment from text."""
        for env, compiled_patterns in ENV_PATTERNS.items():
            if any(p.search(text_lower) for p in compiled_patterns):
                return env
        return Environment.UNKNOWN

    def _detect_severity(self, text_lower: str) -> Severity:
        """Detect severity from text."""
        for sev, compiled_patterns in SEVERITY_PATTERNS.items():
            if any(p.search(text_lower) for p in compiled_patterns):
                return sev
        # Default based on error indicators
        if re.search(r"\b(down|outage|crash)\b", text_lower):
            return Severity.HIGH
        if re.search(r"\b(error|failed)\b", text_lower):
            return Severity.MEDIUM
        return Severity.MEDIUM

    def _extract_symptoms(self, text: str) -> list[str]:
        """Extract symptom sentences from text."""
        symptoms: list[str] = []
        sentences = re.split(r"[.!?\n]", text)

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            # Check for error indicators using compiled patterns
            if any(p.search(sentence) for p in COMPILED_PATTERNS["errors"]):
                symptoms.append(sentence[:200])

        return symptoms[:10]  # Limit to 10 symptoms

    def _extract_error_messages(self, text: str) -> list[str]:
        """Extract error messages from text."""
        errors: list[str] = []

        # Quoted strings that look like errors
        quoted = re.findall(
            r'["\']([^"\']*(?:error|failed|exception)[^"\']*)["\']', text, re.IGNORECASE
        )
        errors.extend(quoted)

        # Lines starting with common error prefixes
        for line in text.split("\n"):
            line = line.strip()
            if re.match(r"^(error|failed|exception|fatal):", line, re.IGNORECASE):
                errors.append(line[:200])

        return list(set(errors))[:10]

    def _parse_timestamps(self, raw_timestamps: list[str]) -> list[datetime]:
        """Parse raw timestamp strings into datetime objects."""
        parsed: list[datetime] = []

        formats = [
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%d/%m/%Y %H:%M:%S",
        ]

        for ts in raw_timestamps:
            for fmt in formats:
                try:
                    # Handle timezone suffixes
                    clean_ts = re.sub(r"[Z+-]\d{2}:?\d{2}$", "", ts)
                    parsed.append(datetime.strptime(clean_ts, fmt))
                    break
                except ValueError:
                    continue

        return parsed

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract technical keywords from text."""
        keywords: set[str] = set()

        # Technical terms patterns
        tech_patterns = [
            r"\b(cpu|memory|ram|disk|network|io)\b",
            r"\b(load|usage|utilization|latency|throughput)\b",
            r"\b(container|pod|deployment|replica|node)\b",
            r"\b(database|cache|queue|broker|proxy)\b",
        ]

        for pattern in tech_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            keywords.update(m.lower() for m in matches)

        return list(keywords)[:20]

    def _parse_log_line(self, line: str, line_number: int) -> LogEntry:
        """Parse a single log line."""
        # Try to extract timestamp using compiled patterns
        timestamp = None
        for pattern in COMPILED_PATTERNS["timestamps"]:
            match = pattern.search(line)
            if match:
                ts_str = match.group(1)
                timestamp = self._parse_single_timestamp(ts_str)
                break

        # Detect log level using compiled patterns
        level = LogLevel.INFO
        line_lower = line.lower()
        for log_level, compiled_patterns in LOG_LEVEL_PATTERNS.items():
            if any(p.search(line_lower) for p in compiled_patterns):
                level = log_level
                break

        # Try to extract source (common log formats)
        source = ""
        # Syslog format: hostname service[pid]:
        syslog_match = re.search(r"^\S+\s+\d+\s+[\d:]+\s+(\S+)\s+(\S+?)(?:\[\d+\])?:", line)
        if syslog_match:
            source = syslog_match.group(2)
        else:
            # JSON-like: "service": "name" or service=name
            service_match = re.search(r'(?:service["\s:=]+)([a-zA-Z0-9_-]+)', line, re.IGNORECASE)
            if service_match:
                source = service_match.group(1)

        # Message is the whole line (could be refined)
        message = line

        return LogEntry(
            timestamp=timestamp,
            level=level,
            source=source,
            message=message[:500],
            line_number=line_number,
            raw=line,
        )

    def _parse_single_timestamp(self, ts_str: str) -> datetime | None:
        """Parse a single timestamp string."""
        formats = [
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%b %d %H:%M:%S",
        ]

        clean_ts = re.sub(r"[Z+-]\d{2}:?\d{2}$", "", ts_str)

        for fmt in formats:
            try:
                dt = datetime.strptime(clean_ts, fmt)
                # For syslog format without year, use current year
                if dt.year == 1900:
                    dt = dt.replace(year=datetime.now().year)
                return dt
            except ValueError:
                continue

        return None
