# -*- coding: utf-8 -*-
"""
Evidence Layer tests — unit + integration + HTTP + adversarial.
=================================================================

Run:   pytest tests/test_evidence_layer.py -v

Coverage:
  • contract validity and public-safety boundaries
  • normalizer rejection rules
  • canonical registry expansion
  • relevance adjudicator (weighted + hard rejects)
  • multi-stage retriever end-to-end
  • fail_closed_pipeline integration (G4/G5/G6)
  • production_runtime response fields
  • adversarial: domain contamination, wrong-law, OCR noise
"""
from __future__ import annotations
import os
import sys
import importlib
import pytest

from core.evidence import (
    EvidenceRecord, EvidenceSet, SourceType, VerificationStatus, AuthorityRank,
    get_retriever, get_adjudicator, get_canonical_registry,
)
from core.evidence.contract import TextQuality
from core.evidence.normalizer import (
    get_normalizer, normalize_article_number, assess_text_quality, clean_text,
)
from core.evidence.adjudicator import RelevanceAdjudicatorV2, RelevanceVerdict
from core.evidence.canonical_expanded import ExpandedCanonicalRegistry
from core.legal_gates import (
    LegalIssueClassifier, FactPatternExtractor, LegalDomain, FactPattern,
)


# ═════════════════════════════════════════════════════════════════
# Unit — EvidenceRecord contract
# ═════════════════════════════════════════════════════════════════

class TestEvidenceRecordContract:
    def test_default_record_is_not_usable(self):
        r = EvidenceRecord()
        assert r.is_usable() is False

    def test_verified_statute_is_usable(self):
        r = EvidenceRecord(
            source_type=SourceType.STATUTE,
            article_text="نص المادة…",
            verification_status=VerificationStatus.VERIFIED,
            text_quality=TextQuality.CLEAN,
        )
        assert r.is_usable() is True

    def test_corrupted_record_is_rejected(self):
        r = EvidenceRecord(
            source_type=SourceType.STATUTE,
            article_text="x",
            verification_status=VerificationStatus.VERIFIED,
            text_quality=TextQuality.CORRUPTED,
        )
        assert r.is_usable() is False

    def test_public_citation_never_includes_internal_ids(self):
        r = EvidenceRecord(
            law_title="قانون العمل القطري",
            law_number="14", law_year="2004",
            article_number=61,
            chunk_id=999999,
            full_document_id="secret_id",
        )
        cite = r.public_citation()
        assert "999999" not in cite
        assert "secret_id" not in cite
        assert "قانون العمل القطري" in cite
        assert "المادة 61" in cite

    def test_public_dict_strips_internals(self):
        r = EvidenceRecord(
            source_type=SourceType.STATUTE,
            law_title="قانون العمل القطري",
            article_text="نص",
            verification_status=VerificationStatus.VERIFIED,
            text_quality=TextQuality.CLEAN,
            chunk_id=123, full_document_id="docX",
        )
        d = r.to_public_dict()
        assert "chunk_id" not in d
        assert "full_document_id" not in d
        assert "relevance_score" not in d
        assert d["citation"] == r.public_citation()


# ═════════════════════════════════════════════════════════════════
# Unit — Normalizer
# ═════════════════════════════════════════════════════════════════

class TestNormalizer:
    def test_normalize_latin_article_number(self):
        assert normalize_article_number("61") == 61
        assert normalize_article_number("  42 ") == 42

    def test_normalize_arabic_article_number(self):
        assert normalize_article_number("٦١") == 61
        assert normalize_article_number("١٢٣") == 123

    def test_normalize_rejects_non_numeric(self):
        assert normalize_article_number("abc") is None
        assert normalize_article_number("") is None
        assert normalize_article_number(None) is None

    def test_assess_corrupted_when_too_short(self):
        q, ar, frag, ocr = assess_text_quality("xx")
        assert q == TextQuality.CORRUPTED

    def test_assess_corrupted_on_nav_noise(self):
        q, _, _, _ = assess_text_quality(
            "إبحث في مواد التشريع والأحكام القضائية والفتاوى"
        )
        assert q == TextQuality.CORRUPTED

    def test_assess_clean_on_clear_arabic(self):
        text = "يُعاقب بالحبس مدة لا تجاوز سبع سنوات كل من ارتكب فعلاً يندرج تحت هذا البند."
        q, ar, frag, ocr = assess_text_quality(text)
        assert q in (TextQuality.CLEAN, TextQuality.MINOR)
        assert ar > 0.60

    def test_clean_text_strips_nav_markers(self):
        dirty = "إبحث في مواد التشريع والنص القانوني هنا"
        assert "إبحث في مواد التشريع" not in clean_text(dirty)

    def test_from_db_chunk_rejects_empty(self):
        n = get_normalizer()
        rec, reason = n.from_db_chunk({"content": ""})
        assert rec is None and reason == "empty_content"

    def test_from_db_chunk_rejects_non_dict(self):
        n = get_normalizer()
        rec, reason = n.from_db_chunk("not a dict")
        assert rec is None


# ═════════════════════════════════════════════════════════════════
# Unit — Canonical Registry
# ═════════════════════════════════════════════════════════════════

class TestCanonicalRegistry:
    def test_registry_has_minimum_laws(self):
        reg = get_canonical_registry()
        assert len(reg.all_law_ids()) >= 20, \
            f"Expected >=20 canonical laws, got {len(reg.all_law_ids())}"

    def test_domain_corpora_employment(self):
        reg = get_canonical_registry()
        assert "labor_law" in reg.domain_corpora(LegalDomain.EMPLOYMENT)

    def test_domain_corpora_criminal(self):
        reg = get_canonical_registry()
        c = reg.domain_corpora(LegalDomain.CRIMINAL)
        assert "penal_code" in c
        assert "cyber_crimes_law" in c
        assert "drug_law" in c

    def test_resolve_law_by_alias(self):
        reg = get_canonical_registry()
        law = reg.resolve_law("قانون العمل")
        assert law is not None
        assert law.law_id == "labor_law"

    def test_verify_valid_citation(self):
        reg = get_canonical_registry()
        v = reg.verify("قانون العمل", 61, LegalDomain.EMPLOYMENT)
        assert v.confidence == "verified"
        assert v.domain_match is True

    def test_verify_wrong_domain_rejected(self):
        reg = get_canonical_registry()
        v = reg.verify("قانون العمل", 61, LegalDomain.CRIMINAL)
        assert v.confidence == "unverified"
        assert "domain_mismatch" in v.block_reason

    def test_verify_article_out_of_range(self):
        reg = get_canonical_registry()
        v = reg.verify("قانون العمل", 9999, LegalDomain.EMPLOYMENT)
        assert v.confidence == "unverified"
        assert "article_out_of_range" in v.block_reason

    def test_verify_unknown_law_rejected(self):
        reg = get_canonical_registry()
        v = reg.verify("قانون غير موجود أبداً", 1, LegalDomain.CIVIL)
        assert v.confidence == "unverified"
        assert "law_not_in_canonical_registry" in v.block_reason


# ═════════════════════════════════════════════════════════════════
# Unit — Relevance Adjudicator
# ═════════════════════════════════════════════════════════════════

class TestAdjudicator:
    def setup_method(self):
        self.adj = get_adjudicator()

    def _make_statute(self, canonical_id="labor_law", domain="employment",
                       article=61, quality=TextQuality.CLEAN,
                       status=VerificationStatus.VERIFIED):
        return EvidenceRecord(
            source_type=SourceType.STATUTE,
            law_title="قانون العمل القطري",
            article_text="نص المادة القانونية الكامل",
            article_number=article, canonical_id=canonical_id,
            domain=domain,
            verification_status=status,
            text_quality=quality,
            authority_rank=AuthorityRank.STATUTE_IN_FORCE,
            in_force_status="in_force",
        )

    def test_domain_mismatch_hard_reject(self):
        rec = self._make_statute()
        fp = FactPattern()
        v = self.adj.adjudicate(rec, LegalDomain.CRIMINAL, fp,
                                 issue_keywords=["سرقة"])
        assert v.is_relevant is False
        assert "domain_mismatch" in v.hard_reject_reason

    def test_corrupted_text_hard_reject(self):
        rec = self._make_statute(quality=TextQuality.CORRUPTED)
        fp = FactPattern()
        v = self.adj.adjudicate(rec, LegalDomain.EMPLOYMENT, fp)
        assert v.is_relevant is False
        assert "text_quality_corrupted" in v.hard_reject_reason

    def test_unverified_statute_hard_reject(self):
        rec = self._make_statute(status=VerificationStatus.UNVERIFIED)
        fp = FactPattern()
        v = self.adj.adjudicate(rec, LegalDomain.EMPLOYMENT, fp)
        assert v.is_relevant is False
        assert "statute_unverified" in v.hard_reject_reason

    def test_good_employment_record_passes(self):
        rec = self._make_statute()
        fp = FactPattern()
        v = self.adj.adjudicate(rec, LegalDomain.EMPLOYMENT, fp,
                                 issue_keywords=["عمل", "فصل"])
        assert v.is_relevant is True
        assert v.composite_score > 0.50


# ═════════════════════════════════════════════════════════════════
# Integration — multi-stage retriever
# ═════════════════════════════════════════════════════════════════

class TestRetrieverIntegration:
    def test_family_query_produces_verified_statutes(self):
        q = "ما حقوقي في حضانة أطفالي بعد الطلاق"
        c = LegalIssueClassifier().classify(q)
        f = FactPatternExtractor().extract(q)
        es = get_retriever().retrieve(
            q, c, f, issue_keywords=["حضانة", "طلاق"])
        assert es.has_evidence()
        assert es.has_direct_statute()
        # top record should be family law
        top = es.top_authority()
        assert top is not None
        assert top.canonical_id == "family_law" or top.domain == "family"

    def test_adversarial_banking_query_does_not_return_traffic_law(self):
        q = "نزاع قرض بنكي مع مصرف قطري ومطالبة بفوائد تأخير"
        c = LegalIssueClassifier().classify(q)
        f = FactPatternExtractor().extract(q)
        es = get_retriever().retrieve(
            q, c, f, issue_keywords=["بنك", "قرض", "فوائد"])
        # Must NOT return traffic law results
        for r in es.records:
            assert r.canonical_id != "traffic_law", \
                f"Traffic law leaked into banking query: {r.public_citation()}"

    def test_adversarial_inheritance_query_does_not_return_penal(self):
        q = "تقسيم الميراث بين الورثة في قطر وحقوق الزوجة"
        c = LegalIssueClassifier().classify(q)
        f = FactPatternExtractor().extract(q)
        es = get_retriever().retrieve(
            q, c, f, issue_keywords=["ميراث", "ورثة"])
        for r in es.records:
            assert r.canonical_id != "penal_code", \
                f"Penal code leaked into inheritance query: {r.public_citation()}"

    def test_domain_unknown_returns_empty_set(self):
        """If classifier returns UNKNOWN domain, no evidence should be retrieved."""
        from core.legal_gates import ClassificationResult
        c = ClassificationResult(primary_domain=LegalDomain.UNKNOWN)
        f = FactPattern()
        es = get_retriever().retrieve("سؤال غامض جداً", c, f)
        assert len(es.records) == 0
        assert es.stage_e_selected == 0

    def test_evidence_set_trace_is_populated(self):
        q = "ما حقوقي في عقد العمل"
        c = LegalIssueClassifier().classify(q)
        f = FactPatternExtractor().extract(q)
        es = get_retriever().retrieve(q, c, f, issue_keywords=["عمل"])
        trace = es.trace_summary()
        for field in ("stage_a_candidates", "stage_b_retrieved",
                       "stage_c_adjudicated", "stage_d_verified",
                       "stage_e_selected"):
            assert field in trace


# ═════════════════════════════════════════════════════════════════
# Integration — fail_closed_pipeline uses G4/G5/G6
# ═════════════════════════════════════════════════════════════════

class TestPipelineIntegration:
    def test_pipeline_exposes_evidence_set_on_success(self):
        from core.fail_closed_pipeline import answer_fail_closed
        result = answer_fail_closed(
            "ما حقوقي في حضانة أطفالي بعد الطلاق في قانون الأسرة القطري"
        )
        if not result.is_blocked:
            # when unblocked, evidence set must be populated
            assert result.evidence_set is not None
            assert result.evidence_set.has_direct_statute()
            assert "G4_evidence_retrieval" in result.gates_passed
            assert "G5_evidence_sufficient" in result.gates_passed
            assert "G6_canonical_verification" in result.gates_passed

    def test_pipeline_populates_public_sources_safely(self):
        from core.fail_closed_pipeline import answer_fail_closed
        result = answer_fail_closed(
            "أحكام الحضانة وحقوق الأم في قطر"
        )
        if result.public_sources:
            for s in result.public_sources:
                # public dict must not expose internals
                assert "chunk_id" not in s
                assert "full_document_id" not in s
                assert "citation" in s

    def test_pipeline_evidence_trace_has_stages(self):
        from core.fail_closed_pipeline import answer_fail_closed
        result = answer_fail_closed(
            "أريد فهم أحكام الحضانة في القانون القطري"
        )
        if result.evidence_trace:
            assert "stage_e_selected" in result.evidence_trace


# ═════════════════════════════════════════════════════════════════
# HTTP — live path with evidence layer
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


class TestHTTPEvidenceIntegration:
    def test_json_response_includes_evidence_trace(self, client):
        r = client.post("/api/v1/query/", json={
            "query": "أحكام الحضانة في قانون الأسرة القطري",
            "session_id": "ev-http-1",
        })
        body = r.json()
        if body.get("from_beta_gate") is True:
            return  # beta upstream middleware short-circuits
        assert "evidence_trace" in body, "evidence_trace missing from response"

    def test_json_sources_are_safe_dicts_only(self, client):
        r = client.post("/api/v1/query/", json={
            "query": "ما حقوقي في حضانة الأطفال بعد الطلاق في قطر",
            "session_id": "ev-http-2",
        })
        body = r.json()
        for s in body.get("sources", []):
            # public firewall check — no internal ids leaked
            assert "chunk_id" not in s
            assert "full_document_id" not in s
            assert "relevance_score" not in s

    def test_drafting_refusal_no_evidence_call(self, client):
        """Drafting queries must refuse WITHOUT running retrieval.

        The drafting pre-gate runs BEFORE any evidence call, so the
        response must have no evidence_trace (None or absent / empty).
        """
        r = client.post("/api/v1/query/", json={
            "query": "اكتب لي مذكرة دفاع كاملة",
            "session_id": "ev-http-3",
        })
        body = r.json()
        if body.get("from_beta_gate") is True:
            return  # beta upstream gate
        assert body.get("is_blocked") is True
        # evidence_trace absent (None) OR empty dict — never populated
        trace = body.get("evidence_trace")
        assert trace in (None, {}), \
            f"drafting refusal leaked evidence trace: {trace}"

    def test_narrative_with_contract_word_is_not_drafting(self, client):
        """Mentioning 'عقد بيع' in narrative must NOT trigger drafting refusal."""
        r = client.post("/api/v1/query/", json={
            "query": "تم تزوير توقيعي على عقد بيع عقار رغم أنني لم أوقع عليه مطلقاً",
            "session_id": "ev-http-4",
        })
        body = r.json()
        assert "drafting_request_rejected" not in body.get("block_reasons", []), \
            "narrative contract mention wrongly flagged as drafting"


# ═════════════════════════════════════════════════════════════════
# Adversarial — cross-domain contamination
# ═════════════════════════════════════════════════════════════════

class TestAdversarialContamination:
    def _retrieve(self, q, issue_kws):
        c = LegalIssueClassifier().classify(q)
        f = FactPatternExtractor().extract(q)
        return get_retriever().retrieve(q, c, f, issue_keywords=issue_kws)

    def test_bank_query_never_returns_traffic(self):
        es = self._retrieve(
            "نزاع قرض بنكي ومطالبة بفوائد مركبة",
            ["بنك", "قرض", "فوائد"])
        leaks = [r for r in es.records if r.canonical_id == "traffic_law"]
        assert not leaks

    def test_software_ip_never_returns_administrative(self):
        es = self._retrieve(
            "نزاع ملكية فكرية على برنامج حاسوبي وحقوق المؤلف",
            ["برمجيات", "حق المؤلف", "ملكية فكرية"])
        leaks = [r for r in es.records
                  if r.canonical_id == "administrative_judiciary_law"]
        assert not leaks

    def test_cyber_crime_query_never_returns_family_law(self):
        es = self._retrieve(
            "تم ابتزازي إلكترونياً عبر الواتساب بصور خاصة",
            ["ابتزاز", "جرائم إلكترونية"])
        leaks = [r for r in es.records if r.canonical_id == "family_law"]
        assert not leaks

    def test_wrong_article_number_blocked(self):
        """Article 9999 of labor law (out of range) must be rejected."""
        reg = get_canonical_registry()
        v = reg.verify("قانون العمل القطري", 9999, LegalDomain.EMPLOYMENT)
        assert v.confidence == "unverified"
        assert "article_out_of_range" in v.block_reason


# ═════════════════════════════════════════════════════════════════
# Firewall — no raw retrieval leakage
# ═════════════════════════════════════════════════════════════════

class TestFirewall:
    def test_public_citation_has_no_sql(self):
        r = EvidenceRecord(
            law_title="قانون العمل",
            law_number="14", law_year="2004",
            article_number=61,
        )
        cite = r.public_citation()
        assert "SELECT" not in cite.upper()
        assert "FROM" not in cite.upper()
        assert "chunk_id" not in cite.lower()

    def test_public_snippet_trims_long_text(self):
        r = EvidenceRecord(article_text="ن" * 5000)
        snippet = r.public_snippet(max_chars=280)
        assert len(snippet) <= 282  # 280 + "…"

    def test_to_public_dict_has_only_safe_keys(self):
        r = EvidenceRecord(
            source_type=SourceType.STATUTE,
            article_text="نص",
            verification_status=VerificationStatus.VERIFIED,
            text_quality=TextQuality.CLEAN,
            relevance_score=0.85,
            chunk_id=42,
        )
        d = r.to_public_dict()
        allowed = {"source_type", "citation", "snippet", "domain",
                    "authority_rank", "verified", "in_force"}
        # every key must be in allowed set
        for k in d.keys():
            assert k in allowed, f"leaked field in public dict: {k}"
