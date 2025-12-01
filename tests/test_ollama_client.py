"""
Tests for Ollama client functionality.
"""

import unittest
from unittest.mock import MagicMock, patch

from merlya.llm.ollama_client import OllamaClient, OllamaModel, get_ollama_client


class TestOllamaClient(unittest.TestCase):
    """Test cases for OllamaClient."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = OllamaClient(base_url="http://localhost:11434")

    def test_init_default_url(self):
        """Test client initializes with default URL."""
        client = OllamaClient()
        self.assertEqual(client.base_url, "http://localhost:11434")

    def test_init_custom_url(self):
        """Test client initializes with custom URL."""
        client = OllamaClient(base_url="http://custom:8080")
        self.assertEqual(client.base_url, "http://custom:8080")

    @patch("merlya.llm.ollama_client.requests.get")
    def test_is_available_success(self, mock_get):
        """Test is_available returns True when server responds."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = self.client.is_available()
        self.assertTrue(result)

    @patch("merlya.llm.ollama_client.requests.get")
    def test_is_available_failure(self, mock_get):
        """Test is_available returns False when server unavailable."""
        import requests
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")

        result = self.client.is_available()
        self.assertFalse(result)

    @patch("merlya.llm.ollama_client.requests.get")
    def test_list_models_success(self, mock_get):
        """Test list_models returns models from API."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [
                {"name": "llama3:8b", "size": 1000000, "modified_at": "2024-01-01", "digest": "abc123"}
            ]
        }
        mock_get.return_value = mock_response

        # Clear cache first
        self.client._models_cache = None
        models = self.client.list_models(refresh=True)

        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].name, "llama3:8b")

    @patch("merlya.llm.ollama_client.requests.get")
    def test_list_models_caching(self, mock_get):
        """Test list_models caches results."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [{"name": "llama3:8b", "size": 100, "modified_at": "", "digest": "abc"}]
        }
        mock_get.return_value = mock_response

        # Clear cache
        self.client._models_cache = None

        # First call
        self.client.list_models(refresh=True)
        # Second call should use cache
        self.client.list_models(refresh=False)

        # requests.get should only be called once
        self.assertEqual(mock_get.call_count, 1)

    def test_get_model_names(self):
        """Test get_model_names returns list of names."""
        self.client._models_cache = [
            OllamaModel(name="model1", size=100, modified_at="", digest="abc"),
            OllamaModel(name="model2", size=200, modified_at="", digest="def"),
        ]

        names = self.client.get_model_names()
        self.assertEqual(names, ["model1", "model2"])

    @patch("merlya.llm.ollama_client.requests.get")
    def test_get_status_offline(self, mock_get):
        """Test get_status when offline."""
        import requests
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")

        status = self.client.get_status()

        self.assertFalse(status["available"])
        self.assertEqual(status["models"], [])

    @patch("merlya.llm.ollama_client.requests.get")
    def test_get_status_online(self, mock_get):
        """Test get_status when online."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [
                {"name": "llama3:8b", "size": 4_000_000_000, "modified_at": "2024-01-01", "digest": "abc"}
            ]
        }
        mock_get.return_value = mock_response

        status = self.client.get_status()

        self.assertTrue(status["available"])
        self.assertEqual(status["model_count"], 1)

    def test_suggest_model_balanced(self):
        """Test suggest_model for balanced use case."""
        self.client._models_cache = [
            OllamaModel(name="llama3.2:3b", size=4_000_000_000, modified_at="", digest="abc"),
            OllamaModel(name="mistral:7b", size=3_800_000_000, modified_at="", digest="def"),
        ]

        suggestion = self.client.suggest_model("balanced")
        # Should prefer llama3.2 for balanced (first in recommended list)
        self.assertIn(suggestion, ["llama3.2:3b", "mistral:7b"])

    def test_suggest_model_fast(self):
        """Test suggest_model for fast use case."""
        self.client._models_cache = [
            OllamaModel(name="llama3:8b", size=4_000_000_000, modified_at="", digest="abc"),
            OllamaModel(name="qwen2.5:0.5b", size=500_000_000, modified_at="", digest="def"),
        ]

        suggestion = self.client.suggest_model("fast")
        # Should prefer qwen2.5 for fast
        self.assertEqual(suggestion, "qwen2.5:0.5b")

    def test_suggest_model_empty_cache(self):
        """Test suggest_model with no models."""
        self.client._models_cache = []

        suggestion = self.client.suggest_model()
        self.assertIsNone(suggestion)


class TestOllamaModel(unittest.TestCase):
    """Test cases for OllamaModel dataclass."""

    def test_size_gb(self):
        """Test size in GB calculation."""
        model = OllamaModel(name="test", size=4_500_000_000, modified_at="", digest="abc")
        self.assertAlmostEqual(model.size_gb, 4.19, places=1)

    def test_display_size_gb(self):
        """Test display size for GB."""
        model = OllamaModel(name="test", size=4_500_000_000, modified_at="", digest="abc")
        self.assertEqual(model.display_size, "4.2GB")

    def test_display_size_mb(self):
        """Test display size for MB."""
        model = OllamaModel(name="test", size=500_000_000, modified_at="", digest="abc")
        self.assertEqual(model.display_size, "477MB")


class TestGetOllamaClient(unittest.TestCase):
    """Test cases for get_ollama_client factory."""

    def test_singleton_instance(self):
        """Test factory returns singleton."""
        # Reset singleton for test
        import merlya.llm.ollama_client as module
        module._ollama_client = None

        client1 = get_ollama_client()
        client2 = get_ollama_client()

        self.assertIs(client1, client2)

    @patch.dict("os.environ", {"OLLAMA_HOST": "http://custom:9999"})
    def test_env_override(self):
        """Test OLLAMA_HOST environment variable."""
        import merlya.llm.ollama_client as module
        module._ollama_client = None

        client = get_ollama_client()
        self.assertEqual(client.base_url, "http://custom:9999")


if __name__ == "__main__":
    unittest.main()
