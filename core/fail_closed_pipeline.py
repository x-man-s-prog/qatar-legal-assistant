# -*- coding: utf-8 -*-
"""
core.fail_closed_pipeline — DECOMMISSIONED.

The entire fail-closed 8-gate pipeline (`FailClosedPipeline`,
`answer_fail_closed`, `get_fail_closed_pipeline`) was retired during
the runtime_v2 cutover. Legal reasoning is now produced exclusively
by `core.runtime_v2` (entry via `core.runtime_v2.adapter.answer_json`).

Any attempt to call the old entry points raises
`LegacyRuntimeDecommissionedError`. There is no fallback and no
compatibility path by design.

Migration map:
    answer_fail_closed(query)        → core.runtime_v2.answer(query)
    get_fail_closed_pipeline()       → (no replacement; not needed)
    FailClosedPipeline().run(query)  → core.runtime_v2.answer(query)
"""
from __future__ import annotations

from core.production_runtime import (
    LegacyRuntimeDecommissionedError,
    LEGACY_DECOMMISSION_MESSAGE,
)


def _seal(entry: str):
    def _stub(*args, **kwargs):
        raise LegacyRuntimeDecommissionedError(entry=entry)
    _stub.__name__ = entry
    _stub.__qualname__ = entry
    return _stub


# ── Sealed public entry points ───────────────────────────────────────
answer_fail_closed       = _seal("answer_fail_closed")
get_fail_closed_pipeline = _seal("get_fail_closed_pipeline")


class FailClosedPipeline:
    """Sealed shell of the former fail-closed pipeline class."""

    def __init__(self, *args, **kwargs):
        raise LegacyRuntimeDecommissionedError(
            entry="FailClosedPipeline.__init__",
        )

    def run(self, *args, **kwargs):
        raise LegacyRuntimeDecommissionedError(
            entry="FailClosedPipeline.run",
        )

    def _build_insufficiency(self, *args, **kwargs):
        raise LegacyRuntimeDecommissionedError(
            entry="FailClosedPipeline._build_insufficiency",
        )


class FailClosedResult:
    """Sealed shell of the former result dataclass — kept importable so
    old module references do not explode at import time, but any
    instantiation raises the decommission error."""

    def __init__(self, *args, **kwargs):
        raise LegacyRuntimeDecommissionedError(
            entry="FailClosedResult.__init__",
        )


__all__ = [
    "LegacyRuntimeDecommissionedError",
    "LEGACY_DECOMMISSION_MESSAGE",
    "answer_fail_closed",
    "get_fail_closed_pipeline",
    "FailClosedPipeline",
    "FailClosedResult",
]
