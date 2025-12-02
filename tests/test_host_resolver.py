"""
Tests for host resolver with disambiguation.
"""
import pytest
from unittest.mock import MagicMock, patch
from merlya.context.host_resolver import (
    HostResolver,
    ResolvedHost,
    get_host_resolver,
    reset_host_resolver,
    resolve_hostname,
)
from merlya.context.sources.base import Host, InventorySource


@pytest.fixture(autouse=True)
def reset_resolver():
    """Reset resolver singleton between tests."""
    reset_host_resolver()
    yield
    reset_host_resolver()


@pytest.fixture
def mock_registry():
    """Create a mock host registry with test hosts."""
    registry = MagicMock()
    registry.is_empty.return_value = False

    # Create test hosts
    hosts = {
        "ansible": Host(
            hostname="ANSIBLE",
            ip_address="192.168.107.250",
            source=InventorySource.ANSIBLE_INVENTORY,
            environment="production",
            groups=["ansible", "devops"],
        ),
        "ansibledevops": Host(
            hostname="ANSIBLEDEVOPS",
            ip_address="192.168.107.251",
            source=InventorySource.ANSIBLE_INVENTORY,
            environment="development",
            groups=["devops"],
        ),
        "preprodlb": Host(
            hostname="preprodlb",
            ip_address="10.0.1.10",
            source=InventorySource.ANSIBLE_INVENTORY,
            environment="staging",
            groups=["loadbalancer", "haproxy"],
        ),
        "prodlb": Host(
            hostname="prodlb",
            ip_address="10.0.1.11",
            source=InventorySource.ANSIBLE_INVENTORY,
            environment="production",
            groups=["loadbalancer", "haproxy"],
        ),
    }
    registry.hosts = hosts
    registry.get.side_effect = lambda name: hosts.get(name.lower())
    return registry


class TestHostResolver:
    """Tests for HostResolver class."""

    def test_exact_match(self, mock_registry):
        """Test exact hostname match (case-insensitive)."""
        resolver = HostResolver(mock_registry)
        result = resolver.resolve("ANSIBLE")

        assert result.exact_match is True
        assert result.host is not None
        assert result.host.hostname == "ANSIBLE"
        assert result.confidence == 1.0
        assert result.disambiguation_needed is False

    def test_exact_match_case_insensitive(self, mock_registry):
        """Test case-insensitive exact match."""
        resolver = HostResolver(mock_registry)
        result = resolver.resolve("ansible")

        assert result.exact_match is True
        assert result.host is not None
        assert result.host.hostname == "ANSIBLE"

    def test_partial_match_single_candidate(self, mock_registry):
        """Test partial match with single clear candidate."""
        resolver = HostResolver(mock_registry)
        result = resolver.resolve("preprod")

        # Should match preprodlb with high confidence
        assert result.host is not None
        assert result.host.hostname == "preprodlb"
        assert result.confidence >= 0.6
        assert result.disambiguation_needed is False

    def test_ambiguous_match_similar_names(self, mock_registry):
        """Test that similar names trigger disambiguation."""
        # When searching for 'ansible', it might match both ANSIBLE and ANSIBLEDEVOPS
        resolver = HostResolver(mock_registry)

        # Simulate a case where the search term is ambiguous
        result = resolver.resolve("ansib")  # Partial that could match both

        # Both hosts should be in alternatives if disambiguation is needed
        # Or one should be clearly preferred
        if result.disambiguation_needed:
            assert len(result.alternatives) >= 1
        else:
            # One clear winner
            assert result.host is not None

    def test_no_match(self, mock_registry):
        """Test when no hosts match."""
        resolver = HostResolver(mock_registry)
        result = resolver.resolve("nonexistent")

        assert result.host is None
        assert result.exact_match is False
        assert result.disambiguation_needed is False
        assert result.error_message is not None

    def test_empty_query(self, mock_registry):
        """Test with empty query."""
        resolver = HostResolver(mock_registry)
        result = resolver.resolve("")

        assert result.host is None
        assert result.error_message is not None

    def test_context_boosting(self, mock_registry):
        """Test that context helps with disambiguation."""
        resolver = HostResolver(mock_registry)

        # With 'devops' context, ANSIBLEDEVOPS should be preferred
        result_with_context = resolver.resolve("ansible", context="devops")

        # Both should be valid results, but context may influence selection
        assert result_with_context.host is not None

    def test_format_disambiguation(self, mock_registry):
        """Test disambiguation message formatting."""
        resolver = HostResolver(mock_registry)

        # Create a result that needs disambiguation
        result = ResolvedHost(
            host=None,
            exact_match=False,
            confidence=0.7,
            alternatives=[("ANSIBLE", 0.9), ("ANSIBLEDEVOPS", 0.85)],
            disambiguation_needed=True,
            error_message="Multiple hosts match"
        )

        msg = resolver.format_disambiguation(result, "ansible")

        assert "Multiple hosts match" in msg
        assert "ANSIBLE" in msg
        assert "ANSIBLEDEVOPS" in msg


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_get_host_resolver_singleton(self):
        """Test that get_host_resolver returns a singleton."""
        resolver1 = get_host_resolver()
        resolver2 = get_host_resolver()

        assert resolver1 is resolver2

    def test_resolve_hostname_convenience(self, mock_registry):
        """Test resolve_hostname convenience function."""
        with patch('merlya.context.host_resolver.get_host_resolver') as mock_get:
            mock_resolver = MagicMock()
            mock_resolver.resolve.return_value = ResolvedHost(
                host=mock_registry.hosts["ansible"],
                exact_match=True,
                confidence=1.0,
                alternatives=[],
                disambiguation_needed=False
            )
            mock_get.return_value = mock_resolver

            result = resolve_hostname("ansible")

            assert result.exact_match is True
            mock_resolver.resolve.assert_called_once_with("ansible", None)


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_registry_not_loaded(self):
        """Test behavior when registry is empty and needs loading."""
        empty_registry = MagicMock()
        empty_registry.is_empty.return_value = True
        empty_registry.hosts = {}
        empty_registry.load_all_sources.return_value = None

        resolver = HostResolver(empty_registry)
        result = resolver.resolve("anyhost")

        # Should try to load sources
        empty_registry.load_all_sources.assert_called_once()
        assert result.host is None

    def test_special_characters_in_query(self, mock_registry):
        """Test handling of special characters in query."""
        resolver = HostResolver(mock_registry)

        # These should not crash
        result1 = resolver.resolve("host-with-dash")
        result2 = resolver.resolve("host.with.dots")
        result3 = resolver.resolve("host_with_underscore")

        assert result1.host is None  # No match expected
        assert result2.host is None
        assert result3.host is None

    def test_very_long_query(self, mock_registry):
        """Test handling of very long query strings."""
        resolver = HostResolver(mock_registry)

        long_query = "a" * 1000
        result = resolver.resolve(long_query)

        # Should not crash, just return no match
        assert result.host is None

    def test_whitespace_handling(self, mock_registry):
        """Test that whitespace is properly handled."""
        resolver = HostResolver(mock_registry)

        result = resolver.resolve("  ansible  ")

        # Should strip whitespace and find match
        assert result.host is not None
        assert result.host.hostname == "ANSIBLE"
