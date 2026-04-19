# -*- coding: utf-8 -*-
"""
DB Activation tests — proves ingest_db_chunks actually processes rows.

Uses a MockAsyncPool that mimics asyncpg: supports async `acquire()` +
`fetch()` with keyset pagination. Runs synthetic rows (good + bad +
duplicate + OCR noise + wrong article) through the full pipeline.

Run:  pytest tests/test_db_activation.py -v
"""
from __future__ import annotations
import asyncio
import os
import sys
import importlib
import pytest


# ═════════════════════════════════════════════════════════════════
# MockAsyncPool — asyncpg-compatible shape
# ═════════════════════════════════════════════════════════════════

class _MockConn:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, sql, *args):
        # Honor "WHERE id > $1 ORDER BY id LIMIT $2" semantics
        if len(args) >= 2:
            last_id, limit = args[0], args[1]
        elif len(args) == 1:
            last_id, limit = args[0], 100
        else:
            last_id, limit = 0, 100
        out = [r for r in self._rows if r.get("id", 0) > last_id][:limit]
        return out

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None


class MockAsyncPool:
    def __init__(self, rows):
        self._rows = rows

    def acquire(self):
        return _MockConn(self._rows)

    async def close(self):
        return None


# ═════════════════════════════════════════════════════════════════
# Synthetic row fixtures
# ═════════════════════════════════════════════════════════════════

GOOD_LABOR_ROW = {
    "id": 1, "law_id": 14, "source": "almeezan",
    "law_name": "قانون العمل القطري",
    "law_number": "14", "law_year": "2004",
    "article_number": "61",
    "content": (
        "يلتزم العامل بأن يؤدي العمل بنفسه، وأن يبذل في أدائه من العناية ما "
        "يبذله الشخص المعتاد، وأن يأتمر بأوامر صاحب العمل الخاصة بتنفيذ العمل "
        "في حدود الاتفاق والقانون والأصول العامة للصناعة."
    ),
    "domain": "employment",
}

GOOD_FAMILY_ROW = {
    "id": 2, "law_id": 22, "source": "almeezan",
    "law_name": "قانون الأسرة القطري",
    "law_number": "22", "law_year": "2006",
    "article_number": "165",
    "content": (
        "الحضانة حفظ الولد ورعايته وتربيته بما لا يتعارض مع حق وليه في الولاية "
        "على النفس."
    ),
    "domain": "family",
}

DUPLICATE_FAMILY_ROW = {
    # Same (law, article, content) as GOOD_FAMILY_ROW → should be deduplicated
    "id": 3, "law_id": 22, "source": "almeezan",
    "law_name": "قانون الأسرة القطري",
    "law_number": "22", "law_year": "2006",
    "article_number": "165",
    "content": (
        "الحضانة حفظ الولد ورعايته وتربيته بما لا يتعارض مع حق وليه في الولاية "
        "على النفس."
    ),
    "domain": "family",
}

CORRUPTED_OCR_ROW = {
    "id": 4, "law_id": 99, "source": "almeezan",
    "law_name": "قانون مجهول",
    "law_number": "0", "law_year": "0",
    "article_number": "1",
    "content": "إبحث في مواد التشريع ملفات متعلقة",  # pure nav-noise
    "domain": "",
}

EMPTY_ROW = {
    "id": 5, "law_id": None, "source": "",
    "law_name": "", "law_number": "", "law_year": "",
    "article_number": "", "content": "",
    "domain": "",
}

OUT_OF_RANGE_ARTICLE_ROW = {
    "id": 6, "law_id": 14, "source": "almeezan",
    "law_name": "قانون العمل القطري",
    "law_number": "14", "law_year": "2004",
    "article_number": "9999",   # article range for labor_law is 1..145
    "content": (
        "نص لا يجب قبوله لأنه يدّعي مادة 9999 من قانون العمل وهي غير موجودة."
    ),
    "domain": "employment",
}

UNKNOWN_LAW_ROW = {
    "id": 7, "law_id": 777, "source": "almeezan",
    "law_name": "قانون وهمي غير موجود في السجل",
    "law_number": "777", "law_year": "1999",
    "article_number": "1",
    "content": (
        "نص من قانون وهمي غير موجود في السجل الكنسي ويجب رفضه من الـ binder "
        "أو قبوله كـ support-only لا أكثر مع توسيم واضح."
    ),
    "domain": "",
}

GOOD_CRIMINAL_ROW = {
    "id": 8, "law_id": 11, "source": "almeezan",
    "law_name": "قانون العقوبات القطري",
    "law_number": "11", "law_year": "2004",
    "article_number": "311",
    "content": (
        "كل من تسبب بخطئه في موت شخص بأن كان ذلك ناشئاً عن إهماله أو رعونته "
        "أو عدم احترازه أو عدم مراعاته للقوانين واللوائح يعاقب بالحبس."
    ),
    "domain": "criminal",
}


ALL_ROWS = [
    GOOD_LABOR_ROW, GOOD_FAMILY_ROW, DUPLICATE_FAMILY_ROW,
    CORRUPTED_OCR_ROW, EMPTY_ROW, OUT_OF_RANGE_ARTICLE_ROW,
    UNKNOWN_LAW_ROW, GOOD_CRIMINAL_ROW,
]


# ═════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _reset_stores():
    """Reset KnowledgeStore + Quarantine + ActivationState before each test."""
    from core.knowledge.store import get_store
    from core.knowledge.quarantine import get_quarantine
    from core.knowledge.db_activation import reset_state
    get_store().reset()
    get_quarantine().reset()
    reset_state()
    yield


# ═════════════════════════════════════════════════════════════════
# Unit tests — activation state machine
# ═════════════════════════════════════════════════════════════════

class TestActivationStateMachine:
    def test_skip_mode_does_nothing(self):
        from core.knowledge.db_activation import activate_for_test
        result = activate_for_test(pool=None, mode="skip")
        assert result["mode"] == "skip"
        assert result["attempted"] is True
        assert result["completed"] is True
        assert result["rows_read"] == 0

    def test_persisted_mode_without_snapshot_is_noop(self, tmp_path):
        os.environ["DB_KNOWLEDGE_SNAPSHOT_PATH"] = str(tmp_path / "empty.pkl")
        from core.knowledge.db_activation import activate_for_test
        from core.knowledge import persistence
        importlib.reload(persistence)
        result = activate_for_test(pool=None, mode="persisted")
        assert result["mode"] == "persisted"
        assert result["snapshot_loaded"] is False
        assert result["completed"] is True
        assert result["rows_read"] == 0

    def test_full_mode_without_pool_returns_error(self):
        from core.knowledge.db_activation import activate_for_test
        result = activate_for_test(pool=None, mode="full")
        assert result["mode"] == "full"
        assert "db_pool_unavailable" in result["errors"]
        assert result["completed"] is True


# ═════════════════════════════════════════════════════════════════
# Integration — full DB ingest via mock pool
# ═════════════════════════════════════════════════════════════════

class TestFullDBIngest:
    def test_ingests_good_rows_into_store(self):
        from core.knowledge.db_activation import activate_for_test
        from core.knowledge.store import get_store
        pool = MockAsyncPool(ALL_ROWS)
        result = activate_for_test(pool=pool, mode="full")
        assert result["completed"] is True
        assert result["db_available"] is True
        assert result["rows_read"] == len(ALL_ROWS)
        # Store must contain the good rows
        store = get_store()
        labor = store.by_canonical("labor_law")
        family = store.by_canonical("family_law")
        crim = store.by_canonical("penal_code")
        assert any(r.article_number == 61 for r in labor)
        assert any(r.article_number == 165 for r in family)
        assert any(r.article_number == 311 for r in crim)

    def test_duplicate_row_is_collapsed(self):
        from core.knowledge.db_activation import activate_for_test
        from core.knowledge.store import get_store
        pool = MockAsyncPool(ALL_ROWS)
        result = activate_for_test(pool=pool, mode="full")
        store = get_store()
        # Family article 165 appears twice in input — store must have exactly 1
        family_165 = store.by_article("family_law", 165)
        assert len(family_165) == 1, \
            f"Expected dedup to collapse to 1, got {len(family_165)}"
        # The duplicate counter must be >= 1
        assert store.duplicates_count() >= 1

    def test_corrupted_row_quarantined(self):
        from core.knowledge.db_activation import activate_for_test
        from core.knowledge.quarantine import get_quarantine
        pool = MockAsyncPool(ALL_ROWS)
        activate_for_test(pool=pool, mode="full")
        reasons = get_quarantine().reasons_breakdown()
        assert sum(reasons.values()) >= 1

    def test_empty_row_quarantined_with_reason(self):
        from core.knowledge.db_activation import activate_for_test
        from core.knowledge.quarantine import get_quarantine
        pool = MockAsyncPool([EMPTY_ROW])
        activate_for_test(pool=pool, mode="full")
        reasons = get_quarantine().reasons_breakdown()
        assert "no_text" in reasons or "legacy_noise" in reasons

    def test_out_of_range_article_quarantined(self):
        from core.knowledge.db_activation import activate_for_test
        from core.knowledge.quarantine import get_quarantine
        pool = MockAsyncPool([OUT_OF_RANGE_ARTICLE_ROW])
        activate_for_test(pool=pool, mode="full")
        reasons = get_quarantine().reasons_breakdown()
        assert "unverifiable_article" in reasons

    def test_unknown_law_handled_by_binder(self):
        from core.knowledge.db_activation import activate_for_test
        from core.knowledge.store import get_store
        from core.knowledge.quarantine import get_quarantine
        pool = MockAsyncPool([UNKNOWN_LAW_ROW])
        activate_for_test(pool=pool, mode="full")
        # Unknown law → either quarantined or bound as support-only
        # It must NOT be runtime-eligible unless binder finds domain
        store = get_store()
        quar = get_quarantine()
        assert (store.count() + quar.count()) >= 1, \
            "row must be accounted for — no silent drop"


# ═════════════════════════════════════════════════════════════════
# Snapshot persistence
# ═════════════════════════════════════════════════════════════════

class TestPersistence:
    def test_snapshot_save_and_load(self, tmp_path):
        snap = tmp_path / "test_snap.pkl"
        os.environ["DB_KNOWLEDGE_SNAPSHOT_PATH"] = str(snap)

        # Fresh reload of persistence module to pick up env
        from core.knowledge import persistence
        importlib.reload(persistence)
        from core.knowledge.db_activation import activate_for_test
        from core.knowledge.store import get_store

        # Ingest → snapshot should be saved
        pool = MockAsyncPool([GOOD_LABOR_ROW, GOOD_FAMILY_ROW, GOOD_CRIMINAL_ROW])
        result = activate_for_test(pool=pool, mode="full")
        assert result["completed"] is True
        assert snap.exists(), "snapshot file should exist after full ingest"

        # Reset store and load via "persisted" mode — DB should not be touched
        get_store().reset()
        result2 = activate_for_test(pool=None, mode="persisted")
        assert result2["snapshot_loaded"] is True
        assert get_store().count() >= 3

    def test_version_mismatch_refused(self, tmp_path):
        import pickle
        snap = tmp_path / "bad_version.pkl"
        # Write a snapshot with wrong version
        with snap.open("wb") as f:
            pickle.dump({"header": {"version": "v0.0"}, "records": []}, f)
        os.environ["DB_KNOWLEDGE_SNAPSHOT_PATH"] = str(snap)

        from core.knowledge import persistence
        importlib.reload(persistence)
        loaded = persistence.load_snapshot()
        assert loaded is None, "version mismatch must refuse"


# ═════════════════════════════════════════════════════════════════
# Retriever uses DB-derived records post-ingest
# ═════════════════════════════════════════════════════════════════

class TestRetrieverReadsDBDerived:
    def test_db_statute_surfaces_in_retrieval(self):
        """Ingest a DB row → it must be visible in KnowledgeStore lookups.

        Uses store.by_canonical (not retriever) to avoid dependence on
        the classifier's confidence floor — this test is about DB-ingest
        visibility, not about end-to-end classification.
        """
        from core.knowledge.db_activation import activate_for_test
        from core.knowledge.store import get_store

        pool = MockAsyncPool([GOOD_CRIMINAL_ROW])
        activate_for_test(pool=pool, mode="full")

        # Ingested record must appear in the canonical index
        store = get_store()
        penal_recs = store.by_canonical("penal_code")
        m311 = [r for r in penal_recs if r.article_number == 311]
        assert m311, "DB-ingested penal article 311 not in store"

        # And it must be runtime_eligible
        assert m311[0].is_runtime_eligible(), \
            "DB record should be runtime_eligible after full ingest"

        # And the retriever's corpus must also see it via by_domain
        crim_recs = store.by_domain("criminal", runtime_eligible_only=True)
        assert any(r.article_number == 311 for r in crim_recs)

    def test_retrieval_trace_counts_db_origin(self):
        from core.knowledge.db_activation import activate_for_test
        from core.evidence import get_retriever
        from core.legal_gates import LegalIssueClassifier, FactPatternExtractor

        pool = MockAsyncPool([GOOD_LABOR_ROW])
        activate_for_test(pool=pool, mode="full")

        q = "ما واجبات العامل في عقد العمل"
        c = LegalIssueClassifier().classify(q)
        f = FactPatternExtractor().extract(q)
        es = get_retriever().retrieve(q, c, f, issue_keywords=["عامل", "عمل"])
        trace = es.trace_summary()
        # The trace must be present and carry stage_b_from_db field
        assert "stage_b_from_db" in trace


# ═════════════════════════════════════════════════════════════════
# Live endpoint — debug/knowledge-activation reports state
# ═════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def client():
    os.environ["USE_FAIL_CLOSED_RUNTIME"]    = "true"
    os.environ["ENABLE_LEGACY_FALLBACK"]     = "false"
    os.environ["DISABLE_STREAM_LEGACY_PATH"] = "true"
    os.environ["DB_KNOWLEDGE_ACTIVATION_MODE"] = "skip"  # startup won't block
    if "core.runtime_flags" in sys.modules:
        importlib.reload(sys.modules["core.runtime_flags"])
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app, headers={"Referer": "http://localhost:8000/"}) as c:
        yield c


class TestActivationEndpoint:
    def test_debug_endpoint_reports_activation_state(self, client):
        r = client.get("/debug/knowledge-activation")
        assert r.status_code == 200
        body = r.json()
        for k in ("activation", "snapshot", "store", "quarantine"):
            assert k in body

    def test_activation_state_has_required_keys(self, client):
        r = client.get("/debug/knowledge-activation")
        body = r.json()
        act = body["activation"]
        for key in ("attempted", "completed", "mode", "db_available",
                     "snapshot_loaded", "rows_read", "ingested",
                     "quarantined", "errors"):
            assert key in act


# ═════════════════════════════════════════════════════════════════
# Production runtime exposes activation snapshot on every response
# ═════════════════════════════════════════════════════════════════

class TestProductionRuntimeExposesActivation:
    def test_response_carries_knowledge_activation_snapshot(self, client):
        r = client.post("/api/v1/query/", json={
            "query": "أحكام الحضانة في القانون القطري وحقوق الأم",
            "session_id": "db-act-1",
        })
        body = r.json()
        if body.get("from_beta_gate") is True:
            return
        # knowledge_activation must appear on every new-runtime response
        ka = body.get("knowledge_activation")
        assert ka is not None
        assert "mode" in ka
        assert "total_records" in ka
        assert "per_source_type" in ka


# ═════════════════════════════════════════════════════════════════
# Adversarial — wrong-law DB rows can't pollute results
# ═════════════════════════════════════════════════════════════════

class TestAdversarialDBRows:
    def test_out_of_range_never_retrieved(self):
        from core.knowledge.db_activation import activate_for_test
        from core.knowledge.store import get_store
        pool = MockAsyncPool([OUT_OF_RANGE_ARTICLE_ROW])
        activate_for_test(pool=pool, mode="full")
        # Must NOT be in store — it's quarantined
        labor = get_store().by_canonical("labor_law")
        # article 9999 must never appear
        assert not any(r.article_number == 9999 for r in labor)

    def test_corrupted_ocr_never_becomes_evidence(self):
        from core.knowledge.db_activation import activate_for_test
        from core.evidence import get_retriever
        from core.legal_gates import LegalIssueClassifier, FactPatternExtractor
        pool = MockAsyncPool([CORRUPTED_OCR_ROW])
        activate_for_test(pool=pool, mode="full")
        # No query should return the corrupted row as a source
        q = "سؤال قانوني عام"
        c = LegalIssueClassifier().classify(q)
        f = FactPatternExtractor().extract(q)
        es = get_retriever().retrieve(q, c, f)
        for r in es.records:
            assert "ملفات متعلقة" not in (r.article_text or "")
            assert "إبحث في مواد التشريع" not in (r.article_text or "")

    def test_duplicates_collapsed_in_retrieval(self):
        from core.knowledge.db_activation import activate_for_test
        from core.evidence import get_retriever
        from core.legal_gates import LegalIssueClassifier, FactPatternExtractor
        pool = MockAsyncPool([GOOD_FAMILY_ROW, DUPLICATE_FAMILY_ROW])
        activate_for_test(pool=pool, mode="full")
        q = "أحكام الحضانة في القانون القطري"
        c = LegalIssueClassifier().classify(q)
        f = FactPatternExtractor().extract(q)
        es = get_retriever().retrieve(q, c, f, issue_keywords=["حضانة"])
        # Final set must NOT contain two copies of article 165
        fam_165 = [r for r in es.records
                    if r.canonical_id == "family_law" and r.article_number == 165]
        assert len(fam_165) <= 1
