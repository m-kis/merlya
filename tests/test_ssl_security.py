#!/usr/bin/env python3
"""
Tests for SSL certificate checking security improvements.

This test verifies that the SSL certificate checking module properly validates
domain names and prevents command injection vulnerabilities.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from merlya.core.context import SharedContext
from merlya.tools.security.base import SecurityResult
from merlya.tools.security.ssl import _is_valid_domain, check_ssl_certs


class TestSSLSecurity:
    """Test SSL security improvements."""

    def test_is_valid_domain(self):
        """Test domain validation function."""
        # Valid domains
        assert _is_valid_domain("example.com")
        assert _is_valid_domain("sub.example.com")
        assert _is_valid_domain("test-site.co.uk")
        assert _is_valid_domain("a.b.c.d.e.f.g.h.i.j.k.l.m.n.o.p.q.r.s.t.u.v.w.x.y.z.com")

        # Invalid domains
        assert not _is_valid_domain("")
        assert not _is_valid_domain("localhost")  # No dot
        assert not _is_valid_domain("example..com")  # Double dot
        assert not _is_valid_domain(".example.com")  # Leading dot
        assert not _is_valid_domain("example.com.")  # Trailing dot
        assert not _is_valid_domain("exa mple.com")  # Space
        assert not _is_valid_domain("example.com;rm -rf /")  # Command injection
        assert not _is_valid_domain("example.com`whoami`")  # Command injection
        assert not _is_valid_domain("example.com$(whoami)")  # Command injection
        assert not _is_valid_domain("a" * 254)  # Too long

    @pytest.mark.asyncio
    async def test_check_ssl_certs_with_invalid_domains(self):
        """Test that invalid domains are properly handled."""
        # Mock context and dependencies
        ctx = MagicMock(spec=SharedContext)
        ctx.hosts.get_by_name = AsyncMock(return_value=None)
        ctx.get_ssh_pool = AsyncMock()

        # Test with mixed valid and invalid domains
        domains = [
            "example.com",  # Valid
            "invalid;domain",  # Invalid - contains semicolon
            "sub.example.com",  # Valid
            "",  # Invalid - empty
            "localhost",  # Invalid - no dot
        ]

        # Mock the SSH pool to avoid actual connections
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock(
            return_value=MagicMock(
                exit_code=0,
                stdout="notBefore=Jan 1 00:00:00 2024 GMT\nnotAfter=Jan 1 00:00:00 2025 GMT\nsubject=CN=example.com\nissuer=CN=CA",
            )
        )
        ctx.get_ssh_pool.return_value = mock_pool

        # Execute the function
        result = await check_ssl_certs(ctx, "testhost", domains=domains)

        # Verify the result
        assert isinstance(result, SecurityResult)
        assert result.success

        # Check that invalid domains were skipped
        data = result.data
        assert data["total_checked"] == 2  # Only valid domains checked
        assert len(data["certificates"]) == 2

        # Check that issues were reported for invalid domains
        issues = data["issues"]
        assert any("invalid;domain" in issue for issue in issues)
        assert any("localhost" in issue for issue in issues)

    @pytest.mark.asyncio
    async def test_check_ssl_certs_all_invalid_domains(self):
        """Test handling when all domains are invalid."""
        # Mock context and dependencies
        ctx = MagicMock(spec=SharedContext)

        # Test with only invalid domains
        domains = [
            "invalid;domain",
            "another`whoami`",
            "",
        ]

        # Execute the function
        result = await check_ssl_certs(ctx, "testhost", domains=domains)

        # Verify the result
        assert isinstance(result, SecurityResult)
        assert not result.success
        assert "No valid domains" in result.error

        # Check that no certificates were checked
        data = result.data
        assert data["total_checked"] == 0
        assert len(data["certificates"]) == 0

        # Check that issues were reported for all invalid domains
        issues = data["issues"]
        assert len(issues) == 3


if __name__ == "__main__":
    pytest.main([__file__])
