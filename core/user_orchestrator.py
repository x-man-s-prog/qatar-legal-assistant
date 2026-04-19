# -*- coding: utf-8 -*-
"""
Ordinary User Orchestrator — Unified public-user response pipeline.
Runs all user layers in correct order, produces one clean FinalUserResponse.
Does NOT replace any existing layer. Orchestrates them.
"""
from __future__ import annotations
import logging, threading, re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from core.simple_answer import simplify_for_user, SimpleResponseMode
from core.user_risk import apply_user_risk_layer, UserRiskProfile, UserRiskLevel
from core.scenario_engine import check_scenario_guidance
from core.explanation_engine import build_user_explanation
from core.user_evaluator import OrdinaryUserEvaluator, OrdinaryUserEvaluationCase, OrdinaryUserEvaluationResult
from core.public_guardrails import apply_public_guardrails, PublicGuardrailResult
from core.cross_domain_reasoner import enhance_answer_for_multi_domain
from core.stabilization import (
    enhance_with_case_analysis as _stab_case_analysis,
    safe_clean as _stab_safe_clean,
    should_activate_case_analysis as _stab_should_activate,
)
# PHASE CORE FIX: full legal thinking engine (supersedes simpler case_analysis)
from core.legal_thinking_engine import (
    enhance_with_legal_thinking as _brain_enhance,
    should_activate_legal_thinking as _brain_should_activate,
)
# PHASE ADVANCED: expert prioritized analysis (supersedes brain output for complex queries)
from core.expert_legal_analysis import (
    enhance_with_expert_analysis as _expert_enhance,
)
# PHASE LEGAL GROUNDING FIX: zero-hallucination citation filter (final-step)
from core.legal_grounding import (
    ground_legal_text as _grounding_filter,
)

log = logging.getLogger("user_orch")


# ══════════════════════════════════════════════════════════════
# User Mode
# ══════════════════════════════════════════════════════════════

class UserFacingMode(str, Enum):
    PUBLIC = "public"
    PROFESSIONAL = "professional"
    INTERNAL_DEBUG = "internal_debug"


# ══════════════════════════════════════════════════════════════
# Final User Response
# ══════════════════════════════════════════════════════════════

@dataclass
class FinalUserResponse:
    user_mode: str = ""
    final_text: str = ""
    short_answer: str = ""
    explanation_sections: list[str] = field(default_factory=list)
    caution_text: str = ""
    guidance_text: str = ""
    next_steps: str = ""
    limitation_text: str = ""
    public_guardrail_applied: bool = False
    scenario_guidance_applied: bool = False
    cross_domain_applied: bool = False
    risk_level: str = "low"
    user_quality_score: float = 0.0
    final_status: str = "ok"  # ok | guided | fallback
    notes_internal: list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════
# Output Assembly Policy
# ══════════════════════════════════════════════════════════════

class UserOutputAssemblyPolicy:

    def deduplicate(self, parts: list[str]) -> list[str]:
        seen = set()
        result = []
        for p in parts:
            normalized = p.strip().lower()[:50]
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(p)
        return result

    def merge_sections(self, sections: list[str], max_total: int = 3500) -> str:
        # PHASE CORE FIX: raised from 600 to 2500 chars for the legal
        # thinking output. PHASE ADVANCED: raised to 3500 chars to fit the
        # expert prioritized analysis (summary + ranked details + sequence).
        deduped = self.deduplicate([s for s in sections if s.strip()])
        merged = "\n\n".join(deduped)
        if len(merged) > max_total:
            merged = merged[:max_total].rsplit("\n", 1)[0]
        return merged.strip()

    def finalize(self, text: str) -> str:
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" {2,}", " ", text)
        return text.strip()


# ══════════════════════════════════════════════════════════════
# Metrics
# ══════════════════════════════════════════════════════════════

class _OrchestratorMetrics:
    def __init__(self):
        self._lock = threading.Lock()
        self.public_runs = 0
        self.professional_runs = 0
        self.debug_runs = 0
        self.guidance_triggered = 0
        self.guardrail_applied = 0
        self.caution_merges = 0
        self.dedup_prevented = 0
        self.quality_scores: list[float] = []

    def snapshot(self) -> dict:
        with self._lock:
            total = self.public_runs + self.professional_runs + self.debug_runs
            t = max(total, 1)
            avg_q = sum(self.quality_scores[-100:]) / max(len(self.quality_scores[-100:]), 1)
            return {
                "total_runs": total,
                "public_runs": self.public_runs,
                "professional_runs": self.professional_runs,
                "scenario_guidance_rate": round(self.guidance_triggered / t * 100, 1),
                "public_guardrail_rate": round(self.guardrail_applied / t * 100, 1),
                "caution_merge_rate": round(self.caution_merges / t * 100, 1),
                "dedup_prevented": self.dedup_prevented,
                "avg_user_quality_score": round(avg_q, 3),
            }


# ══════════════════════════════════════════════════════════════
# Orchestrator
# ══════════════════════════════════════════════════════════════

class OrdinaryUserOrchestrator:

    def __init__(self):
        self._assembly = UserOutputAssemblyPolicy()
        self._evaluator = OrdinaryUserEvaluator()
        self._metrics = _OrchestratorMetrics()

    def run(self, answer: str, query: str, domain: str = "",
            decision_type: str = "direct", confidence: float = 1.0,
            limitations: list[str] = None,
            mode: UserFacingMode = UserFacingMode.PUBLIC,
            brain_route: str = "", is_structured: bool = False) -> FinalUserResponse:

        if mode == UserFacingMode.PUBLIC:
            return self._run_public(answer, query, domain, decision_type,
                                     confidence, limitations, brain_route, is_structured)
        elif mode == UserFacingMode.PROFESSIONAL:
            return self._run_professional(answer, query, domain, decision_type,
                                           confidence, limitations)
        else:
            return self._run_debug(answer, query, domain, decision_type, confidence)

    def _run_public(self, answer, query, domain, decision_type,
                     confidence, limitations, brain_route, is_structured) -> FinalUserResponse:
        resp = FinalUserResponse(user_mode="public")
        self._metrics.public_runs += 1

        # 1. Scenario guidance check
        guidance = check_scenario_guidance(query, brain_route, is_structured)
        if guidance:
            resp.guidance_text = guidance
            resp.scenario_guidance_applied = True
            resp.final_text = guidance
            resp.final_status = "guided"
            self._metrics.guidance_triggered += 1
            log.info("[USER_ORCH] public: guided")
            return resp

        # 2. Risk assessment
        risk_answer, risk_profile = apply_user_risk_layer(
            answer, query, domain, confidence, decision_type)
        resp.risk_level = risk_profile.risk_level.value
        has_risk = risk_profile.risk_level in (
            UserRiskLevel.HIGH_CRIMINAL, UserRiskLevel.HIGH_FAMILY)

        # 2.5 Cross-domain reasoning (no-op for single-domain queries)
        try:
            _cd_enhanced, _cd_plan = enhance_answer_for_multi_domain(risk_answer, query)
            if _cd_plan is not None and _cd_plan.is_multi_domain():
                # Only restructure if the answer has content and the plan deems it safe
                if risk_answer.strip() and _cd_plan.safe_to_answer_jointly:
                    risk_answer = _cd_enhanced
                    resp.cross_domain_applied = True
                    log.info("[USER_ORCH] cross-domain applied: primary=%s secondaries=%s",
                             _cd_plan.primary_domain, _cd_plan.secondary_domains)
        except Exception as _cd_err:
            log.debug("cross_domain (non-critical): %s", _cd_err)

        # 2.75 PHASE ADVANCED: Expert Legal Analysis — prioritized, ranked
        # judgment (decisive items surface first, fixable vs non-fixable
        # weaknesses, immediate vs secondary priorities). Internally runs
        # the LegalThinkingEngine and upgrades its output. Single source of
        # truth for complex consultation queries.
        _brain_applied = False
        try:
            if _brain_should_activate(query):
                _expert_enhanced, _brain_applied, _expert_plan = _expert_enhance(
                    risk_answer, query)
                if _brain_applied:
                    risk_answer = _expert_enhanced
                    log.info("[USER_ORCH] expert legal analysis applied: issue=%s",
                             _expert_plan.issue_type.value if _expert_plan else "?")
        except Exception as _expert_err:
            log.debug("expert_legal_analysis (non-critical): %s", _expert_err)

        # Fallback: simpler case analysis (for queries that trigger the legacy
        # activator but not the full brain).
        if not _brain_applied:
            try:
                if _stab_should_activate(query, domain):
                    _ca_enhanced, _ca_applied = _stab_case_analysis(
                        risk_answer, query, domain=domain)
                    if _ca_applied:
                        risk_answer = _ca_enhanced
                        log.info("[USER_ORCH] case analysis applied (fallback)")
            except Exception as _ca_err:
                log.debug("case_analysis (non-critical): %s", _ca_err)

        # 3. Explanation building
        answer_type = "high_risk" if has_risk else decision_type
        # General info queries: skip domain-specific next steps (avoids unnecessary warnings)
        explain_domain = "" if risk_profile.risk_level == UserRiskLevel.MODERATE else domain
        explained = build_user_explanation(
            risk_answer, answer_type, explain_domain, has_risk,
            risk_profile.requires_deadline_warning, limitations)

        # 4. Public guardrails
        guarded, guardrail_result = apply_public_guardrails(
            explained, query, resp.risk_level, confidence, domain, is_public=True)
        resp.public_guardrail_applied = guardrail_result.hardening_applied
        if guardrail_result.hardening_applied:
            self._metrics.guardrail_applied += 1

        # 5. Assembly
        sections = [s for s in guarded.split("\n\n") if s.strip()]
        before_dedup = len(sections)
        clean = self._assembly.merge_sections(sections)
        after_dedup = len(clean.split("\n\n"))
        if after_dedup < before_dedup:
            self._metrics.dedup_prevented += (before_dedup - after_dedup)

        resp.final_text = self._assembly.finalize(clean)
        # PHASE FIX: unified output cleanup — removes fillers + robotic openings
        try:
            resp.final_text = _stab_safe_clean(resp.final_text)
        except Exception as _oc_err:
            log.debug("output_cleaner (non-critical): %s", _oc_err)
        # PHASE LEGAL GROUNDING FIX: zero-hallucination citation filter.
        # Strips unverified law/article references regardless of where they
        # came from (LLM, retrieval, or upstream layers). VERIFIED references
        # pass through; PARTIAL keeps the law name only; UNVERIFIED is replaced
        # with a safe placeholder.
        try:
            _ground = _grounding_filter(resp.final_text, issue_domain=domain)
            if _ground.citations_blocked or _ground.citations_downgraded:
                log.info("[GROUNDING] blocked=%d downgraded=%d on session response",
                         len(_ground.citations_blocked),
                         len(_ground.citations_downgraded))
            resp.final_text = _ground.text
        except Exception as _g_err:
            log.debug("legal_grounding (non-critical): %s", _g_err)
        resp.short_answer = resp.final_text.split("\n")[0][:80] if resp.final_text else ""

        # 6. Quality evaluation (lightweight)
        eval_case = OrdinaryUserEvaluationCase(
            case_id="live", query=query, domain=domain,
            should_include_caution=has_risk,
            should_avoid_overwarning=not has_risk)
        eval_result = self._evaluator.evaluate(eval_case, resp.final_text,
                                                risk_level=resp.risk_level)
        resp.user_quality_score = eval_result.total_score
        self._metrics.quality_scores.append(eval_result.total_score)

        if guardrail_result.fallback_applied:
            resp.final_status = "fallback"
        else:
            resp.final_status = "ok"

        log.info("[USER_ORCH] public: status=%s risk=%s quality=%.2f guardrail=%s",
                 resp.final_status, resp.risk_level, resp.user_quality_score,
                 resp.public_guardrail_applied)
        return resp

    def _run_professional(self, answer, query, domain, decision_type,
                           confidence, limitations) -> FinalUserResponse:
        resp = FinalUserResponse(user_mode="professional")
        self._metrics.professional_runs += 1

        # Lighter pipeline: explanation + mild risk
        explained = build_user_explanation(answer, decision_type, domain,
                                            has_risk=False, limitations=limitations)
        resp.final_text = self._assembly.finalize(explained)
        resp.short_answer = resp.final_text.split("\n")[0][:80] if resp.final_text else ""
        resp.final_status = "ok"

        log.info("[USER_ORCH] professional: len=%d", len(resp.final_text))
        return resp

    def _run_debug(self, answer, query, domain, decision_type,
                    confidence) -> FinalUserResponse:
        resp = FinalUserResponse(user_mode="internal_debug")
        self._metrics.debug_runs += 1

        resp.final_text = answer
        resp.short_answer = answer[:80]
        resp.notes_internal = [
            f"domain={domain}", f"decision={decision_type}",
            f"confidence={confidence}",
        ]
        resp.final_status = "ok"
        return resp

    def get_metrics(self) -> dict:
        return self._metrics.snapshot()


# ══════════════════════════════════════════════════════════════
# Singleton
# ══════════════════════════════════════════════════════════════

_orchestrator: Optional[OrdinaryUserOrchestrator] = None

def get_orchestrator() -> OrdinaryUserOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = OrdinaryUserOrchestrator()
    return _orchestrator
