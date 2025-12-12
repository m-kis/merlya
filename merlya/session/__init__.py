"""
Merlya Session Module.

Manages conversation context, token budgets, and automatic summarization.

Components:
- TokenEstimator: Estimates token counts for messages
- ContextTierPredictor: Auto-detects optimal context tier
- SessionSummarizer: Hybrid summarization (ONNX → LLM → truncate)
- SessionManager: Main orchestrator

Usage:
    from merlya.session import SessionManager, ContextTier

    # Create manager
    manager = SessionManager(db=ctx.db, model="gpt-4")

    # Start session
    await manager.start_session(conversation_id="conv-123")

    # Add messages
    await manager.add_message(user_message, router_result)

    # Get context for LLM
    context = await manager.get_context_window()
    print(f"Using {context.token_estimate.total_tokens} tokens")

    # End session
    summary = await manager.end_session()
"""

from merlya.session.context_tier import (
    TIER_CONFIG,
    ComplexityFactors,
    ContextTier,
    ContextTierPredictor,
    TierLimits,
)
from merlya.session.manager import ContextWindow, SessionManager, SessionState
from merlya.session.summarizer import SessionSummarizer, SummaryResult
from merlya.session.token_estimator import TokenEstimate, TokenEstimator

__all__ = [
    "TIER_CONFIG",
    "ComplexityFactors",
    "ContextTier",
    # Context tier
    "ContextTierPredictor",
    "ContextWindow",
    # Main manager
    "SessionManager",
    "SessionState",
    # Summarization
    "SessionSummarizer",
    "SummaryResult",
    "TierLimits",
    "TokenEstimate",
    # Token estimation
    "TokenEstimator",
]
