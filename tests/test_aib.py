# -*- coding: utf-8 -*-
"""
AIB — Adaptive Intelligence Balancer regression tests.

AIB's hard rule: NO internal_failure due to depth. When IRA refuses
an output because of insufficient hypotheses / missing pivots, AIB
adapts to FULL_MULTI / PARTIAL_MULTI / SINGLE_ADAPTIVE / SKELETON.

Covers:
  A. Adaptation-mode classification
  B. Violation-set adaptability detection
  C. Text composers per mode (single / partial / skeleton)
  D. Requirement downgrade preserves PEAL baselines
  E. MLRE expansion path
  F. Live scenarios — queries that USED TO crash to internal_failure
"""
from __future__ import annotations

import pytest

from core.runtime import (
    AdaptationMode, AdaptationResult,
    aib_adapt, is_adaptable_violation_set,
    classify_adaptation_mode,
    compose_single_adaptive, compose_partial_multi,
    compose_skeleton_adaptive,
    downgrade_requirements,
    PipelineState, PipelineRequirements,
    ResponseAuthor, UnifiedArtifacts,
)
from core.production_runtime import answer_query_direct
from core.conversation import get_state_engine


# ═════════════════════════════════════════════════════════════════
# SECTION A — Adaptable-violation detection
# ═════════════════════════════════════════════════════════════════

class TestAdaptabilityDetection:
    def test_ira_violations_are_adaptable(self):
        violations = [
            "ira:insufficient_hypotheses:need>=2:got=1",
            "ira:pivots_not_generated",
        ]
        assert is_adaptable_violation_set(violations) is True

    def test_mixed_violations_are_not_adaptable(self):
        violations = [
            "mlre_not_executed",
            "ira:insufficient_hypotheses:need>=2:got=1",
        ]
        assert is_adaptable_violation_set(violations) is False

    def test_pure_peal_violations_are_not_adaptable(self):
        violations = ["domain_not_resolved", "mlre_not_executed"]
        assert is_adaptable_violation_set(violations) is False

    def test_empty_violations_not_adaptable(self):
        assert is_adaptable_violation_set([]) is False


# ═════════════════════════════════════════════════════════════════
# SECTION B — Mode classification
# ═════════════════════════════════════════════════════════════════

class TestModeClassification:
    def test_single_survivor_no_pivots_picks_single_adaptive(self):
        state = PipelineState(
            mlre_executed=True, survivors_count=1,
            pivots_count=0, decisive_tests_count=0,
        )
        req = PipelineRequirements(needs_multi_path=True, min_hypotheses=2)
        mode = classify_adaptation_mode(
            state, req, ["ira:insufficient_hypotheses"],
        )
        assert mode == AdaptationMode.SINGLE_ADAPTIVE

    def test_two_survivors_picks_partial(self):
        state = PipelineState(
            mlre_executed=True, survivors_count=2,
            pivots_count=1, decisive_tests_count=2,
        )
        req = PipelineRequirements(needs_multi_path=True)
        mode = classify_adaptation_mode(state, req, [])
        assert mode == AdaptationMode.PARTIAL_MULTI

    def test_three_or_more_survivors_picks_full(self):
        state = PipelineState(
            mlre_executed=True, survivors_count=3,
            pivots_count=1,
        )
        req = PipelineRequirements()
        mode = classify_adaptation_mode(state, req, [])
        assert mode == AdaptationMode.FULL_MULTI

    def test_no_mlre_at_all_picks_skeleton(self):
        state = PipelineState(mlre_executed=False, survivors_count=0)
        req = PipelineRequirements()
        mode = classify_adaptation_mode(state, req, [])
        assert mode == AdaptationMode.SKELETON


# ═════════════════════════════════════════════════════════════════
# SECTION C — Text composers
# ═════════════════════════════════════════════════════════════════

class TestComposers:
    def test_single_adaptive_has_required_blocks(self):
        mlre_trace = {
            "reality": {
                "paths": [{
                    "legal_theory": "عقد مدني",
                    "weakest_point": "ضعف الإثبات الكتابي",
                    "what_must_be_proven": ["العقد", "التسليم"],
                    "score": 0.48,
                }],
            },
        }
        text = compose_single_adaptive(mlre_trace)
        # Required blocks
        assert "التكييف المرجَّح" in text
        assert "لماذا لا يوجد تكييف بديل" in text
        assert "ما الذي قد يخلق تكييفاً بديلاً" in text
        assert "أخطر نقطة ضعف" in text
        assert "⚠️" in text   # limitation disclosure

    def test_partial_multi_shows_both_paths(self):
        mlre_trace = {
            "reality": {
                "paths": [
                    {"legal_theory": "عقد بيع",
                     "weakest_point": "التقادم", "score": 0.55},
                    {"legal_theory": "هبة",
                     "weakest_point": "شرط القبض", "score": 0.35},
                ],
                "pivot_conditions": ["إذا ثبت القبض"],
                "decisive_tests": ["إثبات: محضر الاستلام"],
            },
        }
        text = compose_partial_multi(mlre_trace)
        assert "التكييف المرجَّح" in text
        assert "تكييف بديل" in text
        assert "التوازن بين المسارين" in text
        assert "⚠️" in text

    def test_skeleton_adaptive_shows_structure(self):
        mlre_trace = {
            "reality": {
                "paths": [
                    {"legal_theory": "مسار (١)"},
                    {"legal_theory": "مسار (٢)"},
                ],
                "decisive_tests": ["إثبات وقوع الفعل"],
            },
        }
        text = compose_skeleton_adaptive(mlre_trace)
        assert "صياغة تحليلية غير حاسمة" in text
        assert "مسار (١)" in text
        assert "⚠️" in text

    def test_composers_handle_empty_trace(self):
        text_single = compose_single_adaptive({})
        text_skel   = compose_skeleton_adaptive({})
        assert text_single
        assert text_skel


# ═════════════════════════════════════════════════════════════════
# SECTION D — Requirement downgrade
# ═════════════════════════════════════════════════════════════════

class TestDowngrade:
    def test_single_adaptive_relaxes_multi_path(self):
        original = PipelineRequirements(
            needs_mlre=True, needs_multi_path=True,
            min_hypotheses=2, must_generate_pivots=True,
            needs_pivot_output=True,
        )
        state = PipelineState(survivors_count=1)
        out = downgrade_requirements(
            original, state, AdaptationMode.SINGLE_ADAPTIVE,
        )
        assert out.needs_multi_path is False
        assert out.must_generate_pivots is False
        assert out.needs_pivot_output is False
        assert out.min_hypotheses <= 1
        # Baseline PEAL still required
        assert out.needs_mlre is True

    def test_partial_multi_relaxes_dual(self):
        original = PipelineRequirements(
            needs_mlre=True, needs_multi_path=True,
            needs_dual_strategy=True, min_hypotheses=2,
        )
        state = PipelineState(survivors_count=2)
        out = downgrade_requirements(
            original, state, AdaptationMode.PARTIAL_MULTI,
        )
        assert out.needs_dual_strategy is False

    def test_skeleton_relaxes_all_depth_flags(self):
        original = PipelineRequirements(
            needs_mlre=True, needs_multi_path=True,
            must_generate_pivots=True, needs_pivot_output=True,
        )
        state = PipelineState(survivors_count=0)
        out = downgrade_requirements(
            original, state, AdaptationMode.SKELETON,
        )
        assert out.needs_multi_path is False
        assert out.must_generate_pivots is False
        assert out.needs_pivot_output is False


# ═════════════════════════════════════════════════════════════════
# SECTION E — Adapt entry point
# ═════════════════════════════════════════════════════════════════

class TestAdaptFunction:
    def test_adapt_returns_populated_result(self):
        artifacts = UnifiedArtifacts(
            author=ResponseAuthor.MLRE_OUTPUT_COMPOSER,
            text="original insufficient text",
            domain="criminal",
            mlre_trace={
                "reality": {"paths": [{
                    "legal_theory": "مسؤولية جنائية",
                    "weakest_point": "انتفاء القصد",
                    "score": 0.40,
                }]},
            },
            peal_requirements={
                "needs_mlre": True,
                "needs_multi_path": True,
                "min_hypotheses": 2,
                "must_generate_pivots": True,
                "needs_pivot_output": True,
            },
        )
        result = aib_adapt(
            artifacts,
            ["ira:insufficient_hypotheses:need>=2:got=1",
             "ira:pivots_not_generated"],
            query="ما الأقوى؟",
        )
        assert isinstance(result, AdaptationResult)
        assert result.adapted is True
        assert result.text
        assert result.mode in (
            AdaptationMode.SINGLE_ADAPTIVE,
            AdaptationMode.PARTIAL_MULTI,
            AdaptationMode.FULL_MULTI,
            AdaptationMode.SKELETON,
        )

    def test_adapt_never_crashes_on_empty_mlre(self):
        artifacts = UnifiedArtifacts(
            author=ResponseAuthor.FAIL_CLOSED_PIPELINE,
            text="t", domain="", mlre_trace={},
        )
        result = aib_adapt(artifacts, [], query="")
        assert result.text


# ═════════════════════════════════════════════════════════════════
# SECTION F — Live integration: no more internal_failure due to depth
# ═════════════════════════════════════════════════════════════════

DEPTH_TRIGGERING_QUERIES = [
    ("cheque_guarantee_draft", "اكتب مذكرة دفاع في شيك ضمان — ضمان أم وفاء؟"),
    ("strongest_abstract",     "ما الأقوى في تكييف هذا النزاع؟"),
    ("decisive_abstract",      "ما الذي يحسم بين المدني والجزائي؟"),
    ("partnership_work",       "شراكة أم عمل؟ شريكي يأخذ راتباً."),
    ("pre_death",              "مرض الموت — ما الذي يحسم صحة التصرف قبل الوفاة؟"),
    ("ip_ownership",           "ملكية الكود — للمطور أم الشركة؟"),
    ("assault_defense",        "اكتب مذكرة دفاع في اعتداء مع دفع بدفاع شرعي."),
    ("partnership_fraud",      "نزاع شراكة مع شبهة احتيال — ما المسار الأقوى؟"),
]


class TestLiveNoInternalFailureFromDepth:
    @pytest.mark.parametrize(
        "label,query", DEPTH_TRIGGERING_QUERIES,
        ids=[c[0] for c in DEPTH_TRIGGERING_QUERIES],
    )
    def test_never_internal_failure_due_to_depth(self, label, query):
        get_state_engine().reset(f"aib_live_{label}")
        r = answer_query_direct(query, f"aib_live_{label}")
        author = r.get("output_author", "")
        # The response must NOT be internal_failure
        # (it may be any legal/drafting author).
        assert author != "internal_failure", \
            f"{label}: fell through to internal_failure"

    @pytest.mark.parametrize(
        "label,query", DEPTH_TRIGGERING_QUERIES,
        ids=[c[0] for c in DEPTH_TRIGGERING_QUERIES],
    )
    def test_response_carries_answer_text(self, label, query):
        get_state_engine().reset(f"aib_text_{label}")
        r = answer_query_direct(query, f"aib_text_{label}")
        assert r.get("answer"), f"{label}: empty answer"
        assert len(r["answer"]) > 100

    @pytest.mark.parametrize(
        "label,query", DEPTH_TRIGGERING_QUERIES,
        ids=[c[0] for c in DEPTH_TRIGGERING_QUERIES],
    )
    def test_authority_stamp_preserved(self, label, query):
        get_state_engine().reset(f"aib_auth_{label}")
        r = answer_query_direct(query, f"aib_auth_{label}")
        assert r.get("authoritative_execution_path") == "UNIFIED_LEGAL_RUNTIME"
        assert r.get("legacy_used") is False
        assert r.get("fallback_used") is False


class TestAIBAdaptationTelemetry:
    def test_aib_trace_when_adapted(self):
        """An abstract "ما الأقوى" query triggers AIB adaptation."""
        get_state_engine().reset("aib_trace_1")
        r = answer_query_direct(
            "ما الأقوى في تكييف هذا النزاع؟", "aib_trace_1",
        )
        aib = r.get("aib", {}) or {}
        # Either it adapted or it passed IRA cleanly. Either is valid.
        if aib:
            assert aib.get("adapted") is True
        # runtime_notes should mention AIB when adaptation happened
        if aib.get("adapted"):
            notes = r.get("runtime_notes", []) or []
            assert any("aib_adaptation:" in n for n in notes)
