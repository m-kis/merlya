"""Tests for slash command support in merlya run."""

from __future__ import annotations

from merlya.cli.run import (
    BLOCKED_COMMANDS,
    INTERACTIVE_COMMANDS,
    _check_command_allowed,
    _parse_slash_command,
)


class TestParseSlashCommand:
    """Tests for _parse_slash_command function."""

    def test_simple_command(self):
        """Test parsing simple command without subcommand."""
        base, full, args = _parse_slash_command("/health")
        assert base == "health"
        assert full == "health"
        assert args == []

    def test_command_with_subcommand(self):
        """Test parsing command with subcommand."""
        base, full, args = _parse_slash_command("/hosts list")
        assert base == "hosts"
        assert full == "hosts list"
        assert args == []

    def test_command_with_args(self):
        """Test parsing command with arguments."""
        base, full, args = _parse_slash_command("/hosts list --tag=web")
        assert base == "hosts"
        assert full == "hosts list"
        assert args == ["--tag=web"]

    def test_command_with_multiple_args(self):
        """Test parsing command with multiple arguments."""
        base, full, args = _parse_slash_command("/scan myhost --full --json")
        assert base == "scan"
        assert full == "scan myhost"
        assert args == ["--full", "--json"]

    def test_command_lowercase(self):
        """Test that command names are lowercased."""
        base, full, _args = _parse_slash_command("/HOSTS LIST")
        assert base == "hosts"
        assert full == "hosts list"

    def test_empty_command(self):
        """Test parsing empty command."""
        base, full, args = _parse_slash_command("/")
        assert base == ""
        assert full == ""
        assert args == []

    def test_command_with_dash_arg(self):
        """Test that args starting with - are not treated as subcommands."""
        base, full, args = _parse_slash_command("/log -v")
        assert base == "log"
        assert full == "log"
        assert args == ["-v"]


class TestCheckCommandAllowed:
    """Tests for _check_command_allowed function."""

    def test_blocked_exit(self):
        """Test that exit command is blocked."""
        allowed, msg = _check_command_allowed("/exit")
        assert not allowed
        assert "not available in batch mode" in msg

    def test_blocked_quit(self):
        """Test that quit command is blocked."""
        allowed, _ = _check_command_allowed("/quit")
        assert not allowed

    def test_blocked_new(self):
        """Test that new command is blocked."""
        allowed, _ = _check_command_allowed("/new")
        assert not allowed

    def test_blocked_conv(self):
        """Test that conv command is blocked."""
        allowed, _ = _check_command_allowed("/conv list")
        assert not allowed

    def test_interactive_hosts_add(self):
        """Test that hosts add is blocked as interactive."""
        allowed, msg = _check_command_allowed("/hosts add myhost")
        assert not allowed
        assert "requires interactive input" in msg

    def test_interactive_secret_set(self):
        """Test that secret set is blocked as interactive."""
        allowed, msg = _check_command_allowed("/secret set API_KEY")
        assert not allowed
        assert "requires interactive input" in msg

    def test_interactive_ssh_config(self):
        """Test that ssh config is blocked as interactive."""
        allowed, msg = _check_command_allowed("/ssh config myhost")
        assert not allowed
        assert "requires interactive input" in msg

    def test_allowed_health(self):
        """Test that health command is allowed."""
        allowed, msg = _check_command_allowed("/health")
        assert allowed
        assert msg is None

    def test_allowed_hosts_list(self):
        """Test that hosts list is allowed."""
        allowed, msg = _check_command_allowed("/hosts list")
        assert allowed
        assert msg is None

    def test_allowed_scan(self):
        """Test that scan command is allowed."""
        allowed, msg = _check_command_allowed("/scan myhost")
        assert allowed
        assert msg is None

    def test_allowed_model_show(self):
        """Test that model show is allowed."""
        allowed, msg = _check_command_allowed("/model show")
        assert allowed
        assert msg is None

    def test_allowed_hosts_import(self):
        """Test that hosts import is allowed."""
        allowed, msg = _check_command_allowed("/hosts import hosts.toml")
        assert allowed
        assert msg is None

    def test_allowed_log_level(self):
        """Test that log level is allowed."""
        allowed, msg = _check_command_allowed("/log level debug")
        assert allowed
        assert msg is None


class TestCommandSets:
    """Tests for command classification sets."""

    def test_blocked_commands_contains_exit_variants(self):
        """Test that all exit variants are blocked."""
        assert "exit" in BLOCKED_COMMANDS
        assert "quit" in BLOCKED_COMMANDS
        assert "q" in BLOCKED_COMMANDS

    def test_blocked_commands_contains_conversation(self):
        """Test that conversation commands are blocked."""
        assert "conv" in BLOCKED_COMMANDS
        assert "conversation" in BLOCKED_COMMANDS
        assert "new" in BLOCKED_COMMANDS

    def test_interactive_commands_complete(self):
        """Test that interactive commands set is complete."""
        assert "hosts add" in INTERACTIVE_COMMANDS
        assert "ssh config" in INTERACTIVE_COMMANDS
        assert "secret set" in INTERACTIVE_COMMANDS
