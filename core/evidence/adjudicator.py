# -*- coding: utf-8 -*-
"""
RelevanceAdjudicator v2 — the real relevance judge.
=====================================================

This replaces the minimal RelevanceAdjudicator in legal_gates.py for the
evidence layer. It scores across 10 dimensions with explicit weights and
hard-rejection rules.

Hard rejections (score forced to 0):
  - domain mismatch (chunk domain outside allowed corpora)
  - law_id mismatch (for statutes: canonical law not in expected_corpora)
  - text quality corrupted
  - article out of canonical range

Soft scoring (weighted):
   1. domain_match             0.20
   2. law_id_allowed           0.15
   3. issue_match              0.15
   4. fact_pattern_fit         0.10
   5. remedy_fit               0.08
   6. party_role_fit           0.07
   7. temporal_relevance       0.05
   8. authority_rank_bonus     0.10
   9. text_integrity           0.05
  10. citation_reliability     0.05

Threshold: composite >= 0.40 to pass (stricter per source_type).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.evidence.contract import (
    EvidenceRecord, SourceType, VerificationStatus, AuthorityRank, TextQuality,
)
from core.legal_gates import LegalDomain, FactPattern
from core.evidence.canonical_expanded import get_canonical_registry


# ═════════════════════════════════════════════════════════════════
# Thresholds per source type
# ═════════════════════════════════════════════════════════════════

_COMPOSITE_THRESHOLDS: dict[SourceType, float] = {
    SourceType.STATUTE:              0.50,   # statutes: strict
    SourceType.REGULATION:           0.45,
    SourceType.CASE_LAW:             0.40,
    SourceType.LEGAL_PRINCIPLE:      0.40,
    SourceType.OFFICIAL_EXPLANATION: 0.35,
    SourceType.STRUCTURED_TABLE:     0.30,
    SourceType.UNKNOWN:              0.60,   # unknown source → very strict
}


# ═════════════════════════════════════════════════════════════════
# Verdict
# ═════════════════════════════════════════════════════════════════

@dataclass
class RelevanceVerdict:
    is_relevant: bool = False
    composite_score: float = 0.0
    breakdown: dict = field(default_factory=dict)
    hard_reject_reason: str = ""
    threshold_used: float = 0.0
    source_type: str = ""

    def to_dict(self) -> dict:
        return {
            "is_relevant":        self.is_relevant,
            "composite_score":    round(self.composite_score, 3),
            "breakdown":          {k: round(v, 3) for k, v in self.breakdown.items()},
            "hard_reject_reason": self.hard_reject_reason,
            "threshold_used":     self.threshold_used,
            "source_type":        self.source_type,
        }


# ═════════════════════════════════════════════════════════════════
# The adjudicator
# ═════════════════════════════════════════════════════════════════

class RelevanceAdjudicatorV2:
    """Ten-dimensional weighted relevance judge with hard rejection rules."""

    WEIGHTS = {
        "domain_match":          0.20,
        "law_id_allowed":        0.15,
        "issue_match":           0.15,
        "fact_pattern_fit":      0.10,
        "remedy_fit":            0.08,
        "party_role_fit":        0.07,
        "temporal_relevance":    0.05,
        "authority_rank_bonus":  0.10,
        "text_integrity":        0.05,
        "citation_reliability":  0.05,
    }

    def __init__(self):
        self._registry = get_canonical_registry()

    def adjudicate(self, record: EvidenceRecord,
                    issue_domain: LegalDomain,
                    fact_pattern: FactPattern,
                    issue_keywords: Optional[list[str]] = None,
                    requested_remedies: Optional[list[str]] = None,
                    party_roles: Optional[list[str]] = None,
                    ) -> RelevanceVerdict:
        issue_keywords = issue_keywords or []
        requested_remedies = requested_remedies or []
        party_roles = party_roles or []

        verdict = RelevanceVerdict(source_type=record.source_type.value)
        breakdown: dict[str, float] = {}

        # ── Hard rejection: text quality corrupted ──
        if record.text_quality == TextQuality.CORRUPTED:
            verdict.hard_reject_reason = "text_quality_corrupted"
            return verdict

        # ── Hard rejection: article out of range (statute) ──
        if record.source_type == SourceType.STATUTE \
           and record.verification_status == VerificationStatus.UNVERIFIED:
            verdict.hard_reject_reason = "statute_unverified"
            return verdict

        chunk_text = record.article_text or record.snippet_text or ""

        # ── 1. Domain match ──
        allowed_ids = self._registry.domain_corpora(issue_domain)
        if issue_domain == LegalDomain.UNKNOWN:
            # Unknown domain → cannot enforce match — neutral
            breakdown["domain_match"] = 0.5
        elif record.source_type == SourceType.STATUTE:
            # For statutes: canonical_id must be in allowed corpora
            if record.canonical_id and record.canonical_id in allowed_ids:
                breakdown["domain_match"] = 1.0
            else:
                # Hard reject — wrong domain is disqualifying
                verdict.hard_reject_reason = \
                    f"domain_mismatch:canonical={record.canonical_id or 'none'}_vs_{issue_domain.value}"
                return verdict
        else:
            # Non-statute sources use the domain tag
            if record.domain and record.domain == issue_domain.value:
                breakdown["domain_match"] = 1.0
            elif not record.domain:
                breakdown["domain_match"] = 0.4
            else:
                breakdown["domain_match"] = 0.0

        # ── 2. Law ID allowed (only meaningful for statutes) ──
        if record.source_type == SourceType.STATUTE:
            breakdown["law_id_allowed"] = \
                1.0 if (record.canonical_id and record.canonical_id in allowed_ids) else 0.0
        else:
            breakdown["law_id_allowed"] = 0.6  # N/A for non-statutes → neutral

        # ── 3. Issue match ──
        if issue_keywords and chunk_text:
            hits = sum(1 for kw in issue_keywords if kw in chunk_text)
            # Also credit issue_tags on the record
            tag_hits = sum(1 for tag in record.issue_tags
                            for kw in issue_keywords if kw in tag)
            total = min(1.0, (hits + 0.5 * tag_hits) / max(len(issue_keywords), 1))
            breakdown["issue_match"] = total
        elif not issue_keywords:
            breakdown["issue_match"] = 0.5  # neutral
        else:
            breakdown["issue_match"] = 0.0

        # ── 4. Fact pattern fit ──
        if fact_pattern and fact_pattern.evidence_present:
            ev_hits = sum(1 for ev in fact_pattern.evidence_present
                           if isinstance(ev, str) and ev and ev in chunk_text)
            base = min(1.0, ev_hits / max(len(fact_pattern.evidence_present), 1))
            breakdown["fact_pattern_fit"] = max(base, 0.3)
        else:
            breakdown["fact_pattern_fit"] = 0.4

        # ── 5. Remedy fit ──
        if requested_remedies and chunk_text:
            rem_hits = sum(1 for r in requested_remedies if r and r in chunk_text)
            breakdown["remedy_fit"] = min(1.0, rem_hits / max(len(requested_remedies), 1))
        else:
            breakdown["remedy_fit"] = 0.5

        # ── 6. Party role fit ──
        if party_roles and chunk_text:
            role_hits = sum(1 for p in party_roles if p and p in chunk_text)
            breakdown["party_role_fit"] = min(1.0, role_hits / max(len(party_roles), 1) + 0.2)
        else:
            breakdown["party_role_fit"] = 0.5

        # ── 7. Temporal relevance (in-force matters) ──
        if record.in_force_status == "in_force":
            breakdown["temporal_relevance"] = 1.0
        elif record.in_force_status == "amended":
            breakdown["temporal_relevance"] = 0.7
        elif record.in_force_status == "repealed":
            breakdown["temporal_relevance"] = 0.0
        else:
            breakdown["temporal_relevance"] = 0.5

        # ── 8. Authority rank bonus ──
        breakdown["authority_rank_bonus"] = \
            min(1.0, int(record.authority_rank) / 100.0)

        # ── 9. Text integrity ──
        if record.text_quality == TextQuality.CLEAN:
            breakdown["text_integrity"] = 1.0
        elif record.text_quality == TextQuality.MINOR:
            breakdown["text_integrity"] = 0.8
        elif record.text_quality == TextQuality.NOISY:
            breakdown["text_integrity"] = 0.4
        else:
            breakdown["text_integrity"] = 0.0

        # ── 10. Citation reliability ──
        if record.source_type == SourceType.STATUTE:
            if record.verification_status == VerificationStatus.VERIFIED:
                breakdown["citation_reliability"] = 1.0
            elif record.verification_status == VerificationStatus.PARTIAL:
                breakdown["citation_reliability"] = 0.6
            else:
                breakdown["citation_reliability"] = 0.0
        elif record.source_type == SourceType.LEGAL_PRINCIPLE:
            breakdown["citation_reliability"] = 0.7
        else:
            breakdown["citation_reliability"] = 0.5

        # ── Composite ──
        composite = sum(breakdown[k] * self.WEIGHTS[k] for k in self.WEIGHTS)

        threshold = _COMPOSITE_THRESHOLDS.get(record.source_type, 0.40)

        verdict.composite_score = composite
        verdict.breakdown = breakdown
        verdict.threshold_used = threshold
        verdict.is_relevant = composite >= threshold

        if not verdict.is_relevant:
            verdict.hard_reject_reason = f"below_threshold:{composite:.2f}<{threshold}"

        return verdict


# ═════════════════════════════════════════════════════════════════
# Singleton
# ═════════════════════════════════════════════════════════════════

_adjudicator: Optional[RelevanceAdjudicatorV2] = None


def get_adjudicator() -> RelevanceAdjudicatorV2:
    global _adjudicator
    if _adjudicator is None:
        _adjudicator = RelevanceAdjudicatorV2()
    return _adjudicator
