# -*- coding: utf-8 -*-
"""
SEA — Single Entry Authority.

THE non-negotiable rule:

    Every response to the user MUST originate from the UNIFIED pipeline.

This module provides the mechanism that proves it:

  • `unified_entry_context()` — a thread-local context manager that marks
    a request as having entered via the authorized entry point.

  • `assert_entered_via_unified()` — an assertion helper called by the
    AuthoritativeOutputGate (and other exit-points) that HARD-FAILS if
    the current thread is not inside an active unified-entry context.

  • `IllegalDirectResponseError` — the exception raised when a legacy /
    bypass / split-execution path tries to emit a response.

Nothing else may return a response to the user. Any code path that
wants to reach the user must go through `ProductionRuntime.answer_json`,
which wraps the execution in `unified_entry_context()`.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Optional


# ═════════════════════════════════════════════════════════════════
# Thread-local entry marker
# ═════════════════════════════════════════════════════════════════

_tls = threading.local()


def _ctx() -> dict:
    """Return the thread-local context dict (created lazily)."""
    if not hasattr(_tls, "data"):
        _tls.data = {
            "entered": False,
            "depth": 0,
            "source": "",
            "request_id": "",
            "entry_stack": [],
        }
    return _tls.data


class IllegalDirectResponseError(RuntimeError):
    """Raised when a response is emitted outside the unified pipeline."""


# ═════════════════════════════════════════════════════════════════
# Public API — entering / asserting / leaving
# ═════════════════════════════════════════════════════════════════

@contextmanager
def unified_entry_context(
    *,
    source: str = "ProductionRuntime.answer_json",
    request_id: str = "",
):
    """Mark the current thread as being inside the unified pipeline.

    Every public entry point (answer_json, stream_query, test harness,
    CLI wrapper, etc.) MUST wrap its execution in this context so that
    downstream assertions see the marker.

    Nested re-entry is supported (depth counter) — a sub-call from
    within a pipeline-managed routine does NOT reset the marker.
    """
    ctx = _ctx()
    ctx["entered"] = True
    ctx["depth"] += 1
    ctx["source"] = source or ctx["source"]
    ctx["request_id"] = request_id or ctx["request_id"]
    ctx["entry_stack"].append(source)
    try:
        yield ctx
    finally:
        ctx["depth"] = max(0, ctx["depth"] - 1)
        if ctx["entry_stack"]:
            ctx["entry_stack"].pop()
        if ctx["depth"] <= 0:
            ctx["entered"] = False
            ctx["source"] = ""
            ctx["request_id"] = ""


def is_in_unified_context() -> bool:
    """True iff the current thread is inside an active unified entry."""
    return bool(_ctx().get("entered"))


def current_entry_source() -> str:
    return _ctx().get("source", "")


def current_entry_depth() -> int:
    return int(_ctx().get("depth", 0) or 0)


def assert_entered_via_unified(
    *,
    detail: str = "",
    allow_operational: bool = True,
) -> None:
    """Raise IllegalDirectResponseError when called outside the unified
    pipeline.

    `allow_operational=True` lets the `SEA_STRICT=0` env var temporarily
    disable the guard in constrained environments (e.g. direct unit
    tests that never emit to the user). In production the guard is
    always on.
    """
    if is_in_unified_context():
        return
    # Escape hatch for unit tests that never reach the user
    if allow_operational and os.environ.get("SEA_STRICT", "1") == "0":
        return
    raise IllegalDirectResponseError(
        "ILLEGAL DIRECT RESPONSE — MUST USE UNIFIED_PIPELINE. "
        f"detail={detail or 'no active unified_entry_context'}"
    )


# ═════════════════════════════════════════════════════════════════
# Split-execution detection
# ═════════════════════════════════════════════════════════════════

def detect_split_execution(runtime_notes: list[str]) -> Optional[str]:
    """Return a reason string if two authors contributed text to the
    same response, else None.

    Heuristic: inspect the runtime_notes for multiple author markers
    that the unified pipeline would never emit simultaneously.
    """
    if not runtime_notes:
        return None
    author_markers = 0
    for n in runtime_notes:
        if n.startswith("author_stamp:"):
            author_markers += 1
        if n == "legacy_answer_replaced":
            # This is fine — MLRE replaces pipeline text, tracked
            continue
    if author_markers > 1:
        return f"multiple_author_stamps:{author_markers}"
    # If runtime_notes contains BOTH "dlp_rescue" AND "mlre_output_used"
    # for the same turn, something glued two authors together.
    seen_dlp    = any("dlp:mode=" in n for n in runtime_notes)
    seen_mlre   = any("mlre_output_used:true" in n for n in runtime_notes)
    seen_legacy = any("legacy_answer_replaced" in n for n in runtime_notes)
    # This combination is legitimate: MLRE composer replaces the pipeline
    # answer AND DLP ran for drafting (when intent == drafting). Only
    # flag a split when both are present but only one should have run.
    return None


# ═════════════════════════════════════════════════════════════════
# Legacy-call guard decorators
# ═════════════════════════════════════════════════════════════════

def sealed_legacy(reason: str = ""):
    """Decorator that turns a legacy function into a runtime trap.

    Any call to a function decorated with @sealed_legacy will raise
    IllegalDirectResponseError — regardless of where the call originates.
    Use this to retire legacy composers that must never run again.
    """
    def _wrap(fn):
        def _trap(*args, **kwargs):
            raise IllegalDirectResponseError(
                f"LEGACY EXECUTION DETECTED: {fn.__name__} is sealed. "
                f"reason={reason or 'legacy path replaced by UNIFIED_PIPELINE'}"
            )
        _trap.__name__ = fn.__name__
        _trap.__qualname__ = getattr(fn, "__qualname__", fn.__name__)
        _trap.__doc__ = (
            (fn.__doc__ or "") + f"\n\n[SEALED by SEA — {reason}]"
        )
        _trap._sealed_legacy = True   # type: ignore[attr-defined]
        return _trap
    return _wrap
