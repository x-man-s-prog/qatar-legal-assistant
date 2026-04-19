# -*- coding: utf-8 -*-
"""
PEAL — Pre-Execution Authority Lock regression tests.

PEAL protects THINKING. For a given (query, intent), PEAL ensures the
required reasoning stages (domain, issue graph, MLRE, DLP, canonical)
actually ran BEFORE the output gate stamps authority.

Covers:
  A. Requirement detection from the query + intent
  B. Validator rules (domain / graph / MLRE / DLP / canonical)
  C. Gate integration — emission refused when PEAL fails
  D. Live integration — PEAL telemetry attached to every response
  E. Trigger scenarios (multi-path queries, drafting intents)
"""
from __future__ import annotations

import pytest

from core.runtime import (
    PipelineState, PipelineRequirements, PEALReport,
    PreExecutionValidator, detect_requirements,
    extract_state_from_artifacts,
    ResponseAuthor, UnifiedArtifacts,
    AuthoritativeOutputGate, AuthoritativeOutputViolation,
)
from core.production_runtime import answer_query_direct
from core.conversation import get_state_engine


# ═════════════════════════════════════════════════════════════════
# SECTION A — Requirement detection
# ═════════════════════════════════════════════════════════════════

class TestRequirementDetection:
    def test_empty_query_has_no_requirements(self):
        r = detect_requirements("")
        assert r.needs_mlre is False
        assert r.needs_dlp  is False
        assert r.intent_tag == "empty"

    def test_smalltalk_skips_legal_requirements(self):
        r = detect_requirements("السلام عليكم")
        assert r.needs_mlre is False
        assert r.needs_issue_graph is False
        assert r.intent_tag == "smalltalk"

    def test_drafting_intent_forces_dlp_and_mlre(self):
        r = detect_requirements("اكتب مذكرة دفاع في قضية شيك.")
        assert r.needs_dlp  is True
        assert r.needs_mlre is True
        assert r.intent_tag == "drafting"

    def test_disjunctive_triggers_multi_path(self):
        r = detect_requirements("هل هي شراكة أم عمل؟")
        assert r.needs_mlre is True
        assert r.intent_tag == "multi_path_analysis"

    def test_comparison_triggers_multi_path(self):
        r = detect_requirements("ما الفرق بين التكييف الجنائي والمدني؟")
        assert r.needs_mlre is True
        assert r.intent_tag == "multi_path_analysis"

    def test_default_analytical_still_requires_mlre(self):
        r = detect_requirements("ما حكم الشيك بدون رصيد في قطر؟")
        # Policy: every legal analytical query routes through MLRE
        assert r.needs_mlre is True
        assert r.intent_tag == "analytical"

    def test_triggered_reasons_are_observable(self):
        r = detect_requirements("شراكة أم عمل؟")
        assert len(r.trigger_reasons) >= 1


# ═════════════════════════════════════════════════════════════════
# SECTION B — Validator rules
# ═════════════════════════════════════════════════════════════════

class TestValidator:
    def test_all_required_stages_ran_passes(self):
        state = PipelineState(
            domain_resolved=True, issue_graph_built=True,
            mlre_executed=True, dlp_mode_decided=True,
            dlp_mode="conditional_draft",
            canonical_verified=True,
        )
        reqs = PipelineRequirements(
            needs_mlre=True, needs_dlp=True,
            needs_canonical=True,
        )
        report = PreExecutionValidator.validate(state, reqs)
        assert report.is_clean is True

    def test_mlre_required_but_missing_fails(self):
        state = PipelineState(
            domain_resolved=True, issue_graph_built=True,
            mlre_executed=False,   # <-- missing
            canonical_verified=True,
        )
        reqs = PipelineRequirements(needs_mlre=True)
        report = PreExecutionValidator.validate(state, reqs)
        assert report.is_clean is False
        assert "mlre_not_executed" in report.violations

    def test_dlp_required_but_missing_fails(self):
        state = PipelineState(
            domain_resolved=True, issue_graph_built=True,
            mlre_executed=True,
            dlp_mode_decided=False,   # <-- missing
            canonical_verified=True,
        )
        reqs = PipelineRequirements(needs_mlre=True, needs_dlp=True)
        report = PreExecutionValidator.validate(state, reqs)
        assert report.is_clean is False
        assert "dlp_mode_not_decided" in report.violations

    def test_issue_graph_required_but_missing_fails(self):
        state = PipelineState(
            domain_resolved=True,
            issue_graph_built=False,   # <-- missing
            mlre_executed=True,
            canonical_verified=True,
        )
        reqs = PipelineRequirements(needs_mlre=True)
        report = PreExecutionValidator.validate(state, reqs)
        assert report.is_clean is False
        assert "issue_graph_missing" in report.violations

    def test_domain_required_but_missing_fails(self):
        state = PipelineState(
            domain_resolved=False,   # <-- missing
            issue_graph_built=True,
            mlre_executed=True,
            canonical_verified=True,
        )
        reqs = PipelineRequirements(needs_mlre=True)
        report = PreExecutionValidator.validate(state, reqs)
        assert report.is_clean is False
        assert "domain_not_resolved" in report.violations

    def test_canonical_required_but_missing_fails(self):
        state = PipelineState(
            domain_resolved=True, issue_graph_built=True,
            mlre_executed=True,
            canonical_verified=False,   # <-- missing
        )
        reqs = PipelineRequirements(needs_mlre=True, needs_canonical=True)
        report = PreExecutionValidator.validate(state, reqs)
        assert report.is_clean is False
        assert "canonical_not_verified" in report.violations


# ═════════════════════════════════════════════════════════════════
# SECTION C — Gate integration
# ═════════════════════════════════════════════════════════════════

class TestGateIntegration:
    def test_gate_skips_peal_when_not_opted_in(self):
        """Artifacts without peal_requirements skip PEAL (opt-in policy)."""
        a = UnifiedArtifacts(
            author=ResponseAuthor.FAIL_CLOSED_PIPELINE,
            text="جواب قانوني مختصر وواضح.",
            domain="criminal",
            is_grounded=True,
        )
        # No peal_requirements set → no PEAL enforcement
        r = AuthoritativeOutputGate.emit(a)
        assert r["output_author"] == "fail_closed_pipeline"

    def test_gate_rejects_when_mlre_required_and_missing(self):
        a = UnifiedArtifacts(
            author=ResponseAuthor.FAIL_CLOSED_PIPELINE,
            text="جواب قانوني بدون MLRE.",
            domain="criminal",
            is_grounded=True,
            peal_requirements={
                "needs_domain": True,
                "needs_issue_graph": True,
                "needs_mlre": True,
                "needs_dlp": False,
                "needs_canonical": True,
                "intent_tag": "analytical",
                "trigger_reasons": ["default_analytical_policy"],
            },
            peal_state={
                "domain_resolved": True,
                "issue_graph_built": True,
                "mlre_executed": False,    # <-- violation
                "dlp_mode_decided": False,
                "canonical_verified": True,
            },
        )
        with pytest.raises(AuthoritativeOutputViolation):
            AuthoritativeOutputGate.emit(a)

    def test_gate_rejects_when_dlp_required_and_missing(self):
        a = UnifiedArtifacts(
            author=ResponseAuthor.DLP_FULL_DRAFT,
            text="مذكرة — هيكل كامل.",
            domain="criminal",
            is_grounded=True,
            drafting={
                "drafting_intent_detected": True,
                "drafting_mode": "full_draft",
            },
            peal_requirements={
                "needs_mlre": True,
                "needs_dlp": True,
                "needs_domain": True,
                "needs_issue_graph": True,
                "needs_canonical": True,
                "intent_tag": "drafting",
            },
            peal_state={
                "domain_resolved": True,
                "issue_graph_built": True,
                "mlre_executed": True,
                "dlp_mode_decided": False,   # <-- violation
                "canonical_verified": True,
            },
        )
        with pytest.raises(AuthoritativeOutputViolation):
            AuthoritativeOutputGate.emit(a)

    def test_operational_authors_bypass_peal(self):
        """Cancelled / internal-failure / safety-stop authors skip PEAL."""
        from core.runtime import build_cancelled_artifacts, build_internal_failure_artifacts
        for a in (
            build_cancelled_artifacts(request_id="x", stage="t"),
            build_internal_failure_artifacts(reason="t"),
        ):
            a.peal_requirements = {
                "needs_mlre": True, "needs_dlp": True,
            }
            a.peal_state = {"mlre_executed": False, "dlp_mode_decided": False}
            # Should NOT raise
            r = AuthoritativeOutputGate.emit(a)
            assert r["output_author"] in {"cancelled", "internal_failure"}


# ═════════════════════════════════════════════════════════════════
# SECTION D — Live integration tests
# ═════════════════════════════════════════════════════════════════

class TestLivePEAL:
    def test_multi_path_query_forces_mlre(self):
        get_state_engine().reset("peal_live_mp")
        r = answer_query_direct(
            "شراكة أم عمل؟ صديقي كان يأخذ راتباً شهرياً.",
            "peal_live_mp",
        )
        peal = r.get("_peal", {}) or {}
        reqs = peal.get("requirements", {}) or {}
        state = peal.get("state", {}) or {}
        assert reqs.get("needs_mlre") is True
        # If PEAL is clean, MLRE executed. If PEAL violated, runtime
        # rescued via internal_failure (still a valid outcome).
        if peal.get("is_clean"):
            assert state.get("mlre_executed") is True

    def test_drafting_request_forces_dlp(self):
        get_state_engine().reset("peal_live_draft")
        r = answer_query_direct(
            "اكتب لي مذكرة دفاع في قضية شيك ضمان.",
            "peal_live_draft",
        )
        peal = r.get("_peal", {}) or {}
        reqs = peal.get("requirements", {}) or {}
        state = peal.get("state", {}) or {}
        assert reqs.get("needs_dlp") is True
        assert reqs.get("intent_tag") == "drafting"
        if peal.get("is_clean"):
            assert state.get("dlp_mode_decided") is True
            assert state.get("dlp_mode", "")

    def test_analytical_query_runs_mlre(self):
        get_state_engine().reset("peal_live_analytical")
        r = answer_query_direct(
            "ما حكم الشيك بدون رصيد في قطر؟",
            "peal_live_analytical",
        )
        peal = r.get("_peal", {}) or {}
        reqs = peal.get("requirements", {}) or {}
        assert reqs.get("needs_mlre") is True

    def test_smalltalk_requires_nothing(self):
        get_state_engine().reset("peal_live_smalltalk")
        r = answer_query_direct("السلام عليكم", "peal_live_smalltalk")
        peal = r.get("_peal", {}) or {}
        reqs = peal.get("requirements", {}) or {}
        # Either no PEAL (operational author) OR no legal requirements
        if reqs:
            assert reqs.get("needs_mlre") is False
            assert reqs.get("needs_dlp")  is False

    def test_peal_trace_is_attached(self):
        get_state_engine().reset("peal_live_trace")
        r = answer_query_direct(
            "اكتب مذكرة دفاع في اعتداء بسيط.",
            "peal_live_trace",
        )
        assert "_peal" in r
        peal = r["_peal"]
        assert "requirements" in peal
        assert "state" in peal

    def test_cheque_query_has_mlre(self):
        """PEAL regression: شيك ضمان MUST route through MLRE."""
        get_state_engine().reset("peal_live_cheque")
        r = answer_query_direct(
            "اكتب مذكرة دفاع في شيك ضمان.",
            "peal_live_cheque",
        )
        peal = r.get("_peal", {}) or {}
        state = peal.get("state", {}) or {}
        reqs = peal.get("requirements", {}) or {}
        assert reqs.get("needs_mlre") is True
        if peal.get("is_clean"):
            assert state.get("mlre_executed") is True


# ═════════════════════════════════════════════════════════════════
# SECTION E — State extractor
# ═════════════════════════════════════════════════════════════════

class TestStateExtractor:
    def test_extract_from_empty_artifacts(self):
        a = UnifiedArtifacts(author=ResponseAuthor.FAIL_CLOSED_PIPELINE)
        state = extract_state_from_artifacts(a)
        assert state.domain_resolved is False
        assert state.mlre_executed is False
        assert state.dlp_mode_decided is False

    def test_extract_detects_mlre_from_output_composition(self):
        a = UnifiedArtifacts(
            author=ResponseAuthor.MLRE_OUTPUT_COMPOSER,
            text="text",
            domain="criminal",
            mlre_trace={
                "output_composition": {
                    "mlre_output_used": True,
                    "survivors_count": 3,
                },
            },
        )
        state = extract_state_from_artifacts(a)
        assert state.mlre_executed is True

    def test_extract_detects_domain_from_mlre_paths(self):
        a = UnifiedArtifacts(
            author=ResponseAuthor.FAIL_CLOSED_PIPELINE,
            text="text",
            domain="",   # empty pipeline domain
            mlre_trace={
                "reality": {
                    "paths": [{"domain": "criminal", "rank": 1}],
                },
            },
        )
        state = extract_state_from_artifacts(a)
        # MLRE surviving domain should count as domain-resolved
        assert state.domain_resolved is True

    def test_extract_detects_dlp_from_drafting_dict(self):
        a = UnifiedArtifacts(
            author=ResponseAuthor.DLP_FULL_DRAFT,
            text="t", domain="criminal",
            drafting={
                "drafting_intent_detected": True,
                "drafting_mode": "conditional_draft",
            },
        )
        state = extract_state_from_artifacts(a)
        assert state.dlp_mode_decided is True
        assert state.dlp_mode == "conditional_draft"
