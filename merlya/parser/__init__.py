"""
Merlya Parser Module.

Provides structured parsing of user input and system output:
- Incident descriptions -> IncidentInput
- Log output -> ParsedLog
- Host queries -> HostQueryInput
- Commands -> CommandInput

Usage:
    from merlya.parser import ParserService

    # Initialize with tier
    service = ParserService.get_instance(tier="balanced")
    await service.initialize()

    # Parse incident
    result = await service.parse_incident("Production server web-01 is down...")
    print(result.incident.affected_hosts)  # ['web-01']
    print(result.confidence)  # 0.75

    # Or use convenience functions
    from merlya.parser import parse_incident, parse_log
    result = await parse_incident("Server crashed with OOM error")
"""

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
    ParsingResult,
    Severity,
)
from merlya.parser.service import (
    ParserService,
    parse_command,
    parse_host_query,
    parse_incident,
    parse_log,
)

__all__ = [
    # Service
    "ParserService",
    # Convenience functions
    "parse_incident",
    "parse_log",
    "parse_host_query",
    "parse_command",
    # Models
    "ParsingResult",
    "IncidentInput",
    "IncidentParsingResult",
    "ParsedLog",
    "LogEntry",
    "LogParsingResult",
    "HostQueryInput",
    "HostQueryParsingResult",
    "CommandInput",
    "CommandParsingResult",
    # Enums
    "Severity",
    "Environment",
    "LogLevel",
]
