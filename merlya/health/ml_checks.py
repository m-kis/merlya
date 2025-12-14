"""
Merlya Health - ML checks module.

Provides machine learning model health checks (ONNX).
"""

from __future__ import annotations

import os

from merlya.core.types import CheckStatus, HealthCheck
from merlya.router.intent_classifier import IntentClassifier
from merlya.skills.registry import get_registry as get_skills_registry


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


async def check_onnx_for_skills(tier: str | None = None) -> HealthCheck:
    """
    Check if ONNX model loads correctly when skills are enabled.

    This is a CRITICAL check: if skills are registered and ONNX fails to load,
    Merlya should not start (unless LLM fallback is configured for skill matching).

    Args:
        tier: Model tier for ONNX model selection.

    Returns:
        HealthCheck with critical=True if ONNX required but unavailable.
    """
    from loguru import logger

    from merlya.config import get_config

    config = get_config()

    # Check if skills are enabled
    try:
        registry = get_skills_registry()
        stats = registry.get_stats()
        skills_count = stats.get("total", 0)
    except Exception:
        skills_count = 0

    if skills_count == 0:
        return HealthCheck(
            name="onnx_skills",
            status=CheckStatus.OK,
            message="ℹ️ No skills loaded - ONNX not required",
            details={"skills_count": 0, "onnx_required": False},
        )

    # Check if LLM fallback is configured for skill matching
    llm_fallback = config.router.llm_fallback
    has_llm_fallback = bool(llm_fallback)

    # Try to actually load the ONNX model
    try:
        classifier = IntentClassifier(use_embeddings=True, tier=tier)
        loaded = await classifier.load_model(allow_download=False)

        if loaded and classifier.model_loaded:
            return HealthCheck(
                name="onnx_skills",
                status=CheckStatus.OK,
                message=f"✅ ONNX model loaded for skill matching ({skills_count} skills)",
                details={
                    "skills_count": skills_count,
                    "onnx_loaded": True,
                    "llm_fallback": has_llm_fallback,
                },
            )
    except Exception as e:
        logger.warning(f"⚠️ ONNX load failed: {e}")

    # ONNX failed to load
    if has_llm_fallback:
        # LLM fallback available - warning only
        return HealthCheck(
            name="onnx_skills",
            status=CheckStatus.WARNING,
            message=f"⚠️ ONNX failed, using LLM fallback for {skills_count} skills",
            details={
                "skills_count": skills_count,
                "onnx_loaded": False,
                "llm_fallback": llm_fallback,
            },
        )
    else:
        # No fallback - CRITICAL ERROR
        return HealthCheck(
            name="onnx_skills",
            status=CheckStatus.ERROR,
            message=f"❌ ONNX required for skills but failed to load ({skills_count} skills)",
            critical=True,
            details={
                "skills_count": skills_count,
                "onnx_loaded": False,
                "llm_fallback": None,
                "fix": "Configure router.llm_fallback or fix ONNX installation",
            },
        )
