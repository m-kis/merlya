"""Integration tests for hosts import with elevation from actual files."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from merlya.commands.handlers.hosts_io import (
    _import_csv,
    _import_json,
    _import_toml,
    _import_yaml,
)
from merlya.persistence.models import ElevationMethod


@pytest.fixture
def mock_ctx():
    """Create a mock SharedContext."""
    ctx = MagicMock()
    ctx.hosts = MagicMock()
    ctx.hosts.get_by_name = AsyncMock(return_value=None)  # No existing hosts
    ctx.hosts.create = AsyncMock()
    return ctx


@pytest.fixture
def fixtures_dir():
    """Return path to fixtures directory."""
    return Path(__file__).parent / "fixtures" / "import_examples"


class TestTomlImport:
    """Test TOML import with elevation."""

    @pytest.mark.asyncio
    async def test_import_toml_with_elevation(self, mock_ctx, fixtures_dir):
        """Test importing TOML file with elevation config."""
        toml_file = fixtures_dir / "hosts_with_elevation.toml"
        content = toml_file.read_text()

        imported, errors = await _import_toml(mock_ctx, content)

        assert imported == 3
        assert len(errors) == 0

        # Verify create was called with correct elevation
        calls = mock_ctx.hosts.create.call_args_list
        assert len(calls) == 3

        # Check test-web01 has sudo_password
        hosts_created = {call.args[0].name: call.args[0] for call in calls}

        web01 = hosts_created["test-web01"]
        assert web01.elevation_method == ElevationMethod.SUDO_PASSWORD
        assert web01.elevation_user == "root"

        db01 = hosts_created["test-db01"]
        assert db01.elevation_method == ElevationMethod.SUDO

        bastion = hosts_created["test-bastion"]
        assert bastion.elevation_method == ElevationMethod.NONE


class TestYamlImport:
    """Test YAML import with elevation."""

    @pytest.mark.asyncio
    async def test_import_yaml_with_elevation(self, mock_ctx, fixtures_dir):
        """Test importing YAML file with elevation config."""
        yaml_file = fixtures_dir / "hosts_with_elevation.yaml"
        content = yaml_file.read_text()

        imported, errors = await _import_yaml(mock_ctx, content)

        assert imported == 3
        assert len(errors) == 0

        calls = mock_ctx.hosts.create.call_args_list
        hosts_created = {call.args[0].name: call.args[0] for call in calls}

        app01 = hosts_created["test-app01"]
        assert app01.elevation_method == ElevationMethod.SUDO_PASSWORD

        app02 = hosts_created["test-app02"]
        assert app02.elevation_method == ElevationMethod.DOAS

        legacy = hosts_created["test-legacy"]
        assert legacy.elevation_method == ElevationMethod.SU


class TestCsvImport:
    """Test CSV import with elevation."""

    @pytest.mark.asyncio
    async def test_import_csv_with_elevation(self, mock_ctx, fixtures_dir):
        """Test importing CSV file with elevation config."""
        csv_file = fixtures_dir / "hosts_with_elevation.csv"
        content = csv_file.read_text()

        imported, errors = await _import_csv(mock_ctx, content)

        assert imported == 3
        assert len(errors) == 0

        calls = mock_ctx.hosts.create.call_args_list
        hosts_created = {call.args[0].name: call.args[0] for call in calls}

        worker01 = hosts_created["test-worker01"]
        assert worker01.elevation_method == ElevationMethod.SUDO_PASSWORD
        assert worker01.elevation_user == "root"

        worker02 = hosts_created["test-worker02"]
        assert worker02.elevation_method == ElevationMethod.SUDO

        monitor = hosts_created["test-monitor"]
        assert monitor.elevation_method == ElevationMethod.NONE


class TestJsonImport:
    """Test JSON import with elevation."""

    @pytest.mark.asyncio
    async def test_import_json_with_elevation(self, mock_ctx, fixtures_dir):
        """Test importing JSON file with elevation config."""
        json_file = fixtures_dir / "hosts_with_elevation.json"
        content = json_file.read_text()

        imported, errors = await _import_json(mock_ctx, content)

        assert imported == 2
        assert len(errors) == 0

        calls = mock_ctx.hosts.create.call_args_list
        hosts_created = {call.args[0].name: call.args[0] for call in calls}

        cache01 = hosts_created["test-cache01"]
        assert cache01.elevation_method == ElevationMethod.SUDO_PASSWORD
        assert cache01.elevation_user == "root"

        cache02 = hosts_created["test-cache02"]
        assert cache02.elevation_method == ElevationMethod.SUDO
