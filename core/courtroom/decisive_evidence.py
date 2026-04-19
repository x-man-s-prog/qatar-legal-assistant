# -*- coding: utf-8 -*-
"""
Decisive Evidence Detector — flags evidence that materially shifts outcome.

Operates ONLY on EvidenceRecords already verified by canonical registry.
Does NOT call LLM. Does NOT bypass adjudicator.

Decisiveness score = weighted sum of:
  - authority_rank (statute > case_law > principle)
  - directness (article matches issue exactly vs general principle)
  - independence (only chunk supporting this claim → high decisiveness)
  - issue_centrality (matches the central issue, not ancillary)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.evidence.contract import (
    EvidenceRecord, SourceType, AuthorityRank, EvidenceSet,
)


@dataclass
class DecisiveFinding:
    record:           EvidenceRecord
    decisiveness:     float
    rationale:        str
    is_decisive:      bool

    def to_public(self) -> dict:
        return {
            "citation":     self.record.public_citation(),
            "decisiveness": round(self.decisiveness, 3),
            "is_decisive":  self.is_decisive,
            "why":          self.rationale,
        }


def score_decisiveness(rec: EvidenceRecord, evidence_set: EvidenceSet,
                        issue_keywords: Optional[list[str]] = None) -> DecisiveFinding:
    """Score one record against the whole set."""
    issue_keywords = issue_keywords or []
    score = 0.0
    why_parts: list[str] = []

    # Authority weight
    auth = int(rec.authority_rank) / 100.0
    score += 0.30 * auth
    if auth >= 0.90:
        why_parts.append("authority_top")

    # Direct article statute > principle
    if rec.source_type == SourceType.STATUTE and rec.article_number is not None:
        score += 0.25
        why_parts.append("direct_article")

    # Independence — is this the only record for this canonical id?
    same_canonical = [r for r in evidence_set.records
                       if r.canonical_id and r.canonical_id == rec.canonical_id]
    if len(same_canonical) == 1:
        score += 0.20
        why_parts.append("only_authority")

    # Issue centrality
    chunk_text = rec.article_text or rec.snippet_text
    if issue_keywords and chunk_text:
        hits = sum(1 for kw in issue_keywords if kw and kw in chunk_text)
        if hits >= 2:
            score += 0.15
            why_parts.append("multi_issue_match")
        elif hits == 1:
            score += 0.08

    # Top relevance score from adjudicator
    if rec.relevance_score >= 0.75:
        score += 0.10
        why_parts.append("top_relevance")

    is_decisive = score >= 0.55
    return DecisiveFinding(
        record=rec, decisiveness=min(1.0, score),
        rationale="+".join(why_parts) if why_parts else "weak_signal",
        is_decisive=is_decisive,
    )


class DecisiveEvidenceDetector:
    """Top-N decisive findings for an EvidenceSet."""

    def detect(self, evidence_set: EvidenceSet,
                issue_keywords: Optional[list[str]] = None,
                top_k: int = 3) -> list[DecisiveFinding]:
        if not evidence_set or not evidence_set.records:
            return []
        findings = [
            score_decisiveness(r, evidence_set, issue_keywords)
            for r in evidence_set.records
        ]
        findings.sort(key=lambda f: f.decisiveness, reverse=True)
        return findings[:top_k]
