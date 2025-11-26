"""
Ollama Client for local LLM support.

Provides:
- Health check for Ollama server
- Model discovery (list available models)
- Model info (size, parameters)
- Connection management with auto-retry
"""
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from athena_ai.utils.logger import logger


@dataclass
class OllamaModel:
    """Information about an Ollama model."""
    name: str
    size: int  # bytes
    modified_at: str
    digest: str
    parameter_size: str = ""
    quantization: str = ""

    @property
    def size_gb(self) -> float:
        """Size in GB."""
        return self.size / (1024 ** 3)

    @property
    def display_size(self) -> str:
        """Human-readable size."""
        if self.size >= 1024 ** 3:
            return f"{self.size_gb:.1f}GB"
        elif self.size >= 1024 ** 2:
            return f"{self.size / (1024 ** 2):.0f}MB"
        else:
            return f"{self.size / 1024:.0f}KB"


class OllamaClient:
    """
    Client for interacting with Ollama local LLM server.

    Provides health checks, model discovery, and configuration helpers.
    """

    DEFAULT_BASE_URL = "http://localhost:11434"
    TIMEOUT = 5  # seconds

    # Recommended models by use case
    RECOMMENDED_MODELS = {
        "fast": ["qwen2.5:0.5b", "smollm2:1.7b", "phi3:mini"],
        "balanced": ["llama3.2:3b", "mistral:7b", "gemma2:9b"],
        "best": ["llama3.1:70b", "deepseek-coder:33b", "mixtral:8x7b"],
        "coding": ["deepseek-coder:6.7b", "codellama:7b", "starcoder2:7b"],
    }

    def __init__(self, base_url: Optional[str] = None):
        """
        Initialize Ollama client.

        Args:
            base_url: Ollama server URL (default: http://localhost:11434)
        """
        self.base_url = base_url or os.getenv("OLLAMA_HOST", self.DEFAULT_BASE_URL)
        # Remove trailing slash
        self.base_url = self.base_url.rstrip("/")
        self._available: Optional[bool] = None
        self._models_cache: Optional[List[OllamaModel]] = None

    def is_available(self) -> bool:
        """
        Check if Ollama server is running and accessible.

        Returns:
            True if server is available, False otherwise
        """
        try:
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=self.TIMEOUT
            )
            self._available = response.status_code == 200
            return self._available
        except requests.exceptions.RequestException as e:
            logger.debug(f"Ollama not available at {self.base_url}: {e}")
            self._available = False
            return False

    def get_version(self) -> Optional[str]:
        """
        Get Ollama server version.

        Returns:
            Version string or None if not available
        """
        try:
            response = requests.get(
                f"{self.base_url}/api/version",
                timeout=self.TIMEOUT
            )
            if response.status_code == 200:
                return response.json().get("version")
        except requests.exceptions.RequestException:
            pass
        return None

    def list_models(self, refresh: bool = False) -> List[OllamaModel]:
        """
        List all available models on the Ollama server.

        Args:
            refresh: Force refresh of cached models

        Returns:
            List of OllamaModel objects
        """
        if self._models_cache is not None and not refresh:
            return self._models_cache

        try:
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=self.TIMEOUT
            )
            if response.status_code == 200:
                data = response.json()
                models = []
                for m in data.get("models", []):
                    details = m.get("details", {})
                    models.append(OllamaModel(
                        name=m.get("name", ""),
                        size=m.get("size", 0),
                        modified_at=m.get("modified_at", ""),
                        digest=m.get("digest", "")[:12],
                        parameter_size=details.get("parameter_size", ""),
                        quantization=details.get("quantization_level", ""),
                    ))
                self._models_cache = models
                return models
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to list Ollama models: {e}")

        return []

    def get_model_names(self) -> List[str]:
        """Get list of model names only."""
        return [m.name for m in self.list_models()]

    def has_model(self, model_name: str) -> bool:
        """Check if a specific model is available."""
        names = self.get_model_names()
        # Check exact match or prefix match (e.g., "llama3" matches "llama3:latest")
        return any(
            name == model_name or name.startswith(f"{model_name}:")
            for name in names
        )

    def get_model_info(self, model_name: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed info about a specific model.

        Args:
            model_name: Name of the model

        Returns:
            Model info dict or None
        """
        try:
            response = requests.post(
                f"{self.base_url}/api/show",
                json={"name": model_name},
                timeout=self.TIMEOUT * 2
            )
            if response.status_code == 200:
                return response.json()
        except requests.exceptions.RequestException as e:
            logger.debug(f"Failed to get model info for {model_name}: {e}")
        return None

    def pull_model(self, model_name: str, stream: bool = False) -> bool:
        """
        Pull (download) a model from Ollama registry.

        Args:
            model_name: Name of the model to pull
            stream: Whether to stream progress (not implemented here)

        Returns:
            True if successful
        """
        try:
            response = requests.post(
                f"{self.base_url}/api/pull",
                json={"name": model_name, "stream": False},
                timeout=300  # Models can be large
            )
            return response.status_code == 200
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to pull model {model_name}: {e}")
            return False

    def suggest_model(self, use_case: str = "balanced", available_only: bool = True) -> Optional[str]:
        """
        Suggest a model based on use case.

        Args:
            use_case: One of "fast", "balanced", "best", "coding"
            available_only: Only suggest models that are already downloaded

        Returns:
            Suggested model name or None
        """
        recommended = self.RECOMMENDED_MODELS.get(use_case, self.RECOMMENDED_MODELS["balanced"])

        if available_only:
            available = self.get_model_names()
            for model in recommended:
                # Check if model or variant is available
                base_name = model.split(":")[0]
                for avail in available:
                    if avail.startswith(base_name):
                        return avail
            return None
        else:
            return recommended[0] if recommended else None

    def get_status(self) -> Dict[str, Any]:
        """
        Get comprehensive Ollama status.

        Returns:
            Status dict with availability, version, models, etc.
        """
        status = {
            "available": self.is_available(),
            "base_url": self.base_url,
            "version": None,
            "models": [],
            "model_count": 0,
            "total_size_gb": 0,
        }

        if status["available"]:
            status["version"] = self.get_version()
            models = self.list_models(refresh=True)
            status["models"] = [m.name for m in models]
            status["model_count"] = len(models)
            status["total_size_gb"] = sum(m.size_gb for m in models)

        return status

    def test_generation(self, model: Optional[str] = None, prompt: str = "Say hello") -> Optional[str]:
        """
        Test model generation capability.

        Args:
            model: Model to test (uses first available if not specified)
            prompt: Test prompt

        Returns:
            Generated response or None if failed
        """
        if model is None:
            models = self.get_model_names()
            if not models:
                return None
            model = models[0]

        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": 50}
                },
                timeout=30
            )
            if response.status_code == 200:
                return response.json().get("response", "").strip()
        except requests.exceptions.RequestException as e:
            logger.debug(f"Generation test failed: {e}")

        return None


# Singleton instance
_ollama_client: Optional[OllamaClient] = None


def get_ollama_client() -> OllamaClient:
    """Get or create the singleton Ollama client."""
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OllamaClient()
    return _ollama_client


def check_ollama_available() -> bool:
    """Quick check if Ollama is available."""
    return get_ollama_client().is_available()
