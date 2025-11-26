import os
from typing import List, Dict, Any, Optional
from anthropic import Anthropic
from openai import OpenAI
from athena_ai.utils.logger import logger
from athena_ai.llm.model_config import ModelConfig

class LLMRouter:
    def __init__(self, provider: Optional[str] = None):
        # Use ModelConfig for flexible model management
        self.model_config = ModelConfig()

        # Provider can be overridden or use config
        self.provider = provider or self._detect_provider()

        self.anthropic_client = None
        self.openai_client = None
        self.openrouter_client = None
        self.ollama_client = None

        self._init_clients()

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
            # Ollama uses OpenAI compatible API
            base_url = os.getenv("OLLAMA_HOST", "http://localhost:11434/v1")
            self.ollama_client = OpenAI(
                base_url=base_url,
                api_key="ollama" # Required but ignored
            )

    def generate(self, prompt: str, system_prompt: str = "", model: Optional[str] = None, task: Optional[str] = None) -> str:
        """
        Generate a response from the LLM.

        Args:
            prompt: User prompt
            system_prompt: System context
            model: Explicit model override
            task: Task type for task-specific model selection (correction, planning, synthesis)
        """
        # Get model from config if not explicitly provided
        if not model:
            model = self.model_config.get_model(self.provider, task=task)

        try:
            if self.provider == "anthropic" and self.anthropic_client:
                return self._call_anthropic(prompt, system_prompt, model)
            elif self.provider == "openai" and self.openai_client:
                return self._call_openai(prompt, system_prompt, model)
            elif self.provider == "openrouter" and hasattr(self, 'openrouter_client') and self.openrouter_client:
                return self._call_openrouter(prompt, system_prompt, model)
            elif self.provider == "ollama" and hasattr(self, 'ollama_client') and self.ollama_client:
                return self._call_ollama(prompt, system_prompt, model)
            else:
                # Fallback or mock
                logger.warning("No valid LLM provider configured. Returning mock response.")
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
                        # Mock response for provisioning
                        if "Ansible" in prompt:
                            return '{"tool": "ansible", "playbook": "playbook.yml"}'
                        else:
                            return '{"tool": "terraform", "dir": "./tf", "action": "plan"}'
                    elif "CloudAgent" in system_prompt:
                        # Mock response for cloud
                        if "AWS" in prompt:
                            return '{"provider": "aws", "action": "list_instances"}'
                        else:
                            return '{"provider": "k8s", "action": "list_pods", "namespace": "default"}'
                    else:
                        return '{}'
                return "Mock response: LLM not configured."
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return f"Error: {str(e)}"

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
        """Call Ollama API with configured model."""
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
        response = self.ollama_client.chat.completions.create(
            model=model,
            messages=messages
        )
        return response.choices[0].message.content
