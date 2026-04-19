# -*- coding: utf-8 -*-
"""
Tiered Reasoner — adaptive courtroom intelligence WITHOUT a parallel orchestrator.

Receives an EvidenceSet + sufficiency + binding from FailClosedPipeline
and returns a TieredOutput that carries:
  - tier-appropriate decisive evidence findings
  - tier-appropriate opponent model
  - tier-appropriate conditional outcome framing
  - per-stage timings
  - rendered Arabic enrichment text

This module is INVOKED FROM fail_closed_pipeline post-G8 governor. It
does NOT bypass any gate. It only enriches the answer with intelligence
appropriate to query complexity.

Tier 0 → returns empty enrichment (fast path).
Tier 1 → decisive findings only.
Tier 2 → decisive findings + opponent model + framing.
Tier 3 → all of the above with deeper budgets.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from core.courtroom.complexity_gate import (
    ComplexityTier, ComplexityVerdict, classify_complexity,
)
from core.courtroom.decisive_evidence import (
    DecisiveEvidenceDetector, DecisiveFinding,
)
from core.courtroom.opponent_model import (
    OpponentModel, build_opponent_model,
)
from core.courtroom.outcome_framing import (
    OutcomeFraming, build_conditional_framing,
)
from core.courtroom.domain_packs import get_domain_pack, DomainPack
from core.courtroom.hot_cache import get_hot_cache

from core.evidence.contract import EvidenceSet
from core.knowledge.contract import SufficiencyLevel
from core.knowledge.domain_binder import BindingResult


@dataclass
class TieredOutput:
    tier:                  ComplexityTier
    complexity:            ComplexityVerdict
    decisive_findings:     list[DecisiveFinding] = field(default_factory=list)
    opponent_model:        Optional[OpponentModel] = None
    outcome_framing:       Optional[OutcomeFraming] = None
    domain_pack_used:      Optional[str] = None
    early_exit:            bool = False
    enrichment_text:       str = ""
    stage_timings_ms:      dict = field(default_factory=dict)
    cache_hits:            int = 0

    def to_trace(self) -> dict:
        return {
            "tier":               self.tier.value,
            "complexity":         self.complexity.to_dict(),
            "decisive_count":     len(self.decisive_findings),
            "decisive_top":       [d.to_public() for d in self.decisive_findings[:3]],
            "opponent_model":     (self.opponent_model.to_public()
                                     if self.opponent_model else None),
            "outcome_framing":    (self.outcome_framing.to_public()
                                     if self.outcome_framing else None),
            "domain_pack":        self.domain_pack_used,
            "early_exit":         self.early_exit,
            "stage_timings_ms":   self.stage_timings_ms,
            "cache_hits":         self.cache_hits,
        }


class TieredReasoner:
    def __init__(self):
        self._decisive = DecisiveEvidenceDetector()
        self._cache = get_hot_cache()

    def reason(
        self,
        query:        str,
        evidence_set: Optional[EvidenceSet],
        sufficiency:  SufficiencyLevel,
        domain_value: str,
        binding:      Optional[BindingResult] = None,
        issue_keywords: Optional[list[str]] = None,
    ) -> TieredOutput:
        timings: dict[str, float] = {}
        cache_hits = 0

        # ── Stage 1: Complexity classification (cached) ──
        t0 = time.perf_counter()
        cached = self._cache.get("complexity", query)
        if cached is not None:
            complexity = cached
            cache_hits += 1
        else:
            complexity = classify_complexity(query)
            self._cache.put("complexity", query, complexity)
        timings["complexity_ms"] = round((time.perf_counter() - t0) * 1000, 3)

        out = TieredOutput(tier=complexity.tier, complexity=complexity)
        out.cache_hits = cache_hits
        out.stage_timings_ms = timings

        budget = complexity.tier.reasoning_budget()

        # ── HARD GATE: courtroom only runs when explicitly active for tier ──
        # T0 + T1 → no courtroom enrichment at all (fast default).
        # T2 + T3 → full courtroom intelligence.
        if not budget.get("courtroom_active", False):
            out.early_exit = True
            return out

        # ── Stage 2: Decisive evidence detection (Tier 1+) ──
        if budget["decisive_detect"] and evidence_set:
            t0 = time.perf_counter()
            findings = self._decisive.detect(
                evidence_set, issue_keywords,
                top_k=budget["max_evidence"],
            )
            out.decisive_findings = findings
            timings["decisive_ms"] = round((time.perf_counter() - t0) * 1000, 3)

        # ── Stage 3: Opponent model (Tier 2+) ──
        if budget["opponent_model"] and domain_value:
            t0 = time.perf_counter()
            cache_key = domain_value
            cached_om = self._cache.get("opponent_model", cache_key)
            if cached_om is not None:
                opponent = cached_om
                cache_hits += 1
            else:
                opponent = build_opponent_model(domain_value, binding)
                if opponent is not None:
                    self._cache.put("opponent_model", cache_key, opponent)
            out.opponent_model = opponent
            timings["opponent_ms"] = round((time.perf_counter() - t0) * 1000, 3)

        # ── Stage 4: Conditional outcome framing (Tier 2+) ──
        if budget["outcome_framing"]:
            t0 = time.perf_counter()
            weak_spots = (out.opponent_model.weak_spots_to_attack
                           if out.opponent_model else [])
            framing = build_conditional_framing(
                evidence_set=evidence_set,
                sufficiency=sufficiency,
                decisive=out.decisive_findings,
                opponent_weak_spots=weak_spots,
            )
            out.outcome_framing = framing
            timings["framing_ms"] = round((time.perf_counter() - t0) * 1000, 3)

        # ── Stage 5: Domain pack lookup (informational) ──
        pack = get_domain_pack(domain_value)
        if pack:
            out.domain_pack_used = pack.domain

        # ── Stage 6: Render Arabic enrichment ──
        out.enrichment_text = self._render(out, pack)

        out.stage_timings_ms = timings
        out.cache_hits = cache_hits
        return out

    def _render(self, out: TieredOutput, pack: Optional[DomainPack]) -> str:
        """Compose user-facing Arabic enrichment from the tier output.

        Concise. No internal scaffolding. No raw scores.
        """
        parts: list[str] = []

        if out.tier == ComplexityTier.HARD_FAST_PATH:
            return ""

        # Decisive evidence (if any decisive)
        decisive_only = [d for d in out.decisive_findings if d.is_decisive]
        if decisive_only:
            parts.append("**أدلة حاسمة في الموقف:**")
            for d in decisive_only[:3]:
                parts.append(f"• {d.record.public_citation()}")

        # Opponent model
        if out.opponent_model:
            parts.append("")
            parts.append(out.opponent_model.render_arabic())

        # Outcome framing
        if out.outcome_framing:
            parts.append("")
            parts.append(out.outcome_framing.render_arabic())

        # Domain-pack burden hints (Tier 2+ only)
        if (pack and out.tier in (ComplexityTier.ADVERSARIAL,
                                    ComplexityTier.COURTROOM)
                and pack.common_burdens):
            parts.append("")
            parts.append("**عبء الإثبات في هذا النوع من القضايا:**")
            for b in pack.common_burdens[:3]:
                parts.append(f"• {b}")

        return "\n".join(parts).strip()


_reasoner: Optional[TieredReasoner] = None


def get_tiered_reasoner() -> TieredReasoner:
    global _reasoner
    if _reasoner is None:
        _reasoner = TieredReasoner()
    return _reasoner
