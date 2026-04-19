# -*- coding: utf-8 -*-
"""
core.production_runtime — DECOMMISSIONED.

This module used to host the legacy `ProductionRuntime` / `answer_json`
stack. The system was cut over to `core.runtime_v2` and the legacy
engine was decommissioned in its entirety.

Any attempt to instantiate or call the old entry points now raises
`LegacyRuntimeDecommissionedError`. There is no fallback, no switch,
no dual-runtime mode. Every user-facing answer must come through
`core.runtime_v2.adapter.answer_json(...)` — routed by
`routers/query_router.py`.

Callers should migrate as follows:

    # Before
    from core.production_runtime import answer_query_direct
    resp = answer_query_direct(query, sid)

    # After
    from core.runtime_v2.adapter import answer_json
    resp = answer_json(query, session_id=sid)
"""
from __future__ import annotations


LEGACY_DECOMMISSION_MESSAGE = (
    "LEGACY RUNTIME DECOMMISSIONED — use core.runtime_v2.adapter.answer_json "
    "(routed by routers/query_router.py). "
    "No fallback exists by design; see core/runtime_v2/adapter.py."
)


class LegacyRuntimeDecommissionedError(RuntimeError):
    """Raised for every call into the decommissioned legacy runtime."""
    def __init__(self, *, entry: str = ""):
        msg = LEGACY_DECOMMISSION_MESSAGE
        if entry:
            msg = f"[{entry}] {msg}"
        super().__init__(msg)


def _seal(entry: str):
    def _stub(*args, **kwargs):
        raise LegacyRuntimeDecommissionedError(entry=entry)
    _stub.__name__ = entry
    _stub.__qualname__ = entry
    return _stub


# ── Sealed public entry points ───────────────────────────────────────
get_production_runtime = _seal("get_production_runtime")
answer_query_direct    = _seal("answer_query_direct")


class ProductionRuntime:
    """Sealed shell of the former production runtime class."""

    def __init__(self, *args, **kwargs):
        raise LegacyRuntimeDecommissionedError(
            entry="ProductionRuntime.__init__",
        )

    def answer_json(self, *args, **kwargs):
        raise LegacyRuntimeDecommissionedError(
            entry="ProductionRuntime.answer_json",
        )

    def stream_query(self, *args, **kwargs):
        raise LegacyRuntimeDecommissionedError(
            entry="ProductionRuntime.stream_query",
        )


__all__ = [
    "LegacyRuntimeDecommissionedError",
    "LEGACY_DECOMMISSION_MESSAGE",
    "get_production_runtime",
    "answer_query_direct",
    "ProductionRuntime",
]
