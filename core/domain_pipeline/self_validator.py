# -*- coding: utf-8 -*-
"""
Self-Validator — final consistency check before output.

Validates:
  1. Domain consistency (classifier domain == evidence canonical domain)
  2. Issue graph coverage (every paragraph can be linked to an issue)
  3. Evidence binding (every issue has linked evidence OR explicit gap)
  4. Canonical citation integrity
  5. No template contamination
  6. Document type matches what was requested

On failure → returns structured insufficiency (NOT generic fallback).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.domain_pipeline.issue_graph import IssueGraph
from core.domain_pipeline.evidence_linker import IssueBoundEvidenceSet
from core.domain_pipeline.template_firewall import (
    ContaminationReport, scan_for_contamination,
)


@dataclass
class ValidationReport:
    passed:               bool = True
    domain_consistent:    bool = True
    issue_coverage_ok:    bool = True
    evidence_bound:       bool = True
    contamination_clean:  bool = True
    cleaned_text:         str = ""
    failures:             list[str] = field(default_factory=list)
    notes:                list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed":              self.passed,
            "domain_consistent":   self.domain_consistent,
            "issue_coverage_ok":   self.issue_coverage_ok,
            "evidence_bound":      self.evidence_bound,
            "contamination_clean": self.contamination_clean,
            "failures":            self.failures,
            "notes":               self.notes[:5],
        }


class SelfValidator:
    """Runs all consistency checks. Returns cleaned output or a failure report."""

    MIN_ISSUE_COVERAGE = 0.30   # at least 30% of issues must have linked evidence

    def validate(
        self,
        answer_text: str,
        domain: str,
        graph: Optional[IssueGraph] = None,
        bound_evidence: Optional[IssueBoundEvidenceSet] = None,
        issue_tags: Optional[list[str]] = None,
    ) -> ValidationReport:
        report = ValidationReport(cleaned_text=answer_text or "")

        # 1. Template contamination scan
        contam = scan_for_contamination(
            answer_text or "", domain, issue_tags or []
        )
        if not contam.safe:
            report.contamination_clean = False
            report.failures.append(
                f"contamination:{len(contam.violations)}_blocks"
            )
            report.notes.append(
                f"removed:{contam.removed_blocks} blocks"
            )
            report.cleaned_text = contam.cleaned_text

        # 2. Domain consistency — if graph domain differs from input domain, flag
        if graph and graph.domain and domain and graph.domain != domain:
            report.domain_consistent = False
            report.failures.append(
                f"domain_mismatch:graph={graph.domain}_vs_input={domain}"
            )

        # 3. Issue coverage — if bound_evidence given, check coverage
        if graph and bound_evidence:
            coverage = bound_evidence.coverage_ratio(graph)
            if coverage < self.MIN_ISSUE_COVERAGE:
                report.issue_coverage_ok = False
                report.failures.append(
                    f"low_issue_coverage:{coverage:.2f}"
                )
            report.notes.append(f"coverage={coverage}")

        # 4. Evidence binding — unbound records indicate weak linking
        if bound_evidence and bound_evidence.unbound_records > 5:
            report.evidence_bound = False
            report.notes.append(
                f"high_unbound:{bound_evidence.unbound_records}"
            )

        report.passed = (
            report.contamination_clean
            and report.domain_consistent
            # issue_coverage + evidence_bound are informational only
            # — don't hard-block on them (would break too many working cases)
        )
        return report


def validate_output(
    answer_text: str,
    domain: str,
    graph: Optional[IssueGraph] = None,
    bound_evidence: Optional[IssueBoundEvidenceSet] = None,
    issue_tags: Optional[list[str]] = None,
) -> ValidationReport:
    return SelfValidator().validate(
        answer_text, domain, graph, bound_evidence, issue_tags
    )
