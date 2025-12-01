"""
Verify Local LLM support.
"""
import os
import sys
from unittest.mock import MagicMock

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from merlya.agents.ag2_orchestrator import Ag2Orchestrator


def test_local_llm():
    print("--- Testing Local LLM Support ---")

    # Initialize Orchestrator (mocking autogen to avoid real init if possible, but Ag2Orchestrator inits agents in __init__)
    # We'll rely on the fact that we can check the config without running agents

    # Create a fresh config manager to avoid messing with user's real config
    # We can mock the config manager inside the orchestrator

    orch = Ag2Orchestrator(env="test")

    # Mock ConfigManager
    orch.config_manager = MagicMock()
    orch.config_manager.use_local_llm = False

    # Check default (Cloud)
    config = orch._get_llm_config()
    print(f"Default Config Base URL: {config['config_list'][0].get('base_url')}")
    if "localhost" not in str(config['config_list'][0].get('base_url')):
        print("✅ Default is Cloud")
    else:
        print("❌ Default should be Cloud")

    # Enable Local
    print("\nEnabling Local Mode...")
    orch.config_manager.use_local_llm = True
    orch.config_manager.local_llm_model = "mistral"

    config = orch._get_llm_config()
    print(f"Local Config Base URL: {config['config_list'][0].get('base_url')}")
    print(f"Local Config Model: {config['config_list'][0].get('model')}")

    if "localhost:11434" in str(config['config_list'][0].get('base_url')):
        print("✅ Local URL correct")
    else:
        print("❌ Local URL incorrect")

    if config['config_list'][0].get('model') == "mistral":
        print("✅ Local Model correct")
    else:
        print("❌ Local Model incorrect")

    # Test Reload
    print("\nTesting Reload...")
    try:
        print(f"Before reload, OPENAI_API_KEY: {os.environ.get('OPENAI_API_KEY')}")
        orch.reload_agents()
        print(f"After reload, OPENAI_API_KEY: {os.environ.get('OPENAI_API_KEY')}")
        print("✅ reload_agents() executed without error")
    except Exception as e:
        print(f"❌ reload_agents() failed: {e}")

if __name__ == "__main__":
    test_local_llm()
