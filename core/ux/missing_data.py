# -*- coding: utf-8 -*-
"""
Missing Data Engine — gap analysis per issue.

Takes: IssueGraph + bound evidence + session facts + conversation state.
Returns: structured report of missing facts / evidence / critical gaps.
No LLM. Deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from core.domain_pipeline.issue_graph import IssueGraph, IssueNode, IssueKind
from core.domain_pipeline.evidence_linker import IssueBoundEvidenceSet


class GapLevel(str, Enum):
    HIGH    = "high"      # blocks ruling and/or drafting
    MEDIUM  = "medium"    # weakens analysis but can proceed with assumptions
    LOW     = "low"       # nice-to-have


@dataclass
class IssueGap:
    issue_id:           str
    issue_question:     str
    issue_kind:         str              # from IssueKind
    missing_facts:      list[str] = field(default_factory=list)
    missing_evidence:   list[str] = field(default_factory=list)
    criticality:        GapLevel = GapLevel.MEDIUM
    has_any_evidence:   bool = False

    def to_dict(self) -> dict:
        return {
            "issue_id":          self.issue_id,
            "issue_question":    self.issue_question,
            "issue_kind":        self.issue_kind,
            "missing_facts":     self.missing_facts,
            "missing_evidence":  self.missing_evidence,
            "criticality":       self.criticality.value,
            "has_any_evidence":  self.has_any_evidence,
        }


@dataclass
class MissingDataReport:
    gaps:                list[IssueGap] = field(default_factory=list)
    critical_count:      int = 0
    medium_count:        int = 0
    low_count:           int = 0
    blocks_ruling:       bool = False
    blocks_drafting:     bool = False
    summary_reasons:     list[str] = field(default_factory=list)

    def high_gaps(self) -> list[IssueGap]:
        return [g for g in self.gaps if g.criticality == GapLevel.HIGH]

    def medium_gaps(self) -> list[IssueGap]:
        return [g for g in self.gaps if g.criticality == GapLevel.MEDIUM]

    def top_n_by_criticality(self, n: int = 3) -> list[IssueGap]:
        order = {GapLevel.HIGH: 0, GapLevel.MEDIUM: 1, GapLevel.LOW: 2}
        return sorted(self.gaps, key=lambda g: order[g.criticality])[:n]

    def to_dict(self) -> dict:
        return {
            "total_gaps":       len(self.gaps),
            "critical_count":   self.critical_count,
            "medium_count":     self.medium_count,
            "low_count":        self.low_count,
            "blocks_ruling":    self.blocks_ruling,
            "blocks_drafting":  self.blocks_drafting,
            "summary_reasons":  self.summary_reasons,
            "gaps":             [g.to_dict() for g in self.gaps[:10]],
        }


# ═════════════════════════════════════════════════════════════════
# Criticality rules — which issue kinds are HIGH / MEDIUM / LOW
# ═════════════════════════════════════════════════════════════════

def _criticality_for_kind(kind: str, has_any_evidence: bool) -> GapLevel:
    """Kind + evidence presence → gap criticality."""
    if kind == IssueKind.PRIMARY.value:
        return GapLevel.HIGH if not has_any_evidence else GapLevel.MEDIUM
    if kind == IssueKind.THRESHOLD.value:
        return GapLevel.HIGH   # threshold MUST be answered first
    if kind == IssueKind.PROOF.value:
        return GapLevel.HIGH if not has_any_evidence else GapLevel.MEDIUM
    if kind == IssueKind.DEFENSE.value:
        return GapLevel.MEDIUM
    if kind == IssueKind.REMEDY.value:
        return GapLevel.LOW
    if kind == IssueKind.PROCEDURAL.value:
        return GapLevel.LOW
    return GapLevel.MEDIUM


# ═════════════════════════════════════════════════════════════════
# Fact-keyword overlap — detects if session facts address an issue
# ═════════════════════════════════════════════════════════════════

def _facts_cover_issue(issue: IssueNode, facts: list[str]) -> tuple[bool, list[str]]:
    """Returns (covered, missing_proof_elements)."""
    if not issue.required_proof:
        return (True, [])
    joined_facts = " ".join(facts).lower() if facts else ""
    missing: list[str] = []
    covered_count = 0
    for proof_element in issue.required_proof:
        # A proof element is considered covered if ANY of its 2-3 keywords
        # appear in the concatenated facts
        keywords = proof_element.split()[:3]
        if joined_facts and any(kw in joined_facts for kw in keywords if kw):
            covered_count += 1
        else:
            missing.append(proof_element)
    # Count as covered if at least 50% of proof elements are hit
    covered = (covered_count / max(len(issue.required_proof), 1)) >= 0.5
    return (covered, missing)


# ═════════════════════════════════════════════════════════════════
# Main analyzer
# ═════════════════════════════════════════════════════════════════

def analyze_gaps(
    graph: Optional[IssueGraph],
    bound_evidence: Optional[IssueBoundEvidenceSet],
    facts: Optional[list[str]] = None,
) -> MissingDataReport:
    """Produce a structured gap report for the current case state."""
    report = MissingDataReport()
    facts = facts or []

    if graph is None or not graph.nodes:
        report.summary_reasons.append("no_issue_graph")
        report.blocks_ruling = True
        report.blocks_drafting = True
        return report

    for iid, issue in graph.nodes.items():
        # Evidence coverage for this issue
        links = bound_evidence.links_for(iid) if bound_evidence else []
        has_evidence = len(links) > 0

        # Fact coverage for this issue
        facts_covered, missing_proof = _facts_cover_issue(issue, facts)

        if has_evidence and facts_covered:
            continue   # no gap

        gap = IssueGap(
            issue_id=iid,
            issue_question=issue.question,
            issue_kind=issue.kind.value,
            has_any_evidence=has_evidence,
        )
        if not has_evidence:
            gap.missing_evidence.append(f"سند قانوني مرتبط بالمسألة")
        if not facts_covered:
            gap.missing_facts.extend(missing_proof)

        gap.criticality = _criticality_for_kind(issue.kind.value, has_evidence)
        report.gaps.append(gap)

    # Tallies
    for g in report.gaps:
        if g.criticality == GapLevel.HIGH:
            report.critical_count += 1
        elif g.criticality == GapLevel.MEDIUM:
            report.medium_count += 1
        else:
            report.low_count += 1

    # Block rules
    if report.critical_count > 0:
        report.blocks_drafting = True
        report.summary_reasons.append(
            f"critical_gaps:{report.critical_count}"
        )
    if report.critical_count >= 2:
        report.blocks_ruling = True

    return report
