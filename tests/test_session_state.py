# -*- coding: utf-8 -*-
"""Unit tests for core/session_state — server-side state machine."""
import pytest

from core.session_state import (
    Phase,
    SessionState,
    load_state,
    save_state,
    delete_state,
    load_state_sync,
    save_state_sync,
    delete_state_sync,
)


# ── dataclass / turn log ─────────────────────────────────────────

def test_ss_default_is_idle():
    s = SessionState(session_id="x")
    assert s.phase is Phase.IDLE
    assert s.history == []
    assert s.memo_facts == []
    assert s.topic is None


def test_ss_append_turn_user():
    s = SessionState(session_id="x")
    s.append_turn("user", "hello")
    assert len(s.history) == 1
    assert s.history[0] == {"role": "user", "content": "hello"}


def test_ss_append_turn_skips_empty():
    s = SessionState(session_id="x")
    s.append_turn("user", "")
    s.append_turn("assistant", "  ")
    assert s.history == []


def test_ss_append_turn_rejects_bad_role():
    s = SessionState(session_id="x")
    s.append_turn("system", "ignored")
    assert s.history == []


def test_ss_history_cap_50():
    s = SessionState(session_id="x")
    for i in range(60):
        s.append_turn("user", f"msg {i}")
    assert len(s.history) == 50
    # Oldest 10 should be dropped
    assert s.history[0]["content"] == "msg 10"
    assert s.history[-1]["content"] == "msg 59"


def test_ss_append_fact_dedupe():
    s = SessionState(session_id="x")
    s.append_fact("احمد 3 سنوات")
    s.append_fact("احمد 3 سنوات")
    s.append_fact("سوء سلوك")
    assert s.memo_facts == ["احمد 3 سنوات", "سوء سلوك"]


def test_ss_reset_memo_state():
    s = SessionState(
        session_id="x",
        phase=Phase.AWAITING_MEMO_DETAILS,
        topic="حضانة",
        memo_facts=["احمد"],
    )
    s.reset_memo_state()
    assert s.phase is Phase.IDLE
    assert s.memo_facts == []
    # Topic is preserved (sticky)
    assert s.topic == "حضانة"


# ── Phase transitions via route ─────────────────────────────────

def test_ss_transition_memo_ask_details():
    s = SessionState(session_id="x")
    s.transition_by_route("memo_ask_details")
    assert s.phase is Phase.AWAITING_MEMO_DETAILS


def test_ss_transition_memo_ask_topic():
    s = SessionState(session_id="x")
    s.transition_by_route("memo_ask_topic")
    assert s.phase is Phase.AWAITING_MEMO_TOPIC


def test_ss_transition_memo_drafting():
    s = SessionState(session_id="x", phase=Phase.AWAITING_MEMO_DETAILS)
    s.transition_by_route("memo")
    assert s.phase is Phase.MEMO_DRAFTING


def test_ss_transition_unknown_route_no_change():
    s = SessionState(session_id="x", phase=Phase.MEMO_DRAFTING)
    s.transition_by_route("unknown_xyz")
    assert s.phase is Phase.MEMO_DRAFTING


# ── Serialization round-trip ─────────────────────────────────────

def test_ss_json_roundtrip():
    s = SessionState(
        session_id="x",
        phase=Phase.AWAITING_MEMO_DETAILS,
        topic="حضانة",
        history=[{"role": "user", "content": "اكتب مذكرة"}],
        memo_facts=["احمد 3 سنوات"],
    )
    raw = s.to_json()
    s2 = SessionState.from_json(raw)
    assert s2.session_id == s.session_id
    assert s2.phase is s.phase
    assert s2.topic == s.topic
    assert s2.history == s.history
    assert s2.memo_facts == s.memo_facts


# ── Redis persistence ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ss_load_missing_returns_empty():
    s = await load_state("test-ss-missing-" + "x" * 16)
    assert s.phase is Phase.IDLE
    assert s.history == []


@pytest.mark.asyncio
async def test_ss_save_and_load_roundtrip():
    sid = "test-ss-rt"
    s = SessionState(
        session_id=sid,
        phase=Phase.AWAITING_MEMO_DETAILS,
        topic="حضانة",
    )
    s.append_turn("user", "اكتب مذكرة")
    assert await save_state(s) is True
    s2 = await load_state(sid)
    assert s2.phase is Phase.AWAITING_MEMO_DETAILS
    assert s2.topic == "حضانة"
    assert s2.history[-1]["content"] == "اكتب مذكرة"
    await delete_state(sid)


@pytest.mark.asyncio
async def test_ss_delete_removes_state():
    sid = "test-ss-del"
    s = SessionState(session_id=sid, phase=Phase.MEMO_DRAFTING)
    await save_state(s)
    await delete_state(sid)
    s2 = await load_state(sid)
    assert s2.phase is Phase.IDLE


# ── Sync wrappers ────────────────────────────────────────────────

def test_ss_sync_roundtrip():
    sid = "test-ss-sync"
    s = SessionState(
        session_id=sid,
        phase=Phase.AWAITING_MEMO_TOPIC,
        topic=None,
    )
    s.append_turn("user", "اكتب المذكرة")
    assert save_state_sync(s) is True
    s2 = load_state_sync(sid)
    assert s2.phase is Phase.AWAITING_MEMO_TOPIC
    assert len(s2.history) == 1
    delete_state_sync(sid)


def test_ss_sync_empty_sid():
    s = load_state_sync("")
    assert s.session_id == ""
    assert s.phase is Phase.IDLE
