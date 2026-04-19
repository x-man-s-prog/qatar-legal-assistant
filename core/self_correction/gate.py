# -*- coding: utf-8 -*-
"""
Reliability Gate V3 — strict legal-grade final checkpoint.
5 verdict tiers: PASS | PASS_WITH_WARNINGS | REPAIR | REPAIR_AGAIN | REFUSE
"""
import logging
from .schemas import (
    GateDecision, GateVerdict, RiskScore,
    CitationVerificationResult, GroundingResult,
    ContradictionResult, CoverageResult, RepairResult,
)
from .risk_scorer import RISK_PASS, RISK_WARN, RISK_REPAIR, RISK_REWRITE

log = logging.getLogger("sc_pipeline")

_REFUSAL_MSG = (
    "لم أتمكن من تقديم إجابة موثوقة على هذا السؤال بناءً على المصادر المتوفرة. "
    "أنصحك بمراجعة بوابة الميزان (almeezan.qa) أو استشارة محامٍ مختص."
)


def decide(
    answer: str,
    risk: RiskScore,
    citation: CitationVerificationResult,
    grounding: GroundingResult,
    contradiction: ContradictionResult,
    coverage: CoverageResult,
    repair: RepairResult | None = None,
) -> GateDecision:
    warnings: list[str] = list(risk.risk_factors)
    final_answer = repair.repaired_answer if repair else answer
    conf_adj = 0.0

    # ══ Hard refusal rules (non-negotiable) ══

    # Rule 1: Fabricated citations surviving repair
    if citation.fabricated:
        surviving = [f for f in citation.fabricated if f in final_answer] if repair else citation.fabricated
        if surviving:
            log.warning("[GATE] REFUSE: fabricated citations survived: %s", surviving[:3])
            return GateDecision(
                verdict=GateVerdict.REFUSE, final_answer=_REFUSAL_MSG,
                confidence_adjustment=-50, warnings=warnings, risk=risk,
                citation_result=citation, refused_reason="مواد مفبركة لم تُحذف")

    # Rule 2: Major unresolved contradictions
    if contradiction.has_major:
        major_remaining = any(
            c.severity == "major" and c.answer_segment in final_answer
            for c in contradiction.contradictions)
        if major_remaining:
            log.warning("[GATE] REFUSE: major contradictions remain")
            return GateDecision(
                verdict=GateVerdict.REFUSE, final_answer=_REFUSAL_MSG,
                confidence_adjustment=-40, warnings=warnings, risk=risk,
                contradiction_result=contradiction,
                refused_reason="تناقضات جوهرية مع النصوص")

    # Rule 3: ALL decisive claims unsupported + no verified citations
    has_citation_grounding = citation.verified > 0
    if (grounding.total > 0 and grounding.unsupported_decisive > 0
            and grounding.grounded == 0 and not has_citation_grounding):
        log.warning("[GATE] REFUSE: zero grounded claims, no verified citations")
        return GateDecision(
            verdict=GateVerdict.REFUSE, final_answer=_REFUSAL_MSG,
            confidence_adjustment=-50, warnings=warnings, risk=risk,
            grounding_result=grounding, refused_reason="لا سند لأي ادعاء")

    # Rule 4: Risk exceeds rewrite threshold after repair
    if risk.overall_risk > RISK_REWRITE:
        log.warning("[GATE] REFUSE: risk=%.2f > threshold", risk.overall_risk)
        return GateDecision(
            verdict=GateVerdict.REFUSE, final_answer=_REFUSAL_MSG,
            confidence_adjustment=-40, warnings=warnings, risk=risk,
            refused_reason=f"مخاطرة عالية: {risk.overall_risk:.0%}")

    # ══ Graduated pass tiers ══

    # Clean pass
    if risk.overall_risk <= RISK_PASS:
        return GateDecision(
            verdict=GateVerdict.PASS, final_answer=final_answer,
            confidence_adjustment=0, warnings=[], risk=risk,
            citation_result=citation, grounding_result=grounding,
            contradiction_result=contradiction, coverage_result=coverage,
            repair_result=repair)

    # Pass with warnings
    if risk.overall_risk <= RISK_WARN:
        conf_adj = -int(risk.overall_risk * 20)
        if coverage.partial:
            warnings.append("إجابة جزئية")
        return GateDecision(
            verdict=GateVerdict.PASS_WITH_WARNINGS, final_answer=final_answer,
            confidence_adjustment=conf_adj, warnings=warnings, risk=risk,
            citation_result=citation, grounding_result=grounding,
            contradiction_result=contradiction, coverage_result=coverage,
            repair_result=repair)

    # Medium risk — pass with stronger warnings
    conf_adj = -int(risk.overall_risk * 30)
    if coverage.partial and coverage.missing_aspects:
        warnings.append("جوانب ناقصة في الإجابة")

    return GateDecision(
        verdict=GateVerdict.PASS_WITH_WARNINGS, final_answer=final_answer,
        confidence_adjustment=conf_adj, warnings=warnings, risk=risk,
        citation_result=citation, grounding_result=grounding,
        contradiction_result=contradiction, coverage_result=coverage,
        repair_result=repair)
