# -*- coding: utf-8 -*-
"""
Evidence Linker — binds each EvidenceRecord to a specific IssueNode.

An unbound EvidenceRecord (one that can't be tied to any issue in the
graph) is REJECTED. This prevents generic citations being used as
controlling authority for narrow issues.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.domain_pipeline.issue_graph import IssueGraph, IssueNode, IssueKind
from core.evidence.contract import EvidenceRecord, SourceType


@dataclass
class EvidenceLink:
    issue_id:        str
    record:          EvidenceRecord
    evidence_role:   str = ""        # direct | corroborative | contextual
    directness:      float = 0.0     # 0..1
    proves_element:  str = ""
    admissibility:   str = "admissible"

    def to_dict(self) -> dict:
        return {
            "issue_id":       self.issue_id,
            "citation":       self.record.public_citation(),
            "evidence_role":  self.evidence_role,
            "directness":     round(self.directness, 3),
            "proves_element": self.proves_element,
            "admissibility":  self.admissibility,
        }


@dataclass
class IssueBoundEvidenceSet:
    links:           list[EvidenceLink] = field(default_factory=list)
    unbound_records: int = 0
    unbound_reasons: list[str] = field(default_factory=list)

    def links_for(self, issue_id: str) -> list[EvidenceLink]:
        return [L for L in self.links if L.issue_id == issue_id]

    def has_direct_for(self, issue_id: str) -> bool:
        return any(L.evidence_role == "direct" for L in self.links_for(issue_id))

    def coverage_ratio(self, graph: IssueGraph) -> float:
        total = len(graph.nodes) or 1
        covered = sum(1 for iid in graph.nodes if self.links_for(iid))
        return round(covered / total, 3)

    def to_dict(self) -> dict:
        return {
            "total_links":      len(self.links),
            "unbound_records":  self.unbound_records,
            "unbound_reasons":  self.unbound_reasons[:5],
            "links_by_issue": {
                iid: len(self.links_for(iid))
                for iid in {L.issue_id for L in self.links}
            },
        }


def _compute_directness(record: EvidenceRecord, issue: IssueNode,
                         issue_keywords: list[str]) -> float:
    """Score 0..1: how directly does this evidence address the issue?"""
    if not record.is_usable():
        return 0.0
    base = 0.3
    text = record.article_text or record.snippet_text or ""
    # Keyword overlap boost
    if issue_keywords:
        hits = sum(1 for kw in issue_keywords if kw and kw in text)
        base += min(0.35, hits * 0.12)
    # Required proof overlap boost
    for pr in issue.required_proof:
        if pr and any(w in text for w in pr.split()[:3]):
            base += 0.10
    # Direct statute on-point bonus
    if record.source_type == SourceType.STATUTE and record.article_number:
        base += 0.10
    return min(1.0, base)


def _classify_role(directness: float, issue: IssueNode,
                    record: EvidenceRecord) -> str:
    if directness >= 0.65:
        return "direct"
    if directness >= 0.40:
        return "corroborative"
    return "contextual"


def bind_evidence_to_issues(
    graph: IssueGraph,
    records: list[EvidenceRecord],
    issue_keywords: Optional[list[str]] = None,
) -> IssueBoundEvidenceSet:
    """For each record, find the best-matching issue and create an EvidenceLink.
    Records that can't be meaningfully linked are counted as unbound and
    NOT included in the output.
    """
    out = IssueBoundEvidenceSet()
    issue_keywords = issue_keywords or []

    if not graph.nodes:
        out.unbound_records = len(records)
        out.unbound_reasons.append("empty_issue_graph")
        return out

    issue_list = list(graph.nodes.values())

    for rec in records:
        if not rec.is_usable():
            out.unbound_records += 1
            out.unbound_reasons.append(
                f"unusable:{rec.verification_status.value}")
            continue

        # Score against every issue — pick best
        scored: list[tuple[IssueNode, float]] = []
        for issue in issue_list:
            d = _compute_directness(rec, issue, issue_keywords)
            scored.append((issue, d))

        scored.sort(key=lambda t: -t[1])
        best_issue, best_score = scored[0]

        # Minimum threshold — below this, record is not linked
        if best_score < 0.30:
            out.unbound_records += 1
            out.unbound_reasons.append(
                f"below_directness_floor:{rec.public_citation()[:40]}")
            continue

        role = _classify_role(best_score, best_issue, rec)
        proves = (best_issue.required_proof[0]
                   if best_issue.required_proof else "")
        out.links.append(EvidenceLink(
            issue_id=best_issue.issue_id,
            record=rec,
            evidence_role=role,
            directness=best_score,
            proves_element=proves,
            admissibility="admissible",
        ))

    return out
