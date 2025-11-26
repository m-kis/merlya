import os
from athena_ai.llm.router import LLMRouter

def test_ollama_init():
    # Mock env vars
    os.environ["ATHENA_PROVIDER"] = "ollama"
    os.environ["OLLAMA_MODEL"] = "llama3"
    # Clear other keys to ensure precedence or isolation
    if "OPENROUTER_API_KEY" in os.environ: del os.environ["OPENROUTER_API_KEY"]
    if "OPENAI_API_KEY" in os.environ: del os.environ["OPENAI_API_KEY"]
    if "ANTHROPIC_API_KEY" in os.environ: del os.environ["ANTHROPIC_API_KEY"]
    
    router = LLMRouter(provider="ollama")
    
    assert router.provider == "ollama"
    assert router.ollama_client is not None
    assert router.ollama_client.base_url == "http://localhost:11434/v1/"
    
    print("LLMRouter initialized correctly with Ollama.")

if __name__ == "__main__":
    test_ollama_init()
