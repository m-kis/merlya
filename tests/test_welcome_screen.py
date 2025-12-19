import pytest

from merlya.i18n.loader import I18n
from merlya.repl.loop import (
    WelcomeStatus,
    build_welcome_lines,
    format_model_label,
)


@pytest.fixture(autouse=True)
def reset_i18n() -> None:
    I18n.reset_instance()
    yield
    I18n.reset_instance()


def test_format_model_label_prefers_agent_model() -> None:
    label = format_model_label(
        agent_model="openrouter:minimax/minimax-m2",
        provider="openrouter",
        model="amazon/nova-2-lite-v1:free",
    )
    assert label == "✅ openrouter:minimax/minimax-m2"


def test_format_model_label_fallbacks_to_config() -> None:
    label = format_model_label(
        agent_model=None,
        provider="anthropic",
        model="claude-3-5-sonnet",
    )
    assert label == "✅ anthropic:claude-3-5-sonnet"


def test_format_model_label_handles_no_colon() -> None:
    label = format_model_label(
        agent_model="gpt-4o",
        provider="openai",
        model="gpt-4o",
    )
    assert label == "✅ openai:gpt-4o"


def test_build_welcome_lines_simplified() -> None:
    translator = I18n(language="en").t
    status = WelcomeStatus(
        version="0.6.0",
        env="dev",
        session_id="session123",
        model_label="✅ openrouter:minimax/minimax-m2",
        keyring_label="✅ OK",
    )

    hero_lines, warning_lines = build_welcome_lines(translator, status)

    # Model is in the hero lines
    assert any("openrouter:minimax/minimax-m2" in line for line in hero_lines)
    # Keyring is in the hero lines
    assert any("✅ OK" in line for line in hero_lines)
    # Version is in the hero lines
    assert any("0.6.0" in line for line in hero_lines)
    # Warning lines exist
    assert warning_lines
    # No Router line anymore
    assert not any("Router:" in line for line in hero_lines)


def test_build_welcome_lines_contains_commands() -> None:
    translator = I18n(language="en").t
    status = WelcomeStatus(
        version="0.6.0",
        env="dev",
        session_id="session123",
        model_label="✅ openai:gpt-4o",
        keyring_label="✅ OK",
    )

    hero_lines, _ = build_welcome_lines(translator, status)

    # Commands are listed
    assert any("/help" in line and "/hosts" in line for line in hero_lines)
