# -*- coding: utf-8 -*-
"""
Domain → Issue Pipeline rebuild.

Public API:
    from core.domain_pipeline import (
        IssueGraph, IssueNode, build_issue_graph,
        EvidenceLink, bind_evidence_to_issues,
        TemplateFirewall, scan_for_contamination,
        SelfValidator, validate_output,
    )
"""
from core.domain_pipeline.issue_graph import (
    IssueNode, IssueGraph, build_issue_graph,
)
from core.domain_pipeline.evidence_linker import (
    EvidenceLink, IssueBoundEvidenceSet, bind_evidence_to_issues,
)
from core.domain_pipeline.template_firewall import (
    TemplateFirewall, scan_for_contamination, ContaminationReport,
    get_firewall,
)
from core.domain_pipeline.self_validator import (
    SelfValidator, ValidationReport, validate_output,
)

__all__ = [
    "IssueNode", "IssueGraph", "build_issue_graph",
    "EvidenceLink", "IssueBoundEvidenceSet", "bind_evidence_to_issues",
    "TemplateFirewall", "scan_for_contamination", "ContaminationReport",
    "get_firewall",
    "SelfValidator", "ValidationReport", "validate_output",
]
