"""Tests for the setup wizard parsing functions."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from merlya.setup.models import HostData
from merlya.setup.parsers import (
    parse_ansible_inventory,
    parse_etc_hosts,
    parse_known_hosts,
    parse_ssh_config,
)
from merlya.setup.parsers.ansible import _expand_ansible_range
from merlya.setup.parsers.utils import safe_parse_port


class TestSafeParsePort:
    """Tests for _safe_parse_port helper."""

    def test_valid_port(self) -> None:
        """Test valid port values."""
        assert safe_parse_port(22) == 22
        assert safe_parse_port("22") == 22
        assert safe_parse_port("8080") == 8080
        assert safe_parse_port(65535) == 65535
        assert safe_parse_port(1) == 1

    def test_invalid_port_returns_default(self) -> None:
        """Test invalid ports return default."""
        assert safe_parse_port(0) == 22
        assert safe_parse_port(-1) == 22
        assert safe_parse_port(65536) == 22
        assert safe_parse_port(100000) == 22

    def test_non_numeric_returns_default(self) -> None:
        """Test non-numeric values return default."""
        assert safe_parse_port("abc") == 22
        assert safe_parse_port("") == 22
        assert safe_parse_port(None) == 22

    def test_custom_default(self) -> None:
        """Test custom default value."""
        assert safe_parse_port("invalid", default=2222) == 2222
        assert safe_parse_port(None, default=443) == 443


class TestExpandAnsibleRange:
    """Tests for _expand_ansible_range function."""

    def test_numeric_range(self) -> None:
        """Test numeric range expansion."""
        result = _expand_ansible_range("web[01:03].example.com")
        assert result == [
            "web01.example.com",
            "web02.example.com",
            "web03.example.com",
        ]

    def test_numeric_range_without_padding(self) -> None:
        """Test numeric range without zero-padding."""
        result = _expand_ansible_range("server[1:3]")
        assert result == ["server1", "server2", "server3"]

    def test_numeric_range_with_step(self) -> None:
        """Test numeric range with step."""
        result = _expand_ansible_range("node[1:5:2]")
        assert result == ["node1", "node3", "node5"]

    def test_letter_range(self) -> None:
        """Test letter range expansion."""
        result = _expand_ansible_range("db[a:c]")
        assert result == ["dba", "dbb", "dbc"]

    def test_no_range(self) -> None:
        """Test pattern without range."""
        result = _expand_ansible_range("single-host")
        assert result == ["single-host"]

    def test_prefix_and_suffix(self) -> None:
        """Test range with prefix and suffix."""
        result = _expand_ansible_range("prod-web[1:2]-us")
        assert result == ["prod-web1-us", "prod-web2-us"]


class TestParseEtcHosts:
    """Tests for parse_etc_hosts function."""

    @pytest.mark.asyncio
    async def test_parse_valid_hosts(self) -> None:
        """Test parsing valid /etc/hosts entries."""
        content = """
# Comment line
127.0.0.1   localhost
192.168.1.10    server1.local   server1
10.0.0.5    myhost
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".hosts", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            hosts = await parse_etc_hosts(path)
            # Should skip localhost
            assert len(hosts) == 2
            names = {h.name for h in hosts}
            assert "server1.local" in names
            assert "myhost" in names
        finally:
            path.unlink()

    @pytest.mark.asyncio
    async def test_skip_localhost_variants(self) -> None:
        """Test that localhost variants are skipped."""
        content = """
127.0.0.1   localhost
::1         localhost ip6-localhost ip6-loopback
255.255.255.255 broadcasthost
192.168.1.1 realhost
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".hosts", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            hosts = await parse_etc_hosts(path)
            assert len(hosts) == 1
            assert hosts[0].name == "realhost"
        finally:
            path.unlink()

    @pytest.mark.asyncio
    async def test_skip_invalid_ip(self) -> None:
        """Test that invalid IPs are skipped."""
        content = """
not.an.ip   hostname1
192.168.1.1 hostname2
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".hosts", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            hosts = await parse_etc_hosts(path)
            assert len(hosts) == 1
            assert hosts[0].name == "hostname2"
        finally:
            path.unlink()


class TestParseSSHConfig:
    """Tests for parse_ssh_config function."""

    @pytest.mark.asyncio
    async def test_parse_basic_config(self) -> None:
        """Test parsing basic SSH config."""
        content = """
Host myserver
    HostName 192.168.1.100
    User admin
    Port 22
    IdentityFile ~/.ssh/id_rsa

Host webserver
    HostName web.example.com
    User www-data
    Port 2222
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".config", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            hosts = await parse_ssh_config(path)
            assert len(hosts) == 2

            myserver = next(h for h in hosts if h.name == "myserver")
            assert myserver.hostname == "192.168.1.100"
            assert myserver.username == "admin"
            assert myserver.port == 22

            webserver = next(h for h in hosts if h.name == "webserver")
            assert webserver.hostname == "web.example.com"
            assert webserver.username == "www-data"
            assert webserver.port == 2222
        finally:
            path.unlink()

    @pytest.mark.asyncio
    async def test_skip_wildcard_host(self) -> None:
        """Test that wildcard Host * is skipped."""
        content = """
Host *
    ServerAliveInterval 60

Host realserver
    HostName 10.0.0.1
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".config", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            hosts = await parse_ssh_config(path)
            assert len(hosts) == 1
            assert hosts[0].name == "realserver"
        finally:
            path.unlink()

    @pytest.mark.asyncio
    async def test_parse_proxyjump(self) -> None:
        """Test parsing ProxyJump directive."""
        content = """
Host target
    HostName 10.0.0.5
    ProxyJump jumphost
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".config", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            hosts = await parse_ssh_config(path)
            assert len(hosts) == 1
            assert hosts[0].jump_host == "jumphost"
        finally:
            path.unlink()


class TestParseKnownHosts:
    """Tests for parse_known_hosts function."""

    @pytest.mark.asyncio
    async def test_parse_basic_known_hosts(self) -> None:
        """Test parsing basic known_hosts."""
        content = """
server1.example.com ssh-rsa AAAAB3...
192.168.1.100 ssh-ed25519 AAAAC3...
github.com,140.82.121.4 ssh-rsa AAAAB3...
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".known_hosts", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            hosts = await parse_known_hosts(path)
            names = {h.name for h in hosts}
            assert "server1.example.com" in names
            assert "192.168.1.100" in names
            assert "github.com" in names
            assert "140.82.121.4" in names
        finally:
            path.unlink()

    @pytest.mark.asyncio
    async def test_skip_hashed_entries(self) -> None:
        """Test that hashed entries are skipped."""
        content = """
|1|abc123base64salt|xyz789base64hash ssh-rsa AAAAB3...
realhost.example.com ssh-rsa AAAAB3...
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".known_hosts", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            hosts = await parse_known_hosts(path)
            assert len(hosts) == 1
            assert hosts[0].name == "realhost.example.com"
        finally:
            path.unlink()

    @pytest.mark.asyncio
    async def test_parse_port_syntax(self) -> None:
        """Test parsing hosts with port syntax [host]:port."""
        content = """
[customport.example.com]:2222 ssh-rsa AAAAB3...
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".known_hosts", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            hosts = await parse_known_hosts(path)
            assert len(hosts) == 1
            assert hosts[0].name == "customport.example.com"
            assert hosts[0].port == 2222
        finally:
            path.unlink()


class TestParseAnsibleInventory:
    """Tests for parse_ansible_inventory function."""

    @pytest.mark.asyncio
    async def test_parse_basic_inventory(self) -> None:
        """Test parsing basic Ansible inventory."""
        content = """
[webservers]
web1 ansible_host=192.168.1.10
web2 ansible_host=192.168.1.11

[dbservers]
db1 ansible_host=192.168.1.20 ansible_user=postgres
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            hosts = await parse_ansible_inventory(path)
            assert len(hosts) == 3

            web1 = next(h for h in hosts if h.name == "web1")
            assert web1.hostname == "192.168.1.10"
            assert "ansible:webservers" in web1.tags

            db1 = next(h for h in hosts if h.name == "db1")
            assert db1.username == "postgres"
            assert "ansible:dbservers" in db1.tags
        finally:
            path.unlink()

    @pytest.mark.asyncio
    async def test_skip_vars_section(self) -> None:
        """Test that :vars sections are skipped."""
        content = """
[webservers]
web1

[webservers:vars]
ansible_user=www-data
some_var=value
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            hosts = await parse_ansible_inventory(path)
            assert len(hosts) == 1
            assert hosts[0].name == "web1"
        finally:
            path.unlink()

    @pytest.mark.asyncio
    async def test_parse_host_range(self) -> None:
        """Test parsing hosts with range patterns."""
        content = """
[webservers]
web[01:03]
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            hosts = await parse_ansible_inventory(path)
            assert len(hosts) == 3
            names = {h.name for h in hosts}
            assert names == {"web01", "web02", "web03"}
        finally:
            path.unlink()

    @pytest.mark.asyncio
    async def test_ungrouped_hosts(self) -> None:
        """Test parsing ungrouped hosts."""
        content = """
# Ungrouped hosts
standalone1
standalone2 ansible_host=10.0.0.1

[webservers]
web1
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            hosts = await parse_ansible_inventory(path)
            assert len(hosts) == 3

            standalone1 = next(h for h in hosts if h.name == "standalone1")
            assert "ansible" in standalone1.tags
            assert not any(t.startswith("ansible:") for t in standalone1.tags if t != "ansible")
        finally:
            path.unlink()


class TestHostDataClass:
    """Tests for HostData dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        host = HostData(name="test")
        assert host.hostname is None
        assert host.port == 22
        assert host.username is None
        assert host.private_key is None
        assert host.jump_host is None
        assert host.tags == []
        assert host.source is None

    def test_with_all_fields(self) -> None:
        """Test with all fields populated."""
        host = HostData(
            name="myhost",
            hostname="192.168.1.1",
            port=2222,
            username="admin",
            private_key="~/.ssh/id_ed25519",
            jump_host="jumpbox",
            tags=["prod", "web"],
            source="ssh-config",
        )
        assert host.name == "myhost"
        assert host.hostname == "192.168.1.1"
        assert host.port == 2222
        assert host.username == "admin"
        assert host.private_key == "~/.ssh/id_ed25519"
        assert host.jump_host == "jumpbox"
        assert host.tags == ["prod", "web"]
        assert host.source == "ssh-config"
