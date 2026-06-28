from __future__ import annotations

"""Gemini model pool and tier helpers for scoring-driven model selection.

The evolution engine explores this pool per agent: an under-performing agent
can be upgraded to the next (more capable) tier, and an over-provisioned agent
can be downgraded to save cost. The validation gate accepts a candidate only if
its judged score (or tool-call efficiency) improves, so model changes that help
are kept and ones that don't are discarded.
"""

from typing import Optional

# Cheapest → most capable. Agents start on gemini-2.5-flash (the seed tier and
# the compiler's DEFAULT_AGENT_MODEL); the engine explores up and down from there.
# All served via the Generative Language API (GeminiAPIClient) — verified
# reachable with the project key. Add newer tiers here as they become available.
GEMINI_MODEL_POOL = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-3.5-flash",
    "gemini-2.5-pro",
]


def _pool_index(model: Optional[str]) -> int:
    """Return the pool index of `model`, defaulting to the flash (middle) tier.

    Unknown / None / legacy model names are treated as the flash tier so the
    next-tier math stays well-defined.
    """
    if model in GEMINI_MODEL_POOL:
        return GEMINI_MODEL_POOL.index(model)
    # Default agents (None, "mock", legacy 1.5 names) map to flash.
    return GEMINI_MODEL_POOL.index("gemini-2.5-flash")


def next_tier(model: Optional[str]) -> Optional[str]:
    """The next more-capable model in the pool, or None if already at the top."""
    idx = _pool_index(model)
    if idx >= len(GEMINI_MODEL_POOL) - 1:
        return None
    return GEMINI_MODEL_POOL[idx + 1]


def prev_tier(model: Optional[str]) -> Optional[str]:
    """The next cheaper model in the pool, or None if already at the bottom."""
    idx = _pool_index(model)
    if idx <= 0:
        return None
    return GEMINI_MODEL_POOL[idx - 1]
