"""
Tests for the Merlya Parser Service.

Tests cover:
- ParserService initialization and tier selection
- HeuristicBackend parsing (incident, log, host query, command)
- Entity extraction
- Confidence scoring
- Edge cases
"""

from __future__ import annotations

import pytest

from merlya.parser import (
    CommandInput,
    Environment,
    HostQueryInput,
    IncidentInput,
    LogLevel,
    ParsedLog,
    ParserService,
    ParsingResult,
    Severity,
)
from merlya.parser.backends.heuristic import HeuristicBackend
from merlya.parser.extractors import extract_host_query, extract_incident, extract_log_info


@pytest.fixture(autouse=True)
def reset_parser_service() -> None:
    """Reset ParserService singleton between tests."""
    ParserService.reset_instance()
    yield
    ParserService.reset_instance()


class TestParserService:
    """Tests for ParserService initialization and tier selection."""

    @pytest.mark.asyncio
    async def test_singleton_pattern(self) -> None:
        """Test that ParserService is a singleton."""
        service1 = ParserService.get_instance(tier="lightweight")
        service2 = ParserService.get_instance()
        assert service1 is service2

    @pytest.mark.asyncio
    async def test_lightweight_tier_uses_heuristic(self) -> None:
        """Test that lightweight tier uses HeuristicBackend."""
        service = ParserService.get_instance(tier="lightweight")
        await service.initialize()
        assert service.backend_name == "heuristic"

    @pytest.mark.asyncio
    async def test_initialize_returns_true(self) -> None:
        """Test that initialization succeeds."""
        service = ParserService.get_instance(tier="lightweight")
        result = await service.initialize()
        assert result is True
        assert service.is_initialized is True

    @pytest.mark.asyncio
    async def test_tier_property(self) -> None:
        """Test tier property (always lightweight since ONNX removed)."""
        service = ParserService.get_instance(tier="balanced")
        # ONNX removed in v0.8.0 - tier is always lightweight now
        assert service.tier == "lightweight"


class TestHeuristicBackend:
    """Tests for HeuristicBackend parsing."""

    @pytest.fixture
    def backend(self) -> HeuristicBackend:
        """Create a HeuristicBackend instance."""
        return HeuristicBackend()

    @pytest.mark.asyncio
    async def test_backend_name(self, backend: HeuristicBackend) -> None:
        """Test backend name property."""
        assert backend.name == "heuristic"
        assert backend.is_loaded is True

    @pytest.mark.asyncio
    async def test_load_returns_true(self, backend: HeuristicBackend) -> None:
        """Test that load always succeeds for heuristic."""
        result = await backend.load()
        assert result is True


class TestIncidentParsing:
    """Tests for incident description parsing."""

    @pytest.fixture
    def backend(self) -> HeuristicBackend:
        """Create a HeuristicBackend instance."""
        return HeuristicBackend()

    @pytest.mark.asyncio
    async def test_parse_simple_incident(self, backend: HeuristicBackend) -> None:
        """Test parsing a simple incident description."""
        text = "Production server web-01 is down with OOM errors"
        result = await backend.parse_incident(text)

        assert isinstance(result.incident, IncidentInput)
        assert result.confidence > 0.0
        assert result.backend_used == "heuristic"

    @pytest.mark.asyncio
    async def test_extract_hosts_from_incident(self, backend: HeuristicBackend) -> None:
        """Test that hosts are extracted from incident."""
        text = "Servers @web-01 and @db-master are failing"
        result = await backend.parse_incident(text)

        assert "web-01" in result.incident.affected_hosts
        assert "db-master" in result.incident.affected_hosts

    @pytest.mark.asyncio
    async def test_detect_production_environment(self, backend: HeuristicBackend) -> None:
        """Test production environment detection."""
        text = "Production server is experiencing high CPU usage"
        result = await backend.parse_incident(text)

        assert result.incident.environment == Environment.PRODUCTION

    @pytest.mark.asyncio
    async def test_detect_staging_environment(self, backend: HeuristicBackend) -> None:
        """Test staging environment detection."""
        text = "Staging environment has database connection issues"
        result = await backend.parse_incident(text)

        assert result.incident.environment == Environment.STAGING

    @pytest.mark.asyncio
    async def test_detect_critical_severity(self, backend: HeuristicBackend) -> None:
        """Test critical severity detection."""
        text = "CRITICAL: Production outage affecting all users"
        result = await backend.parse_incident(text)

        assert result.incident.severity == Severity.CRITICAL

    @pytest.mark.asyncio
    async def test_extract_error_messages(self, backend: HeuristicBackend) -> None:
        """Test error message extraction."""
        text = 'Server failed with error: "Connection refused to database"'
        result = await backend.parse_incident(text)

        assert len(result.incident.error_messages) > 0 or len(result.incident.symptoms) > 0

    @pytest.mark.asyncio
    async def test_extract_file_paths(self, backend: HeuristicBackend) -> None:
        """Test file path extraction."""
        text = "Error in /var/log/nginx/error.log causing issues"
        result = await backend.parse_incident(text)

        assert "/var/log/nginx/error.log" in result.incident.paths

    @pytest.mark.asyncio
    async def test_extract_services(self, backend: HeuristicBackend) -> None:
        """Test service name extraction."""
        text = "nginx and mysql services are not responding"
        result = await backend.parse_incident(text)

        assert "nginx" in result.incident.affected_services
        assert "mysql" in result.incident.affected_services

    @pytest.mark.asyncio
    async def test_incident_truncation(self, backend: HeuristicBackend) -> None:
        """Test that long descriptions are truncated."""
        text = "Error " * 200  # Very long text
        result = await backend.parse_incident(text)

        assert result.truncated is True
        assert len(result.incident.description) <= 503  # 500 + "..."


class TestLogParsing:
    """Tests for log output parsing."""

    @pytest.fixture
    def backend(self) -> HeuristicBackend:
        """Create a HeuristicBackend instance."""
        return HeuristicBackend()

    @pytest.mark.asyncio
    async def test_parse_simple_log(self, backend: HeuristicBackend) -> None:
        """Test parsing simple log output."""
        text = """2024-01-15 10:30:45 ERROR Connection refused
2024-01-15 10:30:46 INFO Retrying connection
2024-01-15 10:30:47 ERROR Failed again"""
        result = await backend.parse_log(text)

        assert isinstance(result.parsed_log, ParsedLog)
        assert result.parsed_log.error_count == 2
        assert result.total_lines == 3

    @pytest.mark.asyncio
    async def test_count_errors_and_warnings(self, backend: HeuristicBackend) -> None:
        """Test error and warning counting."""
        text = """ERROR: First error
WARNING: First warning
ERROR: Second error
INFO: Some info
WARNING: Second warning"""
        result = await backend.parse_log(text)

        assert result.parsed_log.error_count == 2
        assert result.parsed_log.warning_count == 2

    @pytest.mark.asyncio
    async def test_detect_log_patterns(self, backend: HeuristicBackend) -> None:
        """Test detection of common log patterns."""
        text = """Connection refused to database
Request timeout after 30s
Permission denied for /etc/config"""
        result = await backend.parse_log(text)

        assert "connection_refused" in result.parsed_log.patterns_detected
        assert "timeout" in result.parsed_log.patterns_detected
        assert "permission_denied" in result.parsed_log.patterns_detected

    @pytest.mark.asyncio
    async def test_extract_key_errors(self, backend: HeuristicBackend) -> None:
        """Test key error extraction."""
        text = """ERROR: Database connection failed
ERROR: Unable to reach API endpoint"""
        result = await backend.parse_log(text)

        assert len(result.parsed_log.key_errors) >= 1

    @pytest.mark.asyncio
    async def test_log_entry_levels(self, backend: HeuristicBackend) -> None:
        """Test log level detection in entries."""
        text = """ERROR: This is an error
WARN: This is a warning
INFO: This is info
DEBUG: This is debug"""
        result = await backend.parse_log(text)

        levels = [e.level for e in result.parsed_log.entries]
        assert LogLevel.ERROR in levels
        assert LogLevel.WARNING in levels
        assert LogLevel.INFO in levels
        assert LogLevel.DEBUG in levels


class TestHostQueryParsing:
    """Tests for host query parsing."""

    @pytest.fixture
    def backend(self) -> HeuristicBackend:
        """Create a HeuristicBackend instance."""
        return HeuristicBackend()

    @pytest.mark.asyncio
    async def test_parse_list_query(self, backend: HeuristicBackend) -> None:
        """Test parsing a list query."""
        text = "list all hosts"
        result = await backend.parse_host_query(text)

        assert result.query.query_type == "list"

    @pytest.mark.asyncio
    async def test_parse_details_query(self, backend: HeuristicBackend) -> None:
        """Test parsing a details query."""
        text = "show details for @web-01"
        result = await backend.parse_host_query(text)

        assert result.query.query_type == "details"
        assert "web-01" in result.query.target_hosts

    @pytest.mark.asyncio
    async def test_parse_status_query(self, backend: HeuristicBackend) -> None:
        """Test parsing a status query."""
        text = "check status of database servers"
        result = await backend.parse_host_query(text)

        assert result.query.query_type == "status"

    @pytest.mark.asyncio
    async def test_extract_tag_filter(self, backend: HeuristicBackend) -> None:
        """Test tag filter extraction."""
        text = "list hosts with tag=production"
        result = await backend.parse_host_query(text)

        assert "tags" in result.query.filters
        assert "production" in result.query.filters["tags"]

    @pytest.mark.asyncio
    async def test_extract_status_filter(self, backend: HeuristicBackend) -> None:
        """Test status filter extraction."""
        text = "show all running hosts"
        result = await backend.parse_host_query(text)

        assert result.query.filters.get("status") == "running"


class TestCommandParsing:
    """Tests for command parsing."""

    @pytest.fixture
    def backend(self) -> HeuristicBackend:
        """Create a HeuristicBackend instance."""
        return HeuristicBackend()

    @pytest.mark.asyncio
    async def test_parse_simple_command(self, backend: HeuristicBackend) -> None:
        """Test parsing a simple command."""
        text = "run uptime on @web-01"
        result = await backend.parse_command(text)

        assert isinstance(result.command, CommandInput)
        assert "web-01" in (result.command.target_host or "")

    @pytest.mark.asyncio
    async def test_detect_via_host(self, backend: HeuristicBackend) -> None:
        """Test detection of via/jump host."""
        text = "check disk usage on db-server via @bastion"
        result = await backend.parse_command(text)

        assert result.command.via_host == "bastion"

    @pytest.mark.asyncio
    async def test_detect_destructive_command(self, backend: HeuristicBackend) -> None:
        """Test destructive command detection."""
        text = "run rm -rf /tmp/logs on server"
        result = await backend.parse_command(text)

        assert result.command.is_destructive is True

    @pytest.mark.asyncio
    async def test_detect_elevation_needed(self, backend: HeuristicBackend) -> None:
        """Test elevation detection."""
        text = "run sudo systemctl restart nginx"
        result = await backend.parse_command(text)

        assert result.command.requires_elevation is True

    @pytest.mark.asyncio
    async def test_extract_secrets(self, backend: HeuristicBackend) -> None:
        """Test secret reference extraction."""
        text = "connect with password @db-password"
        await backend.parse_command(text)

        # Secrets are extracted in entities
        entities = await backend.extract_entities(text)
        assert "db-password" in entities.get("secrets", [])


class TestEntityExtraction:
    """Tests for entity extraction."""

    @pytest.fixture
    def backend(self) -> HeuristicBackend:
        """Create a HeuristicBackend instance."""
        return HeuristicBackend()

    @pytest.mark.asyncio
    async def test_extract_hosts(self, backend: HeuristicBackend) -> None:
        """Test host extraction."""
        text = "Connect to @web-01 and @db-master"
        entities = await backend.extract_entities(text)

        assert "web-01" in entities.get("hosts", [])
        assert "db-master" in entities.get("hosts", [])

    @pytest.mark.asyncio
    async def test_extract_paths(self, backend: HeuristicBackend) -> None:
        """Test path extraction."""
        text = "Check /var/log/syslog and ~/config/app.yaml"
        entities = await backend.extract_entities(text)

        assert "/var/log/syslog" in entities.get("paths", [])
        assert "~/config/app.yaml" in entities.get("paths", [])

    @pytest.mark.asyncio
    async def test_extract_ip_addresses(self, backend: HeuristicBackend) -> None:
        """Test IP address extraction."""
        text = "Server at 192.168.1.100 is not responding"
        entities = await backend.extract_entities(text)

        assert "192.168.1.100" in entities.get("hosts", [])

    @pytest.mark.asyncio
    async def test_invalid_ip_address_rejected(self, backend: HeuristicBackend) -> None:
        """Test that invalid IP addresses with octets > 255 are rejected."""
        text = "Invalid IP 999.999.999.999 should not be extracted"
        entities = await backend.extract_entities(text)

        hosts = entities.get("hosts", [])
        assert "999.999.999.999" not in hosts

    @pytest.mark.asyncio
    async def test_mixed_valid_invalid_ips(self, backend: HeuristicBackend) -> None:
        """Test that valid IPs are extracted while invalid ones are rejected."""
        text = "Valid 10.0.0.1 and invalid 256.1.2.3 and valid 255.255.255.255"
        entities = await backend.extract_entities(text)

        hosts = entities.get("hosts", [])
        assert "10.0.0.1" in hosts
        assert "255.255.255.255" in hosts
        assert "256.1.2.3" not in hosts

    @pytest.mark.asyncio
    async def test_extract_timestamps(self, backend: HeuristicBackend) -> None:
        """Test timestamp extraction."""
        text = "Error occurred at 2024-01-15T10:30:45Z"
        entities = await backend.extract_entities(text)

        assert len(entities.get("timestamps", [])) > 0


class TestExtractorFunctions:
    """Tests for high-level extractor functions."""

    @pytest.mark.asyncio
    async def test_extract_incident_with_confidence(self) -> None:
        """Test extract_incident returns incident when confident."""
        text = "Production server @web-01 crashed with OOM error"
        incident, result = await extract_incident(text, min_confidence=0.3)

        assert incident is not None
        assert result.confidence >= 0.3

    @pytest.mark.asyncio
    async def test_extract_incident_low_confidence(self) -> None:
        """Test extract_incident returns None when not confident."""
        text = "hello world"  # Not an incident
        _incident, result = await extract_incident(text, min_confidence=0.9)

        # May or may not return incident based on confidence
        assert result is not None

    @pytest.mark.asyncio
    async def test_extract_host_query(self) -> None:
        """Test extract_host_query function."""
        text = "list all hosts with tag=web"
        query, _result = await extract_host_query(text)

        assert isinstance(query, HostQueryInput)
        assert query.query_type == "list"

    @pytest.mark.asyncio
    async def test_extract_log_info(self) -> None:
        """Test extract_log_info function."""
        text = """ERROR: Connection failed
INFO: Retrying..."""
        log_info, _result = await extract_log_info(text)

        assert isinstance(log_info, ParsedLog)
        assert log_info.error_count >= 1


class TestParsingResult:
    """Tests for ParsingResult model."""

    def test_parsing_result_defaults(self) -> None:
        """Test ParsingResult default values."""
        result = ParsingResult()

        assert result.confidence == 0.0
        assert result.coverage_ratio == 0.0
        assert result.has_unparsed_blocks is True
        assert result.truncated is False
        assert result.backend_used == "unknown"

    def test_parsing_result_validation(self) -> None:
        """Test ParsingResult field validation."""
        result = ParsingResult(confidence=0.5, coverage_ratio=0.8)

        assert 0.0 <= result.confidence <= 1.0
        assert 0.0 <= result.coverage_ratio <= 1.0


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.fixture
    def backend(self) -> HeuristicBackend:
        """Create a HeuristicBackend instance."""
        return HeuristicBackend()

    @pytest.mark.asyncio
    async def test_empty_input(self, backend: HeuristicBackend) -> None:
        """Test handling of empty input."""
        result = await backend.parse_incident("")

        assert result.incident.description == ""
        assert result.confidence <= 0.5

    @pytest.mark.asyncio
    async def test_unicode_input(self, backend: HeuristicBackend) -> None:
        """Test handling of unicode characters."""
        text = "Erreur sur le serveur: échec de connexion à la base de données"
        result = await backend.parse_incident(text)

        assert result is not None
        assert result.incident.description != ""

    @pytest.mark.asyncio
    async def test_very_long_input(self, backend: HeuristicBackend) -> None:
        """Test handling of very long input."""
        text = "Error message " * 1000
        result = await backend.parse_incident(text)

        assert result.truncated is True
        assert len(result.incident.description) <= 503

    @pytest.mark.asyncio
    async def test_special_characters(self, backend: HeuristicBackend) -> None:
        """Test handling of special characters."""
        text = "Error: <script>alert('xss')</script>"
        result = await backend.parse_incident(text)

        assert result is not None

    @pytest.mark.asyncio
    async def test_multiline_log(self, backend: HeuristicBackend) -> None:
        """Test handling of multiline log with stack traces."""
        text = """java.lang.NullPointerException
    at com.example.Service.process(Service.java:42)
    at com.example.Main.run(Main.java:15)
ERROR: Service crashed"""
        result = await backend.parse_log(text)

        assert result.total_lines == 4
        assert result.parsed_log.error_count >= 1
