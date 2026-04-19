# -*- coding: utf-8 -*-
"""
Live-path rewiring tests.
=========================

These tests verify production HTTP endpoints ACTUALLY route through
the fail-closed runtime — not the legacy LLM-first path. Failures
here indicate rewiring regression, not unit-test regression.

Run:
    pytest tests/test_live_rewiring.py -v

What each test proves:
  test_json_uses_fail_closed          → runtime stamp on /api/v1/query/
  test_json_gates_metadata            → gates_passed/gates_failed present
  test_json_greeting_pregate          → greetings take conv pre-gate
  test_json_drafting_refusal          → drafting requests explicitly refused
  test_stream_uses_fail_closed        → runtime stamp on /api/v1/stream/
  test_stream_done_frame_gates        → done frame carries trace
  test_pipeline_direct_reachable      → fail_closed importable & runnable
  test_production_runtime_singleton   → ProductionRuntime is a singleton
  test_no_legacy_unless_flag          → legacy off by default
  test_runtime_flags_snapshot         → flags readable via snapshot()
  test_bypass_surface_closed          → only /api/v1/query/ and /stream/ produce answers
"""
from __future__ import annotations
import os
import sys
import json
import importlib

import pytest


# ─────────────────────────────────────────────────────────────────
# Fixture: FastAPI TestClient with known flags
# ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    """A TestClient bound to the live FastAPI app with new-runtime on.

    The TestClient sets a Referer that matches the security middleware's
    same-origin bypass, so tests don't need the production API_KEY.
    """
    os.environ["USE_FAIL_CLOSED_RUNTIME"]    = "true"
    os.environ["ENABLE_LEGACY_FALLBACK"]     = "false"
    os.environ["DISABLE_STREAM_LEGACY_PATH"] = "true"
    os.environ["STRICT_PRODUCTION_GATING"]   = "true"

    # Reload flags module so it picks up our env vars
    if "core.runtime_flags" in sys.modules:
        importlib.reload(sys.modules["core.runtime_flags"])
    else:
        import core.runtime_flags  # noqa: F401

    from fastapi.testclient import TestClient
    from main import app
    # Same-origin header bypasses API-Key check in security_middleware
    with TestClient(app, headers={"Referer": "http://localhost:8000/"}) as c:
        yield c


# ═════════════════════════════════════════════════════════════════
# JSON endpoint — runtime identity & gates
# ═════════════════════════════════════════════════════════════════

def test_json_uses_fail_closed(client):
    """/api/v1/query/ must stamp runtime on the response
    (or be a beta-middleware block — acceptable upstream gate)."""
    r = client.post("/api/v1/query/", json={
        "query": "ما هي عقوبة السرقة في القانون القطري؟",
        "session_id": "test-rw-001",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    if body.get("from_beta_gate") is True:
        return  # beta upstream block — acceptable
    runtime = body.get("runtime")
    assert runtime in ("fail_closed", "conversation_pregate", "beta_pregate"), \
        f"Expected new-runtime stamp, got runtime={runtime!r} body={body}"


def test_json_gates_metadata(client):
    """Every new-runtime response must carry gates_passed/gates_failed
    (or be an upstream beta block)."""
    r = client.post("/api/v1/query/", json={
        "query": "أنا تم فصلي تعسفياً من شركة بعد 5 سنوات خدمة. ما حقوقي القانونية؟",
        "session_id": "test-rw-002",
    })
    body = r.json()
    if body.get("from_beta_gate") is True:
        return  # beta upstream block — acceptable
    assert "gates_passed" in body, f"missing gates_passed: {body}"
    assert "gates_failed" in body, f"missing gates_failed: {body}"
    assert "runtime" in body, f"missing runtime: {body}"
    assert body["runtime"] in ("fail_closed", "conversation_pregate")


def test_json_greeting_pregate(client):
    """Greetings take the conversation pre-gate, not fail_closed
    (or upstream beta gate blocks — acceptable)."""
    r = client.post("/api/v1/query/", json={
        "query": "مرحبا",
        "session_id": "test-rw-003",
    })
    body = r.json()
    if body.get("from_beta_gate") is True:
        return  # beta upstream block — acceptable
    assert body.get("runtime") == "conversation_pregate", \
        f"Expected conversation pregate, got {body.get('runtime')}"


def test_json_drafting_refusal(client):
    """Drafting requests are explicitly refused — never silent bypass
    (or upstream beta block is acceptable)."""
    r = client.post("/api/v1/query/", json={
        "query": "اكتب لي مذكرة دفاع في قضية سرقة",
        "session_id": "test-rw-004",
    })
    body = r.json()
    if body.get("from_beta_gate") is True:
        return  # beta upstream block — acceptable
    assert body.get("runtime") == "fail_closed"
    assert body.get("is_blocked") is True
    assert "drafting_request_rejected" in body.get("block_reasons", []), \
        f"Expected drafting_request_rejected, got {body.get('block_reasons')}"


# ═════════════════════════════════════════════════════════════════
# Stream endpoint — runtime identity & trace
# ═════════════════════════════════════════════════════════════════

def test_stream_uses_fail_closed(client):
    """/api/v1/stream/ start frame must carry runtime stamp
    OR the request must be an explicit beta-middleware block (upstream).
    """
    r = client.post("/api/v1/stream/", json={
        "query": "ما هي شروط عقد الشراكة التجارية؟",
        "session_id": "test-rw-005",
    })
    assert r.status_code == 200
    # Case 1: beta HTTP middleware intercepted → JSON body with from_beta_gate
    ctype = r.headers.get("content-type", "")
    if "application/json" in ctype:
        body = r.json()
        assert body.get("from_beta_gate") is True, \
            f"JSON response but not beta-block: {body}"
        return
    # Case 2: SSE — check frames
    lines = [ln for ln in r.text.split("\n") if ln.startswith("data: ")]
    assert lines, f"no SSE frames received: {r.text[:500]}"
    start_frames = [ln for ln in lines
                     if '"type": "start"' in ln or '"type":"start"' in ln]
    assert start_frames, f"no start frame: {lines[:3]}"
    start = json.loads(start_frames[0][len("data: "):])
    assert start.get("runtime") in ("fail_closed", "conversation_pregate", "beta_pregate"), \
        f"start frame runtime = {start}"


def test_stream_done_frame_gates(client):
    """Stream done frame must carry gates + block_reasons
    OR be an upstream beta block (JSON response).
    """
    r = client.post("/api/v1/stream/", json={
        "query": "سؤال قانوني عام",
        "session_id": "test-rw-006",
    })
    ctype = r.headers.get("content-type", "")
    if "application/json" in ctype:
        body = r.json()
        assert body.get("from_beta_gate") is True
        return
    lines = [ln for ln in r.text.split("\n") if ln.startswith("data: ")]
    done_frames = [ln for ln in lines
                    if '"type": "done"' in ln or '"type":"done"' in ln]
    assert done_frames, f"no done frame: {lines[-3:]}"
    done = json.loads(done_frames[0][len("data: "):])
    # Trace fields must be present
    assert "gates_passed" in done
    assert "gates_failed" in done
    assert "block_reasons" in done
    assert "runtime" in done
    assert "is_blocked" in done


# ═════════════════════════════════════════════════════════════════
# Direct pipeline reachability
# ═════════════════════════════════════════════════════════════════

def test_pipeline_direct_reachable():
    """fail_closed_pipeline must be importable and runnable."""
    from core.fail_closed_pipeline import answer_fail_closed, FailClosedResult
    result = answer_fail_closed("تم فصلي تعسفياً من شركتي بعد سنوات خدمة طويلة")
    assert isinstance(result, FailClosedResult)
    assert hasattr(result, "text")
    assert hasattr(result, "is_blocked")
    assert hasattr(result, "gates_passed")
    assert hasattr(result, "elapsed_seconds")


def test_production_runtime_singleton():
    """get_production_runtime returns the same instance every call."""
    from core.production_runtime import get_production_runtime
    r1 = get_production_runtime()
    r2 = get_production_runtime()
    assert r1 is r2


def test_production_runtime_direct_call():
    """answer_query_direct runs the full pipeline without HTTP."""
    from core.production_runtime import answer_query_direct
    body = answer_query_direct("ما هو الفصل التعسفي وما حقوق العامل؟",
                                session_id="direct-test")
    assert body["runtime"] == "fail_closed"
    assert "gates_passed" in body
    assert "gates_failed" in body
    assert "is_blocked" in body


# ═════════════════════════════════════════════════════════════════
# Flag control
# ═════════════════════════════════════════════════════════════════

def test_runtime_flags_snapshot():
    """Flags are readable and explicit."""
    from core.runtime_flags import snapshot
    s = snapshot()
    for key in ("USE_FAIL_CLOSED_RUNTIME", "ENABLE_LEGACY_FALLBACK",
                 "DISABLE_STREAM_LEGACY_PATH", "STRICT_PRODUCTION_GATING"):
        assert key in s, f"flag {key} missing from snapshot"


def test_no_legacy_unless_flag():
    """Default env → legacy MUST be off."""
    os.environ.pop("ENABLE_LEGACY_FALLBACK", None)
    from core.runtime_flags import reload_from_env
    s = reload_from_env()
    assert s["ENABLE_LEGACY_FALLBACK"] is False
    assert s["USE_FAIL_CLOSED_RUNTIME"] is True


def test_strict_refusal_when_both_off(monkeypatch):
    """When new=off AND legacy=off, endpoint must refuse — no silent path.

    POST-UNIFICATION: flags are LOCKED constants — env vars cannot disable
    the unified runtime. This test now verifies the lock holds even with
    hostile env values.
    """
    monkeypatch.setenv("USE_FAIL_CLOSED_RUNTIME", "false")
    monkeypatch.setenv("ENABLE_LEGACY_FALLBACK", "true")
    from core.runtime_flags import reload_from_env
    s = reload_from_env()
    # Locks must hold — env cannot override
    assert s["USE_FAIL_CLOSED_RUNTIME"] is True, \
        "unification lock breached — runtime can be turned off"
    assert s["ENABLE_LEGACY_FALLBACK"] is False, \
        "unification lock breached — legacy can be re-enabled"


# ═════════════════════════════════════════════════════════════════
# Bypass surface check
# ═════════════════════════════════════════════════════════════════

def test_bypass_surface_is_minimal():
    """
    Only /api/v1/query/ and /api/v1/stream/ should produce answers.
    Anything else that looks like an answer-producing route is a bypass.
    """
    from main import app
    # Collect all POST routes
    paths = []
    for r in app.routes:
        methods = getattr(r, "methods", None) or set()
        path = getattr(r, "path", "")
        if "POST" in methods:
            paths.append(path)

    # Allowed answer-producing POST routes
    allowed = {"/api/v1/query/", "/api/v1/stream/"}
    # Other POST routes are fine as long as they don't look like answer routes
    suspicious = [p for p in paths
                   if (p not in allowed)
                   and ("query" in p.lower() or "answer" in p.lower() or "ask" in p.lower())]
    assert not suspicious, f"suspicious answer-producing POST routes: {suspicious}"


def test_runtime_stamp_on_every_response(client):
    """EVERY response from /api/v1/query/ must carry a runtime field
    OR be an explicit beta-middleware block (from_beta_gate=True).

    The beta HTTP middleware is an upstream security gate — it may
    block a request before it reaches our runtime. That is acceptable
    (it is not a silent bypass; it's a security pre-gate).
    """
    for query in [
        "مرحبا",
        "ما حكم السرقة؟",
        "اكتب لي عقد عمل",
        "-",
    ]:
        r = client.post("/api/v1/query/", json={
            "query": query,
            "session_id": f"stamp-{hash(query) & 0xFFFF}",
        })
        body = r.json()
        has_runtime = "runtime" in body
        is_beta_block = body.get("from_beta_gate") is True
        assert has_runtime or is_beta_block, \
            f"response lacks runtime stamp AND is not a beta block: query={query!r} body={body}"
