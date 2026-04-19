# -*- coding: utf-8 -*-
"""
Drafting Liberation Protocol — Mode Enum + Signal Aggregator.

Replaces the binary draftable/not-draftable gate with a five-way choice:

    FULL_DRAFT           — complete, ship-quality memo
    CONDITIONAL_DRAFT    — primary + clearly-framed fallback
    DUAL_STRATEGY_DRAFT  — two parallel paths, both defensible
    SKELETON_DRAFT       — structured legal outline; explicit gaps
    NOT_DRAFTABLE_YET    — last resort: no legal structure exists

NOT_DRAFTABLE_YET is returned ONLY when there is no usable domain, no
usable issue graph, AND no MLRE survivors. In any other case the system
MUST emit a useful legal document (one of the four draftable modes).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DraftingMode(str, Enum):
    FULL_DRAFT           = "full_draft"
    CONDITIONAL_DRAFT    = "conditional_draft"
    DUAL_STRATEGY_DRAFT  = "dual_strategy_draft"
    SKELETON_DRAFT       = "skeleton_draft"
    NOT_DRAFTABLE_YET    = "not_draftable_yet"


# ═════════════════════════════════════════════════════════════════
# Input signals
# ═════════════════════════════════════════════════════════════════

@dataclass
class DraftingSignals:
    """Everything the selector needs to pick a mode.

    All fields are optional — missing values are treated as "no signal"
    and default the selector toward the more conservative mode in the
    surrounding band (never toward NOT_DRAFTABLE when any structure
    exists).
    """
    # MLRE signal
    survivor_count:      int = 0
    primary_composite:   float = 0.0      # top survivor's composite
    secondary_composite: float = 0.0      # second survivor's composite
    has_pivots:          bool = False
    has_decisive_tests:  bool = False
    reality_answerable:  bool = True

    # Issue graph signal
    domain_resolved:     bool = False
    issue_count:         int = 0
    has_primary_issue:   bool = False

    # Evidence signal
    bound_links:         int = 0
    coverage_ratio:      float = 0.0      # covered issues / total
    direct_citations:    int = 0

    # Facts / UX signal
    fact_count:          int = 0
    minimum_facts:       int = 1          # doc-type dependent

    # Raw gaps (reason codes) that otherwise caused NOT_DRAFTABLE
    raw_gaps:            list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "survivor_count":      self.survivor_count,
            "primary_composite":   round(self.primary_composite, 3),
            "secondary_composite": round(self.secondary_composite, 3),
            "has_pivots":          self.has_pivots,
            "has_decisive_tests":  self.has_decisive_tests,
            "domain_resolved":     self.domain_resolved,
            "issue_count":         self.issue_count,
            "has_primary_issue":   self.has_primary_issue,
            "bound_links":         self.bound_links,
            "coverage_ratio":      round(self.coverage_ratio, 3),
            "direct_citations":    self.direct_citations,
            "fact_count":          self.fact_count,
            "minimum_facts":       self.minimum_facts,
            "raw_gaps":            self.raw_gaps[:5],
        }


@dataclass
class DraftingDecision:
    mode:               DraftingMode
    reason:             str = ""
    rule_fired:         str = ""       # internal trace tag
    raw_gaps:           list[str] = field(default_factory=list)
    # A short list of user-safe gap explanations, derived from raw_gaps
    user_safe_gaps:     list[str] = field(default_factory=list)
    # Whether the memo MAY include a secondary/fallback path
    include_secondary:  bool = False
    # Whether MQE+PASL should run over the produced memo text
    run_quality:        bool = True
    # Signals snapshot for trace
    signals:            Optional[DraftingSignals] = None

    def to_dict(self) -> dict:
        return {
            "mode":           self.mode.value,
            "reason":         self.reason,
            "rule_fired":     self.rule_fired,
            "raw_gaps":       self.raw_gaps[:5],
            "user_safe_gaps": self.user_safe_gaps[:5],
            "include_secondary": self.include_secondary,
            "run_quality":    self.run_quality,
            "signals":        self.signals.to_dict() if self.signals else {},
        }


# ═════════════════════════════════════════════════════════════════
# Thresholds (tunable via constants, not config)
# ═════════════════════════════════════════════════════════════════

STRONG_COMPOSITE     = 0.55
GOOD_COMPOSITE       = 0.40
MIN_COMPOSITE        = 0.28

STRONG_COVERAGE      = 0.50
GOOD_COVERAGE        = 0.30
MIN_COVERAGE         = 0.15

STRONG_DIRECT        = 2     # direct citations
MIN_DIRECT           = 1

DUAL_GAP_THRESHOLD   = 0.10  # primary - secondary composite spread


# ═════════════════════════════════════════════════════════════════
# Mode selector
# ═════════════════════════════════════════════════════════════════

def _legacy_gate_would_block(s: DraftingSignals) -> bool:
    """Mirror of the OLD drafting gate logic.

    Returns True when the pre-DLP gate would have refused the draft.
    DLP uses this as a 'boundary' — cases the old gate would have
    allowed must go to FULL/CONDITIONAL/DUAL, never SKELETON.
    """
    if not s.domain_resolved:
        return True
    if s.issue_count <= 0 or not s.has_primary_issue:
        return True
    if s.bound_links <= 0:
        return True
    if s.fact_count < s.minimum_facts:
        return True
    # The old gate used low_issue_coverage < 0.30 as a soft flag (becomes
    # DRAFTABLE_WITH_ASSUMPTIONS, not a block) — so we do NOT gate on it.
    return False


def select_mode(s: DraftingSignals) -> DraftingDecision:
    """Choose a DraftingMode from the signals.

    Order (fail-open toward drafting):
      1. Hard NOT_DRAFTABLE only when NO legal structure at all.
      2. If 2+ survivors ~equally strong                → DUAL_STRATEGY
      3. If 2 survivors, primary > secondary + pivots   → CONDITIONAL
      4. If the OLD gate would have allowed drafting    → FULL
         (never downgraded to SKELETON — DLP cannot be stricter
          than the old gate on admitted cases).
      5. Otherwise (some structure exists)              → SKELETON
    """
    # ── 1) Hard NOT_DRAFTABLE only when everything collapsed ──
    no_domain = not s.domain_resolved
    no_graph  = s.issue_count <= 0 or not s.has_primary_issue
    no_mlre   = s.survivor_count <= 0 or s.primary_composite < MIN_COMPOSITE
    no_evidence = s.bound_links <= 0 and s.coverage_ratio <= 0
    reality_dead = (not s.reality_answerable) and no_mlre

    if no_domain and no_graph and no_mlre and no_evidence:
        return DraftingDecision(
            mode=DraftingMode.NOT_DRAFTABLE_YET,
            reason="لا يوجد هيكل قانوني قابل للبناء حالياً.",
            rule_fired="no_structure_at_all",
            raw_gaps=list(s.raw_gaps),
            signals=s,
        )
    if reality_dead and no_graph and no_evidence:
        return DraftingDecision(
            mode=DraftingMode.NOT_DRAFTABLE_YET,
            reason="تعذّر حسم المسار القانوني من الوقائع والأدلة المتاحة.",
            rule_fired="mlre_all_paths_collapsed",
            raw_gaps=list(s.raw_gaps),
            signals=s,
        )

    # ── 2) DUAL_STRATEGY — two strong parallel paths ──
    if (s.survivor_count >= 2
            and s.secondary_composite >= GOOD_COMPOSITE
            and (s.primary_composite - s.secondary_composite) < DUAL_GAP_THRESHOLD
            and s.bound_links >= 1):
        return DraftingDecision(
            mode=DraftingMode.DUAL_STRATEGY_DRAFT,
            reason="يوجد مساران قانونيان متوازيان قابلان للدفاع.",
            rule_fired="dual_strong_parallel",
            include_secondary=True,
            signals=s,
        )

    # ── 3) CONDITIONAL — primary strong + secondary viable + pivots ──
    if (s.survivor_count >= 2
            and s.primary_composite >= GOOD_COMPOSITE
            and s.secondary_composite >= MIN_COMPOSITE
            and (s.has_pivots or s.has_decisive_tests)):
        return DraftingDecision(
            mode=DraftingMode.CONDITIONAL_DRAFT,
            reason="المسار الأساسي قائم مع وجود تكييف بديل معتبر عند الاقتضاء.",
            rule_fired="primary_plus_conditional_fallback",
            include_secondary=True,
            signals=s,
        )

    # ── 4) FULL — anything the old gate would have allowed ──
    # If the old gate would NOT have blocked, we MUST produce a full memo
    # (not a skeleton) — DLP never regresses on admitted cases.
    if not _legacy_gate_would_block(s):
        return DraftingDecision(
            mode=DraftingMode.FULL_DRAFT,
            reason="تتوفر العناصر الكافية لصياغة مذكرة كاملة.",
            rule_fired="legacy_admitted_full",
            include_secondary=False,
            signals=s,
        )

    # ── 5) SKELETON — some structure exists; legacy gate would have blocked ──
    has_any_path     = s.survivor_count >= 1 or s.has_primary_issue
    has_any_evidence = s.bound_links >= 1 or s.coverage_ratio > 0
    if has_any_path or has_any_evidence or s.issue_count > 0 or s.domain_resolved:
        return DraftingDecision(
            mode=DraftingMode.SKELETON_DRAFT,
            reason="الهيكل القانوني متاح مبدئياً، وتوجد نواقص لا تمنع الصياغة المسؤولة.",
            rule_fired="skeleton_structure_available",
            include_secondary=s.survivor_count >= 2,
            raw_gaps=list(s.raw_gaps),
            signals=s,
        )

    # ── 6) Truly nothing workable ──
    return DraftingDecision(
        mode=DraftingMode.NOT_DRAFTABLE_YET,
        reason="لم يتوفر هيكل قانوني أو دليل يكفي لبناء الصياغة.",
        rule_fired="exhausted",
        raw_gaps=list(s.raw_gaps),
        signals=s,
    )


# ═════════════════════════════════════════════════════════════════
# Signal extraction helper — from (MLRE, graph, bound, facts, doc_type)
# ═════════════════════════════════════════════════════════════════

_DOC_MINIMUM_FACTS = {
    # doc_type_value : minimum facts
    "claim_brief":       3,
    "defense_memo":      1,
    "reply_memo":        1,
    "explanatory_memo":  1,
    "petition_memo":     1,
    "pleading_points":   0,
    "defense_checklist": 0,
    "case_summary":      1,
}


def build_signals(
    mlre=None,
    graph=None,
    bound=None,
    facts: Optional[list[str]] = None,
    doc_type_value: str = "defense_memo",
    raw_gaps: Optional[list[str]] = None,
) -> DraftingSignals:
    """Extract a `DraftingSignals` from the upstream artifacts."""
    s = DraftingSignals(raw_gaps=list(raw_gaps or []))

    # MLRE block
    if mlre is not None:
        survivors = list(getattr(mlre, "survivors", []) or [])
        s.survivor_count = len(survivors)
        composites: list[float] = []
        for triple in survivors:
            if len(triple) >= 2:
                try:
                    composites.append(float(triple[1].composite))
                except Exception:
                    pass
        composites.sort(reverse=True)
        s.primary_composite   = composites[0] if composites else 0.0
        s.secondary_composite = composites[1] if len(composites) > 1 else 0.0

        reality = getattr(mlre, "reality", None)
        if reality is not None:
            s.has_pivots          = bool(
                getattr(reality, "pivot_conditions", None))
            s.has_decisive_tests  = bool(
                getattr(reality, "decisive_tests", None))
            s.reality_answerable  = bool(
                getattr(reality, "can_be_answered", True))

    # Issue-graph block
    if graph is not None:
        s.domain_resolved   = bool(getattr(graph, "domain", ""))
        s.issue_count       = len(getattr(graph, "nodes", {}) or {})
        s.has_primary_issue = bool(getattr(graph, "primary_issue", None))

    # Evidence block
    if bound is not None:
        links = list(getattr(bound, "links", []) or [])
        s.bound_links      = len(links)
        s.direct_citations = sum(
            1 for L in links if getattr(L, "evidence_role", "") == "direct"
        )
        try:
            s.coverage_ratio = float(bound.coverage_ratio(graph)) if graph else 0.0
        except Exception:
            s.coverage_ratio = 0.0

    # Facts
    cleaned_facts = [f for f in (facts or []) if f and f.strip()]
    s.fact_count     = len(cleaned_facts)
    s.minimum_facts  = _DOC_MINIMUM_FACTS.get(doc_type_value, 1)

    return s
