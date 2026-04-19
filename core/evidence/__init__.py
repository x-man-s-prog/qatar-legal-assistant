# -*- coding: utf-8 -*-
"""
Evidence Layer — professional legal evidence retrieval for production.

Public API:
    from core.evidence import (
        EvidenceRecord, EvidenceSet, SourceType, VerificationStatus,
        get_retriever, get_adjudicator, get_canonical_registry,
        retrieve_evidence,
    )
"""
from core.evidence.contract import (
    EvidenceRecord, EvidenceSet, SourceType, VerificationStatus,
    AuthorityRank, TextQuality,
)
from core.evidence.retriever import (
    EvidenceRetriever, get_retriever, retrieve_evidence,
)
from core.evidence.adjudicator import (
    RelevanceAdjudicatorV2, get_adjudicator, RelevanceVerdict,
)
from core.evidence.canonical_expanded import (
    get_canonical_registry, ExpandedCanonicalRegistry,
)

__all__ = [
    "EvidenceRecord", "EvidenceSet", "SourceType", "VerificationStatus",
    "AuthorityRank", "TextQuality",
    "EvidenceRetriever", "get_retriever", "retrieve_evidence",
    "RelevanceAdjudicatorV2", "get_adjudicator", "RelevanceVerdict",
    "get_canonical_registry", "ExpandedCanonicalRegistry",
]
