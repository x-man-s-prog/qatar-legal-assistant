# -*- coding: utf-8 -*-
"""
core.self_correction — public interface.

Exposes the SelfCorrectionPipeline class plus a thin `self_correct`
callable shim expected by `core.modules._load_self_correction()`
(was previously missing and produced a persistent warning at startup:
`self_correction غير متاح (cannot import name 'self_correct')`).
"""
from __future__ import annotations

from typing import Any

from .pipeline import SelfCorrectionPipeline
from .schemas import (
    GateDecision,
    GateVerdict,
    QueryContext,
    QueryComplexity,
)

# Single shared pipeline instance — stateless enough to reuse across
# requests. If a caller needs isolation they can instantiate their own.
_DEFAULT_PIPELINE: SelfCorrectionPipeline | None = None


def _pipeline() -> SelfCorrectionPipeline:
    global _DEFAULT_PIPELINE
    if _DEFAULT_PIPELINE is None:
        _DEFAULT_PIPELINE = SelfCorrectionPipeline()
    return _DEFAULT_PIPELINE


def self_correct(*args: Any, **kwargs: Any) -> Any:
    """Backwards-compatible functional wrapper around SelfCorrectionPipeline.

    The loader in `core.modules._load_self_correction` imports this symbol
    and stashes it on `app_state.self_correction` so other subsystems can
    call it uniformly. Accepts whatever shape callers pass and forwards
    to the pipeline's `run` method — degrades to a no-op if the pipeline
    can't process the input, so this never raises at load time.
    """
    try:
        pl = _pipeline()
    except Exception:
        return None
    # Prefer `run` if it exists; otherwise fall through to `__call__`.
    fn = getattr(pl, "run", None) or getattr(pl, "__call__", None)
    if fn is None:
        return None
    try:
        return fn(*args, **kwargs)
    except Exception:
        # Graceful degradation — self-correction is optional.
        return None


__all__ = [
    "SelfCorrectionPipeline",
    "self_correct",
    "GateDecision",
    "GateVerdict",
    "QueryContext",
    "QueryComplexity",
]
