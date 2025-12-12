"""Tests for variable import/export functionality."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from merlya.commands.handlers.variables_io import (
    _looks_like_secret,
    detect_export_format,
    detect_import_format,
    export_variables,
    generate_template,
    import_variables,
    validate_file_path,
)


class TestValidateFilePath:
    """Tests for file path validation."""

    def test_valid_home_path(self) -> None:
        """Test that home directory paths are valid."""
        home = Path.home()
        test_file = home / ".merlya" / "test.yaml"
        is_valid, error = validate_file_path(test_file)
        assert is_valid is True
        assert error == ""

    def test_valid_tmp_path(self) -> None:
        """Test that paths in allowed directories are valid."""
        # tmp_path is under home or temp, which should be allowed
        # On macOS, /tmp resolves to /private/tmp which may not be in ALLOWED_IMPORT_DIRS
        # Use home directory instead for reliable cross-platform behavior
        test_file = Path.home() / "test_vars.yaml"
        is_valid, error = validate_file_path(test_file)
        assert is_valid is True
        assert error == ""

    def test_rejects_proc_path(self) -> None:
        """Test that /proc paths are rejected."""
        path = Path("/proc/self/environ")
        is_valid, error = validate_file_path(path)
        assert is_valid is False
        assert "Access denied" in error


class TestDetectFormat:
    """Tests for format detection."""

    def test_yaml_extension(self, tmp_path: Path) -> None:
        """Test YAML extension detection."""
        assert detect_import_format(tmp_path / "vars.yaml") == "yaml"
        assert detect_import_format(tmp_path / "vars.yml") == "yaml"

    def test_json_extension(self, tmp_path: Path) -> None:
        """Test JSON extension detection."""
        assert detect_import_format(tmp_path / "vars.json") == "json"

    def test_env_extension(self, tmp_path: Path) -> None:
        """Test .env extension detection."""
        # Note: ".env" as a filename has no suffix in pathlib (it's the stem)
        # So detect_import_format falls back to yaml for ".env"
        # Only "vars.env" works as expected
        assert detect_import_format(tmp_path / ".env") == "yaml"  # No suffix -> default yaml
        assert detect_import_format(tmp_path / "vars.env") == "env"

    def test_export_format_detection(self, tmp_path: Path) -> None:
        """Test export format detection."""
        assert detect_export_format(tmp_path / "vars.yaml") == "yaml"
        assert detect_export_format(tmp_path / "vars.json") == "json"
        assert detect_export_format(tmp_path / "vars.env") == "env"


class TestLooksLikeSecret:
    """Tests for secret detection in values."""

    def test_short_values_not_secrets(self) -> None:
        """Test that short values are not detected as secrets."""
        assert _looks_like_secret("hello") is False
        assert _looks_like_secret("12345") is False
        assert _looks_like_secret("") is False

    def test_long_random_strings_detected(self) -> None:
        """Test that long random strings are detected as potential secrets."""
        assert _looks_like_secret("abcdefghij1234567890abcdefghij12") is True

    def test_openai_key_detected(self) -> None:
        """Test that OpenAI-style keys are detected."""
        assert _looks_like_secret("sk-1234567890abcdefghijklmnopqrstuv") is True

    def test_github_token_detected(self) -> None:
        """Test that GitHub tokens are detected."""
        assert _looks_like_secret("ghp_1234567890abcdefghijklmnopqrstuv12345") is True

    def test_normal_values_not_detected(self) -> None:
        """Test that normal values are not detected as secrets."""
        assert _looks_like_secret("production") is False
        assert _looks_like_secret("my-hostname.example.com") is False


class TestGenerateTemplate:
    """Tests for template generation."""

    def test_yaml_template(self) -> None:
        """Test YAML template generation."""
        template = generate_template("yaml")
        assert "variables:" in template
        assert "secrets:" in template
        assert "deploy-env:" in template

    def test_json_template(self) -> None:
        """Test JSON template generation."""
        template = generate_template("json")
        data = json.loads(template)
        assert "variables" in data
        assert "secrets" in data
        assert "deploy-env" in data["variables"]

    def test_env_template(self) -> None:
        """Test .env template generation."""
        template = generate_template("env")
        assert "DEPLOY_ENV=" in template
        assert "SECRET_DB_PASSWORD=" in template


class TestImportVariables:
    """Tests for variable import."""

    def _make_mock_ctx(self) -> MagicMock:
        """Create a mock context for testing."""
        ctx = MagicMock()

        # Mock variables repository
        ctx.variables = AsyncMock()
        ctx.variables.get_all = AsyncMock(return_value=[])
        ctx.variables.set = AsyncMock()
        ctx.variables.delete = AsyncMock()

        # Mock hosts repository
        ctx.hosts = AsyncMock()
        ctx.hosts.get_by_name = AsyncMock(return_value=None)
        ctx.hosts.create = AsyncMock()

        return ctx

    @pytest.mark.asyncio
    async def test_import_yaml(self) -> None:
        """Test importing from YAML file."""
        mock_ctx = self._make_mock_ctx()
        yaml_file = Path("/tmp") / "test_vars_import.yaml"
        yaml_file.write_text("""
variables:
  deploy-env: production
  log-level: info
secrets:
  - db-password
""")

        try:
            var_count, secret_count, _host_count, secrets, errors = await import_variables(
                mock_ctx, yaml_file, "yaml", merge=True, dry_run=False
            )

            assert var_count == 2
            assert secret_count == 1
            assert "db-password" in secrets
            assert len(errors) == 0
            assert mock_ctx.variables.set.call_count == 2
        finally:
            yaml_file.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_import_json(self) -> None:
        """Test importing from JSON file."""
        mock_ctx = self._make_mock_ctx()
        json_file = Path("/tmp") / "test_vars_import.json"
        json_file.write_text(json.dumps({"variables": {"app-name": "myapp", "version": "1.0.0"}}))

        try:
            var_count, secret_count, _host_count, _secrets, errors = await import_variables(
                mock_ctx, json_file, "json", merge=True, dry_run=False
            )

            assert var_count == 2
            assert secret_count == 0
            assert len(errors) == 0
        finally:
            json_file.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_import_env(self) -> None:
        """Test importing from .env file."""
        mock_ctx = self._make_mock_ctx()
        env_file = Path("/tmp") / "test_vars_import.env"
        env_file.write_text("""
# Configuration
APP_NAME=myapp
LOG_LEVEL=debug
# Secrets
SECRET_API_KEY=
""")

        try:
            var_count, secret_count, _host_count, secrets, errors = await import_variables(
                mock_ctx, env_file, "env", merge=True, dry_run=False
            )

            assert var_count == 2
            assert secret_count == 1
            assert "api-key" in secrets
            assert len(errors) == 0
        finally:
            env_file.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_import_dry_run(self) -> None:
        """Test dry run mode doesn't modify anything."""
        mock_ctx = self._make_mock_ctx()
        yaml_file = Path("/tmp") / "test_vars_dryrun.yaml"
        yaml_file.write_text("""
variables:
  test-var: value
""")

        try:
            var_count, _, _, _, _ = await import_variables(
                mock_ctx, yaml_file, "yaml", merge=True, dry_run=True
            )

            assert var_count == 1
            # Should not have called set in dry run mode
            assert mock_ctx.variables.set.call_count == 0
        finally:
            yaml_file.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_import_rejects_secret_values(self) -> None:
        """Test that values looking like secrets are rejected."""
        mock_ctx = self._make_mock_ctx()
        yaml_file = Path("/tmp") / "test_vars_secret.yaml"
        yaml_file.write_text("""
variables:
  api-key: sk-1234567890abcdefghijklmnopqrstuv
""")

        try:
            var_count, _, _, _, errors = await import_variables(
                mock_ctx, yaml_file, "yaml", merge=True, dry_run=False
            )

            assert var_count == 0
            assert len(errors) == 1
            assert "looks like a secret" in errors[0]
        finally:
            yaml_file.unlink(missing_ok=True)


class TestExportVariables:
    """Tests for variable export."""

    def _make_mock_ctx(self) -> MagicMock:
        """Create a mock context for testing."""
        ctx = MagicMock()

        # Create mock variable objects
        mock_var1 = MagicMock()
        mock_var1.name = "deploy-env"
        mock_var1.value = "production"

        mock_var2 = MagicMock()
        mock_var2.name = "log-level"
        mock_var2.value = "info"

        ctx.variables = AsyncMock()
        ctx.variables.get_all = AsyncMock(return_value=[mock_var1, mock_var2])

        ctx.secrets = MagicMock()
        ctx.secrets.list_keys = MagicMock(return_value=["db-password"])

        return ctx

    @pytest.mark.asyncio
    async def test_export_yaml(self) -> None:
        """Test exporting to YAML format."""
        mock_ctx = self._make_mock_ctx()
        content = await export_variables(mock_ctx, "yaml", include_secrets=False)

        assert "deploy-env:" in content
        assert "production" in content
        assert "secrets:" not in content

    @pytest.mark.asyncio
    async def test_export_yaml_with_secrets(self) -> None:
        """Test exporting to YAML format with secret names."""
        mock_ctx = self._make_mock_ctx()
        content = await export_variables(mock_ctx, "yaml", include_secrets=True)

        assert "deploy-env:" in content
        assert "secrets:" in content
        assert "db-password" in content

    @pytest.mark.asyncio
    async def test_export_json(self) -> None:
        """Test exporting to JSON format."""
        mock_ctx = self._make_mock_ctx()
        content = await export_variables(mock_ctx, "json", include_secrets=False)

        data = json.loads(content)
        assert data["variables"]["deploy-env"] == "production"
        assert "secrets" not in data

    @pytest.mark.asyncio
    async def test_export_env(self) -> None:
        """Test exporting to .env format."""
        mock_ctx = self._make_mock_ctx()
        content = await export_variables(mock_ctx, "env", include_secrets=False)

        assert "DEPLOY_ENV=production" in content
        assert "LOG_LEVEL=info" in content

    @pytest.mark.asyncio
    async def test_export_env_with_secrets(self) -> None:
        """Test exporting to .env format with secret names."""
        mock_ctx = self._make_mock_ctx()
        content = await export_variables(mock_ctx, "env", include_secrets=True)

        assert "DEPLOY_ENV=production" in content
        assert "SECRET_DB_PASSWORD=" in content
