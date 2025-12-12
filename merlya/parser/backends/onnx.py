"""
Merlya Parser - ONNX backend using NER models for entity extraction.

This backend uses ONNX models for Named Entity Recognition:
- tier=balanced: Xenova/distilbert-NER (smaller, faster)
- tier=performance: Xenova/bert-base-NER (more accurate)

Falls back to heuristic parsing if ONNX is not available.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.parser.backends.base import ParserBackend
from merlya.parser.backends.heuristic import HeuristicBackend

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from merlya.parser.models import (
        CommandParsingResult,
        HostQueryParsingResult,
        IncidentParsingResult,
        LogParsingResult,
    )

# Import centralized tier configuration
from merlya.config.tiers import (
    PARSER_MODELS,
    ModelTier,
    get_parser_model_id,
    resolve_parser_model_path,
)

# Legacy alias for backwards compatibility (used in tests)
ONNX_MODELS = {
    "performance": {
        "model_id": PARSER_MODELS[ModelTier.PERFORMANCE].model_id,
        "description": PARSER_MODELS[ModelTier.PERFORMANCE].description,
    },
    "balanced": {
        "model_id": PARSER_MODELS[ModelTier.BALANCED].model_id,
        "description": PARSER_MODELS[ModelTier.BALANCED].description,
    },
}

# NER label mapping (IOB format)
NER_LABELS = {
    "O": "outside",
    "B-PER": "person",
    "I-PER": "person",
    "B-ORG": "organization",
    "I-ORG": "organization",
    "B-LOC": "location",
    "I-LOC": "location",
    "B-MISC": "miscellaneous",
    "I-MISC": "miscellaneous",
}


class ONNXParserBackend(ParserBackend):
    """
    ONNX-based parser backend using NER models.

    Uses Named Entity Recognition to extract structured information.
    Falls back to HeuristicBackend for parsing logic, but enhances
    entity extraction with ONNX NER.
    """

    def __init__(
        self,
        tier: str = "balanced",
        model_id: str | None = None,
    ) -> None:
        """
        Initialize the ONNX parser backend.

        Args:
            tier: Model tier (balanced/performance).
            model_id: Optional explicit model ID override.
        """
        self._tier = tier
        self._model_id = model_id or self._select_model_id(tier)
        self._session: Any | None = None
        self._tokenizer: Any | None = None
        self._loaded = False
        self._id2label: dict[int, str] = {}

        # Fallback to heuristic for complex parsing logic
        self._heuristic = HeuristicBackend()

        logger.debug(f"🧠 ONNXParserBackend initialized with model: {self._model_id}")

    @property
    def name(self) -> str:
        """Return the backend name."""
        return "onnx"

    @property
    def is_loaded(self) -> bool:
        """Return True if the ONNX model is loaded."""
        return self._loaded

    def _select_model_id(self, tier: str) -> str:
        """Select model ID based on tier using centralized config."""
        return get_parser_model_id(tier)

    def _resolve_model_path(self, model_id: str) -> Path:
        """Resolve local model path using centralized config."""
        return resolve_parser_model_path(model_id)

    async def load(self) -> bool:
        """Load the ONNX NER model."""
        if self._loaded:
            return True

        try:
            import onnxruntime as ort  # noqa: F401
            from tokenizers import Tokenizer  # noqa: F401
        except ImportError as e:
            logger.warning(f"⚠️ ONNX dependencies not available: {e}")
            logger.info("ℹ️ Falling back to heuristic backend")
            return False

        try:
            model_path = self._resolve_model_path(self._model_id)
            tokenizer_path = model_path.parent / "tokenizer.json"

            # Download if not exists
            if not model_path.exists() or not tokenizer_path.exists():
                await self._download_model(model_path, tokenizer_path)

            if not model_path.exists():
                logger.warning(f"⚠️ ONNX model not found: {model_path}")
                return False

            if not tokenizer_path.exists():
                logger.warning(f"⚠️ ONNX tokenizer not found: {tokenizer_path}")
                return False

            # Load in thread
            self._session, self._tokenizer = await asyncio.to_thread(
                self._load_onnx_and_tokenizer, model_path, tokenizer_path
            )

            # Load label mapping
            await self._load_label_config(model_path.parent)

            self._loaded = True
            logger.info(f"✅ ONNX parser model loaded: {self._model_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to load ONNX parser model: {e}")
            return False

    def _load_onnx_and_tokenizer(self, model_path: Path, tokenizer_path: Path) -> tuple[Any, Any]:
        """Load ONNX session and tokenizer (runs in thread)."""
        import onnxruntime as ort
        from tokenizers import Tokenizer

        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess = ort.InferenceSession(str(model_path), sess_options)
        tok = Tokenizer.from_file(str(tokenizer_path))
        return sess, tok

    async def _download_model(self, model_path: Path, tokenizer_path: Path) -> None:
        """Download ONNX model and tokenizer."""

        def _do_download() -> None:
            """Blocking download and file copy operations."""
            from huggingface_hub import hf_hub_download

            target_dir = model_path.parent
            target_dir.mkdir(parents=True, exist_ok=True)

            logger.info(f"🔽 Downloading parser model: {self._model_id}...")

            onnx_src = hf_hub_download(repo_id=self._model_id, filename="onnx/model.onnx")
            tokenizer_src = hf_hub_download(repo_id=self._model_id, filename="tokenizer.json")

            # Copy to local directory
            model_path.write_bytes(Path(onnx_src).read_bytes())
            tokenizer_path.write_bytes(Path(tokenizer_src).read_bytes())

            # Try to download config for label mapping
            try:
                config_src = hf_hub_download(repo_id=self._model_id, filename="config.json")
                config_path = model_path.parent / "config.json"
                config_path.write_bytes(Path(config_src).read_bytes())
            except Exception:
                logger.debug("No config.json found for model")

            logger.info(f"✅ Downloaded parser model to {model_path}")

        try:
            await asyncio.to_thread(_do_download)
        except Exception as e:
            logger.warning(f"⚠️ Could not download ONNX model: {e}")

    async def _load_label_config(self, model_dir: Path) -> None:
        """Load label configuration from config.json."""
        config_path = model_dir / "config.json"
        if not config_path.exists():
            # Cannot assume label ordering without config - use empty mapping
            # which will treat all predictions as "O" (outside/no entity)
            logger.warning(
                f"⚠️ No config.json found in {model_dir}; "
                "NER label mapping unavailable, entity extraction will be limited"
            )
            self._id2label = {}
            return

        try:
            import json

            config = json.loads(config_path.read_text())
            if "id2label" in config:
                self._id2label = {int(k): v for k, v in config["id2label"].items()}
            else:
                # Config exists but no id2label - cannot assume ordering
                logger.warning(
                    "⚠️ config.json missing 'id2label' field; "
                    "NER label mapping unavailable, entity extraction will be limited"
                )
                self._id2label = {}
        except Exception as e:
            logger.debug(f"Could not load label config: {e}")
            self._id2label = {}

    async def parse_incident(self, text: str) -> IncidentParsingResult:
        """Parse text as an incident using ONNX NER + heuristic."""
        start_time = time.perf_counter()

        # Get base parsing from heuristic
        result = await self._heuristic.parse_incident(text)

        # Enhance with ONNX NER if loaded
        if self._loaded:
            ner_entities = await self._run_ner(text)
            result = self._enhance_incident_result(result, ner_entities)
            result.backend_used = self.name
            # Increase confidence when ONNX is used
            result.confidence = min(result.confidence + 0.15, 0.95)

        result.parse_time_ms = (time.perf_counter() - start_time) * 1000
        return result

    async def parse_log(self, text: str) -> LogParsingResult:
        """Parse text as log output."""
        start_time = time.perf_counter()

        # Get base parsing from heuristic
        result = await self._heuristic.parse_log(text)

        # NER doesn't add much for logs, keep heuristic result
        if self._loaded:
            result.backend_used = self.name

        result.parse_time_ms = (time.perf_counter() - start_time) * 1000
        return result

    async def parse_host_query(self, text: str) -> HostQueryParsingResult:
        """Parse text as a host query."""
        start_time = time.perf_counter()

        result = await self._heuristic.parse_host_query(text)

        if self._loaded:
            ner_entities = await self._run_ner(text)
            # Enhance host detection with NER
            if "ORG" in ner_entities:
                for org in ner_entities["ORG"]:
                    # Only add if it looks like a valid hostname (not generic org names)
                    if org not in result.query.target_hosts and self._looks_like_hostname(org):
                        result.query.target_hosts.append(org)
            result.backend_used = self.name

        result.parse_time_ms = (time.perf_counter() - start_time) * 1000
        return result

    async def parse_command(self, text: str) -> CommandParsingResult:
        """Parse text as a command."""
        start_time = time.perf_counter()

        result = await self._heuristic.parse_command(text)

        if self._loaded:
            result.backend_used = self.name

        result.parse_time_ms = (time.perf_counter() - start_time) * 1000
        return result

    async def extract_entities(self, text: str) -> dict[str, list[str]]:
        """Extract named entities using ONNX NER."""
        # Start with heuristic entities
        entities = await self._heuristic.extract_entities(text)

        # Enhance with NER if loaded
        if self._loaded:
            ner_entities = await self._run_ner(text)
            # Merge NER entities with heuristic ones
            for entity_type, values in ner_entities.items():
                key = entity_type.lower()
                if key in entities:
                    entities[key] = list(set(entities[key] + values))
                else:
                    entities[key] = values

        return entities

    async def _run_ner(self, text: str) -> dict[str, list[str]]:
        """Run ONNX NER inference on text."""
        if not self._loaded or not self._session or not self._tokenizer:
            return {}

        try:
            import numpy as np

            # Tokenize
            encoding = self._tokenizer.encode(text)
            input_ids = np.array([encoding.ids], dtype=np.int64)
            attention_mask = np.array([encoding.attention_mask], dtype=np.int64)

            # Build inputs
            assert self._session is not None  # Already checked above
            model_inputs = {i.name for i in self._session.get_inputs()}
            run_inputs: dict[str, NDArray[Any]] = {"input_ids": input_ids}
            if "attention_mask" in model_inputs:
                run_inputs["attention_mask"] = attention_mask
            if "token_type_ids" in model_inputs:
                run_inputs["token_type_ids"] = np.zeros_like(input_ids, dtype=np.int64)

            # Run inference in thread (capture session reference for closure)
            session = self._session

            def _infer() -> NDArray[Any]:
                outputs = session.run(None, run_inputs)
                logits: NDArray[Any] = outputs[0]
                return logits

            logits = await asyncio.to_thread(_infer)

            # Get predictions
            predictions = np.argmax(logits, axis=-1)[0]
            tokens = encoding.tokens

            # Extract entities
            entities: dict[str, list[str]] = {}
            current_entity = ""
            current_type = ""

            for _i, (token, pred) in enumerate(zip(tokens, predictions, strict=False)):
                label = self._id2label.get(int(pred), "O")

                if label.startswith("B-"):
                    # New entity starts
                    if current_entity and current_type:
                        if current_type not in entities:
                            entities[current_type] = []
                        entities[current_type].append(current_entity.strip())
                    current_entity = self._clean_token(token)
                    current_type = label[2:]

                elif label.startswith("I-") and label[2:] == current_type:
                    # Continue current entity
                    current_entity += self._clean_token(token, is_continuation=True)

                else:
                    # End of entity
                    if current_entity and current_type:
                        if current_type not in entities:
                            entities[current_type] = []
                        entities[current_type].append(current_entity.strip())
                    current_entity = ""
                    current_type = ""

            # Don't forget last entity
            if current_entity and current_type:
                if current_type not in entities:
                    entities[current_type] = []
                entities[current_type].append(current_entity.strip())

            return entities

        except Exception as e:
            logger.debug(f"NER inference error: {e}")
            return {}

    def _clean_token(self, token: str, is_continuation: bool = False) -> str:
        """Clean a token from subword markers.

        Args:
            token: The token to clean.
            is_continuation: Whether this token continues a previous entity.
        """
        # Remove ## prefix (BERT subword) - no space needed
        if token.startswith("##"):
            return token[2:]
        # Remove Ġ prefix (GPT-style) - space already included
        if token.startswith("Ġ"):
            return " " + token[1:]
        # Non-subword token: add space if continuing an entity
        if is_continuation:
            return " " + token
        return token

    def _looks_like_hostname(self, value: str) -> bool:
        """Check if a value looks like a valid hostname.

        Filters out generic organization names that are unlikely to be hostnames.
        """
        import re

        # Must have at least one dot or hyphen (typical hostname patterns)
        # or contain common hostname indicators
        hostname_indicators = (
            "." in value
            or "-" in value
            or value.endswith(("-server", "-db", "-api", "-app", "-host", "-node"))
            or bool(re.match(r"^[a-z0-9]+-[a-z0-9]+$", value.lower()))  # e.g., web-01
        )

        # Reject if it looks like a generic organization name
        generic_orgs = {
            "microsoft",
            "amazon",
            "google",
            "apple",
            "facebook",
            "meta",
            "netflix",
            "twitter",
            "oracle",
            "ibm",
            "intel",
            "cisco",
            "vmware",
            "redhat",
            "ubuntu",
            "debian",
            "linux",
            "windows",
        }
        if value.lower() in generic_orgs:
            return False

        # Reject if contains spaces (hostnames don't have spaces)
        if " " in value:
            return False

        return hostname_indicators

    def _enhance_incident_result(
        self,
        result: IncidentParsingResult,
        ner_entities: dict[str, list[str]],
    ) -> IncidentParsingResult:
        """Enhance incident result with NER entities."""
        # Add organizations as potential services/hosts
        if "ORG" in ner_entities:
            for org in ner_entities["ORG"]:
                # Check if not already in services and looks like a service name
                if org.lower() not in [
                    s.lower() for s in result.incident.affected_services
                ] and any(
                    pattern in org.lower() for pattern in ["service", "server", "db", "api", "app"]
                ):
                    result.incident.affected_services.append(org)

        # Add locations as potential hosts
        if "LOC" in ner_entities:
            for loc in ner_entities["LOC"]:
                # Locations might be datacenter names or regions
                if loc.lower() not in result.incident.keywords:
                    result.incident.keywords.append(loc.lower())

        # Add miscellaneous as keywords
        if "MISC" in ner_entities:
            for misc in ner_entities["MISC"]:
                if misc.lower() not in result.incident.keywords:
                    result.incident.keywords.append(misc.lower())

        return result
