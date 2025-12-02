"""
Tests for hostname sanitization functionality.
"""
import pytest

from merlya.tools.base import sanitize_hostname


class TestSanitizeHostname:
    """Tests for sanitize_hostname function."""

    def test_clean_hostname_unchanged(self):
        """Clean hostnames should not be modified."""
        assert sanitize_hostname("myserver") == ("myserver", False)
        assert sanitize_hostname("server-01") == ("server-01", False)
        assert sanitize_hostname("app.example.com") == ("app.example.com", False)
        # Note: underscore is not valid in DNS hostnames, so it gets removed
        result, modified = sanitize_hostname("SERVER_123")
        assert result == "SERVER123"
        assert modified is True

    def test_xml_tags_removed(self):
        """XML/HTML tags should be stripped from hostnames."""
        # Real-world example from LLM output
        result, modified = sanitize_hostname(
            'MYSQL8CLUSTER4-1</parameter name="path">/etc/mysql/conf.d/*'
        )
        assert result == "MYSQL8CLUSTER4-1"
        assert modified is True

        # Simple closing tag
        result, modified = sanitize_hostname("myserver</parameter>")
        assert result == "myserver"
        assert modified is True

        # Opening tag
        result, modified = sanitize_hostname("<hostname>myserver")
        assert result == "myserver"
        assert modified is True

    def test_path_suffix_removed(self):
        """Paths appended to hostnames should be stripped."""
        result, modified = sanitize_hostname("myserver/etc/config")
        assert result == "myserver"
        assert modified is True

        result, modified = sanitize_hostname("myserver:/path/to/file")
        assert result == "myserver"
        assert modified is True

    def test_special_chars_removed(self):
        """Invalid hostname characters should be removed."""
        result, modified = sanitize_hostname("my@server!")
        assert result == "myserver"
        assert modified is True

        result, modified = sanitize_hostname("server#123")
        assert result == "server123"
        assert modified is True

    def test_empty_hostname(self):
        """Empty hostnames should return empty."""
        assert sanitize_hostname("") == ("", False)
        assert sanitize_hostname(None) == (None, False)

    def test_dots_and_hyphens_stripped_from_edges(self):
        """Leading/trailing dots and hyphens should be removed."""
        result, modified = sanitize_hostname(".myserver.")
        assert result == "myserver"
        assert modified is True

        result, modified = sanitize_hostname("-myserver-")
        assert result == "myserver"
        assert modified is True

    def test_fqdn_preserved(self):
        """Fully qualified domain names should be preserved."""
        assert sanitize_hostname("server.example.com") == ("server.example.com", False)
        assert sanitize_hostname("db-01.prod.internal") == ("db-01.prod.internal", False)

    def test_complex_malformed_hostname(self):
        """Complex malformed hostnames should be cleaned properly."""
        result, modified = sanitize_hostname(
            'SERVER<tag attr="val">suffix</tag>/path'
        )
        assert result == "SERVERsuffix"
        assert modified is True

    def test_port_number_stripped(self):
        """Port numbers should be stripped from hostname."""
        result, modified = sanitize_hostname("server:22")
        assert result == "server"
        assert modified is True

        result, modified = sanitize_hostname("server:8080")
        assert result == "server"
        assert modified is True

    def test_ipv4_preserved(self):
        """IPv4 addresses should be preserved unchanged."""
        assert sanitize_hostname("192.168.1.1") == ("192.168.1.1", False)
        assert sanitize_hostname("10.0.0.1") == ("10.0.0.1", False)

    def test_ipv6_preserved(self):
        """IPv6 addresses should be preserved unchanged."""
        assert sanitize_hostname("::1") == ("::1", False)
        assert sanitize_hostname("2001:db8::1") == ("2001:db8::1", False)

    def test_unicode_removed(self):
        """Unicode characters should be removed (security)."""
        result, modified = sanitize_hostname("sërvér")
        # Only ASCII letters remain
        assert "ë" not in result
        assert "é" not in result
        assert modified is True


class TestSecurityRedaction:
    """Tests for password redaction in security module."""

    def test_mysql_password_subshell_redacted(self):
        """MySQL password with subshell command should be redacted."""
        from merlya.utils.security import redact_sensitive_info

        command = 'mysql -u statistic -p$(echo LcSf4KE5nE5m9fGj) -e "SHOW STATUS"'
        redacted = redact_sensitive_info(command)

        assert "LcSf4KE5nE5m9fGj" not in redacted
        assert "-p[REDACTED]" in redacted
        assert "-u statistic" in redacted  # Username should remain

    def test_password_quoted_redacted(self):
        """Password with quotes should be redacted."""
        from merlya.utils.security import redact_sensitive_info

        # Single quotes
        command = "mysql -p'mypassword'"
        redacted = redact_sensitive_info(command)
        assert "mypassword" not in redacted

        # Double quotes
        command = 'mysql -p"mypassword"'
        redacted = redact_sensitive_info(command)
        assert "mypassword" not in redacted
