# -*- coding: utf-8 -*-
"""
tests/phase3/test_case_memory_unit.py — unit tests cm1..cm18 (+ cm14b).

Covers:
  • signature determinism & order-invariance     (cm1-cm3)
  • Jaccard similarity edge cases                 (cm4-cm6)
  • entity extractor closed-vocabulary tagging    (cm7-cm10)
  • skip logic truth table                         (cm11-cm14, cm14b)
  • store round-trip, TTL, LRU, cross-loop         (cm15-cm18)

STATUS
------
CP2 · Part B — live: cm1-cm14 + cm14b exercise real implementation.
CP2 · Part C — pending: cm15-cm18 remain ``@pytest.mark.skip``.
"""
import asyncio
import time

import pytest

from core.case_memory import (
    CaseMemoryStore,
    CaseSignature,
    build_case_signature,
    build_case_memory_block,
    extract_entity_tags,
    generate_case_summary_once,
    should_skip_case_memory,
)
from core.case_memory.block_builder import _humanize_age, _MAX_BLOCK_CHARS
from core.case_memory.store import StoredCase
from core.redis_client import get_redis_client


# ═════════════════════════════════════════════════════════════════
# Signature tests (cm1-cm3)
# ═════════════════════════════════════════════════════════════════

def test_cm1_signature_deterministic():
    """Same ``(query, concepts, domain)`` → same ``hash`` across calls."""
    s1 = build_case_signature(
        query="موكلي موظف سرق 50 ألف واعترف",
        concepts=["السرقة", "الاعتراف", "خيانة الأمانة"],
        domain="جنائي",
    )
    s2 = build_case_signature(
        query="موكلي موظف سرق 50 ألف واعترف",
        concepts=["السرقة", "الاعتراف", "خيانة الأمانة"],
        domain="جنائي",
    )
    assert s1 == s2
    assert s1.hash == s2.hash


def test_cm2_signature_concept_order_invariant():
    """Concepts supplied in different orders → identical signature."""
    s1 = build_case_signature(
        query="قضية",
        concepts=["السرقة", "الاعتراف"],
        domain="جنائي",
    )
    s2 = build_case_signature(
        query="قضية",
        concepts=["الاعتراف", "السرقة"],  # reversed
        domain="جنائي",
    )
    assert s1.hash == s2.hash


def test_cm3_signature_entity_order_invariant():
    """Same entities extracted from different word-order queries →
    same signature (entity_tags always sorted inside the extractor)."""
    s1 = build_case_signature(
        query="موكلي موظف اعترف",
        concepts=[],
        domain="جنائي",
    )
    s2 = build_case_signature(
        query="اعترف الموظف موكلي",
        concepts=[],
        domain="جنائي",
    )
    assert s1.entity_tags == s2.entity_tags
    assert s1.hash == s2.hash


# ═════════════════════════════════════════════════════════════════
# Jaccard tests (cm4-cm6)
# ═════════════════════════════════════════════════════════════════

def test_cm4_jaccard_identical():
    """``sig.similarity(sig) == 1.0`` for non-empty signature."""
    s = build_case_signature(
        query="موظف سرق",
        concepts=["السرقة"],
        domain="جنائي",
    )
    assert s.similarity(s) == 1.0


def test_cm5_jaccard_disjoint():
    """Completely disjoint concept/tag sets → 0.0."""
    s1 = build_case_signature(
        query="موكلي موظف",
        concepts=["السرقة"],
        domain="جنائي",
    )
    s2 = build_case_signature(
        query="زوجتي",
        concepts=["الحضانة"],
        domain="مدني",
    )
    assert s1.similarity(s2) == 0.0


def test_cm6_jaccard_partial_overlap():
    """Controlled overlap: |A ∩ B| / |A ∪ B| computed correctly."""
    # Case 1: concepts overlap only — {A,B} vs {B,C} → 1/3
    s1 = CaseSignature(
        domain="جنائي",
        primary_concepts=("A", "B"),
        entity_tags=(),
    )
    s2 = CaseSignature(
        domain="جنائي",
        primary_concepts=("B", "C"),
        entity_tags=(),
    )
    assert abs(s1.similarity(s2) - 1 / 3) < 1e-9

    # Case 2: identical concepts + tags → 1.0
    s3 = CaseSignature(
        domain="جنائي",
        primary_concepts=("A", "B"),
        entity_tags=("role_employee",),
    )
    s4 = CaseSignature(
        domain="جنائي",
        primary_concepts=("A", "B"),
        entity_tags=("role_employee",),
    )
    assert s4.similarity(s3) == 1.0


# ═════════════════════════════════════════════════════════════════
# Entity extractor tests (cm7-cm10)
# ═════════════════════════════════════════════════════════════════

def test_cm7_entity_role_extraction():
    """``موكلي موظف`` → role_self_client + role_employee."""
    tags = extract_entity_tags("موكلي موظف في الشركة")
    assert "role_self_client" in tags
    assert "role_employee" in tags


def test_cm8_entity_money_bucketing():
    """Money bucketing boundaries — each bucket explicitly covered."""
    assert "money_small" in extract_entity_tags("مبلغ 5000 ريال")
    assert "money_medium" in extract_entity_tags("سرق 50 ألف")
    assert "money_medium" in extract_entity_tags("قيمة 50000 ريال")
    assert "money_large" in extract_entity_tags("اختلس 500 ألف")
    assert "money_huge" in extract_entity_tags("2 مليون دينار")


def test_cm9_entity_action_extraction():
    """Conjugations of the same verb collapse to the same tag."""
    assert "action_confession" in extract_entity_tags("المتهم اعترف بالجريمة")
    assert "action_confession" in extract_entity_tags("اعترفت المتهمة")
    assert "action_theft" in extract_entity_tags("سرق المبلغ")


def test_cm10_entity_no_match_returns_empty():
    """No vocabulary match → empty list (not None)."""
    assert extract_entity_tags("مرحبا كيف حالك") == []
    assert extract_entity_tags("") == []
    assert extract_entity_tags("ما هو التقادم") == []


# ═════════════════════════════════════════════════════════════════
# Skip logic (cm11-cm14 + cm14b)
# ═════════════════════════════════════════════════════════════════

def test_cm11_skip_first_turn():
    """``history_length == 0`` → ``(True, "first_turn")``."""
    skip, reason = should_skip_case_memory(
        query="قضية",
        phase0_class=None,
        concepts=["السرقة"],
        history_length=0,
    )
    assert skip is True
    assert reason == "first_turn"


def test_cm12_skip_definitional():
    """Definitional prefix → ``(True, "definitional")``."""
    skip, reason = should_skip_case_memory(
        query="ما عقوبة السرقة في القانون القطري",
        phase0_class=None,
        concepts=["السرقة"],
        history_length=3,
    )
    assert skip is True
    assert reason == "definitional"


def test_cm13_skip_greeting_phase0():
    """``phase0_class == "greeting"`` → skip regardless of other fields."""
    skip, reason = should_skip_case_memory(
        query="مرحبا",
        phase0_class="greeting",
        concepts=["السرقة"],  # non-empty, but greeting still wins
        history_length=5,
    )
    assert skip is True
    assert reason == "phase0_greeting"


def test_cm14_skip_no_concepts():
    """Empty concepts → ``(True, "no_concepts")``.

    Query has role tags but no legal concepts to key memory on.
    """
    skip, reason = should_skip_case_memory(
        query="موكلي موظف",
        phase0_class=None,
        concepts=[],
        history_length=3,
    )
    assert skip is True
    assert reason == "no_concepts"


def test_cm14b_eligible_case():
    """All skip conditions false → ``(False, "eligible")``.

    Bonus positive-case assertion (not in the original cm1-cm18 list)
    to prove the truth-table is covered symmetrically.
    """
    skip, reason = should_skip_case_memory(
        query="موكلي موظف سرق من الشركة",
        phase0_class="case_analysis",
        concepts=["السرقة", "خيانة الأمانة"],
        history_length=3,
    )
    assert skip is False
    assert reason == "eligible"


# ═════════════════════════════════════════════════════════════════
# Store tests (cm15-cm19) — CP2 · Part C
# ═════════════════════════════════════════════════════════════════
#
# All tests use session_ids prefixed with "test-" so the autouse
# fixture in conftest.py (``reset_case_memory_state``) cleans them up.

def _make_sig(query: str, concepts: list[str], domain: str = "جنائي") -> CaseSignature:
    """Helper — build a signature for tests without repeating kwargs."""
    return build_case_signature(query=query, concepts=concepts, domain=domain)


@pytest.mark.asyncio
async def test_cm15_store_and_retrieve_roundtrip():
    """Store a case, retrieve by signature, all fields preserved."""
    store = CaseMemoryStore()
    sig = _make_sig("موكلي موظف سرق", ["السرقة", "الاعتراف"])

    stored = await store.store(
        session_id="test-cm15",
        signature=sig,
        summary="Test case summary.",
        legal_frame={"articles": ["317"], "precedents": []},
    )

    assert stored.case_hash == sig.hash
    assert stored.turn_count == 1
    assert stored.summary == "Test case summary."

    retrieved = await store.get_by_signature("test-cm15", sig)
    assert retrieved is not None
    assert retrieved.case_hash == sig.hash
    assert retrieved.signature == sig
    assert retrieved.legal_frame["articles"] == ["317"]
    assert retrieved.summary == "Test case summary."


@pytest.mark.asyncio
async def test_cm16_ttl_respected():
    """TTL on the case key and the index ZSET is ~30 days.

    Read TTL via ``redis.ttl`` — no real-time wait. Allow a 60-second
    margin for clock skew between SET and the subsequent TTL read.
    """
    store = CaseMemoryStore()
    sig = _make_sig("قضية اختبار", ["السرقة"])

    await store.store(
        session_id="test-cm16",
        signature=sig,
        summary="TTL test.",
        legal_frame={"articles": [], "precedents": []},
    )

    client = await get_redis_client(db=2)

    case_key = f"case:test-cm16:{sig.hash}"
    ttl_case = await client.ttl(case_key)

    expected = 30 * 24 * 3600
    assert expected - 60 <= ttl_case <= expected, (
        f"case TTL out of band: {ttl_case} (expected ~{expected})"
    )

    ttl_index = await client.ttl("case_index:test-cm16")
    assert expected - 60 <= ttl_index <= expected, (
        f"index TTL out of band: {ttl_index} (expected ~{expected})"
    )


@pytest.mark.asyncio
async def test_cm17_lru_eviction_at_50():
    """Inserting the 51st case drops the oldest-accessed one.

    Uses ``asyncio.sleep(0.01)`` between inserts so the last_access
    timestamps are strictly ordered — deterministic eviction target.
    """
    store = CaseMemoryStore()
    sigs: list[CaseSignature] = []

    for i in range(51):
        sig = _make_sig(f"قضية رقم {i}", [f"concept_{i}", "السرقة"])
        sigs.append(sig)
        await store.store(
            session_id="test-cm17",
            signature=sig,
            summary=f"Case {i}",
            legal_frame={"articles": [], "precedents": []},
        )
        await asyncio.sleep(0.01)

    # Oldest (sigs[0]) must have been evicted.
    first = await store.get_by_signature("test-cm17", sigs[0])
    assert first is None, "oldest case should have been evicted"

    # Newest still present.
    last = await store.get_by_signature("test-cm17", sigs[-1])
    assert last is not None

    # Index ZSET exactly at the cap.
    client = await get_redis_client(db=2)
    count = await client.zcard("case_index:test-cm17")
    assert count == 50, f"expected 50 entries in index, got {count}"


@pytest.mark.asyncio
async def test_cm18_find_similar_threshold():
    """``find_similar`` filters by threshold and sorts desc.

    Two stored cases:
      • ``sig_high``: fully overlaps with query (sim = 1.0).
      • ``sig_low``: disjoint concepts (sim < threshold).

    At threshold=0.60 only ``sig_high`` should be returned.
    """
    store = CaseMemoryStore()

    # Fully overlapping (identical concepts) — will be excluded as
    # "self" if the query signature is identical, so we use slightly
    # different concepts that still score high.
    sig_stored_high = _make_sig(
        query="موظف سرق واعترف",
        concepts=["السرقة", "الاعتراف", "خيانة الأمانة"],
        domain="جنائي",
    )
    await store.store(
        session_id="test-cm18",
        signature=sig_stored_high,
        summary="High similarity case",
        legal_frame={"articles": [], "precedents": []},
    )

    # Disjoint concepts (same domain so domain filter doesn't drop it).
    sig_stored_low = _make_sig(
        query="زوجتي تريد الحضانة",
        concepts=["الحضانة"],
        domain="جنائي",
    )
    await store.store(
        session_id="test-cm18",
        signature=sig_stored_low,
        summary="Low similarity case",
        legal_frame={"articles": [], "precedents": []},
    )

    # Query: shares 2 of 3 concepts with sig_stored_high, plus role_employee tag.
    query_sig = _make_sig(
        query="موكلي موظف سرق أمس",
        concepts=["السرقة", "الاعتراف"],
        domain="جنائي",
    )

    results = await store.find_similar(
        session_id="test-cm18",
        current_sig=query_sig,
        threshold=0.60,
        max_results=3,
    )

    # Must have at least the high-similarity hit.
    assert len(results) >= 1
    top_case, top_sim = results[0]
    assert top_case.case_hash == sig_stored_high.hash
    assert top_sim >= 0.60

    # Every returned pair must respect the threshold.
    for case, sim in results:
        assert sim >= 0.60, f"result below threshold: {sim}"

    # Sorted descending by similarity.
    sims = [sim for _, sim in results]
    assert sims == sorted(sims, reverse=True), "results not sorted desc"


@pytest.mark.asyncio
async def test_cm19_session_isolation():
    """Cases in session A must NOT leak to session B, even with
    identical signatures. Verifies the ``session_id``-in-key scheme."""
    store = CaseMemoryStore()
    sig = _make_sig("نفس القضية", ["السرقة"])

    await store.store(
        session_id="test-cm19-a",
        signature=sig,
        summary="Session A case",
        legal_frame={"articles": [], "precedents": []},
    )

    # Session B: exact lookup must return None.
    result_b = await store.get_by_signature("test-cm19-b", sig)
    assert result_b is None

    # Session B: find_similar must return empty.
    results_b = await store.find_similar(
        session_id="test-cm19-b",
        current_sig=sig,
        threshold=0.0,  # even threshold 0 must not leak
        max_results=3,
    )
    assert results_b == []

    # Sanity: session A still has the case.
    result_a = await store.get_by_signature("test-cm19-a", sig)
    assert result_a is not None
    assert result_a.summary == "Session A case"


# ═════════════════════════════════════════════════════════════════
# Summary tests (cm20, cm20b) — CP2 · Part D
# ═════════════════════════════════════════════════════════════════
#
# These tests mock the LLM via ``monkeypatch.setattr`` on
# ``core.case_memory.summary._call_with_timeout``. No real OpenAI call.

@pytest.mark.asyncio
async def test_cm20_summary_generation_success(monkeypatch):
    """Valid LLM response → trimmed, non-None summary returned."""
    async def _mock_llm(**kwargs):
        return (
            "موكل صاحب شركة. موظفه سرق 50 ألف واعترف وعنده سابقة. "
            "المسار: مطالبة جنائية + تعويض مدني."
        )

    import core.case_memory.summary as summary_mod
    monkeypatch.setattr(
        summary_mod,
        "_call_with_timeout",
        lambda func, timeout, **kwargs: _mock_llm(**kwargs),
    )

    result = await generate_case_summary_once(
        query="موكلي موظف سرق 50 ألف",
        answer="بناءً على السرقة والاعتراف والسابقة، المسار المتوقع...",
    )

    assert result is not None
    assert "صاحب شركة" in result
    assert len(result) <= 600
    assert not result.startswith("خطأ")


@pytest.mark.asyncio
async def test_cm20b_summary_llm_failure_returns_none(monkeypatch):
    """LLM raises → ``None`` returned (never propagates)."""
    async def _mock_fail(**kwargs):
        raise ConnectionError("LLM unavailable")

    import core.case_memory.summary as summary_mod
    monkeypatch.setattr(
        summary_mod,
        "_call_with_timeout",
        lambda func, timeout, **kwargs: _mock_fail(**kwargs),
    )

    result = await generate_case_summary_once(
        query="test query",
        answer="test answer",
    )

    assert result is None


# ═════════════════════════════════════════════════════════════════
# Block builder tests (cm21, cm21b, cm21c, cm22) — CP2 · Part D
# ═════════════════════════════════════════════════════════════════

def test_cm21_build_block_with_cases():
    """Matched cases → formatted block with age label + % + context instruction."""
    sig = CaseSignature(
        domain="جنائي",
        primary_concepts=("السرقة",),
        entity_tags=("role_employee",),
    )

    now = time.time()
    # Case from 2 hours ago.
    case_a = StoredCase(
        case_hash=sig.hash,
        session_id="test",
        signature=sig,
        summary="موظف سرق واعترف.",
        legal_frame={"articles": [], "precedents": []},
        turn_count=1,
        created_at=now - 7200,
        last_access=now - 7200,
    )

    block = build_case_memory_block([(case_a, 0.85)], current_query="ما موقفنا؟")

    assert "قضايا سابقة" in block
    assert "ساعتين" in block
    assert "85%" in block
    assert "موظف سرق" in block
    assert len(block) <= _MAX_BLOCK_CHARS


def test_cm21b_build_block_empty_matches():
    """No matches → empty string (no heading-only injection)."""
    assert build_case_memory_block([], current_query="test") == ""


def test_cm21c_humanize_age_boundaries():
    """Arabic singular/dual/plural-2-10/plural-11+ boundaries."""
    # Seconds
    assert _humanize_age(30) == "لحظات"

    # Minutes
    assert _humanize_age(90) == "دقيقة"        # 1.5 min → singular
    assert _humanize_age(150) == "دقيقتين"     # 2.5 min → dual
    assert _humanize_age(300) == "5 دقائق"     # 5 min  → plural 2-10
    assert _humanize_age(900) == "15 دقيقة"    # 15 min → plural 11+

    # Hours
    assert _humanize_age(3600) == "ساعة"        # 1h  → singular
    assert _humanize_age(7200) == "ساعتين"     # 2h  → dual
    assert _humanize_age(3600 * 5) == "5 ساعات"   # 5h  → plural 2-10
    assert _humanize_age(3600 * 15) == "15 ساعة"  # 15h → plural 11+

    # Days
    assert _humanize_age(86400) == "يوم"        # 1d  → singular
    assert _humanize_age(86400 * 2) == "يومين"  # 2d  → dual
    assert _humanize_age(86400 * 5) == "5 أيام" # 5d  → plural 2-10
    assert _humanize_age(86400 * 15) == "15 يوماً"  # 15d → plural 11+


def test_cm22_block_respects_max_chars():
    """3 cases with long summaries → block stays ≤ MAX_BLOCK_CHARS."""
    sig = CaseSignature(
        domain="جنائي",
        primary_concepts=("السرقة",),
        entity_tags=(),
    )

    now = time.time()
    long_summary = "قضية مفصلة جداً " * 30  # ~480 chars

    matches = [
        (
            StoredCase(
                case_hash=f"hash_{i}",
                session_id="test",
                signature=sig,
                summary=long_summary,
                legal_frame={"articles": [], "precedents": []},
                turn_count=1,
                created_at=now - 3600,
                last_access=now - 3600,
            ),
            0.8 - i * 0.1,
        )
        for i in range(3)
    ]

    block = build_case_memory_block(matches, current_query="test")

    assert len(block) <= _MAX_BLOCK_CHARS
    # Heading survives — we truncate whole lines, not the entire block.
    assert "قضايا سابقة" in block
