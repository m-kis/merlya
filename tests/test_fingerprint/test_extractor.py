"""Tests for SemanticSignatureExtractor."""

import pytest

from merlya.fingerprint.cache import ApprovalScope, FingerprintCache
from merlya.fingerprint.extractor import SemanticSignatureExtractor


@pytest.fixture
def extractor() -> SemanticSignatureExtractor:
    """Create extractor without cache."""
    return SemanticSignatureExtractor()


@pytest.fixture
def extractor_with_cache() -> SemanticSignatureExtractor:
    """Create extractor with cache."""
    cache = FingerprintCache()
    return SemanticSignatureExtractor(cache=cache)


class TestCurlPatterns:
    """Tests for curl command extraction."""

    async def test_curl_get(self, extractor: SemanticSignatureExtractor) -> None:
        """Test curl GET request extraction."""
        result = await extractor.extract("curl https://api.example.com/users")

        assert result.signature.action_type == "http_request"
        assert result.signature.verb == "GET"
        assert "api.example.com" in result.signature.targets
        assert result.signature.risk_level == "low"

    async def test_curl_post(self, extractor: SemanticSignatureExtractor) -> None:
        """Test curl POST request extraction."""
        result = await extractor.extract(
            'curl -X POST https://api.example.com/users -d \'{"name": "test"}\''
        )

        assert result.signature.action_type == "http_request"
        assert result.signature.verb == "POST"
        assert result.signature.risk_level == "medium"
        assert "-d" in result.signature.normalized_template

    async def test_curl_delete(self, extractor: SemanticSignatureExtractor) -> None:
        """Test curl DELETE request extraction."""
        result = await extractor.extract("curl -X DELETE https://api.example.com/users/123")

        assert result.signature.action_type == "http_request"
        assert result.signature.verb == "DELETE"
        assert result.signature.risk_level == "high"

    async def test_curl_put(self, extractor: SemanticSignatureExtractor) -> None:
        """Test curl PUT request extraction."""
        result = await extractor.extract(
            'curl -X PUT https://api.example.com/users/123 -d \'{"name": "updated"}\''
        )

        assert result.signature.action_type == "http_request"
        assert result.signature.verb == "PUT"
        assert result.signature.risk_level == "high"


class TestWgetPatterns:
    """Tests for wget command extraction."""

    async def test_wget_simple(self, extractor: SemanticSignatureExtractor) -> None:
        """Test simple wget extraction."""
        result = await extractor.extract("wget https://example.com/file.tar.gz")

        assert result.signature.action_type == "http_request"
        assert result.signature.verb == "GET"
        assert "example.com" in result.signature.targets
        assert result.signature.risk_level == "low"


class TestServicePatterns:
    """Tests for service management extraction."""

    async def test_systemctl_restart(self, extractor: SemanticSignatureExtractor) -> None:
        """Test systemctl restart extraction."""
        result = await extractor.extract("systemctl restart nginx")

        assert result.signature.action_type == "service_management"
        assert result.signature.verb == "restart"
        assert "nginx" in result.signature.targets
        assert result.signature.risk_level == "medium"

    async def test_systemctl_stop(self, extractor: SemanticSignatureExtractor) -> None:
        """Test systemctl stop extraction."""
        result = await extractor.extract("systemctl stop postgresql")

        assert result.signature.action_type == "service_management"
        assert result.signature.verb == "stop"
        assert "postgresql" in result.signature.targets
        assert result.signature.risk_level == "high"

    async def test_systemctl_start(self, extractor: SemanticSignatureExtractor) -> None:
        """Test systemctl start extraction."""
        result = await extractor.extract("systemctl start docker")

        assert result.signature.action_type == "service_management"
        assert result.signature.verb == "start"
        assert result.signature.risk_level == "low"

    async def test_service_restart(self, extractor: SemanticSignatureExtractor) -> None:
        """Test service command extraction."""
        result = await extractor.extract("service nginx restart")

        assert result.signature.action_type == "service_management"
        assert result.signature.verb == "restart"
        assert "nginx" in result.signature.targets


class TestFileOperations:
    """Tests for file operation extraction."""

    async def test_rm_file(self, extractor: SemanticSignatureExtractor) -> None:
        """Test rm command extraction."""
        result = await extractor.extract("rm /tmp/old-file.txt")

        assert result.signature.action_type == "file_delete"
        assert result.signature.risk_level == "high"

    async def test_rm_recursive(self, extractor: SemanticSignatureExtractor) -> None:
        """Test rm -rf extraction."""
        result = await extractor.extract("rm -rf /tmp/old-directory")

        assert result.signature.action_type == "file_delete"
        assert result.signature.risk_level == "high"

    async def test_chmod(self, extractor: SemanticSignatureExtractor) -> None:
        """Test chmod extraction."""
        result = await extractor.extract("chmod 755 /opt/app/bin/run.sh")

        assert result.signature.action_type == "file_permission_change"
        assert result.signature.risk_level == "high"

    async def test_chown(self, extractor: SemanticSignatureExtractor) -> None:
        """Test chown extraction."""
        result = await extractor.extract("chown www-data:www-data /var/www/html")

        assert result.signature.action_type == "file_ownership_change"
        assert result.signature.risk_level == "high"


class TestPackageManagement:
    """Tests for package management extraction."""

    async def test_apt_install(self, extractor: SemanticSignatureExtractor) -> None:
        """Test apt install extraction."""
        result = await extractor.extract("apt install nginx curl htop")

        assert result.signature.action_type == "package_management"
        assert result.signature.verb == "install"
        assert "nginx" in result.signature.targets
        assert result.signature.risk_level == "medium"

    async def test_apt_remove(self, extractor: SemanticSignatureExtractor) -> None:
        """Test apt remove extraction."""
        result = await extractor.extract("apt remove old-package")

        assert result.signature.action_type == "package_management"
        assert result.signature.verb == "remove"
        assert result.signature.risk_level == "high"

    async def test_yum_install(self, extractor: SemanticSignatureExtractor) -> None:
        """Test yum install extraction."""
        result = await extractor.extract("yum install httpd")

        assert result.signature.action_type == "package_management"
        assert result.signature.verb == "install"
        assert "httpd" in result.signature.targets

    async def test_pip_install(self, extractor: SemanticSignatureExtractor) -> None:
        """Test pip install extraction."""
        result = await extractor.extract("pip install requests flask")

        assert result.signature.action_type == "package_management"
        assert result.signature.verb == "install"


class TestProcessManagement:
    """Tests for process management extraction."""

    async def test_kill(self, extractor: SemanticSignatureExtractor) -> None:
        """Test kill extraction."""
        result = await extractor.extract("kill 12345")

        assert result.signature.action_type == "process_management"
        assert result.signature.verb == "kill"
        assert result.signature.risk_level == "high"

    async def test_kill_9(self, extractor: SemanticSignatureExtractor) -> None:
        """Test kill -9 extraction."""
        result = await extractor.extract("kill -9 12345")

        assert result.signature.action_type == "process_management"
        assert result.signature.verb == "kill"
        assert result.signature.risk_level == "critical"

    async def test_pkill(self, extractor: SemanticSignatureExtractor) -> None:
        """Test pkill extraction."""
        result = await extractor.extract("pkill nginx")

        assert result.signature.action_type == "process_management"
        assert result.signature.targets == ["nginx"]


class TestGenericCommands:
    """Tests for generic command extraction."""

    async def test_echo(self, extractor: SemanticSignatureExtractor) -> None:
        """Test echo command falls back to generic."""
        result = await extractor.extract("echo hello world")

        assert result.signature.action_type == "shell_command"
        assert result.signature.verb == "echo"
        assert result.signature.risk_level == "low"

    async def test_unknown_command(self, extractor: SemanticSignatureExtractor) -> None:
        """Test unknown command extraction."""
        result = await extractor.extract("my-custom-script --flag value")

        assert result.signature.action_type == "shell_command"
        assert result.signature.verb == "my-custom-script"
        assert result.signature.risk_level == "low"

    async def test_dangerous_generic(self, extractor: SemanticSignatureExtractor) -> None:
        """Test dangerous generic command gets high risk."""
        result = await extractor.extract("dd if=/dev/zero of=/dev/null bs=1M")

        # dd matches the high-risk list
        assert result.signature.risk_level == "high"


class TestCacheIntegration:
    """Tests for cache integration."""

    async def test_no_cache_requires_approval(self, extractor: SemanticSignatureExtractor) -> None:
        """Test extraction without cache requires new approval."""
        result = await extractor.extract("curl https://example.com")

        assert result.requires_new_approval is True
        assert result.cached_approval is None

    async def test_cached_approval_found(
        self, extractor_with_cache: SemanticSignatureExtractor
    ) -> None:
        """Test cached approval is found."""
        # First extraction
        result1 = await extractor_with_cache.extract("curl https://example.com")
        assert result1.requires_new_approval is True

        # Cache the approval
        extractor_with_cache._cache.set(
            result1.signature,
            approved=True,
            scope=ApprovalScope.SESSION,
        )

        # Second extraction with same template
        result2 = await extractor_with_cache.extract("curl https://example.com")

        assert result2.requires_new_approval is False
        assert result2.cached_approval is not None
        assert result2.cached_approval.approved is True

    async def test_similar_commands_share_approval(
        self, extractor_with_cache: SemanticSignatureExtractor
    ) -> None:
        """Test similar commands share cached approval via template."""
        # First extraction
        result1 = await extractor_with_cache.extract("curl https://example.com/api/v1")

        # Cache approval
        extractor_with_cache._cache.set(
            result1.signature,
            approved=True,
            scope=ApprovalScope.SESSION,
        )

        # Similar command with different URL should have same template hash
        result2 = await extractor_with_cache.extract("curl https://other.com/api/v2")

        # They should share the same normalized template
        assert result1.signature.signature_hash == result2.signature.signature_hash
        assert result2.requires_new_approval is False


class TestSignatureHashing:
    """Tests for signature hash consistency."""

    async def test_same_command_same_hash(self, extractor: SemanticSignatureExtractor) -> None:
        """Test same command produces same hash."""
        result1 = await extractor.extract("systemctl restart nginx")
        result2 = await extractor.extract("systemctl restart nginx")

        assert result1.signature.signature_hash == result2.signature.signature_hash

    async def test_different_service_same_template_hash(
        self, extractor: SemanticSignatureExtractor
    ) -> None:
        """Test different services produce same template hash."""
        result1 = await extractor.extract("systemctl restart nginx")
        result2 = await extractor.extract("systemctl restart apache")

        # Both have the same normalized template
        assert result1.signature.signature_hash == result2.signature.signature_hash

    async def test_different_action_different_hash(
        self, extractor: SemanticSignatureExtractor
    ) -> None:
        """Test different actions produce different hash."""
        result1 = await extractor.extract("systemctl restart nginx")
        result2 = await extractor.extract("systemctl stop nginx")

        # Different actions have different templates
        assert result1.signature.signature_hash != result2.signature.signature_hash
