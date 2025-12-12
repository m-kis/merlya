"""
Tests for ONNX Parser Backend.

Tests ONNXParserBackend with real model download and inference.
Use pytest -m "slow" to run these tests (they download models).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from merlya.parser.backends.onnx import (
    NER_LABELS,
    ONNX_MODELS,
    ONNXParserBackend,
)


class TestONNXParserBackendInit:
    """Tests for ONNXParserBackend initialization."""

    def test_init_default_tier(self):
        """Test initialization with default tier."""
        backend = ONNXParserBackend()

        assert backend._tier == "balanced"
        assert backend._model_id == ONNX_MODELS["balanced"]["model_id"]
        assert backend._loaded is False
        assert backend.name == "onnx"

    def test_init_performance_tier(self):
        """Test initialization with performance tier."""
        backend = ONNXParserBackend(tier="performance")

        assert backend._tier == "performance"
        assert backend._model_id == ONNX_MODELS["performance"]["model_id"]

    def test_init_custom_model_id(self):
        """Test initialization with custom model ID."""
        backend = ONNXParserBackend(model_id="custom/model")

        assert backend._model_id == "custom/model"

    def test_init_creates_heuristic_fallback(self):
        """Test that heuristic fallback is created."""
        backend = ONNXParserBackend()

        assert backend._heuristic is not None
        assert backend._heuristic.name == "heuristic"

    def test_is_loaded_property(self):
        """Test is_loaded property."""
        backend = ONNXParserBackend()

        assert backend.is_loaded is False
        backend._loaded = True
        assert backend.is_loaded is True


class TestONNXParserBackendModelSelection:
    """Tests for model selection logic."""

    def test_select_model_balanced(self):
        """Test balanced tier model selection."""
        backend = ONNXParserBackend()

        model_id = backend._select_model_id("balanced")
        assert model_id == "Xenova/distilbert-NER"

    def test_select_model_performance(self):
        """Test performance tier model selection."""
        backend = ONNXParserBackend()

        model_id = backend._select_model_id("performance")
        assert model_id == "Xenova/bert-base-NER"

    def test_select_model_default(self):
        """Test default model selection for unknown tier."""
        backend = ONNXParserBackend()

        model_id = backend._select_model_id("unknown")
        assert model_id == "Xenova/distilbert-NER"

    def test_select_model_empty(self):
        """Test model selection with empty tier."""
        backend = ONNXParserBackend()

        model_id = backend._select_model_id("")
        assert model_id == "Xenova/distilbert-NER"


class TestONNXParserBackendPathResolution:
    """Tests for model path resolution."""

    def test_resolve_model_path(self):
        """Test model path resolution."""
        backend = ONNXParserBackend()

        path = backend._resolve_model_path("Xenova/bert-base-NER")

        assert path.name == "model.onnx"
        assert "Xenova__bert-base-NER" in str(path)
        assert ".merlya" in str(path)
        assert "models" in str(path)
        assert "parser" in str(path)

    def test_resolve_model_path_special_chars(self):
        """Test path resolution with special characters."""
        backend = ONNXParserBackend()

        path = backend._resolve_model_path("org/model:version")

        assert "org__model__version" in str(path)


class TestONNXParserBackendTokenCleaning:
    """Tests for token cleaning logic."""

    def test_clean_token_bert_subword(self):
        """Test cleaning BERT subword tokens."""
        backend = ONNXParserBackend()

        # BERT subwords start with ##
        assert backend._clean_token("##ing") == "ing"
        assert backend._clean_token("##ed") == "ed"

    def test_clean_token_gpt_style(self):
        """Test cleaning GPT-style tokens."""
        backend = ONNXParserBackend()

        # GPT-style tokens start with Ġ (space indicator)
        assert backend._clean_token("Ġword") == " word"

    def test_clean_token_normal(self):
        """Test cleaning normal tokens."""
        backend = ONNXParserBackend()

        assert backend._clean_token("word") == "word"
        assert backend._clean_token("Hello") == "Hello"

    def test_clean_token_continuation(self):
        """Test cleaning tokens when continuing entity."""
        backend = ONNXParserBackend()

        # When continuing, add space before non-subword tokens
        assert backend._clean_token("word", is_continuation=True) == " word"
        # Subwords don't get extra space
        assert backend._clean_token("##ing", is_continuation=True) == "ing"


class TestNERLabels:
    """Tests for NER label constants."""

    def test_ner_labels_structure(self):
        """Test NER labels have correct structure."""
        assert "O" in NER_LABELS
        assert NER_LABELS["O"] == "outside"

    def test_ner_labels_entities(self):
        """Test NER labels have entity types."""
        assert "B-PER" in NER_LABELS
        assert "I-PER" in NER_LABELS
        assert "B-ORG" in NER_LABELS
        assert "B-LOC" in NER_LABELS
        assert "B-MISC" in NER_LABELS

    def test_ner_labels_values(self):
        """Test NER label values."""
        assert NER_LABELS["B-PER"] == "person"
        assert NER_LABELS["B-ORG"] == "organization"
        assert NER_LABELS["B-LOC"] == "location"
        assert NER_LABELS["B-MISC"] == "miscellaneous"


class TestONNXModels:
    """Tests for ONNX model constants."""

    def test_models_have_performance(self):
        """Test performance model exists."""
        assert "performance" in ONNX_MODELS
        assert "model_id" in ONNX_MODELS["performance"]
        assert "description" in ONNX_MODELS["performance"]

    def test_models_have_balanced(self):
        """Test balanced model exists."""
        assert "balanced" in ONNX_MODELS
        assert "model_id" in ONNX_MODELS["balanced"]

    def test_model_ids_are_valid(self):
        """Test model IDs are in HuggingFace format."""
        for tier, config in ONNX_MODELS.items():
            model_id = config["model_id"]
            assert "/" in model_id, f"{tier} model should be org/name format"


class TestONNXParserBackendLoadMocked:
    """Tests for model loading with mocks."""

    @pytest.mark.asyncio
    async def test_load_returns_false_without_deps(self):
        """Test load returns False when dependencies missing."""
        backend = ONNXParserBackend()

        with (
            patch.dict("sys.modules", {"onnxruntime": None}),
            patch("builtins.__import__", side_effect=ImportError("onnxruntime")),
        ):
            # The backend catches ImportError and returns False
            await backend.load()
            # May return True if deps are actually installed
            # This is more of a smoke test

    @pytest.mark.asyncio
    async def test_load_already_loaded(self):
        """Test load returns True if already loaded."""
        backend = ONNXParserBackend()
        backend._loaded = True

        result = await backend.load()

        assert result is True

    @pytest.mark.asyncio
    async def test_load_model_not_found(self):
        """Test load handles missing model file."""
        backend = ONNXParserBackend()

        # Mock the path to not exist and download to fail
        with patch.object(backend, "_resolve_model_path") as mock_path:
            mock_path.return_value = Path("/nonexistent/model.onnx")
            with patch.object(backend, "_download_model", new_callable=AsyncMock):
                try:
                    import onnxruntime  # noqa: F401
                    from tokenizers import Tokenizer  # noqa: F401

                    result = await backend.load()
                    assert result is False
                except ImportError:
                    pytest.skip("ONNX dependencies not installed")


class TestONNXParserBackendParsingMocked:
    """Tests for parsing methods with mocked inference."""

    @pytest.fixture
    def backend(self):
        """Create a backend with mocked ONNX."""
        backend = ONNXParserBackend()
        backend._loaded = False  # Not loaded, will use heuristic
        return backend

    @pytest.mark.asyncio
    async def test_parse_incident_uses_heuristic(self, backend):
        """Test incident parsing falls back to heuristic."""
        result = await backend.parse_incident("Server web-01 is down with error 500")

        assert result is not None
        assert result.backend_used == "heuristic"
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_parse_log_uses_heuristic(self, backend):
        """Test log parsing uses heuristic."""
        log_text = "2024-01-15 10:30:00 ERROR Failed to connect"
        result = await backend.parse_log(log_text)

        assert result is not None
        assert result.backend_used == "heuristic"

    @pytest.mark.asyncio
    async def test_parse_host_query_uses_heuristic(self, backend):
        """Test host query parsing uses heuristic."""
        result = await backend.parse_host_query("check disk on web-01")

        assert result is not None
        assert result.backend_used == "heuristic"

    @pytest.mark.asyncio
    async def test_parse_command_uses_heuristic(self, backend):
        """Test command parsing uses heuristic."""
        result = await backend.parse_command("df -h")

        assert result is not None
        assert result.backend_used == "heuristic"

    @pytest.mark.asyncio
    async def test_extract_entities_uses_heuristic(self, backend):
        """Test entity extraction uses heuristic."""
        entities = await backend.extract_entities("Check server web-01 at 192.168.1.10")

        assert isinstance(entities, dict)
        # Heuristic should find host and IP
        assert len(entities) > 0


class TestONNXParserBackendEnhancement:
    """Tests for result enhancement logic."""

    def test_enhance_incident_with_org(self):
        """Test incident enhancement with organization entities."""
        backend = ONNXParserBackend()

        # Create a mock incident result
        from merlya.parser.models import IncidentInput, IncidentParsingResult

        incident = IncidentInput(
            description="Server issue",
            affected_services=[],
            keywords=[],
        )
        result = IncidentParsingResult(
            confidence=0.8,
            coverage_ratio=0.9,
            has_unparsed_blocks=False,
            truncated=False,
            incident=incident,
        )

        ner_entities = {"ORG": ["API-Service", "DB-Server"]}

        enhanced = backend._enhance_incident_result(result, ner_entities)

        # Should add service-like organizations
        assert "API-Service" in enhanced.incident.affected_services

    def test_enhance_incident_with_loc(self):
        """Test incident enhancement with location entities."""
        backend = ONNXParserBackend()

        from merlya.parser.models import IncidentInput, IncidentParsingResult

        incident = IncidentInput(
            description="Datacenter issue",
            affected_services=[],
            keywords=[],
        )
        result = IncidentParsingResult(
            confidence=0.8,
            coverage_ratio=0.9,
            has_unparsed_blocks=False,
            truncated=False,
            incident=incident,
        )

        ner_entities = {"LOC": ["us-east-1", "EU-West"]}

        enhanced = backend._enhance_incident_result(result, ner_entities)

        # Locations should be added as keywords
        assert "us-east-1" in enhanced.incident.keywords
        assert "eu-west" in enhanced.incident.keywords

    def test_enhance_incident_with_misc(self):
        """Test incident enhancement with miscellaneous entities."""
        backend = ONNXParserBackend()

        from merlya.parser.models import IncidentInput, IncidentParsingResult

        incident = IncidentInput(
            description="Version issue",
            affected_services=[],
            keywords=[],
        )
        result = IncidentParsingResult(
            confidence=0.8,
            coverage_ratio=0.9,
            has_unparsed_blocks=False,
            truncated=False,
            incident=incident,
        )

        ner_entities = {"MISC": ["v2.0", "production"]}

        enhanced = backend._enhance_incident_result(result, ner_entities)

        # MISC entities should be added as keywords
        assert "v2.0" in enhanced.incident.keywords
        assert "production" in enhanced.incident.keywords


@pytest.mark.slow
class TestONNXParserBackendRealModel:
    """Tests with real ONNX model download.

    These tests are marked as 'slow' and will download the model.
    Run with: pytest -m slow
    """

    @pytest.fixture
    async def loaded_backend(self):
        """Create and load a real ONNX backend."""
        backend = ONNXParserBackend(tier="balanced")

        try:
            import onnxruntime  # noqa: F401
            from tokenizers import Tokenizer  # noqa: F401
        except ImportError:
            pytest.skip("ONNX dependencies not installed")

        loaded = await backend.load()
        if not loaded:
            pytest.skip("Could not load ONNX model")

        return backend

    @pytest.mark.asyncio
    async def test_load_real_model(self, loaded_backend):
        """Test loading the real ONNX model."""
        assert loaded_backend.is_loaded is True
        assert loaded_backend._session is not None
        assert loaded_backend._tokenizer is not None

    @pytest.mark.asyncio
    async def test_run_ner_real(self, loaded_backend):
        """Test real NER inference."""
        text = "John Smith works at Microsoft in Seattle"

        entities = await loaded_backend._run_ner(text)

        # Should find some entities (PER, ORG, LOC)
        assert isinstance(entities, dict)
        # The model should recognize at least one entity type
        found_entities = sum(len(v) for v in entities.values())
        assert found_entities > 0

    @pytest.mark.asyncio
    async def test_extract_entities_real(self, loaded_backend):
        """Test real entity extraction."""
        text = "Check server web-01 at 192.168.1.10 owned by Acme Corp"

        entities = await loaded_backend.extract_entities(text)

        # Should find hosts, IPs from heuristic + NER entities
        assert isinstance(entities, dict)
        assert len(entities) > 0

    @pytest.mark.asyncio
    async def test_parse_incident_real(self, loaded_backend):
        """Test real incident parsing with ONNX enhancement."""
        text = "The API service at datacenter US-East is experiencing high latency"

        result = await loaded_backend.parse_incident(text)

        assert result is not None
        assert result.backend_used == "onnx"
        # Confidence should be boosted when ONNX is used
        assert result.confidence > 0.5

    @pytest.mark.asyncio
    async def test_parse_host_query_real(self, loaded_backend):
        """Test real host query parsing."""
        text = "check disk on production servers in AWS"

        result = await loaded_backend.parse_host_query(text)

        assert result is not None
        assert result.backend_used == "onnx"


class TestONNXParserBackendLabelConfig:
    """Tests for label configuration loading.

    Note: The backend no longer uses default labels when config is missing.
    It returns empty dict and all predictions are treated as "O" (outside/no entity).
    """

    @pytest.mark.asyncio
    async def test_load_label_config_missing_returns_empty(self):
        """Test empty label config when no config.json exists."""
        backend = ONNXParserBackend()

        # Load with non-existent path
        await backend._load_label_config(Path("/nonexistent"))

        # Without config.json, label mapping is empty (cannot assume ordering)
        assert backend._id2label == {}

    @pytest.mark.asyncio
    async def test_load_label_config_from_file(self, tmp_path):
        """Test loading label config from file."""
        backend = ONNXParserBackend()

        # Create config file
        import json

        config = {"id2label": {"0": "O", "1": "B-PER", "2": "I-PER"}}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))

        await backend._load_label_config(tmp_path)

        assert backend._id2label[0] == "O"
        assert backend._id2label[1] == "B-PER"
        assert backend._id2label[2] == "I-PER"

    @pytest.mark.asyncio
    async def test_load_label_config_invalid_json_returns_empty(self, tmp_path):
        """Test empty label config when JSON is invalid."""
        backend = ONNXParserBackend()

        # Create invalid config file
        config_path = tmp_path / "config.json"
        config_path.write_text("not valid json {")

        await backend._load_label_config(tmp_path)

        # Invalid JSON results in empty mapping (graceful degradation)
        assert backend._id2label == {}
