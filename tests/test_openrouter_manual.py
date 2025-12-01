import os

from merlya.llm.router import LLMRouter


def test_openrouter_init():
    # Mock env var
    os.environ["OPENROUTER_API_KEY"] = "sk-or-test-key"

    router = LLMRouter(provider="openrouter")

    assert router.provider == "openrouter"
    assert router.openrouter_client is not None
    assert router.openrouter_client.base_url == "https://openrouter.ai/api/v1/"

    print("LLMRouter initialized correctly with OpenRouter.")

if __name__ == "__main__":
    test_openrouter_init()
