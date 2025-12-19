"""
Merlya Health - ML checks module.

Provides machine learning model health checks (ONNX).
"""

from __future__ import annotations

import os

from merlya.core.types import CheckStatus, HealthCheck
from merlya.router.intent_classifier import IntentClassifier


def check_onnx_model(tier: str | None = None) -> HealthCheck:
    """Check if ONNX embedding model is available or downloadable."""
    from merlya.config import get_config

    override = os.getenv("MERLYA_ROUTER_MODEL")
    config = get_config()
    cfg_model = getattr(config, "router", None)
    model_id = override or (cfg_model.model if cfg_model else None)

    # Use classifier helpers to resolve paths consistently
    selector = IntentClassifier(use_embeddings=False, model_id=model_id, tier=tier)
    selected_id = selector._select_model_id(model_id, tier)
    model_path = selector._resolve_model_path(selected_id)
    tokenizer_path = model_path.parent / "tokenizer.json"

    try:
        import onnxruntime  # noqa: F401
        from tokenizers import Tokenizer  # noqa: F401
    except ImportError as e:
        return HealthCheck(
            name="onnx_model",
            status=CheckStatus.DISABLED,
            message="⚠️ ONNX runtime not installed (router will use pattern matching)",
            details={"error": str(e), "can_download": False},
        )

    missing: list[str] = []
    if not model_path.exists():
        missing.append(str(model_path))
    if not tokenizer_path.exists():
        missing.append(str(tokenizer_path))

    if missing:
        return HealthCheck(
            name="onnx_model",
            status=CheckStatus.WARNING,
            message="⚠️ ONNX assets missing - will download automatically on first use",
            details={"missing": missing, "can_download": True},
        )

    size_mb = model_path.stat().st_size / (1024 * 1024)

    return HealthCheck(
        name="onnx_model",
        status=CheckStatus.OK,
        message=f"✅ ONNX model available ({size_mb:.1f}MB)",
        details={
            "model_path": str(model_path),
            "tokenizer_path": str(tokenizer_path),
            "size_mb": size_mb,
            "exists": True,
            "can_download": False,
        },
    )
