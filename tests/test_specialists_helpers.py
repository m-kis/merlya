"""Tests for the specialist agent elevation helpers."""

from merlya.agent.specialists.elevation import _strip_elevation_prefix


class TestStripElevationPrefix:
    """Tests for _strip_elevation_prefix()."""

    # ------------------------------------------------------------------
    # sudo -S (uppercase S)
    # ------------------------------------------------------------------

    def test_strips_sudo_s(self) -> None:
        assert _strip_elevation_prefix("sudo -S apt update") == "apt update"

    def test_strips_sudo_s_lowercase(self) -> None:
        assert _strip_elevation_prefix("sudo -s apt update") == "apt update"

    def test_strips_sudo_s_systemctl(self) -> None:
        assert _strip_elevation_prefix("sudo -S systemctl restart nginx") == "systemctl restart nginx"

    # ------------------------------------------------------------------
    # Plain sudo (no -S)
    # ------------------------------------------------------------------

    def test_strips_plain_sudo(self) -> None:
        assert _strip_elevation_prefix("sudo apt update") == "apt update"

    def test_strips_plain_sudo_cat(self) -> None:
        assert _strip_elevation_prefix("sudo cat /etc/shadow") == "cat /etc/shadow"

    # ------------------------------------------------------------------
    # doas
    # ------------------------------------------------------------------

    def test_strips_doas(self) -> None:
        assert _strip_elevation_prefix("doas apt update") == "apt update"

    def test_strips_doas_systemctl(self) -> None:
        assert _strip_elevation_prefix("doas systemctl restart nginx") == "systemctl restart nginx"

    # ------------------------------------------------------------------
    # su -c
    # ------------------------------------------------------------------

    def test_strips_su_c_single_quotes(self) -> None:
        assert _strip_elevation_prefix("su -c 'apt update'") == "apt update"

    def test_strips_su_c_double_quotes(self) -> None:
        assert _strip_elevation_prefix('su -c "apt update"') == "apt update"

    def test_strips_su_c_without_quotes(self) -> None:
        assert _strip_elevation_prefix("su -c apt update") == "apt update"

    # ------------------------------------------------------------------
    # No prefix — should be unchanged
    # ------------------------------------------------------------------

    def test_plain_command_unchanged(self) -> None:
        assert _strip_elevation_prefix("apt update") == "apt update"

    def test_systemctl_unchanged(self) -> None:
        assert _strip_elevation_prefix("systemctl restart nginx") == "systemctl restart nginx"

    def test_cat_unchanged(self) -> None:
        assert _strip_elevation_prefix("cat /etc/passwd") == "cat /etc/passwd"

    # ------------------------------------------------------------------
    # Mid-command sudo — must NOT be stripped (only strips from START)
    # ------------------------------------------------------------------

    def test_apt_install_sudo_unchanged(self) -> None:
        """'apt install sudo' should NOT have sudo stripped — it's a package name."""
        assert _strip_elevation_prefix("apt install sudo") == "apt install sudo"

    def test_echo_sudo_in_text_unchanged(self) -> None:
        """echo 'use sudo' should NOT have sudo stripped."""
        assert _strip_elevation_prefix("echo 'use sudo'") == "echo 'use sudo'"

    def test_grep_sudo_log_unchanged(self) -> None:
        """grep through sudo log should NOT be modified."""
        assert _strip_elevation_prefix("grep sudo /var/log/auth.log") == "grep sudo /var/log/auth.log"

    # ------------------------------------------------------------------
    # Chained commands — only the leading prefix is stripped
    # ------------------------------------------------------------------

    def test_strips_leading_prefix_only_in_chain(self) -> None:
        """
        'sudo -S apt update && sudo -S systemctl restart' → leading prefix stripped,
        the rest of the chain is preserved.
        """
        result = _strip_elevation_prefix("sudo -S apt update && sudo -S systemctl restart nginx")
        assert result == "apt update && sudo -S systemctl restart nginx"

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_empty_string(self) -> None:
        assert _strip_elevation_prefix("") == ""

    def test_whitespace_only(self) -> None:
        assert _strip_elevation_prefix("   ") == ""

    def test_sudo_only(self) -> None:
        """'sudo' with no real command after it — returned as-is (not a real case in practice)."""
        # The trailing space is stripped before the regex runs, so "sudo" alone doesn't match.
        result = _strip_elevation_prefix("sudo ")
        assert result in ("", "sudo")  # either is acceptable
