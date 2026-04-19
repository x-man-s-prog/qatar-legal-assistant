# -*- coding: utf-8 -*-
"""
5-dimensional scoring engine.

For every hypothesis:
  1. Legal Plausibility      — does this theory fit Qatari law?
  2. Evidence Feasibility    — can the needed evidence plausibly exist?
  3. Consistency with Facts  — do stated facts align with the theory?
  4. Risk Exposure           — how severe if this interpretation wins?
  5. Adversarial Strength    — how hard is it to knock down?

Final weighted composite but we NEVER just pick the top.
Survival filter (next module) enforces diversity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.mlre.hypothesis import Hypothesis, HypothesisType


@dataclass
class ScoreBreakdown:
    legal_plausibility:   float = 0.0
    evidence_feasibility: float = 0.0
    fact_consistency:     float = 0.0
    risk_exposure:        float = 0.0     # inverted (high risk → lower final if aggressive)
    adversarial_strength: float = 0.0
    composite:            float = 0.0

    def to_dict(self) -> dict:
        return {
            "legal_plausibility":   round(self.legal_plausibility, 3),
            "evidence_feasibility": round(self.evidence_feasibility, 3),
            "fact_consistency":     round(self.fact_consistency, 3),
            "risk_exposure":        round(self.risk_exposure, 3),
            "adversarial_strength": round(self.adversarial_strength, 3),
            "composite":            round(self.composite, 3),
        }


# ═════════════════════════════════════════════════════════════════
# Weights (sum = 1.0)
# ═════════════════════════════════════════════════════════════════

_WEIGHTS = {
    "legal_plausibility":   0.30,
    "evidence_feasibility": 0.25,
    "fact_consistency":     0.25,
    "risk_exposure":        0.10,
    "adversarial_strength": 0.10,
}


# ═════════════════════════════════════════════════════════════════
# Per-dimension scoring
# ═════════════════════════════════════════════════════════════════

def _score_legal_plausibility(h: Hypothesis, classifier_score: float) -> float:
    """How well does the domain/theory match known law?"""
    base = h.plausibility_initial
    # Primary-expected hypothesis benefits from classifier confidence
    if h.hypothesis_type == HypothesisType.PRIMARY_EXPECTED:
        base = max(base, classifier_score)
    # Aggressive / edge-case hypotheses start lower
    if h.hypothesis_type in (HypothesisType.AGGRESSIVE,
                              HypothesisType.WORST_CASE_EXPOSURE,
                              HypothesisType.EDGE_CASE):
        base *= 0.85
    # Issue graph presence bumps plausibility
    if h.issue_graph and h.issue_graph.nodes:
        base = min(1.0, base + 0.10)
    return min(1.0, max(0.0, base))


def _score_evidence_feasibility(h: Hypothesis) -> float:
    """Can the needed evidence plausibly be gathered?"""
    if h.strong_evidence_possible:
        return 0.85
    if h.weak_evidence_only:
        return 0.50
    if h.high_risk_missing_evidence:
        return 0.25
    return 0.50


def _score_fact_consistency(h: Hypothesis, facts: list[str]) -> float:
    """Do the stated facts align with the hypothesis's theory?"""
    if not facts:
        return 0.50   # neutral when no facts
    # Count supporting vs contradicting matches
    joined = " ".join(facts)
    supporting = sum(1 for f in h.supporting_facts if f and f in joined)
    contradicting = sum(1 for f in h.contradicting_facts if f and f in joined)
    # Contradiction_risk from evidence simulation counts too
    base = 0.60 - (0.40 * h.contradiction_risk)
    if supporting:
        base = min(1.0, base + 0.10 * supporting)
    if contradicting:
        base = max(0.0, base - 0.15 * contradicting)
    return base


def _score_risk_exposure(h: Hypothesis) -> float:
    """Higher risk = lower score for non-aggressive hypotheses.
    For AGGRESSIVE / WORST_CASE, the risk is a feature, not a penalty —
    they represent the exposure we MUST consider."""
    risk_map = {
        "low":       0.85,
        "medium":    0.60,
        "high":      0.40,
        "critical":  0.25,
    }
    base = risk_map.get(h.legal_risk_level, 0.50)
    # Aggressive/worst-case hypotheses get their risk inverted — they exist
    # PRECISELY to flag exposure, so high-risk with clear theory = useful
    if h.hypothesis_type in (HypothesisType.AGGRESSIVE,
                              HypothesisType.WORST_CASE_EXPOSURE):
        base = 1.0 - base + 0.20   # invert + bonus
        base = min(1.0, max(0.0, base))
    return base


def _score_adversarial_strength(h: Hypothesis) -> float:
    """How hard is this hypothesis to knock down?
    Inversely proportional to contradiction_risk + missing evidence risk."""
    base = 0.70
    base -= 0.40 * h.contradiction_risk
    if h.high_risk_missing_evidence:
        base -= 0.20
    if h.strong_evidence_possible:
        base += 0.15
    return min(1.0, max(0.0, base))


def score_hypothesis(h: Hypothesis,
                       classifier_score: float = 0.5,
                       facts: Optional[list[str]] = None) -> ScoreBreakdown:
    """Score ONE hypothesis across all 5 dimensions."""
    facts = facts or []
    s = ScoreBreakdown()
    s.legal_plausibility   = _score_legal_plausibility(h, classifier_score)
    s.evidence_feasibility = _score_evidence_feasibility(h)
    s.fact_consistency     = _score_fact_consistency(h, facts)
    s.risk_exposure        = _score_risk_exposure(h)
    s.adversarial_strength = _score_adversarial_strength(h)
    s.composite = (
        _WEIGHTS["legal_plausibility"]   * s.legal_plausibility
      + _WEIGHTS["evidence_feasibility"] * s.evidence_feasibility
      + _WEIGHTS["fact_consistency"]     * s.fact_consistency
      + _WEIGHTS["risk_exposure"]        * s.risk_exposure
      + _WEIGHTS["adversarial_strength"] * s.adversarial_strength
    )
    return s


def score_hypotheses(hypotheses: list[Hypothesis],
                       classifier_score: float = 0.5,
                       facts: Optional[list[str]] = None,
                       ) -> list[tuple[Hypothesis, ScoreBreakdown]]:
    """Score every hypothesis. Returns (hyp, score) pairs — UNSORTED."""
    facts = facts or []
    return [(h, score_hypothesis(h, classifier_score, facts))
             for h in hypotheses]
