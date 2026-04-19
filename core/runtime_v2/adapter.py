# -*- coding: utf-8 -*-
"""
runtime_v2.adapter — the ONE and ONLY bridge between the HTTP layer
and runtime_v2.

Contract:
  • The HTTP router imports `answer_json` from this module — nothing
    else. It must NOT import `core.production_runtime` or any other
    legacy runtime.
  • Decision logic lives in runtime_v2. This adapter performs ONLY
    shape adaptation: it wraps `runtime_v2.answer(...)` and emits a
    response dict that matches the shape the current UI expects.
  • No fallback. No split execution. No legacy call. No switch.

Public functions:
  answer_json(query, session_id, history, *, request_id="")  → dict
  stream_frames(query, session_id, history, *, chunk=40)     → iterator
      yields ("start", dict), ("chunk", dict), ("done", dict) frames
"""
from __future__ import annotations

from typing import Iterable, Optional

from core.runtime_v2 import answer as _v2_answer
from core.runtime_v2.types import Response


# ═════════════════════════════════════════════════════════════════════
# UI-shape projection
# ═════════════════════════════════════════════════════════════════════

# Legacy-compatible field defaults so clients that rely on gate/trace
# keys do not break. Decision logic is in runtime_v2; these are pure
# inert scaffolding values for back-compat.
_EMPTY_TRACE = {
    "gates_passed":    [],
    "gates_failed":    [],
    "block_reasons":   [],
    "fatal_violations":[],
    "evidence_trace":  {},
    "sufficiency_level": "",
    "elapsed_seconds": 0.0,
}


def _response_to_http_dict(
    resp: Response,
    *,
    request_id: str = "",
    elapsed_seconds: float = 0.0,
) -> dict:
    """Project a runtime_v2.Response onto the wire shape the HTTP
    router and its clients expect. No decision logic here."""

    # Synthesize sources from verified evidence only
    sources = [
        {
            "citation":    e.citation,
            "summary":     e.summary,
            "is_verified": e.is_verified,
        }
        for e in resp.evidence
    ]

    # Confidence proxy: weight of the top path, else 0
    confidence = 0
    if resp.paths:
        confidence = int(round(resp.paths[0].weight * 100))

    # is_grounded: we return verified evidence whenever a concrete
    # domain matched. Generic skeletons are intentionally non-grounded.
    is_grounded = bool(resp.evidence) and resp.domain != "general_skeleton"

    # is_blocked: v2 never "blocks"; it may emit a skeleton. For the
    # wire contract we report is_blocked=False — the skeleton is a
    # legitimate response shape, not a block.
    is_blocked = False

    http: dict = {
        # ── Primary fields the UI reads ──
        "answer":           resp.answer_text,
        "sources":          sources,
        "domain":           resp.domain,
        "confidence":       confidence,
        "is_grounded":      is_grounded,
        "is_blocked":       is_blocked,

        # ── v2 authority stamp (visible so dashboards/ETLD can see it) ──
        "runtime":          "runtime_v2",
        "runtime_version":  "v2",
        "runtime_authority":"runtime_v2",
        "legacy_runtime_used": False,
        "authoritative_path":  "runtime_v2",
        "legacy_used":         False,
        "fallback_used":       False,

        # ── v2-native payload (opt-in for new clients) ──
        "intent":           resp.intent.value,
        "reasoning_mode":   resp.reasoning_mode.value,
        "drafting_mode":    (resp.drafting_mode.value
                                if resp.drafting_mode else None),
        "is_skeleton":      resp.is_skeleton,
        "paths": [
            {"label": p.label,
             "articles": list(p.articles),
             "weight": p.weight}
            for p in resp.paths
        ],
        "pivots": [
            {"question": p.question,
             "if_yes":   p.if_yes_path,
             "if_no":    p.if_no_path}
            for p in resp.pivots
        ],
        "established_facts": list(resp.established_facts),
        "missing_facts":     list(resp.missing_facts),

        # ── Memo (drafting intent only) ──
        "memo":             resp.memo_text,

        # ── Inert trace scaffolding for back-compat ──
        **_EMPTY_TRACE,
        "elapsed_seconds":  round(elapsed_seconds, 4),
    }
    if request_id:
        http["request_id"] = request_id
    return http


# ═════════════════════════════════════════════════════════════════════
# Public API — the ONLY two functions the HTTP router may call
# ═════════════════════════════════════════════════════════════════════

def answer_json(
    query:      str,
    session_id: str = "default",
    history:    Optional[list] = None,
    *,
    request_id: str = "",
) -> dict:
    """Single authoritative entry point for runtime_v2 over HTTP."""
    import time
    t0 = time.time()
    resp = _v2_answer(query or "")
    return _response_to_http_dict(
        resp,
        request_id      = request_id or "",
        elapsed_seconds = time.time() - t0,
    )


def stream_frames(
    query:      str,
    session_id: str = "default",
    history:    Optional[list] = None,
    *,
    chunk:      int = 40,
    request_id: str = "",
) -> Iterable[tuple[str, dict]]:
    """Yield SSE-ready frames for streaming output.

    Contract:
      • When the response is a drafting output (memo present), the STREAMED
        text is the MEMO itself — that is what the user asked for. The
        analytical summary is still attached to the "done" frame under
        "answer".
      • When the response is analytical, the streamed text is the answer.
      • Every chunk carries BOTH `content` and `text` keys so older
        clients (that read `content`) and newer clients (that read
        `text`) see the same payload.

    Emits (kind, payload) tuples:
      ("start", {runtime, runtime_version, authoritative_path})
      ("chunk", {content, text})        (repeated)
      ("done",  full_response_dict)
    """
    http = answer_json(query, session_id, history, request_id=request_id)
    yield ("start", {
        "runtime":            http["runtime"],
        "runtime_version":    http["runtime_version"],
        "authoritative_path": http["authoritative_path"],
    })

    # Primary streamed body: the memo when present, else the answer
    body = (http.get("memo") or "").strip()
    if not body:
        body = http.get("answer") or ""

    step = max(1, chunk)
    for i in range(0, len(body), step):
        piece = body[i:i + step]
        # Emit under both keys so legacy and new clients concatenate it
        yield ("chunk", {"content": piece, "text": piece})
    yield ("done", http)
