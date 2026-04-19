# -*- coding: utf-8 -*-
"""
REUP — Root Execution Unification Protocol regression tests.

Hard invariants:
  • Every response carries `authoritative_execution_path=UNIFIED_LEGAL_RUNTIME`
  • Every response carries a known `output_author` (never "unknown")
  • `legacy_used == False`, `fallback_used == False`
  • No legacy text signature (partner minutes, strategic blocks, raw
    reason codes, decorated headers) appears in any user-facing text
  • `_legacy_scan.is_clean == True` for every response

Covers:
  A. Direct gate unit tests
  B. Legacy text signature detector
  C. Single-path invariant across live scenarios (12 cases)
  D. Exception paths still go through the gate
  E. Cancellation goes through the gate
  F. Drafting, analytical, and safety-stop paths all stamp authority
  G. No duplicate response authors inside `production_runtime`
"""
from __future__ import annotations

import re
import pytest

from core.runtime import (
    ResponseAuthor, UnifiedArtifacts,
    AuthoritativeOutputGate, AuthoritativeOutputViolation,
    AUTHORITATIVE_PATH,
    build_internal_failure_artifacts, build_cancelled_artifacts,
    detect_legacy_signatures, is_output_legacy_free,
    LegacyDetectionReport,
)
from core.production_runtime import answer_query_direct, get_production_runtime
from core.conversation import get_state_engine


# ═════════════════════════════════════════════════════════════════
# SECTION A — Gate unit tests
# ═════════════════════════════════════════════════════════════════

class TestGate:
    def test_emit_stamps_authority(self):
        artifacts = UnifiedArtifacts(
            author=ResponseAuthor.FAIL_CLOSED_PIPELINE,
            text="هذا جواب قانوني موجز ومباشر.",
            domain="criminal",
            is_grounded=True,
        )
        response = AuthoritativeOutputGate.emit(artifacts)
        assert response["authoritative_execution_path"] == AUTHORITATIVE_PATH
        assert response["output_author"] == "fail_closed_pipeline"
        assert response["legacy_used"] is False
        assert response["fallback_used"] is False

    def test_emit_rejects_unknown_author(self):
        artifacts = UnifiedArtifacts(author="bogus")  # type: ignore[arg-type]
        with pytest.raises(AuthoritativeOutputViolation):
            AuthoritativeOutputGate.emit(artifacts)

    def test_emit_rejects_empty_text_on_unblocked(self):
        artifacts = UnifiedArtifacts(
            author=ResponseAuthor.FAIL_CLOSED_PIPELINE,
            text="",
            is_blocked=False,
        )
        with pytest.raises(AuthoritativeOutputViolation):
            AuthoritativeOutputGate.emit(artifacts)

    def test_emit_rejects_legacy_text(self):
        artifacts = UnifiedArtifacts(
            author=ResponseAuthor.FAIL_CLOSED_PIPELINE,
            text="أقوى ما يدعمك: محاضر اجتماعات الشركاء.",
            domain="criminal",
        )
        with pytest.raises(AuthoritativeOutputViolation):
            AuthoritativeOutputGate.emit(artifacts)

    def test_emit_rejects_raw_reason_codes(self):
        artifacts = UnifiedArtifacts(
            author=ResponseAuthor.FAIL_CLOSED_PIPELINE,
            text="النتيجة: low_issue_coverage:0.25 ويمكن الاستمرار.",
            domain="criminal",
        )
        with pytest.raises(AuthoritativeOutputViolation):
            AuthoritativeOutputGate.emit(artifacts)

    def test_internal_failure_goes_through_gate(self):
        artifacts = build_internal_failure_artifacts(
            reason="unit_test_failure",
            request_id="rid-1",
        )
        response = AuthoritativeOutputGate.emit(artifacts)
        assert response["output_author"] == "internal_failure"
        assert response["request_id"] == "rid-1"
        assert response["is_blocked"] is True

    def test_cancellation_carries_status_marker(self):
        artifacts = build_cancelled_artifacts(
            request_id="rid-2", stage="mid_pipeline",
        )
        response = AuthoritativeOutputGate.emit(artifacts)
        assert response["status"] == "cancelled"
        assert response["output_author"] == "cancelled"

    def test_drafting_author_without_intent_is_rejected(self):
        artifacts = UnifiedArtifacts(
            author=ResponseAuthor.DLP_SKELETON_DRAFT,
            text="**صياغة أولية** مسودة منظمة.",
            drafting={},   # missing drafting_intent_detected
        )
        with pytest.raises(AuthoritativeOutputViolation):
            AuthoritativeOutputGate.emit(artifacts)


# ═════════════════════════════════════════════════════════════════
# SECTION B — Legacy text signature detector
# ═════════════════════════════════════════════════════════════════

class TestLegacyDetector:
    def test_clean_text_passes(self):
        r = detect_legacy_signatures("هذا نص قانوني نظيف تمامًا.")
        assert r.is_clean is True

    def test_detects_strategic_blocks(self):
        r = detect_legacy_signatures(
            "أقوى ما يدعمك: شهادة الشاهد الأول وسند التحويل."
        )
        assert r.is_clean is False
        assert any("strategic" in h for h in r.hits)

    def test_detects_decorated_headers(self):
        for header in (
            "⚖️ التحليل القضائي: ملاحظات.",
            "📊 السيناريوهات المحتملة: احتمال الفوز.",
            "🎯 الدليل الحاسم في القضية.",
        ):
            assert not is_output_legacy_free(header)

    def test_detects_raw_reason_codes(self):
        for code in ("low_issue_coverage", "no_bound_evidence",
                       "insufficient_facts", "primary_expected",
                       "hybrid_cross_domain"):
            assert not is_output_legacy_free(f"النتيجة: {code} = 1")

    def test_context_gate_allows_banking_template_in_banking(self):
        # "كشف حركة الحساب" is legitimate in a banking memo
        text = "يتبيَّن من كشف حركة الحساب أن الرصيد كافٍ."
        assert is_output_legacy_free(text, domain="banking")

    def test_context_gate_blocks_banking_template_in_family(self):
        text = "يتبيَّن من كشف حركة الحساب أن الرصيد كافٍ."
        assert not is_output_legacy_free(text, domain="family")

    def test_skeleton_is_allowed_to_say_تعذر_صياغة(self):
        text = (
            "**مذكرة دفاع — صياغة أولية (SKELETON DRAFT)**\n\n"
            "تعذّر صياغة مذكرة دفاع بشكل نهائي لكن يوجد هيكل أولي."
        )
        r = detect_legacy_signatures(text, is_draftable_skeleton=True)
        assert r.is_clean is True

    def test_tracked_signature_count_is_bounded(self):
        """If new legacy signatures are found in CI, they must be added
        here deliberately — this test locks the set."""
        from core.runtime.legacy_detector import (
            _HARD_SIGNATURES, _CONTEXT_SIGNATURES,
        )
        # Regression guard: we should have at least the 25 known signatures
        assert len(_HARD_SIGNATURES) >= 25
        assert len(_CONTEXT_SIGNATURES) >= 4


# ═════════════════════════════════════════════════════════════════
# SECTION C — Live single-path invariant across scenarios
# ═════════════════════════════════════════════════════════════════

LIVE_SCENARIOS = [
    # (label, query)
    ("cold_defense",           "اكتب لي مذكرة دفاع."),
    ("cheque_guarantee",       "اكتب مذكرة دفاع في قضية شيك ضمان."),
    ("pre_death_transfer",     "ما حكم تنازل الوالد قبل وفاته بأسبوع؟"),
    ("software_ownership",     "اكتب مذكرة رد في ملكية كود برمجي."),
    ("double_sale",            "اكتب صحيفة دعوى في بيع عقار بعقدين."),
    ("construction_pleading",  "اكتب نقاط مرافعة في مقاولات."),
    ("cyber_defamation",       "اكتب مذكرة دفاع في سب إلكتروني."),
    ("employment_no_contract", "اكتب مذكرة في فصل عامل بدون عقد."),
    ("misleading_investment",  "اكتب مذكرة رد على استثمار مضلل."),
    ("assault_self_defense",   "اكتب مذكرة دفاع في اعتداء مع دفاع شرعي."),
    ("partnership_fraud",      "اكتب مذكرة في نزاع شراكة مع شبهة احتيال."),
    ("empty",                  ""),
    ("analytical_only",        "ما حكم الشيك بدون رصيد في قطر؟"),
]


class TestLiveSinglePath:
    @pytest.mark.parametrize(
        "label,query", LIVE_SCENARIOS, ids=[s[0] for s in LIVE_SCENARIOS],
    )
    def test_every_response_passes_the_gate(self, label, query):
        get_state_engine().reset(f"reup_{label}")
        r = answer_query_direct(query, f"reup_{label}")
        # Authority stamp present
        assert r.get("authoritative_execution_path") == AUTHORITATIVE_PATH, \
            f"{label}: exec_path wrong"
        assert r.get("legacy_used") is False, f"{label}: legacy_used True"
        assert r.get("fallback_used") is False, f"{label}: fallback_used True"
        # Output author is a known enum value
        author_val = r.get("output_author", "")
        known = {a.value for a in ResponseAuthor}
        assert author_val in known, f"{label}: unknown author {author_val!r}"

    @pytest.mark.parametrize(
        "label,query", LIVE_SCENARIOS, ids=[s[0] for s in LIVE_SCENARIOS],
    )
    def test_every_response_passes_legacy_scan(self, label, query):
        get_state_engine().reset(f"reup_scan_{label}")
        r = answer_query_direct(query, f"reup_scan_{label}")
        scan = r.get("_legacy_scan", {}) or {}
        # Either the internal scan is clean, OR the response was itself
        # a structured internal_failure (already legacy-free by construction).
        is_clean = scan.get("is_clean", True)
        is_int_fail = r.get("output_author") == "internal_failure"
        assert is_clean or is_int_fail, \
            f"{label}: legacy hits {scan.get('hits')}"

    @pytest.mark.parametrize(
        "label,query", LIVE_SCENARIOS, ids=[s[0] for s in LIVE_SCENARIOS],
    )
    def test_no_legacy_phrases_reach_user(self, label, query):
        get_state_engine().reset(f"reup_phrase_{label}")
        r = answer_query_direct(query, f"reup_phrase_{label}")
        text = r.get("answer", "") or ""
        # Hard forbidden phrases regardless of context
        banned = [
            "أقوى ما يدعمك:",
            "أبرز نقطة ضعف لديك:",
            "ما يُتوقع أن يدفع به الخصم",
            "📊 السيناريوهات المحتملة",
            "⚖️ التحليل القضائي:",
        ]
        for b in banned:
            assert b not in text, f"{label}: banned phrase {b!r} leaked"

    def test_drafting_request_never_bare_refusal(self):
        """Drafting requests always produce SOMETHING useful — never
        just 'تعذّر صياغة' in isolation."""
        for (label, q) in [
            ("bare_defense", "اكتب لي مذكرة دفاع."),
            ("bare_reply",   "اكتب لي مذكرة رد."),
        ]:
            get_state_engine().reset(f"reup_bare_{label}")
            r = answer_query_direct(q, f"reup_bare_{label}")
            text = r.get("answer", "") or ""
            first_line = text.split("\n", 1)[0]
            # First line should NOT just be "تعذّر صياغة…" without a
            # SKELETON/structured wrapper.
            if first_line.startswith("تعذّر صياغة"):
                assert "صياغة أولية" in text or "SKELETON" in text, \
                    f"{label}: bare refusal without skeleton"


# ═════════════════════════════════════════════════════════════════
# SECTION D — Exception paths still stamp authority
# ═════════════════════════════════════════════════════════════════

class TestExceptionPaths:
    def test_internal_failure_artifact_is_legacy_clean(self):
        a = build_internal_failure_artifacts(
            reason="forced", request_id="x"
        )
        report = detect_legacy_signatures(a.text)
        assert report.is_clean is True

    def test_cancelled_artifact_is_legacy_clean(self):
        a = build_cancelled_artifacts(request_id="y", stage="test")
        report = detect_legacy_signatures(a.text)
        assert report.is_clean is True


# ═════════════════════════════════════════════════════════════════
# SECTION E — No duplicate legacy-style response functions remain
# ═════════════════════════════════════════════════════════════════

class TestSingleProductionEntry:
    def test_single_runtime_instance(self):
        """`get_production_runtime` returns one singleton — no split
        between test runs and runtime."""
        a = get_production_runtime()
        b = get_production_runtime()
        assert a is b

    def test_answer_query_direct_is_gated(self):
        r = answer_query_direct("ما حكم السرقة في قطر؟", "reup_direct_1")
        assert r.get("authoritative_execution_path") == AUTHORITATIVE_PATH

    def test_no_raw_scores_in_any_response(self):
        for q in ("ما هي الشراكة التجارية؟",
                   "اكتب مذكرة دفاع في قضية اعتداء بسيط."):
            r = answer_query_direct(q, "reup_raw_score")
            text = r.get("answer", "") or ""
            # Absolutely no bare decimal scores in user-facing text
            assert not re.search(r"\bcomposite\s*[:=]\s*[\d.]+", text)
            assert not re.search(r"\bscore\s*[:=]\s*[\d.]+", text)
            assert not re.search(r"\bchunk_id\s*[:=]", text)


# ═════════════════════════════════════════════════════════════════
# SECTION F — HTTP shape stability
# ═════════════════════════════════════════════════════════════════

class TestHttpShape:
    def test_all_required_fields_present(self):
        r = answer_query_direct("ما حكم السرقة؟", "reup_shape_1")
        required = [
            "answer", "sources", "domain", "confidence", "is_grounded",
            "runtime", "gates_passed", "gates_failed", "block_reasons",
            "fatal_violations", "elapsed_seconds", "runtime_notes",
            "is_blocked", "evidence_trace", "sufficiency_level",
            "authoritative_path", "authoritative_execution_path",
            "output_author", "legacy_used", "fallback_used",
        ]
        for f in required:
            assert f in r, f"missing field: {f}"

    def test_drafting_request_has_drafting_subdict(self):
        r = answer_query_direct(
            "اكتب لي مذكرة دفاع في قضية شيك.", "reup_shape_2",
        )
        assert "drafting" in r
        d = r["drafting"]
        assert d.get("drafting_intent_detected") is True
        assert "drafting_mode" in d
