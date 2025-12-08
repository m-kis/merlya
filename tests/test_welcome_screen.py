import pytest

from merlya.config.models import RouterConfig
from merlya.i18n.loader import I18n
from merlya.repl.loop import (
    WelcomeStatus,
    build_welcome_lines,
    format_model_labels,
    format_router_label,
)


class DummyClassifier:
    def __init__(self, model_loaded: bool, model_id: str | None = None) -> None:
        self.model_loaded = model_loaded
        self.model_id = model_id


class DummyRouter:
    def __init__(self, model_loaded: bool, model_id: str | None = None) -> None:
        self.classifier = DummyClassifier(model_loaded, model_id)


@pytest.fixture(autouse=True)
def reset_i18n() -> None:
    I18n.reset_instance()
    yield
    I18n.reset_instance()


def test_format_model_labels_prefers_agent_model() -> None:
    provider_label, model_label = format_model_labels(
        agent_model="openrouter:minimax/minimax-m2",
        provider="openrouter",
        model="amazon/nova-2-lite-v1:free",
    )

    assert provider_label == "✅ openrouter (minimax/minimax-m2)"
    assert model_label == "✅ openrouter:minimax/minimax-m2"


def test_format_model_labels_fallbacks_to_config() -> None:
    provider_label, model_label = format_model_labels(
        agent_model=None,
        provider="anthropic",
        model="claude-3-5-sonnet",
    )

    assert provider_label == "✅ anthropic (claude-3-5-sonnet)"
    assert model_label == "✅ anthropic:claude-3-5-sonnet"


def test_format_router_label_prefers_local() -> None:
    router = DummyRouter(model_loaded=True, model_id="router.onnx")
    label = format_router_label(router, RouterConfig())

    assert label.startswith("✅ local")
    assert "router.onnx" in label


def test_format_router_label_reports_fallback_for_llm() -> None:
    config = RouterConfig(type="llm", llm_fallback="openrouter:gpt-4o-mini")

    label = format_router_label(None, config)

    assert label == "🔀 openrouter:gpt-4o-mini"


def test_format_router_label_warns_when_local_unavailable() -> None:
    config = RouterConfig(type="local", llm_fallback="openrouter:gemini")

    label = format_router_label(None, config)

    assert "fallback openrouter:gemini" in label


def test_build_welcome_lines_include_model_and_router() -> None:
    translator = I18n(language="en").t
    status = WelcomeStatus(
        version="0.5.1",
        env="dev",
        session_id="session123",
        provider_label="✅ openrouter (minimax/minimax-m2)",
        model_label="✅ openrouter:minimax/minimax-m2",
        router_label="✅ local",
        keyring_label="✅ Keyring",
    )

    hero_lines, warning_lines = build_welcome_lines(translator, status)

    assert "Router: ✅ local" in hero_lines
    assert "Model: ✅ openrouter:minimax/minimax-m2" in hero_lines
    assert any(status.session_id in line for line in hero_lines)
    assert warning_lines  # Warning block still rendered
