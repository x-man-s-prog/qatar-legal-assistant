# -*- coding: utf-8 -*-
"""
Context Lock Matrix.

Once survivors are selected, we lock down what's allowed:
  - allowed_domains      : only these canonical_ids survive evidence retrieval
  - forbidden_domains    : hard-reject
  - allowed_issue_types  : only these IssueKind values participate
  - forbidden_templates  : template-firewall patterns that must be suppressed
  - evidence_constraints : specific statute/article constraints

The matrix is enforced by downstream retrieval + synthesis.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.mlre.hypothesis import Hypothesis
from core.mlre.scoring import ScoreBreakdown
from core.mlre.adversarial import AdversarialAttack
from core.evidence.canonical_expanded import get_canonical_registry
from core.legal_gates import LegalDomain


@dataclass
class ContextLockMatrix:
    allowed_domains:          set[str] = field(default_factory=set)
    forbidden_domains:        set[str] = field(default_factory=set)
    allowed_canonical_ids:    set[str] = field(default_factory=set)
    allowed_issue_types:      set[str] = field(default_factory=set)
    forbidden_templates:      list[str] = field(default_factory=list)
    evidence_constraints:     list[str] = field(default_factory=list)

    def is_evidence_allowed(self, canonical_id: str) -> bool:
        if canonical_id in self.allowed_canonical_ids:
            return True
        return False

    def is_domain_allowed(self, domain: str) -> bool:
        if domain in self.forbidden_domains:
            return False
        return (not self.allowed_domains) or (domain in self.allowed_domains)

    def to_dict(self) -> dict:
        return {
            "allowed_domains":        sorted(self.allowed_domains),
            "forbidden_domains":      sorted(self.forbidden_domains),
            "allowed_canonical_ids":  sorted(self.allowed_canonical_ids),
            "allowed_issue_types":    sorted(self.allowed_issue_types),
            "forbidden_templates":    self.forbidden_templates,
            "evidence_constraints":   self.evidence_constraints,
        }


# ═════════════════════════════════════════════════════════════════
# Forbidden templates per domain (used to suppress drift)
# ═════════════════════════════════════════════════════════════════

_TEMPLATE_SUPPRESSION: dict[str, list[str]] = {
    # When primary domain is NOT this, these templates are forbidden
    "criminal":    ["محاضر اجتماعات الشركاء", "سند دين موقّع"],
    "civil":       ["محاضر اجتماعات الشركاء", "المادة 203 من قانون العقوبات"],
    "commercial":  ["إنذار إخلاء", "المادة 203 من قانون العقوبات"],
    "banking":     ["محاضر اجتماعات الشركاء", "إنذار إخلاء"],
    "family":      ["سند دين موقّع", "محاضر اجتماعات الشركاء"],
    "inheritance": ["محاضر اجتماعات الشركاء", "المادة 203 من قانون العقوبات"],
    "employment":  ["سند دين موقّع", "إنذار إخلاء"],
    "rental":      ["محاضر اجتماعات الشركاء", "المادة 203 من قانون العقوبات"],
}


def build_context_lock(
    survivors: list[tuple[Hypothesis, ScoreBreakdown, AdversarialAttack]],
) -> ContextLockMatrix:
    """Build a strict lock matrix from surviving hypotheses.

    Rules:
      - allowed_domains = union of surviving domains
      - forbidden_domains = other LegalDomain values NOT in survivors
      - allowed_canonical_ids = union of domain_corpora for allowed domains
      - forbidden_templates = aggregated suppression per primary_domain
    """
    matrix = ContextLockMatrix()
    if not survivors:
        return matrix

    registry = get_canonical_registry()
    for (h, _, _) in survivors:
        matrix.allowed_domains.add(h.domain)
        # Map string → enum for canonical lookup
        try:
            dom_enum = LegalDomain(h.domain)
            matrix.allowed_canonical_ids |= registry.domain_corpora(dom_enum)
        except ValueError:
            pass
        # Collect issue types from the graph
        if h.issue_graph:
            for node in h.issue_graph.nodes.values():
                matrix.allowed_issue_types.add(node.kind.value)

    # Forbidden = all other domains
    all_domains = {d.value for d in LegalDomain if d != LegalDomain.UNKNOWN}
    matrix.forbidden_domains = all_domains - matrix.allowed_domains

    # Forbidden templates from the primary survivor's perspective
    primary_domain = survivors[0][0].domain if survivors else ""
    matrix.forbidden_templates = list(
        _TEMPLATE_SUPPRESSION.get(primary_domain, [])
    )

    # Evidence constraints — textual hints
    for (h, _, _) in survivors:
        if h.issue_graph and h.issue_graph.primary_issue:
            prim = h.issue_graph.nodes.get(h.issue_graph.primary_issue)
            if prim and prim.required_proof:
                for p in prim.required_proof:
                    matrix.evidence_constraints.append(
                        f"{h.domain}:{p}"
                    )

    return matrix
