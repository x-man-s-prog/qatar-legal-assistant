# -*- coding: utf-8 -*-
"""
LegalConversationStateEngine — per-session legal conversation state.

Tracks what is active legally, NOT raw text history. State updates on
every turn based on classification + focus + follow-up intent.

In-memory only, TTL-based eviction. One state per session_id. No DB.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LegalConversationState:
    """The legal state of an ongoing conversation."""

    # ── Identity ──
    conversation_case_id: str = ""
    session_id:           str = ""
    turn_count:           int = 0

    # ── Active legal frame (carried across turns until reset) ──
    active_domain:            str = ""      # "criminal", "family", ...
    active_subdomain:         str = ""      # "defamation", "custody", ...
    active_offense_key:       str = ""      # for criminal: "defamation", "drugs", ...
    active_issues:            list[str] = field(default_factory=list)
    resolved_issues:          list[str] = field(default_factory=list)
    unresolved_issues:        list[str] = field(default_factory=list)

    # ── Active facts (only those user has actually stated) ──
    active_facts:             list[str] = field(default_factory=list)

    # ── Focus tracking ──
    last_focus:               str = ""      # "offense" | "punishment" | "proof" | "defense" | ...
    last_answer_mode:         str = ""      # "direct_short" | "analysis" | ...

    # ── Medium (street / digital / broadcast) ──
    last_medium:              str = ""

    # ── Procedural / burden / evidence focus ──
    last_procedural_posture:  str = ""
    last_burden_focus:        str = ""
    last_evidence_focus:      str = ""

    # ── Meta ──
    last_answer_text_short:   str = ""      # first 200 chars — for repetition detection
    last_updated_ts:          float = 0.0
    ambiguity_status:         str = ""

    # ── Turn timeline (compact) ──
    pivot_log:                list[dict] = field(default_factory=list)

    def to_trace(self) -> dict:
        return {
            "case_id":           self.conversation_case_id,
            "turn_count":        self.turn_count,
            "active_domain":     self.active_domain,
            "active_subdomain":  self.active_subdomain,
            "active_offense":    self.active_offense_key,
            "active_issues":     self.active_issues[:5],
            "resolved_issues":   self.resolved_issues[:3],
            "unresolved_issues": self.unresolved_issues[:3],
            "last_focus":        self.last_focus,
            "last_medium":       self.last_medium,
            "pivot_log_len":     len(self.pivot_log),
        }

    def is_fresh(self, ttl_seconds: int = 1800) -> bool:
        return (time.time() - self.last_updated_ts) < ttl_seconds

    def record_pivot(self, note: str, intent: str = "", focus: str = "") -> None:
        self.pivot_log.append({
            "turn":   self.turn_count,
            "note":   note[:80],
            "intent": intent,
            "focus":  focus,
            "ts":     round(time.time(), 3),
        })
        # Cap pivot log to last 8 entries
        if len(self.pivot_log) > 8:
            self.pivot_log = self.pivot_log[-8:]


# ═════════════════════════════════════════════════════════════════
# State engine — in-memory store with TTL
# ═════════════════════════════════════════════════════════════════

class LegalConversationStateEngine:
    """Thread-safe per-session state store.

    API:
        engine.get(session_id) -> LegalConversationState (creates if missing)
        engine.update(session_id, mutations) -> state
        engine.reset(session_id) -> None
        engine.snapshot() -> dict
    """

    def __init__(self, ttl_seconds: int = 1800, max_sessions: int = 10_000):
        self._lock = threading.RLock()
        self._store: dict[str, LegalConversationState] = {}
        self._ttl = ttl_seconds
        self._max = max_sessions

    def get(self, session_id: str) -> LegalConversationState:
        with self._lock:
            self._evict_expired()
            st = self._store.get(session_id)
            if st is None or not st.is_fresh(self._ttl):
                st = LegalConversationState(
                    conversation_case_id=f"case-{session_id}-{int(time.time())}",
                    session_id=session_id,
                    last_updated_ts=time.time(),
                )
                self._store[session_id] = st
                self._enforce_max()
            return st

    def update(self, session_id: str, **mutations) -> LegalConversationState:
        with self._lock:
            st = self.get(session_id)
            for key, val in mutations.items():
                if hasattr(st, key):
                    setattr(st, key, val)
            st.last_updated_ts = time.time()
            return st

    def record_turn(self, session_id: str, domain: str = "",
                     subdomain: str = "", offense_key: str = "",
                     focus: str = "", medium: str = "",
                     answer_mode: str = "", answer_snippet: str = "",
                     new_issues: Optional[list[str]] = None,
                     new_facts: Optional[list[str]] = None,
                     pivot_note: str = "", intent: str = "") -> LegalConversationState:
        with self._lock:
            st = self.get(session_id)
            st.turn_count += 1
            if domain:      st.active_domain = domain
            if subdomain:   st.active_subdomain = subdomain
            if offense_key: st.active_offense_key = offense_key
            if focus:       st.last_focus = focus
            if medium:      st.last_medium = medium
            if answer_mode: st.last_answer_mode = answer_mode
            if answer_snippet:
                st.last_answer_text_short = answer_snippet[:200]
            if new_issues:
                for iss in new_issues:
                    if iss and iss not in st.active_issues:
                        st.active_issues.append(iss)
                # Cap
                st.active_issues = st.active_issues[-8:]
            if new_facts:
                for f in new_facts:
                    if f and f not in st.active_facts:
                        st.active_facts.append(f)
                st.active_facts = st.active_facts[-8:]
            if pivot_note:
                st.record_pivot(pivot_note, intent, focus)
            st.last_updated_ts = time.time()
            return st

    def reset(self, session_id: str) -> None:
        with self._lock:
            self._store.pop(session_id, None)

    def snapshot(self) -> dict:
        with self._lock:
            self._evict_expired()
            return {
                "active_sessions": len(self._store),
                "ttl_seconds":     self._ttl,
                "max_sessions":    self._max,
            }

    # ── internal ──
    def _evict_expired(self) -> None:
        now = time.time()
        expired = [sid for sid, st in self._store.items()
                    if (now - st.last_updated_ts) > self._ttl]
        for sid in expired:
            del self._store[sid]

    def _enforce_max(self) -> None:
        if len(self._store) > self._max:
            # Evict oldest
            oldest = sorted(self._store.items(),
                             key=lambda kv: kv[1].last_updated_ts)
            for sid, _ in oldest[:len(self._store) - self._max]:
                del self._store[sid]


# Module singleton
_engine: Optional[LegalConversationStateEngine] = None


def get_state_engine() -> LegalConversationStateEngine:
    global _engine
    if _engine is None:
        _engine = LegalConversationStateEngine()
    return _engine
