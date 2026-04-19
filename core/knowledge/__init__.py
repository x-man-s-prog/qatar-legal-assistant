# -*- coding: utf-8 -*-
"""
Knowledge Runtime — converts raw corpus into runtime-live legal knowledge.

Public API:
    from core.knowledge import (
        KnowledgeRecord, KnowledgeStore, QuarantineRecord,
        SourceType, SufficiencyLevel,
        get_store, get_binder, get_ingestor,
        ingest_all, coverage_stats,
    )
"""
from core.knowledge.contract import (
    KnowledgeRecord, QuarantineRecord, SufficiencyLevel,
    KnowledgeSourceType, AdmissibilityStatus,
)
from core.knowledge.store import KnowledgeStore, get_store
from core.knowledge.domain_binder import DomainBinder, get_binder
from core.knowledge.ingestion import (
    KnowledgeIngestor, get_ingestor, ingest_all, coverage_stats,
)
from core.knowledge.quarantine import QuarantineStore, get_quarantine

__all__ = [
    "KnowledgeRecord", "QuarantineRecord", "SufficiencyLevel",
    "KnowledgeSourceType", "AdmissibilityStatus",
    "KnowledgeStore", "get_store",
    "DomainBinder", "get_binder",
    "KnowledgeIngestor", "get_ingestor", "ingest_all", "coverage_stats",
    "QuarantineStore", "get_quarantine",
]
