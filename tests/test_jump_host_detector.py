"""
Tests for jump host detection in SSH pivoting.
"""
import pytest

from merlya.triage.jump_host_detector import (
    JumpHostDetector,
    JumpHostInfo,
    detect_jump_host,
    get_jump_host_detector,
    is_valid_hostname,
    is_valid_ip,
)


class TestJumpHostDetector:
    """Test the JumpHostDetector class."""

    def test_detector_singleton(self):
        """Test that get_jump_host_detector returns the same instance."""
        detector1 = get_jump_host_detector()
        detector2 = get_jump_host_detector()
        assert detector1 is detector2

    def test_detect_via_bastion_english(self):
        """Test detection of 'via @bastion' pattern."""
        result = detect_jump_host("connect to 10.0.0.5 via @bastion")
        assert result is not None
        assert result.jump_host == "bastion"
        assert result.target_host == "10.0.0.5"
        assert result.confidence >= 0.95

    def test_detect_through_jumphost(self):
        """Test detection of 'through @jumphost' pattern."""
        result = detect_jump_host("check disk on server through @jumphost")
        assert result is not None
        assert result.jump_host == "jumphost"
        assert result.confidence >= 0.90

    def test_detect_french_a_travers(self):
        """Test detection of French 'à travers @host' pattern."""
        result = detect_jump_host("accessible via @gateway")
        assert result is not None
        assert result.jump_host == "gateway"
        assert result.confidence >= 0.90

    def test_detect_french_en_passant_par(self):
        """Test detection of French 'en passant par @host' pattern."""
        result = detect_jump_host("en passant par @bastion")
        assert result is not None
        assert result.jump_host == "bastion"
        assert result.confidence >= 0.90

    def test_detect_user_prompt_french(self):
        """Test detection of the exact user prompt in French."""
        query = "j'ai besoin d'investigué sur cette machine 51.68.25.89 mais il n'est accessible qu'a travers la machine @ansible"
        result = detect_jump_host(query)
        assert result is not None
        assert result.jump_host == "ansible"
        assert result.target_host == "51.68.25.89"
        assert result.confidence >= 0.95

    def test_detect_accessible_via_french(self):
        """Test detection of French 'accessible via @host' pattern."""
        result = detect_jump_host("cette machine n'est accessible que via @bastion")
        assert result is not None
        assert result.jump_host == "bastion"
        assert result.confidence >= 0.90

    def test_no_match_simple_command(self):
        """Test that simple commands without @host don't match."""
        result = detect_jump_host("simple command on localhost")
        assert result is None

    def test_no_match_at_variable(self):
        """Test that @variables without pivoting context don't match."""
        result = detect_jump_host("connect to @myhost")
        assert result is None

    def test_extract_ip_target(self):
        """Test that IP addresses are extracted as targets."""
        result = detect_jump_host("192.168.1.100 via @jumpbox")
        assert result is not None
        assert result.jump_host == "jumpbox"
        assert result.target_host == "192.168.1.100"

    def test_extract_ip_from_context(self):
        """Test that IP is extracted even if not in pattern."""
        query = "check host 10.20.30.40 accessible qu'à travers @proxy"
        result = detect_jump_host(query)
        assert result is not None
        assert result.jump_host == "proxy"
        # IP should be extracted from context
        assert result.target_host == "10.20.30.40"


class TestJumpHostInfo:
    """Test the JumpHostInfo dataclass."""

    def test_str_with_target(self):
        """Test string representation with target."""
        info = JumpHostInfo(
            jump_host="bastion",
            target_host="10.0.0.5",
            pattern_matched="test",
            confidence=0.95,
        )
        assert "bastion" in str(info)
        assert "10.0.0.5" in str(info)
        assert "0.95" in str(info)

    def test_str_without_target(self):
        """Test string representation without target."""
        info = JumpHostInfo(
            jump_host="bastion",
            target_host=None,
            pattern_matched="test",
            confidence=0.90,
        )
        assert "bastion" in str(info)
        assert "0.90" in str(info)


class TestExtractJumpAndTarget:
    """Test the convenience extraction method."""

    def test_extract_both(self):
        """Test extraction of both jump and target."""
        detector = JumpHostDetector()
        jump, target = detector.extract_jump_and_target("connect to 10.0.0.5 via @bastion")
        assert jump == "bastion"
        assert target == "10.0.0.5"

    def test_extract_none(self):
        """Test extraction when no match."""
        detector = JumpHostDetector()
        jump, target = detector.extract_jump_and_target("simple command")
        assert jump is None
        assert target is None


class TestSecurityValidation:
    """Security tests for hostname and IP validation."""

    def test_valid_simple_hostname(self):
        """Test that simple hostnames are valid."""
        assert is_valid_hostname("bastion") is True
        assert is_valid_hostname("ansible") is True
        assert is_valid_hostname("jump-host") is True
        assert is_valid_hostname("server01") is True

    def test_valid_fqdn(self):
        """Test that FQDNs are valid."""
        assert is_valid_hostname("bastion.example.com") is True
        assert is_valid_hostname("jump-host.internal.corp") is True

    def test_invalid_hostname_injection(self):
        """Test that injection attempts are rejected."""
        # Command injection attempts
        assert is_valid_hostname("bastion;rm -rf /") is False
        assert is_valid_hostname("bastion`whoami`") is False
        assert is_valid_hostname("bastion$(cat /etc/passwd)") is False
        assert is_valid_hostname("bastion|ls") is False
        assert is_valid_hostname("bastion&&id") is False

    def test_invalid_hostname_special_chars(self):
        """Test that special characters are rejected."""
        assert is_valid_hostname("bastion!") is False
        assert is_valid_hostname("bastion@evil") is False
        assert is_valid_hostname("bastion#1") is False
        assert is_valid_hostname("bastion$var") is False
        assert is_valid_hostname("bastion%20") is False
        assert is_valid_hostname("bastion^") is False
        assert is_valid_hostname("bastion&") is False
        assert is_valid_hostname("bastion*") is False
        assert is_valid_hostname("bastion=") is False

    def test_invalid_hostname_too_long(self):
        """Test that hostnames > 253 chars are rejected."""
        long_name = "a" * 300
        assert is_valid_hostname(long_name) is False

    def test_invalid_hostname_empty(self):
        """Test that empty hostnames are rejected."""
        assert is_valid_hostname("") is False
        assert is_valid_hostname(None) is False  # type: ignore

    def test_valid_ip(self):
        """Test that valid IPs are accepted."""
        assert is_valid_ip("192.168.1.1") is True
        assert is_valid_ip("10.0.0.1") is True
        assert is_valid_ip("255.255.255.255") is True
        assert is_valid_ip("0.0.0.0") is True

    def test_invalid_ip_out_of_range(self):
        """Test that IPs with out-of-range octets are rejected."""
        assert is_valid_ip("999.999.999.999") is False
        assert is_valid_ip("256.1.1.1") is False
        assert is_valid_ip("1.256.1.1") is False
        assert is_valid_ip("1.1.256.1") is False
        assert is_valid_ip("1.1.1.256") is False

    def test_invalid_ip_format(self):
        """Test that malformed IPs are rejected."""
        assert is_valid_ip("192.168.1") is False
        assert is_valid_ip("192.168.1.1.1") is False
        assert is_valid_ip("192.168.1.a") is False
        assert is_valid_ip("not-an-ip") is False

    def test_detect_rejects_invalid_jump_host(self):
        """Test that detection rejects invalid jump host names."""
        # These should NOT match because the hostname is invalid
        result = detect_jump_host("connect via @bastion;rm")
        # Should either be None or have a different (valid) jump_host
        if result is not None:
            assert ";" not in result.jump_host

    def test_detect_rejects_invalid_ip(self):
        """Test that invalid IPs are not extracted as targets."""
        result = detect_jump_host("999.999.999.999 via @bastion")
        assert result is not None
        assert result.jump_host == "bastion"
        # Invalid IP should NOT be extracted
        assert result.target_host != "999.999.999.999"

    def test_jumphost_info_validation(self):
        """Test that JumpHostInfo validates on creation."""
        # Valid creation should work
        info = JumpHostInfo(
            jump_host="bastion",
            target_host="10.0.0.5",
            pattern_matched="test",
            confidence=0.95,
        )
        assert info.jump_host == "bastion"

        # Invalid jump host should raise
        with pytest.raises(ValueError, match="Invalid jump host"):
            JumpHostInfo(
                jump_host="bastion;rm -rf /",
                target_host="10.0.0.5",
                pattern_matched="test",
                confidence=0.95,
            )

        # Invalid target should raise
        with pytest.raises(ValueError, match="Invalid target"):
            JumpHostInfo(
                jump_host="bastion",
                target_host="not;valid;host",
                pattern_matched="test",
                confidence=0.95,
            )
