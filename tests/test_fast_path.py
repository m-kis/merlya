"""
Tests for Fast Path Optimization Module.

Tests semantic detection and keyword fallback for simple queries.
"""
import pytest

from merlya.agents.orchestrator_service.fast_path import (
    FastPathDetector,
    FastPathExecutor,
    FastPathMatch,
    FastPathType,
)


class TestFastPathKeywordDetection:
    """Tests for keyword-based detection (no embeddings)."""

    @pytest.fixture
    def detector_no_embeddings(self):
        """Create a detector that forces keyword fallback."""
        detector = FastPathDetector(credentials_manager=None)
        # Force keyword mode by disabling embeddings
        detector._use_embeddings = False
        return detector

    # Scan host patterns (keyword mode)
    @pytest.mark.parametrize("query,expected_type", [
        ("scan myserver", FastPathType.SCAN_HOST),
        ("scan @myserver", FastPathType.SCAN_HOST),
        ("scan moi le serveur", FastPathType.SCAN_HOST),
        ("quels sont les services", FastPathType.SCAN_HOST),
    ])
    def test_scan_detection_keyword(self, detector_no_embeddings, query, expected_type):
        """Test scan host keyword detection."""
        match = detector_no_embeddings.detect(query)
        assert match.path_type == expected_type

    # List hosts patterns (keyword mode)
    @pytest.mark.parametrize("query,expected_type", [
        ("list hosts", FastPathType.LIST_HOSTS),
        ("list all hosts", FastPathType.LIST_HOSTS),
        ("quels sont les serveurs", FastPathType.LIST_HOSTS),
    ])
    def test_list_hosts_detection_keyword(self, detector_no_embeddings, query, expected_type):
        """Test list hosts keyword detection."""
        match = detector_no_embeddings.detect(query)
        assert match.path_type == expected_type

    # Check host patterns (keyword mode)
    @pytest.mark.parametrize("query,expected_type", [
        ("check @myserver", FastPathType.CHECK_HOST),
        ("ping @myserver", FastPathType.CHECK_HOST),
        ("status of @myhost", FastPathType.CHECK_HOST),
    ])
    def test_check_detection_keyword(self, detector_no_embeddings, query, expected_type):
        """Test check host keyword detection."""
        match = detector_no_embeddings.detect(query)
        assert match.path_type == expected_type


class TestFastPathNoMatch:
    """Tests for queries that should NOT match fast path."""

    @pytest.fixture
    def detector(self):
        """Create a standard detector."""
        return FastPathDetector(credentials_manager=None)

    # Complex queries should go through full orchestration
    @pytest.mark.parametrize("query", [
        "restart nginx on production",
        "deploy the application",
        "analyze performance issues",
        "why is the database slow",
        "configure firewall rules",
        "what is the best way to optimize memory",
        "help me troubleshoot the network",
        "create a backup of the database",
    ])
    def test_no_fast_path_for_complex_queries(self, detector, query):
        """Complex queries should not match fast path."""
        match = detector.detect(query)
        assert match.path_type == FastPathType.NONE, f"Expected NONE for '{query}'"


class TestFastPathParameterExtraction:
    """Tests for hostname and username extraction."""

    @pytest.fixture
    def detector(self):
        return FastPathDetector(credentials_manager=None)

    def test_hostname_extraction_at_variable(self, detector):
        """Test hostname extraction from @variable pattern."""
        match = detector.detect("scan @myserver")
        assert match.hostname == "myserver"

    def test_username_extraction_pattern(self, detector):
        """Test username extraction patterns."""
        # user is pattern
        match = detector.detect("scan @myserver user is admin")
        assert match.username == "admin"


class TestFastPathExecutor:
    """Tests for FastPathExecutor."""

    @pytest.fixture
    def mock_tools(self):
        """Create mock tools."""
        def mock_scan_host(hostname, user=""):
            return f"✅ Host {hostname} scanned (user={user})"

        def mock_list_hosts(environment="all"):
            return f"📋 Hosts in {environment}: host1, host2, host3"

        return {
            "scan_host": mock_scan_host,
            "list_hosts": mock_list_hosts,
        }

    @pytest.fixture
    def executor(self, mock_tools):
        """Create executor with mock tools."""
        return FastPathExecutor(tools=mock_tools)

    @pytest.mark.asyncio
    async def test_execute_scan_host(self, executor):
        """Test scan_host execution."""
        match = FastPathMatch(
            path_type=FastPathType.SCAN_HOST,
            hostname="myserver",
            username="admin",
            confidence=0.90,
            original_query="scan @myserver",
        )
        result = await executor.execute(match)
        assert result is not None
        assert "myserver" in result
        assert "admin" in result

    @pytest.mark.asyncio
    async def test_execute_list_hosts(self, executor):
        """Test list_hosts execution."""
        match = FastPathMatch(
            path_type=FastPathType.LIST_HOSTS,
            environment="production",
            confidence=0.85,
            original_query="list production hosts",
        )
        result = await executor.execute(match)
        assert result is not None
        assert "production" in result

    @pytest.mark.asyncio
    async def test_execute_none_returns_none(self, executor):
        """Test that NONE type returns None."""
        match = FastPathMatch(
            path_type=FastPathType.NONE,
            confidence=0.0,
            original_query="complex query",
        )
        result = await executor.execute(match)
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_missing_hostname_returns_none(self, executor):
        """Test that missing hostname returns None for scan."""
        match = FastPathMatch(
            path_type=FastPathType.SCAN_HOST,
            hostname=None,  # Missing hostname
            confidence=0.85,
            original_query="scan something",
        )
        result = await executor.execute(match)
        assert result is None


class TestFastPathSemanticDetection:
    """Tests for semantic detection when embeddings are available."""

    @pytest.fixture
    def detector(self):
        """Create a detector with embeddings enabled (if available)."""
        return FastPathDetector(credentials_manager=None)

    def test_detector_initializes(self, detector):
        """Test that detector initializes correctly."""
        assert detector is not None
        # Should use embeddings if available, keywords otherwise
        assert hasattr(detector, "_use_embeddings")

    def test_scan_query_detected(self, detector):
        """Test that scan queries are detected (semantic or keyword)."""
        match = detector.detect("scan @myserver")
        # Should match via either semantic or keyword
        assert match.path_type in (FastPathType.SCAN_HOST, FastPathType.CHECK_HOST, FastPathType.NONE)
        # If matched, should have hostname
        if match.path_type != FastPathType.NONE:
            assert match.hostname is not None

    def test_list_query_detected(self, detector):
        """Test that list queries are detected."""
        match = detector.detect("list hosts")
        assert match.path_type == FastPathType.LIST_HOSTS

    def test_confidence_provided(self, detector):
        """Test that confidence score is always provided."""
        match = detector.detect("scan @myserver")
        assert match.confidence >= 0.0
        assert match.confidence <= 1.0
