"""
LLM Provider Readiness Checker.

Verifies that the configured LLM provider is available and properly set up
before starting the REPL. This helps catch configuration issues early.

Checks:
- Ollama: Server availability + configured model exists
- OpenRouter: API key set + API accessible
- Anthropic: API key set
- OpenAI: API key set
"""
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import requests

from merlya.llm.model_config import ModelConfig
from merlya.utils.logger import logger


@dataclass
class ReadinessResult:
    """Result of a provider readiness check."""
    provider: str
    ready: bool
    model: str = ""
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    details: Dict[str, str] = field(default_factory=dict)

    @property
    def has_issues(self) -> bool:
        """Check if there are any errors or warnings."""
        return bool(self.errors or self.warnings)


class ProviderReadinessChecker:
    """
    Checks if the configured LLM provider is ready to use.

    Performs provider-specific checks:
    - API key validation (for cloud providers)
    - Server availability (for Ollama)
    - Model availability (for Ollama)

    Example:
        checker = ProviderReadinessChecker()
        result = checker.check()
        if not result.ready:
            print(f"Provider {result.provider} not ready: {result.errors}")
    """

    # Timeout for HTTP requests (seconds)
    TIMEOUT = 5

    # OpenRouter API endpoint for checking connectivity
    OPENROUTER_API_URL = "https://openrouter.ai/api/v1/models"

    def __init__(self, model_config: Optional[ModelConfig] = None):
        """
        Initialize the readiness checker.

        Args:
            model_config: Optional ModelConfig instance. If not provided, creates one.
        """
        self.model_config = model_config or ModelConfig()

    def check(self, provider: Optional[str] = None) -> ReadinessResult:
        """
        Check if the provider is ready.

        Args:
            provider: Optional provider override. Uses configured provider if not specified.

        Returns:
            ReadinessResult with status and any issues found.
        """
        provider = provider or self.model_config.get_provider()
        model = self.model_config.get_model(provider)

        result = ReadinessResult(provider=provider, ready=False, model=model)

        try:
            if provider == "ollama":
                self._check_ollama(result)
            elif provider == "openrouter":
                self._check_openrouter(result)
            elif provider == "anthropic":
                self._check_anthropic(result)
            elif provider == "openai":
                self._check_openai(result)
            else:
                result.warnings.append(f"Unknown provider '{provider}', skipping readiness check")
                result.ready = True  # Don't block on unknown providers

        except Exception as e:
            logger.error(f"Readiness check failed: {e}")
            result.errors.append(f"Check failed: {e}")

        return result

    def _check_ollama(self, result: ReadinessResult) -> None:
        """
        Check Ollama readiness.

        Verifies:
        1. Ollama server is running and accessible
        2. Configured model is available (downloaded)
        """
        from merlya.llm.ollama_client import OllamaClient

        # Get Ollama base URL from environment or default
        base_url = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        client = OllamaClient(base_url=base_url)

        result.details["base_url"] = base_url

        # Check 1: Server availability
        if not client.is_available():
            result.errors.append(
                f"Ollama server not available at {base_url}. "
                "Is Ollama running? Try: ollama serve"
            )
            return

        result.details["server"] = "available"

        # Check 2: Get server version
        version = client.get_version()
        if version:
            result.details["version"] = version

        # Check 3: Model availability
        model_name = result.model
        if model_name:
            # Strip ollama/ prefix if present
            if model_name.startswith("ollama/"):
                model_name = model_name[7:]

            if not client.has_model(model_name):
                available_models = client.get_model_names()
                result.errors.append(
                    f"Model '{model_name}' not found in Ollama. "
                    f"Available models: {', '.join(available_models[:5]) or 'none'}. "
                    f"Try: ollama pull {model_name}"
                )
                return

            result.details["model_status"] = "available"

        result.ready = True
        logger.info(f"✅ Ollama ready: {base_url}, model: {model_name}")

    def _check_openrouter(self, result: ReadinessResult) -> None:
        """
        Check OpenRouter readiness.

        Verifies:
        1. OPENROUTER_API_KEY is set
        2. OpenRouter API is accessible
        """
        # Check 1: API key
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            result.errors.append(
                "OPENROUTER_API_KEY not set. "
                "Get your API key at https://openrouter.ai/keys"
            )
            return

        result.details["api_key"] = "configured"

        # Check 2: API connectivity (optional, can be slow)
        try:
            response = requests.get(
                self.OPENROUTER_API_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=self.TIMEOUT
            )

            if response.status_code == 401:
                result.errors.append("OpenRouter API key is invalid")
                return
            elif response.status_code != 200:
                result.warnings.append(
                    f"OpenRouter API returned status {response.status_code}"
                )
            else:
                result.details["api_status"] = "accessible"

        except requests.exceptions.Timeout:
            result.warnings.append("OpenRouter API check timed out (may be slow)")
        except requests.exceptions.RequestException as e:
            result.warnings.append(f"Could not reach OpenRouter API: {e}")

        # Still mark as ready if API key is set (connectivity issues might be transient)
        result.ready = True
        logger.info(f"✅ OpenRouter ready: API key configured, model: {result.model}")

    def _check_anthropic(self, result: ReadinessResult) -> None:
        """
        Check Anthropic readiness.

        Verifies:
        1. ANTHROPIC_API_KEY is set
        """
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            result.errors.append(
                "ANTHROPIC_API_KEY not set. "
                "Get your API key at https://console.anthropic.com/"
            )
            return

        result.details["api_key"] = "configured"
        result.ready = True
        logger.info(f"✅ Anthropic ready: API key configured, model: {result.model}")

    def _check_openai(self, result: ReadinessResult) -> None:
        """
        Check OpenAI readiness.

        Verifies:
        1. OPENAI_API_KEY is set
        """
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            result.errors.append(
                "OPENAI_API_KEY not set. "
                "Get your API key at https://platform.openai.com/api-keys"
            )
            return

        result.details["api_key"] = "configured"
        result.ready = True
        logger.info(f"✅ OpenAI ready: API key configured, model: {result.model}")


# Convenience function
def check_provider_readiness(provider: Optional[str] = None) -> ReadinessResult:
    """
    Check if the LLM provider is ready to use.

    Args:
        provider: Optional provider to check. Uses configured provider if not specified.

    Returns:
        ReadinessResult with status and any issues.
    """
    checker = ProviderReadinessChecker()
    return checker.check(provider)


def format_readiness_result(result: ReadinessResult) -> str:
    """
    Format readiness result for display.

    Args:
        result: ReadinessResult to format

    Returns:
        Formatted string for console output
    """
    lines = []

    if result.ready:
        status = "✅"
    elif result.errors:
        status = "❌"
    else:
        status = "⚠️"

    lines.append(f"{status} **{result.provider.upper()}** Provider")

    if result.model:
        lines.append(f"   Model: {result.model}")

    for key, value in result.details.items():
        lines.append(f"   {key}: {value}")

    for error in result.errors:
        lines.append(f"   ❌ {error}")

    for warning in result.warnings:
        lines.append(f"   ⚠️ {warning}")

    return "\n".join(lines)
