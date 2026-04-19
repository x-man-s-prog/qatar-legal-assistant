# -*- coding: utf-8 -*-
"""
MLRE Output Integration — the most important regression suite.

Proves that MLRE is the PRIMARY OUTPUT AUTHORITY:
  A. Output reflects MLRE reality (primary + secondary paths, pivots)
  B. NO legacy/technical leakage reaches the user
  C. Drafting routes through MLRE (single/conditional/dual/not-draftable)
  D. End-to-end /api-style queries shape output correctly
  E. User-safe output (no raw scores, reason codes, hypothesis enums)

Run: pytest tests/test_mlre_output_integration.py -v
"""
from __future__ import annotations

import re
import pytest

from core.mlre import (
    run_mlre, compose_output, OutputMode, ComposedOutput,
    sanitize_user_output, FirewallReport,
    questions_from_mlre, pivot_explanation_text,
    build_memo_from_mlre, DraftingV2Mode,
)
from core.ux.user_intent import UserIntent
from core.production_runtime import (
    get_production_runtime, _mlre_drafting_to_http,
)


# ═════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════

TECHNICAL_LEAK_PATTERNS = [
    r"\blow_issue_coverage\b", r"\bno_bound_evidence\b",
    r"\bissue_graph_unavailable\b", r"\bno_primary_issue\b",
    r"\binsufficient_facts\b", r"\bclaim_brief_needs_detailed_facts\b",
    r"\bengine_exception\b", r"\bfact_pattern_lacks_substance\b",
    r"\bclassification_below_floor\b", r"\bno_legal_signals\b",
    r"\bdomain_tie_low_confidence\b", r"\bevidence_insufficient\b",
    r"\bprimary_expected\b", r"\bclosest_alternative\b",
    r"\bhybrid_cross_domain\b", r"\bworst_case_exposure\b",
    r"\bedge_case\b",
    r"\bMLRE\b", r"\[TRACE[:]",
    r"chunk_id\s*[:=]", r"ruling_id\s*[:=]",
    r"\bcomposite\s*[:=]\s*[\d.]+",
    r"\bscore\s*[:=]\s*[\d.]+",
]


def _assert_no_technical_leakage(text: str) -> None:
    """The text must not contain any raw technical pattern."""
    for pat in TECHNICAL_LEAK_PATTERNS:
        m = re.search(pat, text)
        assert m is None, f"Leaked technical pattern '{pat}' in: {text[:200]!r}"


def _run_mlre_basic(query: str, facts=None):
    return run_mlre(
        query=query,
        facts=facts or [query[:300]],
        max_hypotheses=8,
        max_survivors=3,
    )


# ═════════════════════════════════════════════════════════════════
# SECTION A — MLRE REFLECTION IN OUTPUT
#   (primary + secondary + pivots surface in the composed text)
# ═════════════════════════════════════════════════════════════════

class TestSectionAReflection:
    def test_composer_produces_text_when_survivors_exist(self):
        mlre = _run_mlre_basic(
            "شخص سرق مني أموال بعد أن ادّعى أنه شريكي في المشروع"
        )
        composed = compose_output(mlre, user_intent=UserIntent.ANALYSIS)
        assert isinstance(composed, ComposedOutput)
        if mlre.survivors and mlre.reality and mlre.reality.paths:
            assert composed.used_mlre is True
            assert composed.text.strip() != ""
        else:
            # No survivors → degraded path but no crash
            assert composed.used_mlre is False

    def test_primary_path_appears_in_output(self):
        mlre = _run_mlre_basic("فصلوني من العمل بدون إشعار")
        composed = compose_output(mlre, user_intent=UserIntent.ANALYSIS)
        if composed.used_mlre and mlre.reality.paths:
            primary_theory = mlre.reality.paths[0].legal_theory
            # Some form of primary label should appear
            assert "المرجَّح" in composed.text or primary_theory in composed.text

    def test_secondary_path_surfaces_when_two_survivors(self):
        mlre = _run_mlre_basic(
            "شريكي أخذ أموال الشركة بدون إذن وادّعى أنها حصته"
        )
        composed = compose_output(mlre, user_intent=UserIntent.ANALYSIS)
        if composed.used_mlre and len(mlre.reality.paths) >= 2:
            assert "بديل" in composed.text or composed.show_alternative

    def test_pivot_conditions_appear_when_present(self):
        mlre = _run_mlre_basic(
            "تنازل والدي عن قطعة أرض قبل وفاته بشهرين وهو مريض"
        )
        composed = compose_output(mlre, user_intent=UserIntent.ANALYSIS)
        if mlre.reality and mlre.reality.pivot_conditions and composed.used_mlre:
            # Pivot block should render in at least SOME form
            assert (
                "ينتقل" in composed.text
                or "بديل" in composed.text
                or "حاسم" in composed.text
            )

    def test_action_mode_produces_steps(self):
        mlre = _run_mlre_basic("ماذا أفعل لو سرقت مني سيارتي؟")
        composed = compose_output(mlre, user_intent=UserIntent.ACTION)
        if composed.used_mlre:
            assert composed.mode == OutputMode.ACTION
            assert (
                "الخطوات" in composed.text
                or "توثيق" in composed.text
                or "بلاغ" in composed.text
            )

    def test_analysis_is_default_mode(self):
        mlre = _run_mlre_basic("ما تكييف هذه القضية؟")
        composed = compose_output(mlre, user_intent=None)
        assert composed.mode == OutputMode.ANALYSIS

    def test_composer_trace_is_structured(self):
        mlre = _run_mlre_basic("فصلوني من العمل")
        composed = compose_output(mlre, user_intent=UserIntent.ANALYSIS)
        assert isinstance(composed.trace, dict)
        assert "mlre_output_used" in composed.trace
        assert "output_mode" in composed.trace


# ═════════════════════════════════════════════════════════════════
# SECTION B — NO LEGACY LEAKAGE
#   Firewall strips reason codes, enum names, scores
# ═════════════════════════════════════════════════════════════════

class TestSectionBFirewall:
    def test_firewall_returns_report(self):
        report = sanitize_user_output("عقد بسيط")
        assert isinstance(report, FirewallReport)

    def test_firewall_strips_reason_codes(self):
        dirty = (
            "هذا عقد تجاري. ملاحظة: low_issue_coverage:0.25 و no_bound_evidence "
            "تظهر هنا."
        )
        report = sanitize_user_output(dirty)
        assert "low_issue_coverage:0.25" not in report.cleaned_text
        assert "no_bound_evidence" not in report.cleaned_text
        assert report.scrubbed_telemetry >= 1 or report.replaced_phrases >= 1

    def test_firewall_strips_hypothesis_enums(self):
        dirty = "المسار primary_expected أقوى من closest_alternative بنسبة."
        report = sanitize_user_output(dirty)
        assert "primary_expected" not in report.cleaned_text
        assert "closest_alternative" not in report.cleaned_text
        assert report.scrubbed_telemetry >= 2

    def test_firewall_strips_raw_scores(self):
        dirty = "المسار قوي (composite: 0.452, score=0.63)."
        report = sanitize_user_output(dirty)
        assert "composite: 0.452" not in report.cleaned_text
        assert "score=0.63" not in report.cleaned_text

    def test_firewall_strips_legacy_boilerplate_blocks(self):
        dirty = (
            "بناءً على الوقائع:\n\n"
            "أقوى ما يدعمك: محاضر اجتماعات الشركاء\n"
            "أبرز نقطة ضعف لديك: ضعف الأدلة\n\n"
            "الخلاصة: تُقبل الدعوى."
        )
        report = sanitize_user_output(dirty)
        assert "محاضر اجتماعات الشركاء" not in report.cleaned_text
        assert "أقوى ما يدعمك:" not in report.cleaned_text
        assert report.removed_blocks >= 1

    def test_firewall_strips_trace_markers(self):
        dirty = "السياق: [TRACE: domain=criminal score=0.5] النتيجة واضحة."
        report = sanitize_user_output(dirty)
        assert "[TRACE" not in report.cleaned_text

    def test_firewall_replaces_phrases_with_user_safe_arabic(self):
        dirty = "النتيجة: low_issue_coverage"
        report = sanitize_user_output(dirty)
        # Replacement phrase should appear
        assert "الوقائع" in report.cleaned_text or "تكفي" in report.cleaned_text
        assert "low_issue_coverage" not in report.cleaned_text

    def test_firewall_is_idempotent(self):
        """Running the firewall twice gives the same result."""
        dirty = "بعض النص مع low_issue_coverage يكون هنا."
        r1 = sanitize_user_output(dirty)
        r2 = sanitize_user_output(r1.cleaned_text)
        assert r1.cleaned_text == r2.cleaned_text or r2.replaced_phrases == 0

    def test_firewall_handles_empty(self):
        report = sanitize_user_output("")
        assert report.cleaned_text == ""
        assert report.removed_blocks == 0


# ═════════════════════════════════════════════════════════════════
# SECTION C — DRAFTING MODES
#   single / conditional / dual / not-draftable
# ═════════════════════════════════════════════════════════════════

class TestSectionCDrafting:
    def test_drafting_dict_has_required_keys(self):
        mlre = _run_mlre_basic(
            "اكتب لي مذكرة دفاع لأنه اتهمت ظلماً بجريمة سرقة"
        )
        d = build_memo_from_mlre(
            mlre=mlre,
            query="اكتب لي مذكرة دفاع",
            facts=["اتهمت بجريمة سرقة"],
            drafting_intent="write_defense_memo",
        )
        for k in [
            "text", "safety_mode", "drafting_mode",
            "missing", "assumptions", "cited_laws",
            "blocks_drafting", "drafting_intent_detected",
        ]:
            assert k in d

    def test_no_survivors_yields_not_draftable(self):
        # Force empty-survivors path through a hollow query
        mlre = _run_mlre_basic("؟")
        d = build_memo_from_mlre(
            mlre=mlre,
            query="اكتب مذكرة",
            facts=[],
            drafting_intent="write_defense_memo",
        )
        if not mlre.survivors:
            assert d["blocks_drafting"] is True
            assert d["drafting_mode"] == "not_draftable_mlre"
            # Text must explain WHY — not a generic refusal
            assert "تعذّر" in d["text"]

    def test_drafting_text_is_user_safe(self):
        mlre = _run_mlre_basic(
            "اكتب لي مذكرة دفاع في قضية شيك بدون رصيد"
        )
        d = build_memo_from_mlre(
            mlre=mlre,
            query="اكتب لي مذكرة دفاع",
            facts=["حرر شيك بدون رصيد"],
            drafting_intent="write_defense_memo",
        )
        _assert_no_technical_leakage(d["text"])

    def test_http_adapter_fills_schema(self):
        mlre = _run_mlre_basic("اكتب مذكرة دفاع")
        d = build_memo_from_mlre(
            mlre=mlre, query="اكتب مذكرة",
            facts=["وقائع عامة"],
            drafting_intent="write_defense_memo",
        )
        http = _mlre_drafting_to_http(d, query="اكتب مذكرة")
        # Response contract fields
        for k in [
            "answer", "sources", "domain", "confidence", "is_grounded",
            "runtime", "gates_passed", "gates_failed", "block_reasons",
            "fatal_violations", "elapsed_seconds", "runtime_notes",
            "is_blocked", "evidence_trace", "sufficiency_level",
            "authoritative_path", "legacy_used", "fallback_used",
            "drafting",
        ]:
            assert k in http, f"missing response field: {k}"
        assert http["authoritative_path"] == "unified_fail_closed"
        assert http["legacy_used"] is False
        assert http["runtime"] == "fail_closed"

    def test_drafting_mode_value_is_known(self):
        mlre = _run_mlre_basic("اكتب مذكرة رد")
        d = build_memo_from_mlre(
            mlre=mlre, query="اكتب مذكرة رد",
            facts=["وقائع"],
            drafting_intent="write_reply_memo",
        )
        assert d["drafting_mode"] in {
            "single_path", "conditional", "dual_strategy",
            "not_draftable_mlre", "skeleton_draft",
        }


# ═════════════════════════════════════════════════════════════════
# SECTION D — END-TO-END via ProductionRuntime.answer_json
# ═════════════════════════════════════════════════════════════════

class TestSectionDEndToEnd:
    @pytest.fixture(scope="class")
    def runtime(self):
        return get_production_runtime()

    def test_answer_carries_mlre_trace(self, runtime):
        resp = runtime.answer_json(
            "شخص هددني بالسلاح وأخذ أموالي",
            session_id="mlre_int_test_1",
        )
        assert "mlre" in resp, "response must carry mlre trace"
        # authority contract
        assert resp["runtime"] == "fail_closed"
        assert resp["authoritative_path"] == "unified_fail_closed"
        assert resp["legacy_used"] is False

    def test_answer_carries_output_firewall_report(self, runtime):
        resp = runtime.answer_json(
            "فسخوا عقدي دون مبرر",
            session_id="mlre_int_test_2",
        )
        # firewall ran (key may be absent only if exception path taken)
        assert "output_firewall" in resp or resp.get("is_blocked")

    def test_answer_has_no_technical_leakage(self, runtime):
        resp = runtime.answer_json(
            "ابني يتعرض لتنمر في المدرسة ماذا أفعل؟",
            session_id="mlre_int_test_3",
        )
        _assert_no_technical_leakage(resp.get("answer", ""))

    def test_mlre_trace_exposes_output_composition(self, runtime):
        resp = runtime.answer_json(
            "شريكي أخفى أرباح الشركة عني",
            session_id="mlre_int_test_4",
        )
        mlre = resp.get("mlre") or {}
        # On any successful run with survivors, output_composition should exist
        if mlre.get("survivors_count", 0) > 0:
            assert "output_composition" in mlre

    def test_drafting_request_routes_through_mlre(self, runtime):
        resp = runtime.answer_json(
            "اكتب لي مذكرة دفاع في قضية شيك بدون رصيد. الشيك كان ضماناً.",
            session_id="mlre_int_draft_1",
        )
        # drafting block is always present for drafting requests
        assert "drafting" in resp
        d = resp["drafting"]
        assert d.get("drafting_intent_detected") is True
        # Either MLRE drafted it or fallback ran — either way user-safe
        _assert_no_technical_leakage(resp["answer"])

    def test_authority_contract_stamp_on_drafting(self, runtime):
        resp = runtime.answer_json(
            "اكتب مذكرة رد على دعوى مطالبة مالية",
            session_id="mlre_int_draft_2",
        )
        assert resp.get("authoritative_path") == "unified_fail_closed"
        assert resp.get("legacy_used") is False
        assert resp.get("fallback_used") is False


# ═════════════════════════════════════════════════════════════════
# SECTION E — USER-SAFE OUTPUT (no raw scores, no reason codes)
# ═════════════════════════════════════════════════════════════════

class TestSectionEUserSafe:
    def test_composer_output_is_leak_free(self):
        mlre = _run_mlre_basic(
            "زميلي في العمل يسبني أمام الموظفين"
        )
        composed = compose_output(mlre, user_intent=UserIntent.ANALYSIS)
        _assert_no_technical_leakage(composed.text)

    def test_pivot_questions_are_user_safe(self):
        mlre = _run_mlre_basic(
            "صديقي أخذ مني أموال ولم يردها"
        )
        qs = questions_from_mlre(mlre, max_questions=3)
        for q in qs:
            _assert_no_technical_leakage(q.text)

    def test_composer_has_no_raw_scores(self):
        mlre = _run_mlre_basic("ماذا يحدث في قضية تزوير؟")
        composed = compose_output(mlre, user_intent=UserIntent.ANALYSIS)
        # no raw decimal scores should appear alone like "0.63"
        assert not re.search(r"\b0\.\d{2,3}\b", composed.text), \
            f"raw score leaked: {composed.text[:200]!r}"

    def test_confidence_phrasing_is_natural_language(self):
        mlre = _run_mlre_basic("سرقني موظف البنك")
        composed = compose_output(mlre, user_intent=UserIntent.ANALYSIS)
        if composed.used_mlre:
            # Should use strength phrases in Arabic, not numbers
            low = composed.text
            assert any(w in low for w in [
                "قوي", "معتبر", "محتمل", "ضعيف",
                "منخفضة", "متوسطة", "مرتفعة", "جسيمة",
            ]) or not composed.used_mlre

    def test_pivot_explanation_is_safe(self):
        mlre = _run_mlre_basic("هل هذه سرقة أم خيانة أمانة؟")
        expl = pivot_explanation_text(mlre)
        _assert_no_technical_leakage(expl)


# ═════════════════════════════════════════════════════════════════
# Regression guards — single-sentence invariants
# ═════════════════════════════════════════════════════════════════

class TestInvariants:
    def test_empty_query_does_not_crash_composer(self):
        mlre = _run_mlre_basic("؟")
        composed = compose_output(mlre, user_intent=UserIntent.ANALYSIS)
        assert isinstance(composed, ComposedOutput)

    def test_empty_firewall_is_noop(self):
        r = sanitize_user_output("")
        assert r.cleaned_text == ""

    def test_mlre_drafting_http_has_authority_stamp(self):
        mlre = _run_mlre_basic("اكتب مذكرة")
        d = build_memo_from_mlre(
            mlre=mlre, query="اكتب مذكرة",
            facts=[], drafting_intent="write_defense_memo",
        )
        http = _mlre_drafting_to_http(d, query="اكتب مذكرة")
        assert http["authoritative_path"] == "unified_fail_closed"
        assert http["legacy_used"] is False
        assert http["fallback_used"] is False
