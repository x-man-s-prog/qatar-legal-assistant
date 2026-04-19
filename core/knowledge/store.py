# -*- coding: utf-8 -*-
"""
KnowledgeStore — in-memory multi-indexed store for KnowledgeRecords.

Indexes (all O(1) lookup):
  - by canonical_source_id     (list of records for a law)
  - by article (canonical, num) (single record or list)
  - by domain                   (list)
  - by issue_tag                (list)
  - by source_type              (list)
  - by authority_rank bucket    (list)

The store owns the deduplication / duplicate_group_id assignment.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

from core.knowledge.contract import (
    KnowledgeRecord, KnowledgeSourceType, AdmissibilityStatus,
)
from core.evidence.contract import AuthorityRank

log = logging.getLogger("knowledge_store")


class KnowledgeStore:
    def __init__(self):
        self._records: list[KnowledgeRecord] = []
        # indexes
        self._by_canonical:     dict[str, list[int]] = defaultdict(list)
        self._by_article:       dict[tuple[str, int], list[int]] = defaultdict(list)
        self._by_domain:        dict[str, list[int]] = defaultdict(list)
        self._by_issue_tag:     dict[str, list[int]] = defaultdict(list)
        self._by_source_type:   dict[str, list[int]] = defaultdict(list)
        self._by_fingerprint:   dict[str, int] = {}      # dedup
        self._duplicates:       int = 0

    # ── ingestion ──

    def add(self, rec: KnowledgeRecord) -> bool:
        """Add a record. Returns True if added, False if duplicate."""
        # Dedup by fingerprint
        if rec.source_fingerprint and rec.source_fingerprint in self._by_fingerprint:
            original_idx = self._by_fingerprint[rec.source_fingerprint]
            original = self._records[original_idx]
            # Mark the new one as duplicate (don't store)
            rec.duplicate_group_id = original.knowledge_id
            self._duplicates += 1
            return False

        idx = len(self._records)
        self._records.append(rec)
        if rec.source_fingerprint:
            self._by_fingerprint[rec.source_fingerprint] = idx

        # Multi-index
        if rec.canonical_source_id:
            self._by_canonical[rec.canonical_source_id].append(idx)
        if rec.canonical_source_id and rec.article_number is not None:
            self._by_article[(rec.canonical_source_id, rec.article_number)].append(idx)
        if rec.domain:
            self._by_domain[rec.domain].append(idx)
        for tag in rec.issue_tags:
            self._by_issue_tag[tag].append(idx)
        if rec.source_type:
            self._by_source_type[rec.source_type.value].append(idx)

        return True

    # ── queries ──

    def count(self) -> int:
        return len(self._records)

    def runtime_eligible_count(self) -> int:
        return sum(1 for r in self._records if r.is_runtime_eligible())

    def duplicates_count(self) -> int:
        return self._duplicates

    def all(self) -> list[KnowledgeRecord]:
        return list(self._records)

    def by_canonical(self, canonical_id: str) -> list[KnowledgeRecord]:
        idxs = self._by_canonical.get(canonical_id, [])
        return [self._records[i] for i in idxs]

    def by_article(self, canonical_id: str, article: int) -> list[KnowledgeRecord]:
        idxs = self._by_article.get((canonical_id, article), [])
        return [self._records[i] for i in idxs]

    def by_domain(self, domain: str, runtime_eligible_only: bool = True) -> list[KnowledgeRecord]:
        idxs = self._by_domain.get(domain, [])
        recs = [self._records[i] for i in idxs]
        if runtime_eligible_only:
            recs = [r for r in recs if r.is_runtime_eligible()]
        return recs

    def by_issue_tag(self, tag: str) -> list[KnowledgeRecord]:
        idxs = self._by_issue_tag.get(tag, [])
        return [self._records[i] for i in idxs]

    def by_source_type(self, st: KnowledgeSourceType,
                        runtime_eligible_only: bool = True) -> list[KnowledgeRecord]:
        idxs = self._by_source_type.get(st.value, [])
        recs = [self._records[i] for i in idxs]
        if runtime_eligible_only:
            recs = [r for r in recs if r.is_runtime_eligible()]
        return recs

    def by_domain_and_source_types(self, domain: str,
                                      source_types: list[KnowledgeSourceType],
                                      ) -> list[KnowledgeRecord]:
        """Common retrieval query: domain + any of the source types."""
        allowed = {st.value for st in source_types}
        recs = self.by_domain(domain, runtime_eligible_only=True)
        return [r for r in recs if r.source_type.value in allowed]

    def coverage(self) -> dict:
        """Self-report coverage across multiple axes."""
        per_domain = {d: len(idxs) for d, idxs in self._by_domain.items()}
        per_source = {s: len(idxs) for s, idxs in self._by_source_type.items()}
        per_canonical = {c: len(idxs) for c, idxs in self._by_canonical.items()}
        # Authority bucket
        per_authority: dict[int, int] = defaultdict(int)
        for r in self._records:
            if r.is_runtime_eligible():
                per_authority[int(r.authority_rank)] += 1
        return {
            "total_records":          len(self._records),
            "runtime_eligible_count": self.runtime_eligible_count(),
            "duplicates_dropped":     self._duplicates,
            "per_domain":             per_domain,
            "per_source_type":        per_source,
            "per_canonical":          per_canonical,
            "per_authority_rank":     dict(per_authority),
            "distinct_canonical_laws": len(self._by_canonical),
            "distinct_issue_tags":     len(self._by_issue_tag),
        }

    def reset(self) -> None:
        self._records.clear()
        self._by_canonical.clear()
        self._by_article.clear()
        self._by_domain.clear()
        self._by_issue_tag.clear()
        self._by_source_type.clear()
        self._by_fingerprint.clear()
        self._duplicates = 0


_store: Optional[KnowledgeStore] = None


def get_store() -> KnowledgeStore:
    global _store
    if _store is None:
        _store = KnowledgeStore()
    return _store
