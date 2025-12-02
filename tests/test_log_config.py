"""
Tests for log configuration.

Tests the LogConfig class and log management utilities.
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from merlya.utils.log_config import (
    LogConfig,
    LogLevel,
    get_log_config,
    load_log_config,
    reset_log_config,
    save_log_config,
)


@pytest.fixture(autouse=True)
def reset_config():
    """Reset cached config before each test."""
    reset_log_config()
    yield
    reset_log_config()


class TestLogLevel:
    """Tests for LogLevel enum."""

    def test_valid_levels(self):
        """Test valid log levels."""
        assert LogLevel.from_string("DEBUG") == LogLevel.DEBUG
        assert LogLevel.from_string("debug") == LogLevel.DEBUG
        assert LogLevel.from_string("INFO") == LogLevel.INFO
        assert LogLevel.from_string("WARNING") == LogLevel.WARNING
        assert LogLevel.from_string("ERROR") == LogLevel.ERROR
        assert LogLevel.from_string("CRITICAL") == LogLevel.CRITICAL

    def test_level_aliases(self):
        """Test log level aliases."""
        assert LogLevel.from_string("WARN") == LogLevel.WARNING
        assert LogLevel.from_string("ERR") == LogLevel.ERROR
        assert LogLevel.from_string("CRIT") == LogLevel.CRITICAL
        assert LogLevel.from_string("FATAL") == LogLevel.CRITICAL

    def test_invalid_level(self):
        """Test invalid log level raises error."""
        with pytest.raises(ValueError, match="Unknown log level"):
            LogLevel.from_string("INVALID")


class TestLogConfig:
    """Tests for LogConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = LogConfig()

        assert config.app_log_name == "app.log"
        assert config.file_level == "DEBUG"
        assert config.console_level == "WARNING"
        assert config.rotation_size == "10 MB"
        assert config.rotation_strategy == "size"
        assert config.retention == "1 week"
        assert config.max_files == 10
        assert config.compression == "gz"
        assert config.json_logs is False
        assert config.console_enabled is False

    def test_default_log_dir(self):
        """Test default log directory is set."""
        config = LogConfig()
        expected = str(Path.home() / ".merlya" / "logs")
        assert config.log_dir == expected

    def test_custom_values(self):
        """Test custom configuration values."""
        config = LogConfig(
            log_dir="/tmp/logs",
            app_log_name="custom.log",
            file_level="INFO",
            console_level="ERROR",
            rotation_size="20 MB",
            max_files=5,
        )

        assert config.log_dir == "/tmp/logs"
        assert config.app_log_name == "custom.log"
        assert config.file_level == "INFO"
        assert config.console_level == "ERROR"
        assert config.rotation_size == "20 MB"
        assert config.max_files == 5

    def test_log_path_property(self):
        """Test log_path property."""
        config = LogConfig(log_dir="/tmp/logs", app_log_name="test.log")
        assert config.log_path == Path("/tmp/logs/test.log")

    def test_invalid_console_level(self):
        """Test invalid console level raises error."""
        with pytest.raises(ValueError, match="Invalid console_level"):
            LogConfig(console_level="INVALID")

    def test_invalid_file_level(self):
        """Test invalid file level raises error."""
        with pytest.raises(ValueError, match="Invalid file_level"):
            LogConfig(file_level="INVALID")

    def test_invalid_rotation_strategy(self):
        """Test invalid rotation strategy raises error."""
        with pytest.raises(ValueError, match="rotation_strategy must be one of"):
            LogConfig(rotation_strategy="invalid")

    def test_invalid_compression(self):
        """Test invalid compression raises error."""
        with pytest.raises(ValueError, match="compression must be one of"):
            LogConfig(compression="bz2")

    def test_invalid_rotation_size_format(self):
        """Test invalid rotation size format raises error."""
        with pytest.raises(ValueError, match="Invalid size format"):
            LogConfig(rotation_size="10MB")  # Missing space

    def test_invalid_rotation_size_value(self):
        """Test invalid rotation size value raises error."""
        with pytest.raises(ValueError, match="Invalid size value"):
            LogConfig(rotation_size="abc MB")

    def test_invalid_rotation_size_negative(self):
        """Test negative rotation size raises error."""
        with pytest.raises(ValueError, match="Invalid size value"):
            LogConfig(rotation_size="-10 MB")

    def test_invalid_rotation_size_unit(self):
        """Test invalid rotation size unit raises error."""
        with pytest.raises(ValueError, match="Invalid size unit"):
            LogConfig(rotation_size="10 XB")

    def test_invalid_max_files(self):
        """Test invalid max_files raises error."""
        with pytest.raises(ValueError, match="max_files must be >= 1"):
            LogConfig(max_files=0)

    def test_to_dict(self):
        """Test conversion to dictionary."""
        config = LogConfig()
        d = config.to_dict()

        assert "log_dir" in d
        assert "app_log_name" in d
        assert "file_level" in d
        assert "console_level" in d
        assert "rotation_size" in d
        assert d["app_log_name"] == "app.log"

    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "log_dir": "/custom/logs",
            "app_log_name": "custom.log",
            "file_level": "INFO",
        }
        config = LogConfig.from_dict(data)

        assert config.log_dir == "/custom/logs"
        assert config.app_log_name == "custom.log"
        assert config.file_level == "INFO"
        # Defaults should still apply
        assert config.console_level == "WARNING"

    def test_from_dict_ignores_unknown_fields(self):
        """Test that from_dict ignores unknown fields."""
        data = {
            "log_dir": "/custom/logs",
            "unknown_field": "value",
        }
        config = LogConfig.from_dict(data)
        assert config.log_dir == "/custom/logs"
        assert not hasattr(config, "unknown_field")


class TestLogConfigPersistence:
    """Tests for config file persistence."""

    def test_save_and_load_config(self):
        """Test saving and loading configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "log_config.json"

            with patch.object(
                __import__("merlya.utils.log_config", fromlist=["CONFIG_FILE"]),
                "CONFIG_FILE",
                config_file,
            ):
                from merlya.utils import log_config
                original_config_file = log_config.CONFIG_FILE
                log_config.CONFIG_FILE = config_file

                try:
                    config = LogConfig(
                        log_dir="/custom/logs",
                        file_level="INFO",
                        max_files=5,
                    )

                    # Save
                    assert save_log_config(config) is True
                    assert config_file.exists()

                    # Load
                    reset_log_config()
                    loaded = load_log_config()

                    assert loaded.log_dir == "/custom/logs"
                    assert loaded.file_level == "INFO"
                    assert loaded.max_files == 5
                finally:
                    log_config.CONFIG_FILE = original_config_file

    def test_load_with_env_override(self):
        """Test environment variable overrides."""
        with patch.dict(os.environ, {
            "MERLYA_LOG_LEVEL": "ERROR",
            "MERLYA_LOG_DIR": "/env/logs",
            "MERLYA_LOG_MAX_FILES": "20",
            "MERLYA_LOG_JSON": "true",
        }):
            reset_log_config()
            config = load_log_config()

            assert config.console_level == "ERROR"
            assert config.log_dir == "/env/logs"
            assert config.max_files == 20
            assert config.json_logs is True

    def test_load_nonexistent_config_uses_defaults(self):
        """Test loading from nonexistent file uses defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "nonexistent.json"

            from merlya.utils import log_config
            original_config_file = log_config.CONFIG_FILE
            log_config.CONFIG_FILE = config_file

            try:
                reset_log_config()
                config = load_log_config()

                # Should have default values
                assert config.app_log_name == "app.log"
                assert config.file_level == "DEBUG"
            finally:
                log_config.CONFIG_FILE = original_config_file


class TestLogConfigCaching:
    """Tests for configuration caching."""

    def test_get_log_config_returns_cached(self):
        """Test that get_log_config returns cached instance."""
        config1 = get_log_config()
        config2 = get_log_config()

        assert config1 is config2

    def test_reset_clears_cache(self):
        """Test that reset_log_config clears the cache."""
        config1 = get_log_config()
        reset_log_config()
        config2 = get_log_config()

        assert config1 is not config2


class TestEnsureLogDir:
    """Tests for log directory creation."""

    def test_ensure_log_dir_creates_directory(self):
        """Test that ensure_log_dir creates the directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "logs" / "subdir"
            config = LogConfig(log_dir=str(log_dir))

            assert not log_dir.exists()
            result = config.ensure_log_dir()

            assert log_dir.exists()
            assert result == log_dir

    def test_ensure_log_dir_existing_directory(self):
        """Test ensure_log_dir with existing directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = LogConfig(log_dir=tmpdir)
            result = config.ensure_log_dir()

            assert result == Path(tmpdir)
