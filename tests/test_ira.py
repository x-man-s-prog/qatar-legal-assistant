# -*- coding: utf-8 -*-
"""
IRA — Intelligent Requirement Amplifier regression tests.

PEAL ensures required stages RUN.
IRA ensures they run WITH SUFFICIENT DEPTH.

Covers:
  A. Query-signal extraction (disjunction / decisive / strongest /
     classification dispute / drafting / multi-role)
  B. Requirement amplification rules
  C. Amplified validator (hypothesis floor, pivot generation,
     forbidden DLP modes, pivot-in-output)
  D. Live scenarios — partnership vs work, cheque guarantee, etc.
"""
from __future__ import annotations

import pytest

from core.runtime import (
    QuerySignals, extract_query_signals,
    amplify_requirements, validate_amplified,
    PipelineRequirements, PipelineState,
    PreExecutionValidator, detect_requirements,
    ResponseAuthor, UnifiedArtifacts,
    AuthoritativeOutputGate, AuthoritativeOutputViolation,
)
from core.production_runtime import answer_query_direct
from core.conversation import get_state_engine


# ═════════════════════════════════════════════════════════════════
# SECTION A — Query-signal extraction
# ═════════════════════════════════════════════════════════════════

class TestQuerySignals:
    def test_empty_query_has_no_signals(self):
        s = extract_query_signals("")
        assert s.has_disjunction is False
        assert s.asks_decisive_factor is False
        assert s.role_count == 0

    def test_disjunction_detection(self):
        s = extract_query_signals("هل هي شراكة أم عمل؟")
        assert s.has_disjunction is True
        assert len(s.disjunction_pairs) >= 1

    def test_decisive_factor_detection(self):
        s = extract_query_signals("ما الذي يحسم بين المسارين؟")
        assert s.asks_decisive_factor is True

    def test_strongest_detection(self):
        s = extract_query_signals("ما الأقوى في هذه القضية؟")
        assert s.asks_strongest is True

    def test_classification_dispute_detection(self):
        s = extract_query_signals("هل هذا تكييف جنائي أم مدني؟")
        assert s.has_classification_dispute is True

    def test_drafting_intent_detection(self):
        s = extract_query_signals("اكتب مذكرة دفاع في قضية شيك.")
        assert s.has_drafting_intent is True

    def test_multi_role_detection(self):
        s = extract_query_signals(
            "الشخص كان موظفاً ثم أصبح شريكاً في الشركة."
        )
        assert s.role_count >= 2

    def test_compound_signals_all_fire(self):
        s = extract_query_signals(
            "اكتب مذكرة دفاع — هل الشيك ضمان أم وفاء، وما الذي يحسم؟"
        )
        assert s.has_drafting_intent is True
        assert s.has_disjunction is True
        assert s.asks_decisive_factor is True


# ═════════════════════════════════════════════════════════════════
# SECTION B — Requirement amplification
# ═════════════════════════════════════════════════════════════════

class TestAmplification:
    def test_disjunction_forces_multi_path(self):
        base = PipelineRequirements()
        s = extract_query_signals("شراكة أم عمل؟")
        amplify_requirements(base, s)
        assert base.needs_multi_path is True
        assert base.min_hypotheses >= 2
        assert base.must_generate_pivots is True
        assert base.needs_pivot_output is True

    def test_decisive_factor_forces_pivots(self):
        base = PipelineRequirements()
        s = extract_query_signals("ما الذي يحسم بين المسارين؟")
        amplify_requirements(base, s)
        assert base.must_generate_pivots is True
        assert base.needs_pivot_output is True

    def test_strongest_forces_alternatives(self):
        base = PipelineRequirements()
        s = extract_query_signals("ما الأقوى في التكييف؟")
        amplify_requirements(base, s)
        assert base.min_hypotheses >= 2
        assert base.must_generate_pivots is True

    def test_drafting_plus_multipath_forbids_not_draftable(self):
        base = PipelineRequirements()
        s = extract_query_signals(
            "اكتب مذكرة دفاع — هل هي شراكة أم عمل؟"
        )
        amplify_requirements(base, s)
        assert "not_draftable_yet" in base.forbidden_dlp_modes
        assert "not_draftable_mlre" in base.forbidden_dlp_modes
        assert "conditional_draft" in base.allowed_dlp_modes
        assert "skeleton_draft" in base.allowed_dlp_modes

    def test_drafting_alone_allows_skeleton(self):
        base = PipelineRequirements()
        s = extract_query_signals("اكتب لي مذكرة دفاع.")
        amplify_requirements(base, s)
        assert base.allow_skeleton is True

    def test_multi_role_forces_multi_path(self):
        base = PipelineRequirements()
        s = extract_query_signals(
            "الشخص موظف وشريك في نفس الشركة."
        )
        amplify_requirements(base, s)
        assert base.needs_multi_path is True
        assert base.min_hypotheses >= 2

    def test_amplifications_are_recorded(self):
        base = PipelineRequirements()
        s = extract_query_signals("شراكة أم عمل؟")
        amplify_requirements(base, s)
        assert len(base.amplifications) >= 1


# ═════════════════════════════════════════════════════════════════
# SECTION C — Amplified validator
# ═════════════════════════════════════════════════════════════════

class TestValidateAmplified:
    def test_insufficient_hypotheses_flagged(self):
        req = PipelineRequirements(
            needs_mlre=True, needs_multi_path=True,
            min_hypotheses=2,
        )
        state = PipelineState(
            domain_resolved=True, issue_graph_built=True,
            mlre_executed=True, mlre_has_survivors=True,
            canonical_verified=True,
            survivors_count=1,   # <-- below floor
        )
        violations = validate_amplified(state, req)
        assert any("insufficient_hypotheses" in v for v in violations)

    def test_pivots_not_generated_flagged(self):
        req = PipelineRequirements(
            needs_mlre=True, must_generate_pivots=True,
        )
        state = PipelineState(
            domain_resolved=True, issue_graph_built=True,
            mlre_executed=True, canonical_verified=True,
            survivors_count=3,
            pivots_count=0, decisive_tests_count=0,
        )
        violations = validate_amplified(state, req)
        assert any("pivots_not_generated" in v for v in violations)

    def test_pivot_in_output_required(self):
        req = PipelineRequirements(
            needs_mlre=True, needs_pivot_output=True,
        )
        state = PipelineState(
            domain_resolved=True, issue_graph_built=True,
            mlre_executed=True, canonical_verified=True,
            survivors_count=2, pivots_count=1,
        )
        # Text doesn't mention any pivot marker
        violations = validate_amplified(
            state, req, text="هذا نص بدون ذكر للتحول أو البديل."
        )
        assert any("pivot_not_reflected_in_output" in v for v in violations)

    def test_pivot_in_output_satisfied_by_text_marker(self):
        req = PipelineRequirements(
            needs_mlre=True, needs_pivot_output=True,
        )
        state = PipelineState(
            domain_resolved=True, issue_graph_built=True,
            mlre_executed=True, canonical_verified=True,
            survivors_count=2, pivots_count=1,
        )
        violations = validate_amplified(
            state, req,
            text="متى ينتقل المسار الأول إلى البديل: إذا ثبت X.",
        )
        assert not any("pivot_not_reflected_in_output" in v for v in violations)

    def test_forbidden_dlp_mode_flagged(self):
        req = PipelineRequirements(
            needs_dlp=True,
            forbidden_dlp_modes={"not_draftable_yet", "not_draftable_mlre"},
        )
        state = PipelineState(
            domain_resolved=True, issue_graph_built=True,
            mlre_executed=True, dlp_mode_decided=True,
            dlp_mode="not_draftable_yet",   # <-- forbidden
            canonical_verified=True,
        )
        violations = validate_amplified(
            state, req, dlp_mode="not_draftable_yet",
        )
        assert any("dlp_mode_forbidden" in v for v in violations)

    def test_allowed_dlp_whitelist_enforced(self):
        req = PipelineRequirements(
            needs_dlp=True,
            allowed_dlp_modes={"conditional_draft", "skeleton_draft"},
        )
        state = PipelineState(
            domain_resolved=True, issue_graph_built=True,
            mlre_executed=True, dlp_mode_decided=True,
            dlp_mode="single_path",   # <-- outside whitelist
            canonical_verified=True,
        )
        violations = validate_amplified(
            state, req, dlp_mode="single_path",
        )
        assert any("dlp_mode_not_in_allowed" in v for v in violations)

    def test_clean_state_passes_amplified(self):
        req = PipelineRequirements(
            needs_mlre=True, needs_multi_path=True,
            min_hypotheses=2, must_generate_pivots=True,
            needs_pivot_output=True,
        )
        state = PipelineState(
            domain_resolved=True, issue_graph_built=True,
            mlre_executed=True, canonical_verified=True,
            survivors_count=3, pivots_count=2,
            decisive_tests_count=3,
        )
        violations = validate_amplified(
            state, req,
            text="متى ينتقل المسار الأول إلى البديل: كذا وكذا.",
        )
        assert violations == []


# ═════════════════════════════════════════════════════════════════
# SECTION D — Integration: detect_requirements applies IRA
# ═════════════════════════════════════════════════════════════════

class TestDetectAppliesIRA:
    def test_disjunction_amplifies_baseline(self):
        r = detect_requirements("شراكة أم عمل؟")
        assert r.needs_multi_path is True
        assert r.min_hypotheses >= 2
        assert r.must_generate_pivots is True

    def test_drafting_multipath_sets_forbidden_list(self):
        r = detect_requirements(
            "اكتب مذكرة دفاع — هل هي شراكة أم عمل؟"
        )
        assert "not_draftable_yet" in r.forbidden_dlp_modes
        assert r.needs_dual_strategy is True

    def test_smalltalk_bypasses_ira(self):
        r = detect_requirements("السلام عليكم")
        assert r.min_hypotheses == 0
        assert r.needs_multi_path is False

    def test_plain_analytical_has_no_ira_amplification(self):
        r = detect_requirements("ما حكم الشيك بدون رصيد؟")
        # Plain analytical → MLRE required but no amplified flags
        assert r.needs_mlre is True
        assert r.min_hypotheses == 0
        assert r.needs_pivot_output is False


# ═════════════════════════════════════════════════════════════════
# SECTION E — Live IRA integration
# ═════════════════════════════════════════════════════════════════

class TestLiveIRA:
    def test_partnership_vs_work_forces_multi_path(self):
        get_state_engine().reset("ira_live_partnership")
        r = answer_query_direct(
            "شراكة أم عمل؟ شريكي كان يأخذ راتباً شهرياً.",
            "ira_live_partnership",
        )
        peal = r.get("_peal", {}) or {}
        reqs = peal.get("requirements", {}) or {}
        state = peal.get("state", {}) or {}
        # Amplifications must be recorded
        assert any("multi_path" in a or "disjunction" in a
                      for a in reqs.get("amplifications", []))
        # Requirements must include multi-path mandates
        assert reqs.get("needs_multi_path") is True
        assert reqs.get("min_hypotheses", 0) >= 2
        # If PEAL is clean, MLRE produced ≥ min_hypotheses
        if peal.get("is_clean"):
            assert state.get("survivors_count", 0) >= 2

    def test_cheque_guarantee_drafting_has_forbidden_modes(self):
        get_state_engine().reset("ira_live_cheque")
        r = answer_query_direct(
            "اكتب مذكرة دفاع في شيك ضمان — ضمان أم وفاء؟",
            "ira_live_cheque",
        )
        peal = r.get("_peal", {}) or {}
        reqs = peal.get("requirements", {}) or {}
        # Drafting + multi-path forbids NOT_DRAFTABLE variants
        assert "not_draftable_yet" in (reqs.get("forbidden_dlp_modes") or [])
        # The chosen mode must NOT be in the forbidden list
        state = peal.get("state", {}) or {}
        if peal.get("is_clean"):
            assert state.get("dlp_mode") not in (
                reqs.get("forbidden_dlp_modes") or []
            )

    def test_decisive_factor_requires_pivots_in_output(self):
        get_state_engine().reset("ira_live_decisive")
        r = answer_query_direct(
            "مرض الموت — ما الذي يحسم صحة التصرف قبل الوفاة؟",
            "ira_live_decisive",
        )
        peal = r.get("_peal", {}) or {}
        reqs = peal.get("requirements", {}) or {}
        assert reqs.get("needs_pivot_output") is True
        state = peal.get("state", {}) or {}
        # If clean, pivot content surfaced in text
        if peal.get("is_clean"):
            assert state.get("pivot_in_output") is True

    def test_ip_ownership_forces_multi_path(self):
        get_state_engine().reset("ira_live_ip")
        r = answer_query_direct(
            "ملكية الكود البرمجي — للمطور أم الشركة؟",
            "ira_live_ip",
        )
        peal = r.get("_peal", {}) or {}
        reqs = peal.get("requirements", {}) or {}
        assert reqs.get("needs_multi_path") is True

    def test_plain_analytical_still_permitted(self):
        get_state_engine().reset("ira_live_plain")
        r = answer_query_direct(
            "ما حكم الشيك بدون رصيد في قطر؟",
            "ira_live_plain",
        )
        # Plain analytical should NOT require multi-path or pivot
        peal = r.get("_peal", {}) or {}
        reqs = peal.get("requirements", {}) or {}
        assert reqs.get("needs_multi_path") is False
        assert reqs.get("needs_pivot_output") is False


# ═════════════════════════════════════════════════════════════════
# SECTION F — Gate integration: IRA violations block emission
# ═════════════════════════════════════════════════════════════════

class TestGateIntegration:
    def test_gate_rejects_insufficient_hypotheses(self):
        a = UnifiedArtifacts(
            author=ResponseAuthor.MLRE_OUTPUT_COMPOSER,
            text="تحليل قانوني بسيط",
            domain="criminal",
            mlre_trace={"survivors_count": 1, "surviving_count": 1,
                          "reality": {"paths": [{"domain": "criminal"}]}},
            peal_requirements={
                "needs_domain": True, "needs_issue_graph": True,
                "needs_mlre": True, "needs_dlp": False,
                "needs_canonical": True,
                "needs_multi_path": True,
                "min_hypotheses": 2,
                "must_generate_pivots": False,
                "needs_pivot_output": False,
                "allowed_dlp_modes": [],
                "forbidden_dlp_modes": [],
                "allow_skeleton": True,
                "intent_tag": "multi_path_analysis",
                "amplifications": ["multi_path_on_disjunction"],
            },
            peal_state={
                "domain_resolved": True, "issue_graph_built": True,
                "mlre_executed": True, "mlre_has_survivors": True,
                "dlp_mode_decided": False, "dlp_mode": "",
                "canonical_verified": True,
                "survivors_count": 1,   # <-- violation (need ≥ 2)
                "pivots_count": 0,
                "decisive_tests_count": 0,
                "pivot_in_output": False,
            },
        )
        with pytest.raises(AuthoritativeOutputViolation):
            AuthoritativeOutputGate.emit(a)

    def test_gate_rejects_forbidden_dlp_mode(self):
        a = UnifiedArtifacts(
            author=ResponseAuthor.DLP_NOT_DRAFTABLE,
            text="تعذّر.",
            domain="criminal",
            is_blocked=True,
            drafting={
                "drafting_intent_detected": True,
                "drafting_mode": "not_draftable_yet",
            },
            peal_requirements={
                "needs_domain": True, "needs_issue_graph": True,
                "needs_mlre": True, "needs_dlp": True,
                "needs_canonical": True,
                "needs_multi_path": True,
                "min_hypotheses": 2,
                "must_generate_pivots": True,
                "needs_pivot_output": False,
                "needs_dual_strategy": True,
                "allowed_dlp_modes": ["conditional_draft", "skeleton_draft"],
                "forbidden_dlp_modes": ["not_draftable_yet", "not_draftable_mlre"],
                "allow_skeleton": True,
                "intent_tag": "drafting_multi_path",
                "amplifications": ["drafting_multipath_forbids_not_draftable"],
            },
            peal_state={
                "domain_resolved": True, "issue_graph_built": True,
                "mlre_executed": True, "mlre_has_survivors": True,
                "dlp_mode_decided": True,
                "dlp_mode": "not_draftable_yet",   # <-- forbidden
                "canonical_verified": True,
                "survivors_count": 2,
                "pivots_count": 1,
                "decisive_tests_count": 2,
                "pivot_in_output": False,
            },
        )
        with pytest.raises(AuthoritativeOutputViolation):
            AuthoritativeOutputGate.emit(a)
