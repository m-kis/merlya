import os
from athena_ai.llm.router import LLMRouter

def test_model_override():
    # Mock env vars
    os.environ["OPENROUTER_API_KEY"] = "sk-dummy"
    os.environ["OPENROUTER_MODEL"] = "default-model"
    
    router = LLMRouter(provider="openrouter")
    
    # Test default
    # We can't easily check the model used in the API call without mocking the client method
    # But we can check if the _call_openrouter logic respects the argument
    
    # Let's mock the client
    from unittest.mock import MagicMock
    router.openrouter_client = MagicMock()
    router.openrouter_client.chat.completions.create.return_value.choices = [MagicMock(message=MagicMock(content="response"))]
    
    # Call with override
    router.generate("hello", model="override-model")
    
    # Check if create was called with override-model
    call_args = router.openrouter_client.chat.completions.create.call_args
    assert call_args.kwargs['model'] == "override-model"
    
    print("LLMRouter respected model override.")

if __name__ == "__main__":
    test_model_override()
