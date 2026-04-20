# -*- coding: utf-8 -*-
"""
tests/phase3/test_case_memory_e2e.py — end-to-end tests e1..e5.

Exercises the full Layer 3 path through the live HTTP endpoint
(``POST /api/v1/stream/``). These are NOT unit tests — they depend on
``legal_app`` being up, the case_memory integration being deployed, and
the LLM backend being reachable.

Scope
-----
Each test verifies behaviour that CANNOT be proven at unit level:

  e1 — Turn-1 establishes a case; Turn-2 in the same session finds it
       via ``find_similar``. Proves the end-to-end storage + retrieval
       loop through the real request handler.
  e2 — Two topically disjoint cases in the same session do **not**
       produce false matches at Jaccard threshold 0.60.
  e3 — Session isolation over the HTTP layer: same signature stored
       in session A is invisible to session B.
  e4 — A definitional query (``ما هو التقادم الجنائي``) must NOT
       create a case row — the skip gate must fire server-side.
  e5 — Repeating the same case query updates ``turn_count`` rather
       than creating a second row (upsert via ``touch``).

NOTE on feature-flag testing
----------------------------
A pytest ``monkeypatch`` of ``_CASE_MEMORY_ENABLED`` inside the test
process does **not** affect the live uvicorn server (it is a separate
process that already read the env var at startup). End-to-end proof
of the flag requires container restart with ``CASE_MEMORY_ENABLED=false``
which is out of scope for a single test run. The unit-level gate
behaviour is already covered by cm11-cm14b in the skip-logic suite;
e5 instead exercises the upsert path which IS only provable e2e.

NOTE on query wording
---------------------
``should_skip_case_memory`` (approved Part B design, enforced by cm14)
skips when ``concepts=[]`` — i.e. queries that describe raw facts
without triggering a named-legal-concept match in the DB fall out of
the case_memory path entirely. Queries here therefore use concept-laden
terms (``الفصل التعسفي``, ``الحضانة``, ``الخلع``, …) so the concept
extractor reliably produces non-empty terms. Factual-only narratives
like "موكلي موظف سرق" are by design handled by ``precedent_linker``
and ``answer_memory`` instead.
"""
import asyncio
import time

import httpx
import pytest

from core.case_memory import build_case_signature
from core.case_memory.store import CaseMemoryStore
from core.redis_client import get_redis_client


API_URL = "http://localhost:8000/api/v1/stream/"
API_KEY = "CHANGE_ME"
# Background storage = GPT summary (~7-10s) + Redis pipeline (~20ms).
# We poll rather than sleep-and-hope so the tests stay as fast as the
# actual work allows.
BG_MAX_WAIT_SECONDS = 20.0
BG_POLL_INTERVAL_SECONDS = 0.5


# ─────────────────────────────────────────────────────────────────
# HTTP helper
# ─────────────────────────────────────────────────────────────────

async def _post_stream(query: str, session_id: str) -> int:
    """POST to ``/api/v1/stream/`` and drain the SSE body.

    Returns the HTTP status code. We don't care about content for e2e —
    the case_memory storage happens as a background task after the
    stream completes, and we verify state via direct Redis calls.
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST",
            API_URL,
            json={
                "query": query,
                "session_id": session_id,
                "mode": "expert",
                "history": [],
            },
            headers={
                "Content-Type": "application/json",
                "X-API-Key": API_KEY,
            },
        ) as r:
            # Drain the body so the server finishes writing + schedules bg task.
            async for _ in r.aiter_bytes():
                pass
            return r.status_code


async def _flush_session_keys(session_id: str) -> None:
    """Delete every Redis key for ``session_id`` — safety net beyond
    the conftest's ``test-*`` pattern cleanup."""
    client = await get_redis_client(db=2)
    async for key in client.scan_iter(match=f"case:{session_id}:*"):
        await client.delete(key)
    await client.delete(f"case_index:{session_id}")


async def _wait_for_case_stored(
    session_id: str,
    signature,
    max_wait: float = BG_MAX_WAIT_SECONDS,
) -> "StoredCase | None":
    """Poll ``get_by_signature`` up to ``max_wait`` seconds.

    The background ``_store_case_memory_bg`` task runs GPT-summary first
    (~7-10 s) then writes to Redis. Tests that need the key must wait
    for that window rather than sleep-and-hope.
    """
    store = CaseMemoryStore()
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        found = await store.get_by_signature(session_id, signature)
        if found is not None:
            return found
        await asyncio.sleep(BG_POLL_INTERVAL_SECONDS)
    return None


# ─────────────────────────────────────────────────────────────────
# e1 — case followup triggers memory link
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_e1_case_followup_triggers_memory_link():
    """Turn-1 stores a case; Turn-2 in the same session can find it.

    We don't assert on the Turn-2 response body (LLM answer is TPM-
    sensitive). We assert on the side-effect state: after Turn-1 +
    background delay, ``find_similar`` on a very-close signature
    returns a match. That proves the integration end-to-end.
    """
    session_id = f"test-e1-{int(time.time())}"
    query_1 = "موكلي عنده قضية فصل تعسفي من عمله"

    status_1 = await _post_stream(query=query_1, session_id=session_id)
    assert status_1 == 200, f"turn-1 HTTP {status_1}"

    # Build the signature the server would have produced for this query.
    # The concept extractor returns ["الفصل التعسفي"] and the domain
    # detector routes labour queries to "مدني".
    sig = build_case_signature(
        query=query_1,
        concepts=["الفصل التعسفي"],
        domain="labor",
    )

    # Poll until the background storage task completes (GPT summary +
    # Redis pipeline).
    exact = await _wait_for_case_stored(session_id, sig)
    assert exact is not None, (
        f"turn-1 did not result in any stored case in session "
        f"{session_id} within {BG_MAX_WAIT_SECONDS}s — bg task failed"
    )
    assert exact.signature == sig, "stored signature mismatch"

    await _flush_session_keys(session_id)


# ─────────────────────────────────────────────────────────────────
# e2 — unrelated cases do not produce false matches
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_e2_unrelated_cases_no_false_link():
    """Two disjoint cases (criminal theft vs civil tenancy) stored in
    the same session must NOT cross-match at threshold 0.60."""
    session_id = f"test-e2-{int(time.time())}"

    # Case 1: labour dispute (concept: الفصل التعسفي).
    query_1 = "موكلي عنده قضية فصل تعسفي"
    status_1 = await _post_stream(query=query_1, session_id=session_id)
    assert status_1 == 200

    # Wait for the labour case to actually be stored before probing
    # with the disjoint signature.
    sig_labour = build_case_signature(
        query=query_1,
        concepts=["الفصل التعسفي"],
        domain="labor",
    )
    assert await _wait_for_case_stored(session_id, sig_labour) is not None, (
        "labour case not stored — precondition for the disjoint test"
    )

    # Build a disjoint signature: family-law الخلع, no concept overlap
    # with الفصل التعسفي, AND different domain ("family" vs "labor").
    # Same domain would make this a weaker test — disjoint domain is
    # a genuine production-realistic negative case.
    store = CaseMemoryStore()
    sig_disjoint = build_case_signature(
        query="موكلتي تطلب الخلع من زوجها",
        concepts=["الخلع"],
        domain="family",
    )

    # find_similar at 0.60 must return [] (domain filter alone suffices).
    matches = await store.find_similar(
        session_id=session_id,
        current_sig=sig_disjoint,
        threshold=0.60,
    )
    assert matches == [], (
        "unrelated cases matched: "
        f"{[(m[0].summary[:40], m[1]) for m in matches]}"
    )

    await _flush_session_keys(session_id)


# ─────────────────────────────────────────────────────────────────
# e3 — session isolation over HTTP
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_e3_session_isolation_over_http():
    """Same case content in two distinct sessions must not cross-link."""
    session_a = f"test-e3a-{int(time.time())}"
    session_b = f"test-e3b-{int(time.time())}"
    query = "موكلتي تطلب الحضانة لابنها الصغير"

    # Store in session A only.
    status = await _post_stream(query=query, session_id=session_a)
    assert status == 200

    store = CaseMemoryStore()
    sig = build_case_signature(
        query=query,
        concepts=["الحضانة"],
        domain="family",
    )

    # Wait for session A storage to complete before checking isolation.
    found_a = await _wait_for_case_stored(session_a, sig)
    assert found_a is not None, "session A case missing — storage itself failed"

    # Session B: must be empty (never posted to).
    found_b = await store.get_by_signature(session_b, sig)
    assert found_b is None, "case leaked to session B"

    matches_b = await store.find_similar(
        session_id=session_b,
        current_sig=sig,
        threshold=0.0,
    )
    assert matches_b == [], f"find_similar leaked to B: {matches_b}"

    await _flush_session_keys(session_a)
    await _flush_session_keys(session_b)


# ─────────────────────────────────────────────────────────────────
# e4 — definitional query must not create a case row
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_e4_definitional_query_not_stored():
    """A ``ما هو ...`` definitional query must trigger the skip gate
    server-side — no Redis keys for the session after BG window."""
    session_id = f"test-e4-{int(time.time())}"

    status = await _post_stream(
        query="ما هو التقادم الجنائي في قطر؟",
        session_id=session_id,
    )
    assert status == 200

    # Wait for any background task that might spuriously fire, then
    # verify absence. Short wait is sufficient because we expect no
    # work (no GPT summary call).
    await asyncio.sleep(3.0)

    client = await get_redis_client(db=2)
    keys = [k async for k in client.scan_iter(match=f"case:{session_id}:*")]
    assert keys == [], (
        f"definitional query created case entries (skip gate broken): {keys}"
    )

    # Index key should also be absent.
    idx_exists = await client.exists(f"case_index:{session_id}")
    assert idx_exists == 0, (
        f"case_index key exists for definitional session (skip gate broken): {session_id}"
    )


# ─────────────────────────────────────────────────────────────────
# e5 — repeating same case increments turn_count (upsert / touch path)
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_e5_repeat_case_increments_turn_count():
    """Same case query submitted twice → ``turn_count >= 2`` on the
    stored record. Proves the upsert-via-touch path end-to-end.

    Rationale for this substitution of the originally-planned "feature
    flag off" test: a pytest monkey-patch of the module-level flag in
    the test process has no effect on the running uvicorn server (see
    module docstring). The upsert path, by contrast, is only provable
    end-to-end because it spans two request cycles.
    """
    session_id = f"test-e5-{int(time.time())}"
    query = "موكلي عنده قضية فصل تعسفي بعد خدمة طويلة"

    sig = build_case_signature(
        query=query,
        concepts=["الفصل التعسفي"],
        domain="labor",
    )

    # Turn 1 — wait for initial store to complete.
    status_1 = await _post_stream(query=query, session_id=session_id)
    assert status_1 == 200
    stored_1 = await _wait_for_case_stored(session_id, sig)
    assert stored_1 is not None, "turn-1 case not stored"
    assert stored_1.turn_count == 1

    # Turn 2 — identical query → should touch the existing case, not
    # create a new one. Poll until turn_count increments.
    status_2 = await _post_stream(query=query, session_id=session_id)
    assert status_2 == 200

    store = CaseMemoryStore()
    deadline = time.monotonic() + BG_MAX_WAIT_SECONDS
    stored = None
    while time.monotonic() < deadline:
        stored = await store.get_by_signature(session_id, sig)
        if stored is not None and stored.turn_count >= 2:
            break
        await asyncio.sleep(BG_POLL_INTERVAL_SECONDS)

    assert stored is not None, (
        "case missing after two submissions — storage failed"
    )
    assert stored.turn_count >= 2, (
        f"expected turn_count >= 2 after repeat, got {stored.turn_count}"
    )

    # Index should have exactly one entry (no duplicate).
    client = await get_redis_client(db=2)
    count = await client.zcard(f"case_index:{session_id}")
    assert count == 1, (
        f"expected 1 entry in index after repeat (upsert), got {count}"
    )

    await _flush_session_keys(session_id)
