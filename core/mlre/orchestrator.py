# -*- coding: utf-8 -*-
"""
MLRE Orchestrator — one entry, full multi-hypothesis reasoning.

Flow:
  generate_hypotheses → score → attack → select_survivors
  → build_context_lock → synthesize_reality → return structured output

Also supports a drafting-v2 mode: given the survivors, decide between:
  - Single Path Draft
  - Conditional Draft
  - Dual Strategy Draft
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from core.mlre.hypothesis import (
    Hypothesis, HypothesisType, HypothesisBundle, generate_hypotheses,
)
from core.mlre.scoring import ScoreBreakdown, score_hypotheses
from core.mlre.adversarial import (
    AdversarialAttack, attack_hypotheses, select_survivors,
)
from core.mlre.context_lock import ContextLockMatrix, build_context_lock
from core.mlre.synthesis import LegalReality, synthesize_reality


class DraftingV2Mode(str, Enum):
    SINGLE_PATH    = "single_path"        # one strong survivor
    CONDITIONAL    = "conditional"        # two survivors — write with "إذا..." fallback
    DUAL_STRATEGY  = "dual_strategy"      # two memos: primary + alternative


@dataclass
class MLREResult:
    bundle:              HypothesisBundle = field(default_factory=lambda: HypothesisBundle(query=""))
    scored:              list = field(default_factory=list)   # [(h, score), ...]
    attacked:            list = field(default_factory=list)   # [(h, score, attack), ...]
    survivors:           list = field(default_factory=list)   # subset of attacked
    context_lock:        Optional[ContextLockMatrix] = None
    reality:             Optional[LegalReality] = None
    drafting_v2_mode:    Optional[str] = None

    def to_trace(self) -> dict:
        return {
            "hypothesis_count":     len(self.bundle.hypotheses),
            "surviving_count":      len(self.survivors),
            "rejected_count":       len(self.attacked) - len(self.survivors),
            "hypothesis_types":     [h.hypothesis_type.value
                                     for h in self.bundle.hypotheses],
            "surviving_domains":    [s[0].domain for s in self.survivors],
            "scoring_breakdown":    [
                {"type": h.hypothesis_type.value,
                 "domain": h.domain,
                 "composite": round(sc.composite, 3),
                 "survives": atk.survives,
                 "collapse_score": round(atk.collapse_score, 3)}
                for (h, sc, atk) in self.attacked
            ],
            "reality":              self.reality.to_dict() if self.reality else {},
            "context_lock":         self.context_lock.to_dict() if self.context_lock else {},
            "drafting_v2_mode":     self.drafting_v2_mode,
        }


def _decide_drafting_v2_mode(
    survivors: list[tuple[Hypothesis, ScoreBreakdown, AdversarialAttack]],
) -> DraftingV2Mode:
    """Decide which drafting mode fits the survivor distribution."""
    if len(survivors) <= 1:
        return DraftingV2Mode.SINGLE_PATH
    top_score = survivors[0][1].composite
    second_score = survivors[1][1].composite
    gap = top_score - second_score
    # If the top path clearly dominates → single
    if gap >= 0.25:
        return DraftingV2Mode.SINGLE_PATH
    # If two comparable paths in DIFFERENT domains → dual strategy
    if survivors[0][0].domain != survivors[1][0].domain and gap < 0.10:
        return DraftingV2Mode.DUAL_STRATEGY
    # Otherwise → conditional (one memo with "إذا..." fallback)
    return DraftingV2Mode.CONDITIONAL


def run_mlre(
    query: str,
    facts: Optional[list[str]] = None,
    max_hypotheses: int = 8,
    max_survivors: int = 3,
) -> MLREResult:
    """Top-level entry. Runs the whole MLRE pipeline."""
    facts = facts or []
    result = MLREResult()

    # 1. Generate hypotheses (6-8)
    result.bundle = generate_hypotheses(
        query, facts=facts, max_hypotheses=max_hypotheses
    )

    if not result.bundle.hypotheses:
        # No hypotheses — build an empty reality
        result.reality = synthesize_reality(survivors=[])
        return result

    # 2. Score all 5 dimensions
    # Derive a classifier_score estimate from the primary hypothesis
    primary = next(
        (h for h in result.bundle.hypotheses
         if h.hypothesis_type == HypothesisType.PRIMARY_EXPECTED),
        result.bundle.hypotheses[0],
    )
    classifier_score = primary.plausibility_initial
    result.scored = score_hypotheses(
        result.bundle.hypotheses, classifier_score, facts
    )

    # 3. Adversarial attack
    result.attacked = attack_hypotheses(result.scored)

    # 4. Survival filter (top 2-3 DISTINCT)
    result.survivors = select_survivors(
        result.attacked, max_survivors=max_survivors
    )

    # 5. Context lock
    result.context_lock = build_context_lock(result.survivors)

    # 6. Synthesize structured reality
    result.reality = synthesize_reality(
        result.survivors, all_attacked=result.attacked,
        context_lock=result.context_lock,
    )

    # 7. Drafting v2 mode decision
    result.drafting_v2_mode = _decide_drafting_v2_mode(result.survivors).value

    return result
