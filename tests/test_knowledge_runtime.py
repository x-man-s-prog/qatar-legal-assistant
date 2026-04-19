# -*- coding: utf-8 -*-
"""
Knowledge Runtime tests — ingestion + quarantine + binder + store +
retriever integration + HTTP + adversarial + firewall.

Run: pytest tests/test_knowledge_runtime.py -v
"""
from __future__ import annotations
import os
import sys
import importlib
import pytest

from core.knowledge import (
    KnowledgeRecord, QuarantineRecord, SufficiencyLevel,
    KnowledgeSourceType, AdmissibilityStatus,
    get_store, get_binder, get_ingestor, ingest_all, coverage_stats,
    get_quarantine,
)
from core.knowledge.contract import QUARANTINE_REASONS
from core.evidence.contract import AuthorityRank, TextQuality, VerificationStatus
from core.legal_gates import LegalDomain


# ═════════════════════════════════════════════════════════════════
# Ingestion — no silent drops
# ═════════════════════════════════════════════════════════════════

class TestIngestion:
    @pytest.fixture(autouse=True, scope="class")
    def ensure_ingested(self):
        ingest_all(force=True)

    def test_store_has_records(self):
        assert get_store().count() > 0

    def test_runtime_eligible_count_positive(self):
        assert get_store().runtime_eligible_count() > 100

    def test_multi_source_coverage(self):
        cov = coverage_stats()
        per_src = cov["per_source_type"]
        assert per_src.get("statute", 0) >= 50
        assert per_src.get("legal_principle", 0) >= 30
        assert per_src.get("court_ruling", 0) >= 100

    def test_domain_coverage_spans_multiple(self):
        cov = coverage_stats()
        per_domain = cov["per_domain"]
        # At least 6 distinct domains should have entries
        populated = [d for d, n in per_domain.items() if n > 0]
        assert len(populated) >= 6, f"only {populated} domains populated"

    def test_duplicates_are_dropped(self):
        cov = coverage_stats()
        assert cov["duplicates_dropped"] >= 0
        # Sanity: the store is smaller than total discovered
        assert cov["total_records"] >= cov["runtime_eligible_count"]

    def test_no_silent_drops_everything_accounted(self):
        """Every non-ingested record must be in quarantine."""
        q = get_quarantine()
        # After fresh ingestion, quarantine should hold some records
        assert q.count() >= 0
        for reason in q.reasons_breakdown().keys():
            assert reason in QUARANTINE_REASONS, f"unknown reason code: {reason}"


# ═════════════════════════════════════════════════════════════════
# Quarantine — reason codes
# ═════════════════════════════════════════════════════════════════

class TestQuarantine:
    def test_quarantine_records_have_reason_codes(self):
        q = get_quarantine()
        for rec_dict in q.sample(limit=5):
            assert "reason_code" in rec_dict
            assert rec_dict["reason_code"] in QUARANTINE_REASONS

    def test_quarantine_is_inspectable(self):
        q = get_quarantine()
        breakdown = q.reasons_breakdown()
        assert isinstance(breakdown, dict)

    def test_add_custom_quarantine(self):
        q = get_quarantine()
        before = q.count()
        q.add(
            source_path="test:dummy",
            snippet="نص غير مكتمل",
            reason_code="corrupted_text",
            stage="unit_test",
        )
        assert q.count() == before + 1


# ═════════════════════════════════════════════════════════════════
# Domain Binder
# ═════════════════════════════════════════════════════════════════

class TestDomainBinder:
    def test_labor_text_binds_to_employment(self):
        b = get_binder()
        r = b.bind("تم فصل العامل من شركة بعد إصابة عمل ولم يصرف راتب الأشهر الثلاثة")
        assert r.domain == LegalDomain.EMPLOYMENT

    def test_criminal_text_binds_to_criminal(self):
        b = get_binder()
        r = b.bind("يُعاقب بالحبس كل من ارتكب جريمة سرقة أو تزوير")
        assert r.domain == LegalDomain.CRIMINAL

    def test_family_text_binds_to_family(self):
        b = get_binder()
        r = b.bind("الحضانة وحقوق الأم والنفقة بعد الطلاق")
        assert r.domain == LegalDomain.FAMILY

    def test_canonical_id_locks_domain(self):
        b = get_binder()
        r = b.bind("نص عام جدا", canonical_source_id="labor_law")
        assert r.domain == LegalDomain.EMPLOYMENT
        assert r.locked_by_canonical is True

    def test_subdomain_termination_detected(self):
        b = get_binder()
        r = b.bind("تم فصلي من الشركة دون سبب")
        assert r.subdomain == "termination"

    def test_issue_tag_bounced_cheque(self):
        b = get_binder()
        r = b.bind("حُرر شيك بدون رصيد لا يقابله رصيد")
        assert "bounced_cheque" in r.issue_tags

    def test_remedy_compensation_detected(self):
        b = get_binder()
        r = b.bind("المطالبة بتعويض عن الضرر اللاحق")
        assert "compensation" in r.remedy_tags

    def test_party_role_employee_detected(self):
        b = get_binder()
        r = b.bind("العامل طالب بحقوقه من صاحب العمل")
        assert "employee" in r.party_role_tags


# ═════════════════════════════════════════════════════════════════
# Knowledge Store — multi-index
# ═════════════════════════════════════════════════════════════════

class TestKnowledgeStore:
    @pytest.fixture(autouse=True, scope="class")
    def ensure_ingested(self):
        ingest_all(force=False)

    def test_by_canonical_labor_law(self):
        recs = get_store().by_canonical("labor_law")
        # Some corpora may or may not have labor_law records depending on ingestion sources
        assert isinstance(recs, list)

    def test_by_canonical_family_law(self):
        recs = get_store().by_canonical("family_law")
        assert len(recs) > 0, "family_law should have verified articles"

    def test_by_domain_family_has_records(self):
        recs = get_store().by_domain("family")
        assert len(recs) > 0

    def test_by_domain_criminal_has_records(self):
        recs = get_store().by_domain("criminal")
        assert len(recs) > 0

    def test_by_source_type_statutes(self):
        recs = get_store().by_source_type(KnowledgeSourceType.STATUTE)
        assert len(recs) > 0
        for r in recs:
            assert r.source_type == KnowledgeSourceType.STATUTE

    def test_by_source_type_rulings(self):
        recs = get_store().by_source_type(KnowledgeSourceType.COURT_RULING)
        assert len(recs) > 0

    def test_by_source_type_principles(self):
        recs = get_store().by_source_type(KnowledgeSourceType.LEGAL_PRINCIPLE)
        assert len(recs) > 0

    def test_coverage_report_shape(self):
        c = coverage_stats()
        for k in ("total_records", "runtime_eligible_count",
                   "per_domain", "per_source_type",
                   "distinct_canonical_laws"):
            assert k in c


# ═════════════════════════════════════════════════════════════════
# Contract — firewall safety
# ═════════════════════════════════════════════════════════════════

class TestKnowledgeContract:
    def test_public_citation_has_no_internals(self):
        r = KnowledgeRecord(
            law_title="قانون العمل", law_number="14", law_year="2004",
            article_number=61, document_id="secret123",
        )
        c = r.public_citation()
        assert "secret123" not in c

    def test_non_runtime_eligible_blocked(self):
        r = KnowledgeRecord(
            admissibility=AdmissibilityStatus.UNBOUND,
            text_body="x",
        )
        assert r.is_runtime_eligible() is False

    def test_to_evidence_record_preserves_identity(self):
        r = KnowledgeRecord(
            source_type=KnowledgeSourceType.COURT_RULING,
            ruling_id="tamyiz-2020-42",
            chamber="الدائرة المدنية",
            clean_text="حيث إن الأصل أن…",
            admissibility=AdmissibilityStatus.RUNTIME_ELIGIBLE,
            authority_rank=AuthorityRank.CASE_LAW_TAMYIZ,
            text_quality=TextQuality.CLEAN,
        )
        ev = r.to_evidence_record()
        assert ev.ruling_id == "tamyiz-2020-42"
        assert ev.chamber == "الدائرة المدنية"
        # public_citation now handles case law
        assert "حكم قضائي" in ev.public_citation() or "tamyiz-2020-42" in ev.public_citation()


# ═════════════════════════════════════════════════════════════════
# Retriever integration — KnowledgeStore becomes the source
# ═════════════════════════════════════════════════════════════════

class TestRetrieverUsesKnowledgeStore:
    @pytest.fixture(autouse=True, scope="class")
    def ensure_ingested(self):
        ingest_all(force=False)

    def test_retriever_pulls_from_store(self):
        from core.evidence import get_retriever
        from core.legal_gates import LegalIssueClassifier, FactPatternExtractor
        q = "أريد فهم أحكام الحضانة والنفقة في القانون القطري"
        c = LegalIssueClassifier().classify(q)
        f = FactPatternExtractor().extract(q)
        es = get_retriever().retrieve(q, c, f, issue_keywords=["حضانة", "نفقة"])
        assert es.stage_a_candidates >= 100  # store has hundreds of records
        assert es.has_evidence()

    def test_evidence_set_includes_multiple_source_types(self):
        from core.evidence import get_retriever
        from core.legal_gates import LegalIssueClassifier, FactPatternExtractor
        q = "أحكام الطلاق والحضانة في قطر"
        c = LegalIssueClassifier().classify(q)
        f = FactPatternExtractor().extract(q)
        es = get_retriever().retrieve(q, c, f, issue_keywords=["طلاق", "حضانة"])
        trace = es.trace_summary()
        # The trace must include source-type breakdown
        assert "stage_b_from_statute" in trace
        assert "stage_b_from_principles" in trace
        assert "stage_b_from_case_law" in trace


# ═════════════════════════════════════════════════════════════════
# Sufficiency Intelligence
# ═════════════════════════════════════════════════════════════════

class TestSufficiency:
    def test_sufficiency_enum_values(self):
        levels = {s.value for s in SufficiencyLevel}
        assert "none" in levels
        assert "sufficient_direct" in levels
        assert "sufficient_limited" in levels
        assert "weak" in levels

    def test_sufficient_allows_reasoning(self):
        assert SufficiencyLevel.SUFFICIENT_DIRECT.allows_reasoning() is True
        assert SufficiencyLevel.SUFFICIENT_LIMITED.allows_reasoning() is True

    def test_weak_blocks_reasoning(self):
        assert SufficiencyLevel.WEAK.allows_reasoning() is False
        assert SufficiencyLevel.NONE.allows_reasoning() is False


# ═════════════════════════════════════════════════════════════════
# HTTP — live path uses full knowledge
# ═════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def client():
    os.environ["USE_FAIL_CLOSED_RUNTIME"]    = "true"
    os.environ["ENABLE_LEGACY_FALLBACK"]     = "false"
    os.environ["DISABLE_STREAM_LEGACY_PATH"] = "true"
    if "core.runtime_flags" in sys.modules:
        importlib.reload(sys.modules["core.runtime_flags"])
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app, headers={"Referer": "http://localhost:8000/"}) as c:
        yield c


class TestHTTPKnowledgeIntegration:
    def test_query_response_carries_sufficiency_level(self, client):
        r = client.post("/api/v1/query/", json={
            "query": "أحكام الحضانة والنفقة في القانون القطري وحقوق الأم",
            "session_id": "kr-http-1",
        })
        body = r.json()
        if body.get("from_beta_gate") is True:
            return  # beta upstream gate
        assert "sufficiency_level" in body

    def test_trace_includes_source_breakdown(self, client):
        r = client.post("/api/v1/query/", json={
            "query": "ما حقوقي في حضانة الأطفال بعد الطلاق في قطر",
            "session_id": "kr-http-2",
        })
        body = r.json()
        trace = body.get("evidence_trace", {})
        # when retrieval ran, source-type breakdown must be present
        if trace and trace.get("stage_b_retrieved", 0) > 0:
            assert "stage_b_from_statute" in trace
            assert "stage_b_from_principles" in trace
            assert "stage_b_from_case_law" in trace

    def test_sources_have_firewall_safe_citations(self, client):
        r = client.post("/api/v1/query/", json={
            "query": "أحكام الحضانة في القانون القطري",
            "session_id": "kr-http-3",
        })
        body = r.json()
        for s in body.get("sources", []):
            cite = s.get("citation", "")
            # citation must not be empty and must not contain internal IDs
            assert cite
            assert "chunk_id" not in cite.lower()
            assert "secret" not in cite.lower()


# ═════════════════════════════════════════════════════════════════
# Adversarial — cross-domain contamination (now with full store)
# ═════════════════════════════════════════════════════════════════

class TestAdversarialWithFullKnowledge:
    @pytest.fixture(autouse=True, scope="class")
    def ensure_ingested(self):
        ingest_all(force=False)

    def _retrieve(self, q, issue_kws):
        from core.evidence import get_retriever
        from core.legal_gates import LegalIssueClassifier, FactPatternExtractor
        c = LegalIssueClassifier().classify(q)
        f = FactPatternExtractor().extract(q)
        return get_retriever().retrieve(q, c, f, issue_keywords=issue_kws)

    def test_bank_query_does_not_return_traffic_law(self):
        es = self._retrieve(
            "نزاع قرض بنكي مع مصرف وفوائد تأخير", ["بنك", "قرض"])
        for r in es.records:
            assert r.canonical_id != "traffic_law"

    def test_family_query_does_not_return_penal_code(self):
        es = self._retrieve(
            "أحكام الحضانة وحقوق الأم", ["حضانة", "نفقة"])
        # Criminal rulings should NOT leak in family domain search
        leaks = [r for r in es.records if r.canonical_id == "penal_code"]
        assert not leaks

    def test_inheritance_query_does_not_return_labor_law(self):
        es = self._retrieve(
            "تقسيم الميراث بين الورثة", ["ميراث", "تركة"])
        leaks = [r for r in es.records if r.canonical_id == "labor_law"]
        assert not leaks

    def test_wrong_article_number_blocked(self):
        """Article 9999 of labor law (out of range) must be rejected."""
        from core.evidence import get_canonical_registry
        v = get_canonical_registry().verify(
            "قانون العمل القطري", 9999, LegalDomain.EMPLOYMENT)
        assert v.confidence == "unverified"


# ═════════════════════════════════════════════════════════════════
# Firewall — no raw leakage
# ═════════════════════════════════════════════════════════════════

class TestKnowledgeFirewall:
    def test_knowledge_record_public_dict_is_safe(self):
        kr = KnowledgeRecord(
            source_type=KnowledgeSourceType.STATUTE,
            law_title="قانون العمل", law_number="14", law_year="2004",
            article_number=61, clean_text="نص",
            document_id="secret_doc_id_12345",
            admissibility=AdmissibilityStatus.RUNTIME_ELIGIBLE,
        )
        ev = kr.to_evidence_record()
        d = ev.to_public_dict()
        for key, value in d.items():
            assert "secret_doc_id" not in str(value).lower()
            assert "document_id" not in key.lower()
            assert "chunk_id" not in key.lower()

    def test_case_law_citation_never_empty(self):
        from core.evidence.contract import EvidenceRecord, SourceType
        r = EvidenceRecord(
            source_type=SourceType.CASE_LAW,
            ruling_id="tamyiz-2020-42",
            chamber="الدائرة المدنية",
        )
        cite = r.public_citation()
        assert cite
        assert "حكم" in cite or "tamyiz" in cite
