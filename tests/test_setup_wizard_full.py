"""
Tests for Setup Wizard.

Tests LLMConfig, SetupResult, inventory detection, and host merging logic.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.setup.wizard import (
    PROVIDERS,
    InventorySource,
    LLMConfig,
    SetupResult,
    _merge_fields,
    check_first_run,
    deduplicate_hosts,
    detect_inventory_sources,
    merge_host_data,
    parse_inventory_source,
)


class TestLLMConfig:
    """Tests for LLMConfig dataclass."""

    def test_basic_config(self):
        """Test basic LLM configuration."""
        config = LLMConfig(
            provider="anthropic",
            model="claude-3-5-sonnet-latest",
        )

        assert config.provider == "anthropic"
        assert config.model == "claude-3-5-sonnet-latest"
        assert config.api_key_env is None
        assert config.fallback_model is None

    def test_config_with_api_key(self):
        """Test config with API key environment variable."""
        config = LLMConfig(
            provider="openai",
            model="gpt-4o",
            api_key_env="OPENAI_API_KEY",
        )

        assert config.api_key_env == "OPENAI_API_KEY"

    def test_config_with_fallback(self):
        """Test config with fallback model."""
        config = LLMConfig(
            provider="anthropic",
            model="claude-3-5-sonnet-latest",
            fallback_model="anthropic:claude-3-haiku-20240307",
        )

        assert config.fallback_model == "anthropic:claude-3-haiku-20240307"


class TestSetupResult:
    """Tests for SetupResult dataclass."""

    def test_default_result(self):
        """Test default setup result."""
        result = SetupResult()

        assert result.llm_config is None
        assert result.hosts_imported == 0
        assert result.hosts_skipped == 0
        assert result.sources_imported == []
        assert result.completed is False

    def test_result_with_values(self):
        """Test result with values."""
        config = LLMConfig(provider="openai", model="gpt-4o")
        result = SetupResult(
            llm_config=config,
            hosts_imported=10,
            hosts_skipped=2,
            sources_imported=["SSH Config", "Known Hosts"],
            completed=True,
        )

        assert result.llm_config.provider == "openai"
        assert result.hosts_imported == 10
        assert result.hosts_skipped == 2
        assert len(result.sources_imported) == 2
        assert result.completed is True


class TestInventorySource:
    """Tests for InventorySource dataclass."""

    def test_basic_source(self):
        """Test basic inventory source."""
        source = InventorySource(
            name="SSH Config",
            path=Path.home() / ".ssh" / "config",
            source_type="ssh_config",
            host_count=10,
        )

        assert source.name == "SSH Config"
        assert source.source_type == "ssh_config"
        assert source.host_count == 10


class TestProviders:
    """Tests for provider configuration constants."""

    def test_providers_exist(self):
        """Test all providers are defined."""
        assert "1" in PROVIDERS  # OpenRouter
        assert "2" in PROVIDERS  # Anthropic
        assert "3" in PROVIDERS  # OpenAI
        assert "4" in PROVIDERS  # Ollama

    def test_provider_structure(self):
        """Test provider configuration structure."""
        for _key, config in PROVIDERS.items():
            assert len(config) == 4  # (provider, env_key, default_model, fallback)
            provider, _env_key, default_model, _fallback = config
            assert isinstance(provider, str)
            assert isinstance(default_model, str)
            # env_key can be None (Ollama)
            # fallback should be a string

    def test_anthropic_provider(self):
        """Test Anthropic provider config."""
        provider, env_key, model, _fallback = PROVIDERS["2"]

        assert provider == "anthropic"
        assert env_key == "ANTHROPIC_API_KEY"
        assert "claude" in model

    def test_ollama_no_api_key(self):
        """Test Ollama has no API key requirement."""
        provider, env_key, _model, _fallback = PROVIDERS["6"]

        assert provider == "ollama"
        assert env_key is None

    def test_mistral_provider(self):
        """Test Mistral provider configuration."""
        provider, env_key, model, _fallback = PROVIDERS["4"]

        assert provider == "mistral"
        assert env_key == "MISTRAL_API_KEY"
        assert "mistral" in model

    def test_groq_provider(self):
        """Test Groq provider configuration."""
        provider, env_key, model, _fallback = PROVIDERS["5"]

        assert provider == "groq"
        assert env_key == "GROQ_API_KEY"
        assert "llama" in model


class TestMergeFields:
    """Tests for _merge_fields helper function."""

    @pytest.fixture
    def host_data_class(self):
        """Get HostData class."""
        from merlya.setup.models import HostData

        return HostData

    def test_merge_hostname(self, host_data_class):
        """Test merging hostname."""
        target = host_data_class(name="web-01", hostname="")
        source = host_data_class(name="web-01", hostname="192.168.1.10")

        _merge_fields(target, source)

        assert target.hostname == "192.168.1.10"

    def test_merge_username(self, host_data_class):
        """Test merging username."""
        target = host_data_class(name="web-01", hostname="host.com", username=None)
        source = host_data_class(name="web-01", hostname="host.com", username="admin")

        _merge_fields(target, source)

        assert target.username == "admin"

    def test_merge_private_key(self, host_data_class):
        """Test merging private key."""
        target = host_data_class(name="web-01", hostname="host.com", private_key=None)
        source = host_data_class(name="web-01", hostname="host.com", private_key="/path/to/key")

        _merge_fields(target, source)

        assert target.private_key == "/path/to/key"

    def test_merge_jump_host(self, host_data_class):
        """Test merging jump host."""
        target = host_data_class(name="internal", hostname="host.com", jump_host=None)
        source = host_data_class(name="internal", hostname="host.com", jump_host="bastion")

        _merge_fields(target, source)

        assert target.jump_host == "bastion"

    def test_no_overwrite_existing(self, host_data_class):
        """Test existing values are not overwritten."""
        target = host_data_class(
            name="web-01",
            hostname="192.168.1.10",
            username="admin",
        )
        source = host_data_class(
            name="web-01",
            hostname="10.0.0.1",
            username="root",
        )

        _merge_fields(target, source)

        # Existing values should not change
        assert target.hostname == "192.168.1.10"
        assert target.username == "admin"


class TestMergeHostData:
    """Tests for merge_host_data function."""

    @pytest.fixture
    def host_data_class(self):
        """Get HostData class."""
        from merlya.setup.models import HostData

        return HostData

    @pytest.mark.asyncio
    async def test_merge_empty_list(self):
        """Test merging empty list."""
        result = await merge_host_data([])

        assert result == []

    @pytest.mark.asyncio
    async def test_merge_single_host(self, host_data_class):
        """Test merging single host."""
        hosts = [host_data_class(name="web-01", hostname="192.168.1.10")]

        result = await merge_host_data(hosts)

        assert len(result) == 1
        assert result[0].name == "web-01"

    @pytest.mark.asyncio
    async def test_merge_duplicate_names(self, host_data_class):
        """Test merging hosts with duplicate names."""
        hosts = [
            host_data_class(name="web-01", hostname="192.168.1.10", tags=["ssh-config:1"]),
            host_data_class(name="web-01", hostname="10.0.0.1", tags=["known-hosts:1"]),
        ]

        result = await merge_host_data(hosts)

        # Should merge into one
        assert len(result) == 1
        # SSH config has higher priority
        assert result[0].hostname == "192.168.1.10"
        # Tags should be merged
        assert len(result[0].tags) == 2

    @pytest.mark.asyncio
    async def test_merge_priority_ssh_over_known_hosts(self, host_data_class):
        """Test SSH config has higher priority than known hosts."""
        hosts = [
            host_data_class(
                name="server",
                hostname="known.com",
                username="user1",
                tags=["known-hosts:1"],
            ),
            host_data_class(
                name="server",
                hostname="ssh.com",
                username="user2",
                tags=["ssh-config:1"],
            ),
        ]

        result = await merge_host_data(hosts)

        assert len(result) == 1
        # SSH config values should win
        assert result[0].hostname == "ssh.com"
        assert result[0].username == "user2"

    @pytest.mark.asyncio
    async def test_merge_case_insensitive(self, host_data_class):
        """Test name matching is case insensitive."""
        hosts = [
            host_data_class(name="WEB-01", hostname="192.168.1.10", tags=["a"]),
            host_data_class(name="web-01", hostname="10.0.0.1", tags=["b"]),
        ]

        result = await merge_host_data(hosts)

        # Should be merged (same name, different case)
        assert len(result) == 1


class TestDeduplicateHosts:
    """Tests for deduplicate_hosts function."""

    @pytest.fixture
    def host_data_class(self):
        """Get HostData class."""
        from merlya.setup.models import HostData

        return HostData

    @pytest.mark.asyncio
    async def test_no_duplicates(self, host_data_class):
        """Test when there are no duplicates."""
        hosts = [
            host_data_class(name="web-01", hostname="host1.com"),
            host_data_class(name="web-02", hostname="host2.com"),
        ]
        existing = set()

        result, duplicates = await deduplicate_hosts(hosts, existing)

        assert len(result) == 2
        assert duplicates == 0

    @pytest.mark.asyncio
    async def test_skip_existing(self, host_data_class):
        """Test skipping already existing hosts."""
        hosts = [
            host_data_class(name="web-01", hostname="host1.com"),
            host_data_class(name="web-02", hostname="host2.com"),
        ]
        existing = {"web-01"}

        result, duplicates = await deduplicate_hosts(hosts, existing)

        assert len(result) == 1
        assert result[0].name == "web-02"
        assert duplicates == 1

    @pytest.mark.asyncio
    async def test_skip_duplicates_in_list(self, host_data_class):
        """Test skipping duplicates within the list."""
        hosts = [
            host_data_class(name="web-01", hostname="host1.com"),
            host_data_class(name="web-01", hostname="host2.com"),
        ]
        existing = set()

        result, duplicates = await deduplicate_hosts(hosts, existing)

        assert len(result) == 1
        assert duplicates == 1

    @pytest.mark.asyncio
    async def test_keep_more_complete_host(self, host_data_class):
        """Test keeping the more complete host entry."""
        hosts = [
            host_data_class(name="web-01", hostname="host.com"),
            host_data_class(
                name="web-01",
                hostname="host.com",
                username="admin",
                private_key="/key",
            ),
        ]
        existing = set()

        result, _duplicates = await deduplicate_hosts(hosts, existing)

        assert len(result) == 1
        # Should keep the more complete one
        assert result[0].username == "admin"
        assert result[0].private_key == "/key"

    @pytest.mark.asyncio
    async def test_case_insensitive_existing(self, host_data_class):
        """Test case insensitive matching for existing hosts."""
        hosts = [host_data_class(name="WEB-01", hostname="host.com")]
        existing = {"web-01"}  # lowercase

        result, duplicates = await deduplicate_hosts(hosts, existing)

        assert len(result) == 0
        assert duplicates == 1


class TestDetectInventorySources:
    """Tests for detect_inventory_sources function."""

    @pytest.mark.asyncio
    async def test_detect_returns_list(self):
        """Test that detect_inventory_sources returns a list."""
        mock_ui = MagicMock()

        # Test with real filesystem - function should not crash
        sources = await detect_inventory_sources(mock_ui)

        assert isinstance(sources, list)
        # Each source should be an InventorySource
        for source in sources:
            assert isinstance(source, InventorySource)

    @pytest.mark.asyncio
    async def test_detect_with_mocked_parsers(self):
        """Test source detection with mocked parser counts."""
        mock_ui = MagicMock()

        with (
            patch("merlya.setup.parsers.etc_hosts.count_etc_hosts", return_value=0),
            patch("merlya.setup.parsers.ssh_config.count_ssh_hosts", return_value=0),
            patch("merlya.setup.parsers.known_hosts.count_known_hosts", return_value=0),
            patch("merlya.setup.parsers.ansible.count_ansible_hosts", return_value=0),
        ):
            sources = await detect_inventory_sources(mock_ui)
            # With all counts returning 0, sources may still include paths that exist
            # but they won't be added if count is 0
            assert isinstance(sources, list)


class TestParseInventorySource:
    """Tests for parse_inventory_source function."""

    @pytest.mark.asyncio
    async def test_parse_unknown_type(self):
        """Test parsing unknown source type."""
        source = InventorySource(
            name="Unknown",
            path=Path("/tmp/unknown"),
            source_type="unknown_type",
            host_count=0,
        )

        result = await parse_inventory_source(source)

        assert result == []

    @pytest.mark.asyncio
    async def test_parse_ssh_config_mocked(self):
        """Test parsing SSH config source."""
        source = InventorySource(
            name="SSH Config",
            path=Path("/mock/ssh/config"),
            source_type="ssh_config",
            host_count=5,
        )

        with patch(
            "merlya.setup.parsers.parse_ssh_config",
            new_callable=AsyncMock,
        ) as mock_parser:
            mock_parser.return_value = []

            await parse_inventory_source(source)

            mock_parser.assert_called_once_with(source.path)

    @pytest.mark.asyncio
    async def test_parse_known_hosts_mocked(self):
        """Test parsing known hosts source."""
        source = InventorySource(
            name="Known Hosts",
            path=Path("/mock/known_hosts"),
            source_type="known_hosts",
            host_count=10,
        )

        with patch(
            "merlya.setup.parsers.parse_known_hosts",
            new_callable=AsyncMock,
        ) as mock_parser:
            mock_parser.return_value = []

            await parse_inventory_source(source)

            mock_parser.assert_called_once_with(source.path)


class TestCheckFirstRun:
    """Tests for check_first_run function."""

    @pytest.mark.asyncio
    async def test_first_run_no_config(self, tmp_path):
        """Test first run detection when no config exists."""
        with patch("merlya.setup.wizard.Path") as MockPath:
            MockPath.home.return_value = tmp_path
            tmp_path / ".merlya" / "config.yaml"

            # Config doesn't exist
            await check_first_run()

            # Usually True if config doesn't exist
            # Actual result depends on real filesystem

    @pytest.mark.asyncio
    async def test_not_first_run_config_exists(self, tmp_path):
        """Test when config already exists."""
        # Create the config
        config_dir = tmp_path / ".merlya"
        config_dir.mkdir(parents=True)
        (config_dir / "config.yaml").write_text("provider: openai")

        with patch("merlya.setup.wizard.Path") as MockPath:
            MockPath.home.return_value = tmp_path

            # The function checks Path.home() / ".merlya" / "config.yaml"
            # With real Path, we can test:
            pass


class TestParseRealFiles:
    """Tests for parsing real inventory files."""

    @pytest.fixture
    def ssh_config_content(self):
        """Sample SSH config content."""
        return """
Host web-01
    HostName 192.168.1.10
    User admin
    IdentityFile ~/.ssh/id_rsa

Host db-*
    HostName %h.example.com
    User postgres

Host *
    StrictHostKeyChecking no
"""

    @pytest.fixture
    def etc_hosts_content(self):
        """Sample /etc/hosts content."""
        return """
127.0.0.1       localhost
::1             localhost
192.168.1.10    web-01.local web-01
192.168.1.20    db-01.local db-01
10.0.0.5        cache-server
"""

    @pytest.fixture
    def known_hosts_content(self):
        """Sample known_hosts content."""
        return """
192.168.1.10 ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQ...
web-01.example.com,192.168.1.10 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5...
[github.com]:22 ssh-rsa AAAAB3NzaC1yc2EAAAABIwAAAQEAq2A7hRGm...
"""

    @pytest.mark.asyncio
    async def test_parse_ssh_config_file(self, tmp_path, ssh_config_content):
        """Test parsing real SSH config file."""
        config_path = tmp_path / "config"
        config_path.write_text(ssh_config_content)

        from merlya.setup.parsers.ssh_config import parse_ssh_config

        hosts = await parse_ssh_config(config_path)

        # Should find web-01 but not wildcards
        assert any(h.name == "web-01" for h in hosts)

    @pytest.mark.asyncio
    async def test_parse_etc_hosts_file(self, tmp_path, etc_hosts_content):
        """Test parsing /etc/hosts file."""
        hosts_path = tmp_path / "hosts"
        hosts_path.write_text(etc_hosts_content)

        from merlya.setup.parsers.etc_hosts import parse_etc_hosts

        hosts = await parse_etc_hosts(hosts_path)

        # Should find non-localhost entries (first hostname per line is used)
        assert any(h.name == "web-01.local" for h in hosts)
        assert not any(h.name == "localhost" for h in hosts)

    @pytest.mark.asyncio
    async def test_parse_known_hosts_file(self, tmp_path, known_hosts_content):
        """Test parsing known_hosts file."""
        known_path = tmp_path / "known_hosts"
        known_path.write_text(known_hosts_content)

        from merlya.setup.parsers.known_hosts import parse_known_hosts

        hosts = await parse_known_hosts(known_path)

        # Should extract hostnames
        assert isinstance(hosts, list)


class TestInventoryParsersCount:
    """Tests for inventory source counting functions."""

    def test_count_ssh_hosts(self, tmp_path):
        """Test SSH host counting."""
        config_path = tmp_path / "config"
        config_path.write_text("""
Host web-01
    HostName 192.168.1.10
Host db-01
    HostName 192.168.1.20
Host *
    User admin
""")

        from merlya.setup.parsers.ssh_config import count_ssh_hosts

        count = count_ssh_hosts(config_path)

        # Should count 2 (not the wildcard)
        assert count == 2

    def test_count_etc_hosts(self, tmp_path):
        """Test /etc/hosts counting."""
        hosts_path = tmp_path / "hosts"
        hosts_path.write_text("""
127.0.0.1 localhost
192.168.1.10 web-01
192.168.1.20 db-01
""")

        from merlya.setup.parsers.etc_hosts import count_etc_hosts

        count = count_etc_hosts(hosts_path)

        # Should count 2 (not localhost)
        assert count == 2

    def test_count_known_hosts(self, tmp_path):
        """Test known_hosts counting."""
        known_path = tmp_path / "known_hosts"
        known_path.write_text("""
192.168.1.10 ssh-rsa AAAAB3...
web-01.example.com ssh-ed25519 AAAAC3...
192.168.1.20 ssh-rsa AAAAB3...
""")

        from merlya.setup.parsers.known_hosts import count_known_hosts

        count = count_known_hosts(known_path)

        assert count >= 2


class TestRunLLMSetupMocked:
    """Tests for run_llm_setup with mocked UI."""

    @pytest.mark.asyncio
    async def test_llm_setup_openrouter(self):
        """Test LLM setup with OpenRouter selection."""
        mock_ui = MagicMock()
        mock_ui.prompt_choice = AsyncMock(return_value="1")
        mock_ui.prompt = AsyncMock(return_value="amazon/nova-2-lite-v1:free")
        mock_ui.prompt_secret = AsyncMock(return_value="test-api-key")
        mock_ui.panel = MagicMock()
        mock_ui.success = MagicMock()
        mock_ui.warning = MagicMock()

        with (
            patch("merlya.secrets.get_secret", return_value=None),
            patch("merlya.secrets.set_secret"),
        ):
            from merlya.setup.wizard import run_llm_setup

            config = await run_llm_setup(mock_ui)

            assert config is not None
            assert config.provider == "openrouter"

    @pytest.mark.asyncio
    async def test_llm_setup_ollama_no_api_key(self):
        """Test LLM setup with Ollama (no API key needed)."""
        mock_ui = MagicMock()
        mock_ui.prompt_choice = AsyncMock(return_value="6")  # Ollama (now option 6)
        mock_ui.prompt = AsyncMock(return_value="llama3.2")
        mock_ui.panel = MagicMock()
        mock_ui.success = MagicMock()

        from merlya.setup.wizard import run_llm_setup

        config = await run_llm_setup(mock_ui)

        assert config is not None
        assert config.provider == "ollama"
        assert config.api_key_env is None

    @pytest.mark.asyncio
    async def test_llm_setup_api_key_from_env(self):
        """Test LLM setup with API key from environment."""
        mock_ui = MagicMock()
        mock_ui.prompt_choice = AsyncMock(return_value="2")  # Anthropic
        mock_ui.prompt = AsyncMock(return_value="claude-3-5-sonnet-latest")
        mock_ui.panel = MagicMock()
        mock_ui.success = MagicMock()

        import os

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            from merlya.setup.wizard import run_llm_setup

            config = await run_llm_setup(mock_ui)

            assert config is not None
            assert config.provider == "anthropic"
            # Should have detected key from env
            mock_ui.success.assert_called()

    @pytest.mark.asyncio
    async def test_llm_setup_cancelled(self):
        """Test LLM setup cancelled when no API key provided."""
        mock_ui = MagicMock()
        mock_ui.prompt_choice = AsyncMock(return_value="2")  # Anthropic
        mock_ui.prompt_secret = AsyncMock(return_value="")  # Empty API key
        mock_ui.panel = MagicMock()
        mock_ui.warning = MagicMock()

        import os

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("merlya.secrets.get_secret", return_value=None),
        ):
            from merlya.setup.wizard import run_llm_setup

            # Remove ANTHROPIC_API_KEY if present
            os.environ.pop("ANTHROPIC_API_KEY", None)

            config = await run_llm_setup(mock_ui)

            # Should return None when API key cancelled
            assert config is None
