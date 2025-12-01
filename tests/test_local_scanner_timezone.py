"""
Tests for LocalScanner timezone handling.

Verifies:
- Naive timestamps are interpreted using configured local timezone
- UTC-aware timestamps are handled correctly
- TTL calculation works correctly for both cases
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from merlya.context.local_scanner.scanner import LocalScanner


class TestLocalScannerTimezoneHandling:
    """Tests for naive timestamp handling with timezone configuration."""

    def test_utc_aware_timestamp_ttl_valid(self):
        """Test that UTC-aware timestamps are handled correctly for valid TTL."""
        # Create a context with a UTC-aware timestamp 1 hour ago
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

        mock_repo = MagicMock()
        mock_repo.get_local_context.return_value = {
            "_metadata": {"scanned_at": one_hour_ago.isoformat()},
            "os_info": {"platform": "test"},
        }

        scanner = LocalScanner(mock_repo)

        # With 12h TTL, cache should still be valid (1h < 12h)
        with patch.object(scanner, "scan_all") as mock_scan:
            mock_scan.return_value = MagicMock(to_dict=lambda: {})
            scanner.get_or_scan(ttl_hours=12)
            # scan_all should NOT be called since cache is valid
            mock_scan.assert_not_called()

    def test_utc_aware_timestamp_expired(self):
        """Test that expired UTC-aware timestamps trigger rescan."""
        # Create a context with a UTC-aware timestamp 24 hours ago
        one_day_ago = datetime.now(timezone.utc) - timedelta(hours=24)

        mock_repo = MagicMock()
        mock_repo.get_local_context.return_value = {
            "_metadata": {"scanned_at": one_day_ago.isoformat()},
            "os_info": {"platform": "test"},
        }

        scanner = LocalScanner(mock_repo)

        # With 12h TTL, cache should be expired (24h > 12h)
        with patch.object(scanner, "scan_all") as mock_scan:
            from merlya.context.local_scanner.models import LocalContext
            mock_scan.return_value = LocalContext()
            scanner.get_or_scan(ttl_hours=12)
            # scan_all SHOULD be called since cache is expired
            mock_scan.assert_called_once()

    def test_naive_timestamp_with_local_timezone_config(self):
        """Test naive timestamp interpreted using configured local timezone."""
        # Create a naive timestamp (no timezone info) representing "1 hour ago" in EST
        est_tz = ZoneInfo("America/New_York")
        now_utc = datetime.now(timezone.utc)
        now_est = now_utc.astimezone(est_tz)
        one_hour_ago_est = now_est - timedelta(hours=1)

        # Store as naive timestamp (simulating legacy data stored in local time)
        naive_timestamp = one_hour_ago_est.replace(tzinfo=None).isoformat()

        mock_repo = MagicMock()
        mock_repo.get_local_context.return_value = {
            "_metadata": {"scanned_at": naive_timestamp},
            "os_info": {"platform": "test"},
        }

        scanner = LocalScanner(mock_repo)

        # Mock get_local_timezone to return EST
        with patch("merlya.context.local_scanner.scanner.get_local_timezone") as mock_tz:
            mock_tz.return_value = est_tz

            with patch.object(scanner, "scan_all") as mock_scan:
                mock_scan.return_value = MagicMock(to_dict=lambda: {})
                # With 12h TTL, cache should be valid (~1h old)
                scanner.get_or_scan(ttl_hours=12)
                # scan_all should NOT be called since cache is valid
                mock_scan.assert_not_called()

    def test_naive_timestamp_wrong_timezone_causes_incorrect_ttl(self):
        """Test that naive timestamp with wrong timezone assumption causes TTL issues.

        This demonstrates the bug: if a naive timestamp was stored in local time (e.g., EST)
        but interpreted as UTC, the age calculation will be off.
        """
        # Simulate: timestamp stored 10 hours ago in EST (UTC-5)
        est_tz = ZoneInfo("America/New_York")
        now_utc = datetime.now(timezone.utc)
        now_est = now_utc.astimezone(est_tz)

        # Create a timestamp 10 hours ago in EST
        ten_hours_ago_est = now_est - timedelta(hours=10)
        naive_timestamp = ten_hours_ago_est.replace(tzinfo=None).isoformat()

        # Test 1: With correct timezone (EST), 10h ago < 12h TTL = valid cache
        mock_repo = MagicMock()
        mock_repo.get_local_context.return_value = {
            "_metadata": {"scanned_at": naive_timestamp},
            "os_info": {"platform": "test"},
        }

        scanner = LocalScanner(mock_repo)

        with patch("merlya.context.local_scanner.scanner.get_local_timezone") as mock_tz:
            mock_tz.return_value = est_tz
            with patch.object(scanner, "scan_all") as mock_scan:
                mock_scan.return_value = MagicMock(to_dict=lambda: {})
                scanner.get_or_scan(ttl_hours=12)
                # Cache should be valid (10h < 12h)
                mock_scan.assert_not_called()

        # Test 2: With wrong timezone (UTC), the age calculation will be different
        # EST is UTC-5, so 10h ago EST = 15h ago UTC (in winter) or 14h ago (summer)
        # This would make it appear expired
        mock_repo2 = MagicMock()
        mock_repo2.get_local_context.return_value = {
            "_metadata": {"scanned_at": naive_timestamp},
            "os_info": {"platform": "test"},
        }

        scanner2 = LocalScanner(mock_repo2)

        with patch("merlya.context.local_scanner.scanner.get_local_timezone") as mock_tz:
            mock_tz.return_value = timezone.utc  # Wrong: treating as UTC
            with patch.object(scanner2, "scan_all") as mock_scan:
                from merlya.context.local_scanner.models import LocalContext
                mock_scan.return_value = LocalContext()
                scanner2.get_or_scan(ttl_hours=12)
                # With UTC assumption, age appears ~15h, so cache is expired
                mock_scan.assert_called_once()

    def test_naive_timestamp_logs_debug_message(self, capsys):
        """Test that naive timestamps emit a debug log."""
        # Create a naive timestamp
        one_hour_ago = datetime.now() - timedelta(hours=1)
        naive_timestamp = one_hour_ago.isoformat()  # No timezone info

        mock_repo = MagicMock()
        mock_repo.get_local_context.return_value = {
            "_metadata": {"scanned_at": naive_timestamp},
            "os_info": {"platform": "test"},
        }

        scanner = LocalScanner(mock_repo)

        # Capture logs by enabling loguru sink to stderr
        from io import StringIO

        from merlya.utils.logger import logger

        # Use a custom sink to capture log output
        log_output = StringIO()
        handler_id = logger.add(log_output, level="DEBUG", format="{message}")

        try:
            with patch("merlya.context.local_scanner.scanner.get_local_timezone") as mock_tz:
                mock_tz.return_value = timezone.utc
                with patch.object(scanner, "scan_all") as mock_scan:
                    mock_scan.return_value = MagicMock(to_dict=lambda: {})
                    scanner.get_or_scan(ttl_hours=24)

            # Check that debug log was emitted
            log_contents = log_output.getvalue()
            assert "Naive timestamp encountered" in log_contents
        finally:
            logger.remove(handler_id)

    def test_different_timezone_offsets(self):
        """Test TTL calculation with various timezone offsets."""
        test_timezones = [
            "America/New_York",  # EST/EDT
            "America/Los_Angeles",  # PST/PDT
            "Europe/London",  # GMT/BST
            "Europe/Paris",  # CET/CEST
            "Asia/Tokyo",  # JST
        ]

        for tz_name in test_timezones:
            tz = ZoneInfo(tz_name)
            now_utc = datetime.now(timezone.utc)
            now_local = now_utc.astimezone(tz)

            # 6 hours ago in local time
            six_hours_ago_local = now_local - timedelta(hours=6)
            naive_timestamp = six_hours_ago_local.replace(tzinfo=None).isoformat()

            mock_repo = MagicMock()
            mock_repo.get_local_context.return_value = {
                "_metadata": {"scanned_at": naive_timestamp},
                "os_info": {"platform": "test"},
            }

            scanner = LocalScanner(mock_repo)

            with patch("merlya.context.local_scanner.scanner.get_local_timezone") as mock_tz:
                mock_tz.return_value = tz
                with patch.object(scanner, "scan_all") as mock_scan:
                    mock_scan.return_value = MagicMock(to_dict=lambda: {})
                    # With 12h TTL, 6h old cache should be valid
                    scanner.get_or_scan(ttl_hours=12)
                    mock_scan.assert_not_called(), f"Failed for timezone {tz_name}"

    def test_positive_offset_timezone(self):
        """Test timezone with positive UTC offset (ahead of UTC)."""
        # Use Tokyo time (UTC+9)
        jst_tz = ZoneInfo("Asia/Tokyo")
        now_utc = datetime.now(timezone.utc)
        now_jst = now_utc.astimezone(jst_tz)

        # Create timestamp 2 hours ago in JST
        two_hours_ago_jst = now_jst - timedelta(hours=2)
        naive_timestamp = two_hours_ago_jst.replace(tzinfo=None).isoformat()

        mock_repo = MagicMock()
        mock_repo.get_local_context.return_value = {
            "_metadata": {"scanned_at": naive_timestamp},
            "os_info": {"platform": "test"},
        }

        scanner = LocalScanner(mock_repo)

        # With correct JST interpretation, should be ~2h old
        with patch("merlya.context.local_scanner.scanner.get_local_timezone") as mock_tz:
            mock_tz.return_value = jst_tz
            with patch.object(scanner, "scan_all") as mock_scan:
                mock_scan.return_value = MagicMock(to_dict=lambda: {})
                scanner.get_or_scan(ttl_hours=12)
                # Cache should be valid (2h < 12h)
                mock_scan.assert_not_called()

        # With UTC interpretation (wrong), timestamp appears to be in the future
        # since JST is +9 hours, a "2 hours ago JST" timestamp looks like "7 hours in the future UTC"
        mock_repo2 = MagicMock()
        mock_repo2.get_local_context.return_value = {
            "_metadata": {"scanned_at": naive_timestamp},
            "os_info": {"platform": "test"},
        }

        scanner2 = LocalScanner(mock_repo2)

        with patch("merlya.context.local_scanner.scanner.get_local_timezone") as mock_tz:
            mock_tz.return_value = timezone.utc  # Wrong timezone
            with patch.object(scanner2, "scan_all") as mock_scan:
                mock_scan.return_value = MagicMock(to_dict=lambda: {})
                # With UTC (wrong), the timestamp will appear to be ~7h in the future
                # which means negative age, should still use cache since age < TTL
                scanner2.get_or_scan(ttl_hours=12)
                # Note: negative age (future timestamp) still < TTL, so cache used
                mock_scan.assert_not_called()


class TestGetLocalTimezoneFunction:
    """Tests for the get_local_timezone helper function."""

    def test_returns_utc_by_default_when_local_unavailable(self):
        """Test fallback to UTC when local timezone can't be determined."""

        from merlya.utils.config import get_local_timezone

        with patch("merlya.utils.config.ConfigManager") as mock_config_cls:
            mock_config = MagicMock()
            mock_config.get.return_value = "local"
            mock_config_cls.return_value = mock_config

            # Mock datetime.now().astimezone().tzinfo to return None
            mock_tzinfo = MagicMock()
            mock_tzinfo.tzinfo = None  # Simulate no local timezone
            mock_datetime_instance = MagicMock()
            mock_datetime_instance.astimezone.return_value = mock_tzinfo

            # Patch datetime in the datetime module (where it's imported from)
            with patch("datetime.datetime") as mock_datetime:
                mock_datetime.now.return_value = mock_datetime_instance
                result = get_local_timezone()
                # Should fall back to UTC when local is unavailable
                assert result == ZoneInfo("UTC")

    def test_returns_configured_timezone(self):
        """Test that configured IANA timezone is returned."""
        from merlya.utils.config import get_local_timezone

        with patch("merlya.utils.config.ConfigManager") as mock_config_cls:
            mock_config = MagicMock()
            mock_config.get.return_value = "America/New_York"
            mock_config_cls.return_value = mock_config

            result = get_local_timezone()
            assert result == ZoneInfo("America/New_York")

    def test_invalid_timezone_falls_back_to_utc(self):
        """Test that invalid timezone name falls back to UTC."""
        from merlya.utils.config import get_local_timezone

        with patch("merlya.utils.config.ConfigManager") as mock_config_cls:
            mock_config = MagicMock()
            mock_config.get.return_value = "Invalid/Timezone"
            mock_config_cls.return_value = mock_config

            result = get_local_timezone()
            # Code returns ZoneInfo("UTC") which is equivalent to but not identical to timezone.utc
            assert result == ZoneInfo("UTC")


class TestConfigManagerTimezone:
    """Tests for ConfigManager timezone property."""

    def test_local_timezone_property_default(self):
        """Test that local_timezone property returns default value."""
        from merlya.utils.config import DEFAULT_LOCAL_TIMEZONE, ConfigManager

        with patch.object(ConfigManager, "_load_config", return_value={}):
            config = ConfigManager()
            assert config.local_timezone == DEFAULT_LOCAL_TIMEZONE

    def test_local_timezone_setter_valid(self):
        """Test setting a valid IANA timezone."""
        from merlya.utils.config import ConfigManager

        with patch.object(ConfigManager, "_load_config", return_value={}):
            with patch.object(ConfigManager, "_save_config"):
                config = ConfigManager()
                config.local_timezone = "Europe/Paris"
                assert config.config["local_timezone"] == "Europe/Paris"

    def test_local_timezone_setter_local(self):
        """Test setting 'local' timezone."""
        from merlya.utils.config import ConfigManager

        with patch.object(ConfigManager, "_load_config", return_value={}):
            with patch.object(ConfigManager, "_save_config"):
                config = ConfigManager()
                config.local_timezone = "local"
                assert config.config["local_timezone"] == "local"

    def test_local_timezone_setter_invalid(self):
        """Test that invalid timezone raises ValueError."""
        from merlya.utils.config import ConfigManager

        with patch.object(ConfigManager, "_load_config", return_value={}):
            config = ConfigManager()
            with pytest.raises(ValueError, match="Invalid timezone"):
                config.local_timezone = "Not/A/Real/Timezone"
