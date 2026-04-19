# -*- coding: utf-8 -*-
"""
Adaptive Risk Scorer — context-aware risk scoring.
Adjusts weights and thresholds based on query type, complexity, and retrieval quality.
"""
import logging
from .schemas import (
    CitationVerificationResult, GroundingResult,
    ContradictionResult, CoverageResult, RiskScore, QueryContext, QueryComplexity,
)

log = logging.getLogger("sc_pipeline")

# ══════════════════════════════════════════════════════════════
# Default weights
# ══════════════════════════════════════════════════════════════
_BASE_W = {"citation": 0.35, "grounding": 0.25, "contradiction": 0.25, "coverage": 0.15}

# Thresholds
RISK_PASS = 0.20
RISK_WARN = 0.35
RISK_REPAIR = 0.50
RISK_REWRITE = 0.70


def _get_weights(ctx: QueryContext) -> dict:
    """Adapt weights to query context."""
    w = dict(_BASE_W)
    if ctx.is_legal:
        w["citation"] = 0.40       # Legal → stricter citation
        w["contradiction"] = 0.30  # Legal → contradictions very serious
        w["coverage"] = 0.10
        w["grounding"] = 0.20
    if ctx.has_tools:
        w["grounding"] = 0.30     # Tool answers need strong grounding
        w["citation"] = 0.25
    if ctx.complexity in (QueryComplexity.LEGAL_MULTI, QueryComplexity.COMPLEX):
        w["coverage"] = 0.25      # Complex → coverage matters more
        w["citation"] = 0.30
        w["grounding"] = 0.25
        w["contradiction"] = 0.20
    # Normalize to 1.0
    total = sum(w.values())
    return {k: v / total for k, v in w.items()}


def _get_thresholds(ctx: QueryContext) -> tuple:
    """Stricter thresholds for legal, looser for simple."""
    if not ctx.is_legal:
        return 0.30, 0.45, 0.60, 0.80  # pass, warn, repair, rewrite
    if ctx.complexity == QueryComplexity.SIMPLE:
        return 0.30, 0.45, 0.60, 0.80
    # Legal default — strict
    return RISK_PASS, RISK_WARN, RISK_REPAIR, RISK_REWRITE


def score_risk(
    citation: CitationVerificationResult,
    grounding: GroundingResult,
    contradiction: ContradictionResult,
    coverage: CoverageResult,
    ctx: QueryContext | None = None,
) -> RiskScore:
    if ctx is None:
        ctx = QueryContext()

    w = _get_weights(ctx)
    risk_factors: list[str] = []

    # ── Citation risk ──
    if citation.total == 0:
        c_risk = 0.0
    else:
        c_risk = citation.failed / citation.total
        if citation.fabricated:
            c_risk = max(c_risk, 0.8)
            risk_factors.append(f"مواد مفبركة: {', '.join(citation.fabricated[:3])}")

    # ── Grounding risk ──
    if grounding.total == 0:
        g_risk = 0.0
    else:
        g_risk = grounding.unsupported / grounding.total
        if grounding.unsupported_decisive > 0:
            if citation.verified > 0:
                g_risk = min(g_risk, 0.3)
            else:
                g_risk = max(g_risk, 0.6)
            if g_risk > 0.3:
                risk_factors.append(f"ادعاءات حاسمة بدون سند: {grounding.unsupported_decisive}")

    # ── Contradiction risk ──
    ct_risk = 0.0
    if contradiction.has_major:
        ct_risk = min(1.0, 0.5 + contradiction.count * 0.2)
        risk_factors.append(f"تناقضات جوهرية: {contradiction.count}")
    elif contradiction.count > 0:
        ct_risk = min(0.4, contradiction.count * 0.15)
        risk_factors.append(f"تناقضات ثانوية: {contradiction.count}")

    # ── Coverage risk ──
    cv_risk = max(0.0, (100 - coverage.coverage_pct) / 100)
    if not coverage.covers_main_question:
        cv_risk = max(cv_risk, 0.7)
        risk_factors.append("لا تغطي السؤال الأساسي")
    elif coverage.missing_aspects:
        risk_factors.append(f"جوانب ناقصة: {', '.join(coverage.missing_aspects[:3])}")

    # ── Weighted aggregate ──
    overall = (
        w["citation"] * c_risk
        + w["grounding"] * g_risk
        + w["contradiction"] * ct_risk
        + w["coverage"] * cv_risk
    )

    # ── Retrieval quality adjustment ──
    if ctx.retrieval_confidence < 0.5 and ctx.is_legal:
        overall = min(1.0, overall + 0.1)
        if ctx.retrieval_confidence < 0.3:
            risk_factors.append("جودة الاسترجاع منخفضة")

    return RiskScore(
        citation_risk=round(c_risk, 3),
        grounding_risk=round(g_risk, 3),
        contradiction_risk=round(ct_risk, 3),
        coverage_risk=round(cv_risk, 3),
        overall_risk=round(min(1.0, overall), 3),
        risk_factors=risk_factors,
    )
