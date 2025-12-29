"""Tests for hosts import/export with elevation configuration."""

from merlya.commands.handlers.hosts_io import (
    create_host_from_dict,
    host_to_dict,
    serialize_hosts,
)
from merlya.persistence.models import ElevationMethod, Host


class TestCreateHostFromDict:
    """Test create_host_from_dict with elevation fields."""

    def test_elevation_method_sudo_password(self):
        """Test creating host with sudo_password elevation."""
        data = {
            "name": "test-host",
            "hostname": "192.168.1.10",
            "elevation_method": "sudo_password",
            "elevation_user": "root",
        }
        host = create_host_from_dict(data)

        assert host.name == "test-host"
        assert host.elevation_method == ElevationMethod.SUDO_PASSWORD
        assert host.elevation_user == "root"

    def test_elevation_method_sudo(self):
        """Test creating host with sudo (NOPASSWD) elevation."""
        data = {
            "name": "test-host",
            "hostname": "192.168.1.10",
            "elevation_method": "sudo",
        }
        host = create_host_from_dict(data)

        assert host.elevation_method == ElevationMethod.SUDO
        assert host.elevation_user == "root"  # Default

    def test_elevation_method_doas(self):
        """Test creating host with doas elevation."""
        data = {
            "name": "bsd-host",
            "hostname": "192.168.1.20",
            "elevation_method": "doas",
        }
        host = create_host_from_dict(data)

        assert host.elevation_method == ElevationMethod.DOAS

    def test_elevation_method_su(self):
        """Test creating host with su elevation."""
        data = {
            "name": "legacy-host",
            "hostname": "192.168.1.30",
            "elevation_method": "su",
        }
        host = create_host_from_dict(data)

        assert host.elevation_method == ElevationMethod.SU

    def test_elevation_method_none_default(self):
        """Test that elevation_method defaults to NONE."""
        data = {
            "name": "test-host",
            "hostname": "192.168.1.10",
        }
        host = create_host_from_dict(data)

        assert host.elevation_method == ElevationMethod.NONE

    def test_elevation_method_none_explicit(self):
        """Test explicit none elevation."""
        data = {
            "name": "test-host",
            "hostname": "192.168.1.10",
            "elevation_method": "none",
        }
        host = create_host_from_dict(data)

        assert host.elevation_method == ElevationMethod.NONE

    def test_elevation_user_custom(self):
        """Test custom elevation_user."""
        data = {
            "name": "test-host",
            "hostname": "192.168.1.10",
            "elevation_method": "sudo_password",
            "elevation_user": "admin",
        }
        host = create_host_from_dict(data)

        assert host.elevation_user == "admin"

    def test_elevation_alias(self):
        """Test 'elevation' alias for 'elevation_method'."""
        data = {
            "name": "test-host",
            "hostname": "192.168.1.10",
            "elevation": "sudo_password",  # Using alias
        }
        host = create_host_from_dict(data)

        assert host.elevation_method == ElevationMethod.SUDO_PASSWORD

    def test_elevation_method_case_insensitive(self):
        """Test case insensitive elevation method."""
        data = {
            "name": "test-host",
            "hostname": "192.168.1.10",
            "elevation_method": "SUDO_PASSWORD",
        }
        host = create_host_from_dict(data)

        assert host.elevation_method == ElevationMethod.SUDO_PASSWORD

    def test_elevation_method_hyphen_variant(self):
        """Test hyphenated elevation method (sudo-password)."""
        data = {
            "name": "test-host",
            "hostname": "192.168.1.10",
            "elevation_method": "sudo-password",
        }
        host = create_host_from_dict(data)

        assert host.elevation_method == ElevationMethod.SUDO_PASSWORD


class TestHostToDict:
    """Test host_to_dict with elevation fields."""

    def test_export_elevation_method(self):
        """Test exporting host with elevation_method."""
        host = Host(
            name="test-host",
            hostname="192.168.1.10",
            elevation_method=ElevationMethod.SUDO_PASSWORD,
            elevation_user="root",
        )
        result = host_to_dict(host)

        assert result["elevation_method"] == "sudo_password"
        # elevation_user not exported if default (root)
        assert "elevation_user" not in result

    def test_export_elevation_user_non_default(self):
        """Test exporting host with non-default elevation_user."""
        host = Host(
            name="test-host",
            hostname="192.168.1.10",
            elevation_method=ElevationMethod.SUDO_PASSWORD,
            elevation_user="admin",
        )
        result = host_to_dict(host)

        assert result["elevation_method"] == "sudo_password"
        assert result["elevation_user"] == "admin"

    def test_export_no_elevation(self):
        """Test exporting host without elevation."""
        host = Host(
            name="test-host",
            hostname="192.168.1.10",
            elevation_method=ElevationMethod.NONE,
        )
        result = host_to_dict(host)

        assert "elevation_method" not in result
        assert "elevation_user" not in result


class TestSerializeHosts:
    """Test serialize_hosts with elevation fields."""

    def test_csv_includes_elevation_columns(self):
        """Test CSV serialization includes elevation columns."""
        data = [
            {
                "name": "test-host",
                "hostname": "192.168.1.10",
                "port": 22,
                "elevation_method": "sudo_password",
                "elevation_user": "admin",
            }
        ]
        csv_output = serialize_hosts(data, "csv")

        # Check header includes elevation fields
        assert "elevation_method" in csv_output
        assert "elevation_user" in csv_output
        # Check values are present
        assert "sudo_password" in csv_output
        assert "admin" in csv_output

    def test_json_includes_elevation(self):
        """Test JSON serialization includes elevation."""
        data = [
            {
                "name": "test-host",
                "hostname": "192.168.1.10",
                "elevation_method": "sudo",
            }
        ]
        json_output = serialize_hosts(data, "json")

        assert '"elevation_method": "sudo"' in json_output

    def test_yaml_includes_elevation(self):
        """Test YAML serialization includes elevation."""
        data = [
            {
                "name": "test-host",
                "hostname": "192.168.1.10",
                "elevation_method": "doas_password",
            }
        ]
        yaml_output = serialize_hosts(data, "yaml")

        assert "elevation_method: doas_password" in yaml_output


class TestRoundTrip:
    """Test import/export round trip preserves elevation."""

    def test_roundtrip_elevation(self):
        """Test that elevation config survives import/export."""
        # Create host with elevation
        original = Host(
            name="roundtrip-test",
            hostname="192.168.1.100",
            port=22,
            username="testuser",
            elevation_method=ElevationMethod.SUDO_PASSWORD,
            elevation_user="admin",
            tags=["test"],
        )

        # Export to dict
        exported = host_to_dict(original)

        # Import back
        imported = create_host_from_dict(exported)

        # Verify elevation preserved
        assert imported.elevation_method == original.elevation_method
        assert imported.elevation_user == original.elevation_user
