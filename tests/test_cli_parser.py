"""Tests for CLI argument parser."""

from __future__ import annotations

from merlya import __version__
from merlya.cli import create_parser


def test_create_parser_sets_version() -> None:
    assert isinstance(__version__, str)
    assert __version__


def test_create_parser_parses_run_subcommand() -> None:
    parser = create_parser()
    args = parser.parse_args(["run", "--yes", "--format", "json", "--quiet", "do something"])

    assert args.command == "run"
    assert args.yes is True
    assert args.format == "json"
    assert args.quiet is True
    assert args.task == "do something"


def test_create_parser_parses_config_set() -> None:
    parser = create_parser()
    args = parser.parse_args(["config", "set", "llm.provider", "openai"])

    assert args.command == "config"
    assert args.config_action == "set"
    assert args.key == "llm.provider"
    assert args.value == "openai"
