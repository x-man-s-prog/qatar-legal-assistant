# -*- coding: utf-8 -*-
"""
core/session_state.py — server-side session state machine.

Root-Cause Context (CP5 FINDING #15)
=====================================
Every prior memo-routing fix (CP1 Fix 1.B, CP4 Fix 1 Gate D, CP4
Fix 2 session topic) assumed the client sends a correct ``history``
field on each request. Production UI sends truncated or empty
history on memo-bearing turns (documented in FINDING #12 Cause B).
When history is empty, every pattern-match gate evaporates — the
server has no memory that a memo was requested two turns ago.

Pattern-matching gates (A/B/C/D) + topic-only persistence are
symptomatic fixes. The root cause is that the server keeps NO
authoritative state between turns. Every handler treats every
request as isolated.

Design
======
Redis-backed state machine keyed by session_id.

PHASES (strict enum)
  IDLE                    — no memo request pending, no draft active.
  AWAITING_MEMO_DETAILS   — memo requested, asked for gaps, waiting.
  AWAITING_MEMO_TOPIC     — memo requested with no topic, asked.
  MEMO_DRAFTING           — at least one memo already produced this
                            session; follow-ups ("اكتب بالمعلومات
                            المتوفرة") reuse accumulated context.

FIELDS
  session_id        — stable client-supplied identifier.
  phase             — one of the enum values above.
  topic             — detected memo topic (e.g. "حضانة"). Persists
                      across turns once set.
  history           — full server-authoritative list of turns. Each
                      entry: {role: user|assistant, content: str}.
                      Capped at 50.
  memo_facts        — accumulated facts from user turns during an
                      ongoing memo drafting session. Preserves T3's
                      details when T6 says "اكتب بالمعلومات المتوفرة".
  last_updated      — epoch seconds, for debug + TTL sanity.

Routing contract (enforced in routers/query_router.py::query_stream)
  • Load state FIRST — before phase0, before Gates A/B/C/D.
  • If phase == AWAITING_MEMO_DETAILS → force handle_memo_smart.
    (Ignores query content. Ignores client history. Ignores gates.)
  • If phase == AWAITING_MEMO_TOPIC  → force handle_memo_smart.
  • Otherwise → normal phase0 routing.
  • After the handler's response finishes streaming, update phase
    based on the emitted route and persist state.

Non-goals
---------
• Does NOT replace case_memory (Layer 3) — case_memory is
  CROSS-session semantic similarity. session_state is
  PER-session literal turn log + state machine.
• Does NOT replace the per-turn history that the LLM needs for
  contextual answering. handle_general still sees history;
  it just now comes from server truth, not from UI.

Safety
------
• Redis failures log + degrade (return empty state, return
  False on save). Never raise. Pre-CP5 behaviour remains the
  degraded path when Redis is unavailable.
• TTL 2 hours — long enough for a realistic memo session,
  short enough to prevent stale-state pollution.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)

_TTL_SECONDS = 3600 * 2            # 2 hours
_MAX_HISTORY_ENTRIES = 50          # cap history length
_MAX_FACTS = 20                    # cap accumulated memo facts
_KEY_PATTERN = "session_state:{sid}"


# ═══════════════════════════════════════════════════════════════════
# Phases
# ═══════════════════════════════════════════════════════════════════

class Phase(str, Enum):
    IDLE                    = "idle"
    AWAITING_MEMO_DETAILS   = "awaiting_memo_details"
    AWAITING_MEMO_TOPIC     = "awaiting_memo_topic"
    MEMO_DRAFTING           = "memo_drafting"


# Routes → phases. Used by transition().
_ROUTE_TO_PHASE: dict[str, Phase] = {
    "memo_ask_details": Phase.AWAITING_MEMO_DETAILS,
    "memo_ask_topic":   Phase.AWAITING_MEMO_TOPIC,
    "memo":             Phase.MEMO_DRAFTING,
}


# ═══════════════════════════════════════════════════════════════════
# State dataclass
# ═══════════════════════════════════════════════════════════════════

@dataclass
class SessionState:
    session_id:   str
    phase:        Phase        = Phase.IDLE
    topic:        Optional[str] = None
    history:      list[dict]   = field(default_factory=list)
    memo_facts:   list[str]    = field(default_factory=list)
    last_updated: float        = field(default_factory=time.time)

    # ── Turn log ────────────────────────────────────────────────
    def append_turn(self, role: str, content: str) -> None:
        """Append one turn and cap history length."""
        if role not in ("user", "assistant"):
            return
        content = (content or "").strip()
        if not content:
            return
        self.history.append({"role": role, "content": content})
        if len(self.history) > _MAX_HISTORY_ENTRIES:
            self.history = self.history[-_MAX_HISTORY_ENTRIES:]

    def append_fact(self, fact: str) -> None:
        """Append an accumulated user fact. De-duplicates."""
        f = (fact or "").strip()
        if not f or f in self.memo_facts:
            return
        self.memo_facts.append(f)
        if len(self.memo_facts) > _MAX_FACTS:
            self.memo_facts = self.memo_facts[-_MAX_FACTS:]

    def reset_memo_state(self) -> None:
        """Called when user clearly pivots away from a memo context."""
        self.phase = Phase.IDLE
        # Preserve topic (sticky for quick return) but drop pending facts.
        self.memo_facts = []

    def reset_memo_state_hard(self) -> None:
        """Hard reset — used when user EXPLICITLY requests a new memo on
        a different topic. Wipes phase AND topic AND accumulated facts
        so the new memo starts on a clean slate.

        FINDING #20 root fix: without this, a new ``LEGAL_DRAFT_REQUEST``
        while mid-memo inherits the prior topic's facts and produces
        a hybrid nonsense memo (e.g. user asks for custody memo while
        drug-case facts are still in memo_facts → drug memo emerges
        labeled as custody).
        """
        self.phase = Phase.IDLE
        self.topic = None
        self.memo_facts = []

    # ── Phase transitions ──────────────────────────────────────
    def transition_by_route(self, route: str) -> None:
        """Update phase based on the route the handler decided to emit."""
        new_phase = _ROUTE_TO_PHASE.get(route)
        if new_phase is not None:
            self.phase = new_phase

    # ── Serialization ──────────────────────────────────────────
    def to_json(self) -> str:
        return json.dumps({
            "session_id":   self.session_id,
            "phase":        self.phase.value,
            "topic":        self.topic,
            "history":      self.history,
            "memo_facts":   self.memo_facts,
            "last_updated": self.last_updated,
        }, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "SessionState":
        d = json.loads(raw)
        return cls(
            session_id   = d.get("session_id", ""),
            phase        = Phase(d.get("phase", "idle")),
            topic        = d.get("topic"),
            history      = list(d.get("history", []))[-_MAX_HISTORY_ENTRIES:],
            memo_facts   = list(d.get("memo_facts", []))[-_MAX_FACTS:],
            last_updated = float(d.get("last_updated", time.time())),
        )


# ═══════════════════════════════════════════════════════════════════
# Async primary API
# ═══════════════════════════════════════════════════════════════════

async def load_state(sid: str) -> SessionState:
    """Load state from Redis. Returns fresh empty state on any miss."""
    if not sid:
        return SessionState(session_id="")
    try:
        from core.redis_client import get_redis_client
        client = await get_redis_client(db=2)
        raw = await client.get(_KEY_PATTERN.format(sid=sid))
        if not raw:
            return SessionState(session_id=sid)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        return SessionState.from_json(raw)
    except Exception as e:
        log.debug("session_state load failed: %s", e)
        return SessionState(session_id=sid)


async def save_state(state: SessionState) -> bool:
    """Persist state to Redis. Never raises."""
    if not state.session_id:
        return False
    try:
        from core.redis_client import get_redis_client
        client = await get_redis_client(db=2)
        state.last_updated = time.time()
        await client.set(
            _KEY_PATTERN.format(sid=state.session_id),
            state.to_json(),
            ex=_TTL_SECONDS,
        )
        return True
    except Exception as e:
        log.debug("session_state save failed: %s", e)
        return False


async def delete_state(sid: str) -> bool:
    """Remove all state for a session (test helper)."""
    if not sid:
        return False
    try:
        from core.redis_client import get_redis_client
        client = await get_redis_client(db=2)
        await client.delete(_KEY_PATTERN.format(sid=sid))
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════
# Sync wrappers — for sync-within-async callers (same pattern as
# fact_extractor / session_topic_memory)
# ═══════════════════════════════════════════════════════════════════

def load_state_sync(sid: str) -> SessionState:
    try:
        from core.runtime_v2.corpus import _bg as _corpus_bg
        return _corpus_bg.run(load_state(sid))
    except Exception as e:
        log.debug("session_state sync load failed: %s", e)
        return SessionState(session_id=sid or "")


def save_state_sync(state: SessionState) -> bool:
    try:
        from core.runtime_v2.corpus import _bg as _corpus_bg
        return bool(_corpus_bg.run(save_state(state)))
    except Exception as e:
        log.debug("session_state sync save failed: %s", e)
        return False


def delete_state_sync(sid: str) -> bool:
    try:
        from core.runtime_v2.corpus import _bg as _corpus_bg
        return bool(_corpus_bg.run(delete_state(sid)))
    except Exception:
        return False


__all__ = [
    "Phase", "SessionState",
    "load_state", "save_state", "delete_state",
    "load_state_sync", "save_state_sync", "delete_state_sync",
]
