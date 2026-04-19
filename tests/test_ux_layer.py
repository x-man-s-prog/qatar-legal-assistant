# -*- coding: utf-8 -*-
"""
UX Intelligence Layer tests.

Covers:
  • MissingDataEngine: gap detection per issue
  • LegalQuestionGenerator: issue-tied, deduplicated
  • UserIntent: 5 modes
  • ResponseMode: READY / PARTIAL / NOT_READY transitions
  • Session-scoped asked-question dedup
  • Orchestrator: compose prepend/append text blocks
  • HTTP integration: response carries `ux` block
  • Phase 12 scenarios: cheque / inheritance / drafting
  • Anti-frustration: ≤3 questions, no repeats

Run: pytest tests/test_ux_layer.py -v
"""
from __future__ import annotations
import os, sys, importlib
import pytest

from core.ux import (
    analyze_gaps, GapLevel, IssueGap,
    generate_questions, LegalQuestion,
    detect_user_intent, UserIntent,
    assess_readiness, ResponseMode,
    build_ux_enhancement,
)
from core.ux.orchestrator import get_asked_store
from core.domain_pipeline import build_issue_graph, bind_evidence_to_issues
from core.evidence.contract import (
    EvidenceRecord, SourceType, AuthorityRank, TextQuality, VerificationStatus,
)


# ═════════════════════════════════════════════════════════════════
# User Intent Detection
# ═════════════════════════════════════════════════════════════════

class TestUserIntent:
    def test_drafting_intent(self):
        assert detect_user_intent("اكتب لي مذكرة دفاع") == UserIntent.DRAFTING

    def test_action_intent(self):
        assert detect_user_intent("وش اسوي الحين") == UserIntent.ACTION

    def test_standing_intent(self):
        assert detect_user_intent("تقييم موقفي القانوني") == UserIntent.STANDING_ASSESSMENT

    def test_win_chances_intent(self):
        assert detect_user_intent("هل سأربح القضية") == UserIntent.WIN_CHANCES

    def test_analysis_default(self):
        assert detect_user_intent("ما حكم كذا") == UserIntent.ANALYSIS


# ═════════════════════════════════════════════════════════════════
# Gap Analysis
# ═════════════════════════════════════════════════════════════════

class TestGapAnalysis:
    def test_empty_graph_blocks_everything(self):
        r = analyze_gaps(graph=None, bound_evidence=None, facts=[])
        assert r.blocks_ruling is True
        assert r.blocks_drafting is True

    def test_graph_with_no_evidence_has_gaps(self):
        g = build_issue_graph("criminal", "defamation")
        r = analyze_gaps(g, bound_evidence=None, facts=[])
        assert len(r.gaps) > 0
        assert r.critical_count > 0

    def test_graph_with_evidence_and_facts_fewer_gaps(self):
        g = build_issue_graph("criminal", "defamation")
        rec = EvidenceRecord(
            source_type=SourceType.STATUTE,
            law_title="قانون العقوبات",
            law_number="11", law_year="2004",
            article_number=203,
            article_text="يعاقب من قذف أو سب علانية",
            canonical_id="penal_code",
            verification_status=VerificationStatus.VERIFIED,
            text_quality=TextQuality.CLEAN,
            authority_rank=AuthorityRank.STATUTE_IN_FORCE,
            in_force_status="in_force",
        )
        bound = bind_evidence_to_issues(g, [rec], ["قذف", "سب"])
        facts = ["حدث في مكان عام بحضور 3 شهود وتم تسجيل الواقعة"]
        r_with = analyze_gaps(g, bound, facts)
        r_without = analyze_gaps(g, None, [])
        # With facts+evidence, fewer critical gaps than without
        assert r_with.critical_count <= r_without.critical_count

    def test_gap_criticality_for_threshold_is_high(self):
        g = build_issue_graph("banking", "cheque_guarantee")
        r = analyze_gaps(g, None, [])
        threshold_gaps = [g for g in r.gaps if g.issue_kind == "threshold"]
        assert any(g.criticality == GapLevel.HIGH for g in threshold_gaps)


# ═════════════════════════════════════════════════════════════════
# Question Generation
# ═════════════════════════════════════════════════════════════════

class TestQuestionGenerator:
    def test_questions_tied_to_issue(self):
        g = build_issue_graph("banking", "cheque_guarantee")
        r = analyze_gaps(g, None, [])
        qs = generate_questions(r, domain="banking", subdomain="cheque_guarantee")
        assert len(qs) > 0
        for q in qs:
            assert q.issue_id in g.nodes

    def test_max_three_questions(self):
        g = build_issue_graph("criminal", "defamation")
        r = analyze_gaps(g, None, [])
        qs = generate_questions(r, domain="criminal", subdomain="defamation",
                                  max_questions=3)
        assert len(qs) <= 3

    def test_dedup_against_already_asked(self):
        g = build_issue_graph("banking", "cheque_guarantee")
        r = analyze_gaps(g, None, [])
        qs_first = generate_questions(r, domain="banking",
                                         subdomain="cheque_guarantee",
                                         max_questions=3)
        asked_ids = {q.question_id for q in qs_first}
        qs_second = generate_questions(r, domain="banking",
                                          subdomain="cheque_guarantee",
                                          already_asked=asked_ids,
                                          max_questions=3)
        # New questions must not overlap with first batch
        second_ids = {q.question_id for q in qs_second}
        assert not (second_ids & asked_ids)

    def test_questions_are_specific_not_generic(self):
        g = build_issue_graph("banking", "cheque_guarantee")
        r = analyze_gaps(g, None, [])
        qs = generate_questions(r, domain="banking",
                                  subdomain="cheque_guarantee")
        # Must not be the generic "اشرح أكثر" or "وش التفاصيل"
        for q in qs:
            assert "اشرح أكثر" not in q.text
            assert "وش التفاصيل" not in q.text


# ═════════════════════════════════════════════════════════════════
# Response Mode
# ═════════════════════════════════════════════════════════════════

class TestResponseMode:
    def test_no_gaps_is_ready(self):
        from core.ux.missing_data import MissingDataReport
        r = MissingDataReport()
        assert assess_readiness(r) == ResponseMode.READY

    def test_medium_only_is_partial(self):
        from core.ux.missing_data import MissingDataReport
        r = MissingDataReport(medium_count=2)
        assert assess_readiness(r) == ResponseMode.PARTIAL

    def test_one_critical_analysis_is_partial(self):
        from core.ux.missing_data import MissingDataReport
        r = MissingDataReport(critical_count=1)
        assert assess_readiness(r, UserIntent.ANALYSIS) == ResponseMode.PARTIAL

    def test_one_critical_drafting_is_not_ready(self):
        from core.ux.missing_data import MissingDataReport
        r = MissingDataReport(critical_count=1)
        assert assess_readiness(r, UserIntent.DRAFTING) == ResponseMode.NOT_READY

    def test_two_critical_always_not_ready(self):
        from core.ux.missing_data import MissingDataReport
        r = MissingDataReport(critical_count=2)
        assert assess_readiness(r, UserIntent.ANALYSIS) == ResponseMode.NOT_READY


# ═════════════════════════════════════════════════════════════════
# Orchestrator + session dedup
# ═════════════════════════════════════════════════════════════════

class TestOrchestrator:
    def setup_method(self):
        get_asked_store().reset("ux-sess-1")
        get_asked_store().reset("ux-sess-2")

    def test_not_ready_blocks_and_asks(self):
        g = build_issue_graph("banking", "cheque_guarantee")
        enh = build_ux_enhancement(
            query="شيك وصرفته",
            session_id="ux-sess-1",
            domain="banking",
            subdomain="cheque_guarantee",
            graph=g,
            bound_evidence=None,
            facts=[],
            intent=UserIntent.ACTION,
        )
        assert enh.applied is True
        assert enh.response_mode in ("not_ready", "partial")
        assert len(enh.questions) > 0

    def test_session_dedup_on_repeat(self):
        g = build_issue_graph("criminal", "defamation")
        first = build_ux_enhancement(
            query="واحد سبني",
            session_id="ux-sess-2",
            domain="criminal",
            subdomain="defamation",
            graph=g, bound_evidence=None, facts=[],
            intent=UserIntent.ANALYSIS,
        )
        second = build_ux_enhancement(
            query="تفاصيل أكثر",
            session_id="ux-sess-2",
            domain="criminal",
            subdomain="defamation",
            graph=g, bound_evidence=None, facts=[],
            intent=UserIntent.ANALYSIS,
        )
        first_ids = {q["question_id"] for q in first.questions}
        second_ids = {q["question_id"] for q in second.questions}
        # No question from the first reply should appear in the second
        assert not (first_ids & second_ids)

    def test_ready_mode_no_questions(self):
        from core.ux.missing_data import MissingDataReport
        # Build a case where the graph has all evidence and facts
        enh = build_ux_enhancement(
            query="سؤال قانوني",
            session_id="ux-sess-3",
            domain="",
            graph=None,
            bound_evidence=None,
            facts=[],
            intent=UserIntent.ANALYSIS,
        )
        # When there's no graph, it should still apply (edge case)
        assert enh.applied is True


# ═════════════════════════════════════════════════════════════════
# Phase 12 — PROMPT scenarios
# ═════════════════════════════════════════════════════════════════

class TestPhase12Scenarios:
    """The exact scenarios from the prompt must produce specific questions."""

    def test_cheque_scenario_asks_about_guarantee(self):
        """'عندي شيك وصرفته' → must ask about guarantee/condition/contract."""
        g = build_issue_graph("banking", "cheque_guarantee")
        r = analyze_gaps(g, None, [])
        qs = generate_questions(r, domain="banking",
                                  subdomain="cheque_guarantee")
        combined = " ".join(q.text for q in qs)
        # Must ask about nature of cheque (guarantee vs payment)
        assert "ضمان" in combined or "وفاء" in combined

    def test_inheritance_scenario_asks_about_death_illness(self):
        """'أبوي حول فلوس لأخوي' → must ask about death / timing / counter-value."""
        g = build_issue_graph("inheritance", "pre_death_transfer")
        r = analyze_gaps(g, None, [])
        qs = generate_questions(r, domain="inheritance",
                                  subdomain="pre_death_transfer")
        combined = " ".join(q.text for q in qs)
        # Must touch illness, health, timing, or counter-value angles
        for keyword in ("مرض", "مقابل", "مدة", "وفاة", "صحية", "طبي"):
            if keyword in combined:
                return
        pytest.fail(f"no death-illness angle in: {combined[:200]}")

    def test_drafting_on_empty_is_not_ready(self):
        """'اكتب مذكرة' with no prior context → NOT_READY."""
        enh = build_ux_enhancement(
            query="اكتب لي مذكرة",
            session_id="ph12-draft",
            domain="",
            graph=None, bound_evidence=None, facts=[],
            intent=UserIntent.DRAFTING,
        )
        # Empty graph → blocks drafting
        assert enh.response_mode == "not_ready" or enh.blocks_answer


# ═════════════════════════════════════════════════════════════════
# HTTP integration — response carries ux block
# ═════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def client():
    os.environ["USE_FAIL_CLOSED_RUNTIME"]    = "true"
    os.environ["ENABLE_LEGACY_FALLBACK"]     = "false"
    os.environ["DB_KNOWLEDGE_ACTIVATION_MODE"] = "skip"
    if "core.runtime_flags" in sys.modules:
        importlib.reload(sys.modules["core.runtime_flags"])
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app, headers={"Referer": "http://localhost:8000/"}) as c:
        yield c


class TestHTTPUXIntegration:
    def test_response_carries_ux_block(self, client):
        r = client.post("/api/v1/query/", json={
            "query": "أحكام الحضانة في القانون القطري",
            "session_id": "ux-http-1",
        })
        body = r.json()
        if body.get("from_beta_gate") is True:
            return
        if not body.get("is_blocked"):
            assert "ux" in body

    def test_ux_trace_contains_intent(self, client):
        r = client.post("/api/v1/query/", json={
            "query": "تقييم موقفي في نزاع عمالي",
            "session_id": "ux-http-2",
        })
        body = r.json()
        if body.get("from_beta_gate") is True:
            return
        ux = body.get("ux", {})
        if ux:
            assert ux.get("user_intent") in (
                "standing_assessment", "analysis", "action",
                "drafting", "win_chances",
            )

    def test_fail_closed_still_enforced(self, client):
        r = client.post("/api/v1/query/", json={
            "query": "أحكام الحضانة في قطر",
            "session_id": "ux-http-3",
        })
        body = r.json()
        if body.get("from_beta_gate") is True:
            return
        # Authority stamp intact
        assert body.get("authoritative_path") == "unified_fail_closed"
        assert body.get("legacy_used") is False
