import os
from types import SimpleNamespace

from merlya.config.provider_env import ensure_provider_env, ollama_requires_api_key


def test_ensure_provider_env_sets_default_with_v1(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    cfg = SimpleNamespace(model=SimpleNamespace(provider="ollama", base_url=None, model="llama3.2"))

    ensure_provider_env(cfg)

    assert cfg.model.base_url.endswith("/v1")
    assert cfg.model.base_url == "http://localhost:11434/v1"
    assert os.environ["OLLAMA_BASE_URL"] == cfg.model.base_url
    assert os.environ["OLLAMA_HOST"] == cfg.model.base_url


def test_ensure_provider_env_appends_v1(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    cfg = SimpleNamespace(
        model=SimpleNamespace(
            provider="ollama", base_url="http://localhost:11434", model="llama3.2"
        )
    )

    ensure_provider_env(cfg)

    assert cfg.model.base_url.endswith("/v1")
    assert cfg.model.base_url == "http://localhost:11434/v1"


def test_ensure_provider_env_defaults_cloud_endpoint(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    cfg = SimpleNamespace(
        model=SimpleNamespace(provider="ollama", model="ministral-3:14b-cloud", base_url=None)
    )

    ensure_provider_env(cfg)

    assert cfg.model.base_url == "https://ollama.com/v1"
    assert os.environ["OLLAMA_BASE_URL"] == cfg.model.base_url
    assert os.environ["OLLAMA_HOST"] == cfg.model.base_url


def test_ensure_provider_env_migrates_legacy_api_host(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    cfg = SimpleNamespace(
        model=SimpleNamespace(
            provider="ollama",
            model="ministral-3:14b-cloud",
            base_url="https://api.ollama.ai/v1",
        )
    )

    ensure_provider_env(cfg)

    assert cfg.model.base_url == "https://ollama.com/v1"
    assert os.environ["OLLAMA_BASE_URL"] == "https://ollama.com/v1"
    assert os.environ["OLLAMA_HOST"] == "https://ollama.com/v1"


def test_ollama_requires_api_key_detects_cloud_model():
    cfg = SimpleNamespace(
        model=SimpleNamespace(provider="ollama", model="ministral-3:14b-cloud", base_url=None)
    )
    assert ollama_requires_api_key(cfg) is True


def test_ollama_requires_api_key_detects_remote_base_url():
    cfg = SimpleNamespace(
        model=SimpleNamespace(
            provider="ollama", model="llama3.2", base_url="https://api.ollama.ai/v1"
        )
    )
    assert ollama_requires_api_key(cfg) is True


def test_ollama_requires_api_key_false_for_local():
    cfg = SimpleNamespace(
        model=SimpleNamespace(
            provider="ollama", model="llama3.2", base_url="http://localhost:11434/v1"
        )
    )
    assert ollama_requires_api_key(cfg) is False
