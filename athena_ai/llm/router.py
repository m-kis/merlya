import os
from typing import Optional

from anthropic import Anthropic
from openai import OpenAI

from athena_ai.llm.model_config import ModelConfig
from athena_ai.llm.ollama_client import OllamaClient, get_ollama_client
from athena_ai.utils.display import get_display_manager
from athena_ai.utils.logger import logger


class LLMRouter:
    def __init__(self, provider: Optional[str] = None, fallback_to_cloud: bool = True):
        """
        Initialize LLM Router.

        Args:
            provider: Explicit provider override
            fallback_to_cloud: If True, fallback to cloud if Ollama unavailable
        """
        # Use ModelConfig for flexible model management
        self.model_config = ModelConfig()
        self.fallback_to_cloud = fallback_to_cloud

        # Provider can be overridden or use config
        self._requested_provider = provider
        self.provider = provider or self._detect_provider()

        self.anthropic_client = None
        self.openai_client = None
        self.openrouter_client = None
        self.ollama_openai_client = None  # OpenAI-compat client for Ollama
        self.ollama_native_client: Optional[OllamaClient] = None  # Native Ollama client

        self._init_clients()
        self._verify_ollama_if_needed()

    def _detect_provider(self) -> str:
        """Auto-detect provider from env vars or config."""
        # Check env vars first
        if os.getenv("ATHENA_PROVIDER") == "ollama" or os.getenv("OLLAMA_MODEL"):
            return "ollama"
        elif os.getenv("OPENROUTER_API_KEY"):
            return "openrouter"
        elif os.getenv("OPENAI_API_KEY"):
            return "openai"
        elif os.getenv("ANTHROPIC_API_KEY"):
            return "anthropic"

        # Fall back to config
        return self.model_config.get_provider()

    def _init_clients(self):
        """Initialize API clients based on available credentials."""
        if os.getenv("ANTHROPIC_API_KEY"):
            self.anthropic_client = Anthropic()
        if os.getenv("OPENAI_API_KEY"):
            self.openai_client = OpenAI()
        if os.getenv("OPENROUTER_API_KEY"):
            self.openrouter_client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=os.getenv("OPENROUTER_API_KEY")
            )
        if os.getenv("OLLAMA_HOST") or self.provider == "ollama":
            # Initialize both native client and OpenAI-compat client
            self.ollama_native_client = get_ollama_client()
            base_url = os.getenv("OLLAMA_HOST", "http://localhost:11434") + "/v1"
            self.ollama_openai_client = OpenAI(
                base_url=base_url,
                api_key="ollama"  # Required but ignored
            )

    def _verify_ollama_if_needed(self):
        """Verify Ollama is available and fallback if not."""
        if self.provider != "ollama":
            return

        if self.ollama_native_client is None:
            self.ollama_native_client = get_ollama_client()

        if not self.ollama_native_client.is_available():
            logger.warning("Ollama server not available at %s", self.ollama_native_client.base_url)

            if self.fallback_to_cloud:
                fallback = self._get_fallback_provider()
                if fallback:
                    logger.info(f"Falling back to cloud provider: {fallback}")
                    self.provider = fallback
                else:
                    logger.error("No fallback provider available. LLM calls may fail.")
            else:
                logger.warning("Ollama not available and fallback disabled.")
        else:
            models = self.ollama_native_client.get_model_names()
            logger.info(f"Ollama available with {len(models)} models: {', '.join(models[:3])}...")

    def _get_fallback_provider(self) -> Optional[str]:
        """Get first available cloud provider for fallback."""
        if os.getenv("OPENROUTER_API_KEY"):
            return "openrouter"
        if os.getenv("ANTHROPIC_API_KEY"):
            return "anthropic"
        if os.getenv("OPENAI_API_KEY"):
            return "openai"
        return None

    def is_ollama_available(self) -> bool:
        """Check if Ollama is available."""
        if self.ollama_native_client is None:
            self.ollama_native_client = get_ollama_client()
        return self.ollama_native_client.is_available()

    def get_ollama_status(self) -> dict:
        """Get Ollama status including models."""
        if self.ollama_native_client is None:
            self.ollama_native_client = get_ollama_client()
        return self.ollama_native_client.get_status()

    def switch_provider(self, provider: str, verify: bool = True) -> bool:
        """
        Switch to a different provider.

        Args:
            provider: Provider name (ollama, openrouter, anthropic, openai)
            verify: Verify provider is available before switching

        Returns:
            True if switch successful
        """
        if provider == "ollama":
            if verify and not self.is_ollama_available():
                logger.error("Cannot switch to Ollama: server not available")
                return False
            self._init_clients()  # Re-init to ensure Ollama client is ready

        old_provider = self.provider
        self.provider = provider
        self.model_config.set_provider(provider)
        logger.info(f"Switched provider: {old_provider} -> {provider}")
        return True

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        model: Optional[str] = None,
        task: Optional[str] = None,
        show_spinner: bool = True
    ) -> str:
        """
        Generate a response from the LLM.

        Args:
            prompt: User prompt
            system_prompt: System context
            model: Explicit model override
            task: Task type for task-specific model selection
            show_spinner: Show spinner during LLM request (default: True)
        """
        # Get model from config if not explicitly provided
        if not model:
            model = self.model_config.get_model(self.provider, task=task)

        # Determine which provider call function to use
        call_func = self._get_provider_call_func()
        if call_func is None:
            logger.warning("No valid LLM provider configured. Returning mock response.")
            return self._get_mock_response(prompt, system_prompt)

        try:
            return self._call_with_spinner(
                call_func, prompt, system_prompt, model, show_spinner
            )
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return f"Error: {str(e)}"

    def _get_provider_call_func(self):
        """Get the appropriate provider call function."""
        if self.provider == "anthropic" and self.anthropic_client:
            return self._call_anthropic
        elif self.provider == "openai" and self.openai_client:
            return self._call_openai
        elif self.provider == "openrouter" and hasattr(self, 'openrouter_client') and self.openrouter_client:
            return self._call_openrouter
        elif self.provider == "ollama" and self.ollama_openai_client:
            return self._call_ollama
        return None

    def _call_with_spinner(self, call_func, prompt: str, system_prompt: str,
                          model: str, show_spinner: bool) -> str:
        """Execute provider call with optional spinner."""
        if show_spinner:
            display = get_display_manager()
            spinner_msg = f"🧠 Thinking ({self.provider})..."
            with display.spinner(spinner_msg):
                return call_func(prompt, system_prompt, model)
        return call_func(prompt, system_prompt, model)

    def _get_mock_response(self, prompt: str, system_prompt: str) -> str:
        """Generate mock response for testing without LLM."""
        if "Return ONLY a JSON" in prompt or "Return a JSON" in prompt:
            if "AgentCoordinator" in system_prompt or "agent coordinator" in system_prompt.lower():
                return '{"steps": [{"agent": "DiagnosticAgent", "task": "Check system status"}]}'
            elif "DiagnosticAgent" in system_prompt or "diagnostic agent" in system_prompt.lower():
                return '["uptime", "df -h"]'
            elif "MonitoringAgent" in system_prompt:
                return '["top -b -n 1"]'
            elif "RemediationAgent" in system_prompt:
                return '[{"command": "echo remediation", "type": "shell"}]'
            elif "ProvisioningAgent" in system_prompt:
                if "Ansible" in prompt:
                    return '{"tool": "ansible", "playbook": "playbook.yml"}'
                return '{"tool": "terraform", "dir": "./tf", "action": "plan"}'
            elif "CloudAgent" in system_prompt:
                if "AWS" in prompt:
                    return '{"provider": "aws", "action": "list_instances"}'
                return '{"provider": "k8s", "action": "list_pods", "namespace": "default"}'
            return '{}'
        return "Mock response: LLM not configured."

    def _call_anthropic(self, prompt: str, system_prompt: str, model: str) -> str:
        """Call Anthropic API with configured model."""
        response = self.anthropic_client.messages.create(
            model=model,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text

    def _call_openai(self, prompt: str, system_prompt: str, model: str) -> str:
        """Call OpenAI API with configured model."""
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
        response = self.openai_client.chat.completions.create(
            model=model,
            messages=messages
        )
        return response.choices[0].message.content

    def _call_openrouter(self, prompt: str, system_prompt: str, model: str) -> str:
        """Call OpenRouter API with configured model."""
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
        response = self.openrouter_client.chat.completions.create(
            model=model,
            messages=messages
        )
        return response.choices[0].message.content

    def _call_ollama(self, prompt: str, system_prompt: str, model: str) -> str:
        """Call Ollama API with configured model via OpenAI-compatible client."""
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
        response = self.ollama_openai_client.chat.completions.create(
            model=model,
            messages=messages
        )
        return response.choices[0].message.content
