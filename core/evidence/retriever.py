# -*- coding: utf-8 -*-
"""
Multi-stage Evidence Retriever.
================================

Five deterministic stages — none optional, all logged for observability.

  Stage A — Eligibility filter:  decide which corpora can be touched.
  Stage B — Candidate retrieval: pull candidates within eligible corpora.
  Stage C — Relevance adjudication: 10-dim scoring with hard rejections.
  Stage D — Canonical verification: statute citations must match registry.
  Stage E — Selection:             dedup, sort, cap.

Data sources (in priority order):
  1. scripts/verified_articles.json   — manually curated (highest trust)
  2. scripts/principles_index.json    — extracted judicial principles
  3. DB `chunks` table                — only when pool is available AND
                                        after strict filtering

If a source is unreachable (e.g. DB not available in tests), it's skipped
and recorded in the trace — NEVER silently absent.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from core.evidence.contract import (
    EvidenceRecord, EvidenceSet, SourceType, VerificationStatus,
)
from core.evidence.normalizer import get_normalizer
from core.evidence.adjudicator import get_adjudicator, RelevanceVerdict
from core.evidence.canonical_expanded import get_canonical_registry
from core.legal_gates import (
    LegalDomain, FactPattern, ClassificationResult,
)

log = logging.getLogger("evidence_retriever")


# ═════════════════════════════════════════════════════════════════
# Data file paths
# ═════════════════════════════════════════════════════════════════

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_VERIFIED_ARTICLES = _PROJECT_ROOT / "scripts" / "verified_articles.json"
_PRINCIPLES_INDEX  = _PROJECT_ROOT / "scripts" / "principles_index.json"


# ═════════════════════════════════════════════════════════════════
# Static data loaders — loaded ONCE at module import
# ═════════════════════════════════════════════════════════════════

def _safe_load_json(path: Path) -> dict:
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        log.warning("evidence_retriever: failed to load %s: %s", path.name, e)
    return {}


class _KnowledgeStoreCorpus:
    """Adapter: exposes the global KnowledgeStore as an EvidenceRecord feed.

    Replaces the old _StaticCorpus which loaded only verified_articles.json
    and principles_index.json. The KnowledgeStore now owns the full corpus:
    verified articles + principles + court rulings + ministerial decisions
    + (when DB available) normalized chunks.

    Every runtime-eligible KnowledgeRecord is surfaced here as an
    EvidenceRecord via `to_evidence_record()`, so the retriever's
    downstream stages (adjudication + verification + selection) remain
    unchanged.
    """

    def __init__(self):
        # Trigger ingestion once; idempotent.
        from core.knowledge.ingestion import ingest_all
        from core.knowledge.store import get_store
        from core.knowledge.contract import KnowledgeSourceType

        ingest_all(force=False)
        self._store = get_store()
        self._KST = KnowledgeSourceType
        log.info("[evidence_corpus_v2] knowledge store loaded: "
                 "total=%d eligible=%d",
                 self._store.count(), self._store.runtime_eligible_count())

    def candidates_for_domain(self, domain_value: str) -> list[EvidenceRecord]:
        """All runtime-eligible EvidenceRecords for a domain, across all source types."""
        records = self._store.by_domain(domain_value, runtime_eligible_only=True)
        out: list[EvidenceRecord] = []
        for kr in records:
            ev = kr.to_evidence_record()
            # Stamp relevance_score=0 — adjudicator will set it
            out.append(ev)
        return out

    def principle_candidates_matching(self, query: str,
                                         issue_keywords: list[str]) -> list[EvidenceRecord]:
        """Principles + rulings that match query text or issue_keywords.

        Returns EvidenceRecords (support_only most of the time).
        """
        kw_lower = [kw.lower() for kw in issue_keywords if kw]
        query_lower = (query or "").lower()
        out: list[EvidenceRecord] = []

        for st in (self._KST.LEGAL_PRINCIPLE, self._KST.COURT_RULING):
            for kr in self._store.by_source_type(st, runtime_eligible_only=True):
                text_lower = (kr.clean_text or kr.text_body or "").lower()
                topic = (kr.principle_topic or "").lower()
                tag_hit = any(kw in topic for kw in kw_lower) \
                           or topic in query_lower
                kw_hit = any(kw in text_lower for kw in kw_lower) if kw_lower else False
                if tag_hit or kw_hit:
                    out.append(kr.to_evidence_record())
        return out


_STATIC: Optional[_KnowledgeStoreCorpus] = None


def _get_static() -> _KnowledgeStoreCorpus:
    global _STATIC
    if _STATIC is None:
        _STATIC = _KnowledgeStoreCorpus()
    return _STATIC


# ═════════════════════════════════════════════════════════════════
# Retriever
# ═════════════════════════════════════════════════════════════════

class EvidenceRetriever:
    """Five-stage retrieval. No stage is skipped."""

    # Max candidates per stage (prevents runaway searches)
    MAX_CANDIDATES     = 60
    MAX_AFTER_RELEVANCE = 20
    MAX_FINAL          = 8

    def __init__(self):
        self._registry = get_canonical_registry()
        self._adjudicator = get_adjudicator()

    def retrieve(self, query: str,
                  classification: ClassificationResult,
                  fact_pattern: FactPattern,
                  issue_keywords: Optional[list[str]] = None,
                  requested_remedies: Optional[list[str]] = None,
                  party_roles: Optional[list[str]] = None,
                  ) -> EvidenceSet:
        """Run the full 5-stage retrieval."""
        es = EvidenceSet()
        es.query_domain = classification.primary_domain.value
        es.query_issues = list(issue_keywords or [])

        # ── Stage A: Eligibility ──
        allowed_corpora = self._registry.domain_corpora(classification.primary_domain)
        es.retrieval_trace["stage_a_allowed_corpora"] = list(allowed_corpora)

        if classification.primary_domain == LegalDomain.UNKNOWN:
            log.info("[retriever] domain=UNKNOWN — no eligible corpora")
            es.retrieval_trace["stage_a_result"] = "domain_unknown_no_corpora"
            return es

        # ── Stage B: Candidate retrieval (from KnowledgeStore) ──
        corpus = _get_static()

        # B.1: domain-locked retrieval (statutes + rulings + principles bound to domain)
        domain_value = classification.primary_domain.value
        domain_candidates = corpus.candidates_for_domain(domain_value)

        # B.2: cross-domain principles/rulings matching issue keywords
        cross_candidates = corpus.principle_candidates_matching(query, issue_keywords or [])

        # Merge without duplication (by fingerprint)
        seen_fp: set[str] = set()
        candidates: list[EvidenceRecord] = []
        for rec in domain_candidates + cross_candidates:
            fp = rec.source_fingerprint or rec.snippet_text[:60]
            if fp in seen_fp:
                continue
            seen_fp.add(fp)
            # For statutes, enforce canonical-corpus locking
            if rec.source_type == SourceType.STATUTE \
               and rec.canonical_id \
               and rec.canonical_id not in allowed_corpora:
                continue
            candidates.append(rec)

        from core.knowledge.store import get_store as _k_store
        es.stage_a_candidates = _k_store().runtime_eligible_count()
        es.stage_b_retrieved = len(candidates)
        es.retrieval_trace["stage_b_from_statute"] = sum(
            1 for c in candidates if c.source_type == SourceType.STATUTE)
        es.retrieval_trace["stage_b_from_principles"] = sum(
            1 for c in candidates if c.source_type == SourceType.LEGAL_PRINCIPLE)
        es.retrieval_trace["stage_b_from_case_law"] = sum(
            1 for c in candidates if c.source_type == SourceType.CASE_LAW)
        # DB-origin breakdown — how many DB-derived records reached this stage
        es.retrieval_trace["stage_b_from_db"] = sum(
            1 for c in candidates
            if (c.full_document_id and str(c.full_document_id).isdigit())
            or (hasattr(c, "chunk_id") and c.chunk_id is not None)
        )

        # Cap to prevent runaway
        candidates = candidates[:self.MAX_CANDIDATES]

        # ── Stage C: Relevance adjudication ──
        surviving: list[tuple[EvidenceRecord, RelevanceVerdict]] = []
        rejection_reasons: list[str] = []
        for rec in candidates:
            verdict = self._adjudicator.adjudicate(
                record             = rec,
                issue_domain       = classification.primary_domain,
                fact_pattern       = fact_pattern,
                issue_keywords     = issue_keywords,
                requested_remedies = requested_remedies,
                party_roles        = party_roles,
            )
            if verdict.is_relevant:
                rec.relevance_score = verdict.composite_score
                rec.score_breakdown = verdict.breakdown
                surviving.append((rec, verdict))
            else:
                rejection_reasons.append(
                    verdict.hard_reject_reason
                    or f"below_threshold:{verdict.composite_score:.2f}"
                )

        es.stage_c_adjudicated = len(surviving)
        es.rejected_count += len(candidates) - len(surviving)
        # Store only first 10 reasons to avoid trace bloat
        es.rejection_reasons.extend(rejection_reasons[:10])

        # Cap for verification stage
        surviving.sort(key=lambda t: t[1].composite_score, reverse=True)
        surviving = surviving[:self.MAX_AFTER_RELEVANCE]

        # ── Stage D: Canonical verification ──
        verified_records: list[EvidenceRecord] = []
        for rec, _verdict in surviving:
            if rec.source_type == SourceType.STATUTE:
                # Statutes need canonical verification
                v = self._registry.verify(
                    rec.law_title, rec.article_number,
                    classification.primary_domain,
                )
                if v.confidence == "verified":
                    rec.verification_status = VerificationStatus.VERIFIED
                    verified_records.append(rec)
                elif v.confidence == "partial" and rec.article_number is None:
                    rec.verification_status = VerificationStatus.PARTIAL
                    verified_records.append(rec)
                else:
                    es.rejection_reasons.append(
                        f"canonical_reject:{v.block_reason}"[:120]
                    )
                    es.rejected_count += 1
            else:
                # Non-statute sources skip canonical verification
                verified_records.append(rec)

        es.stage_d_verified = len(verified_records)

        # ── Stage E: Selection (dedup + cap + sort) ──
        # Dedup by (canonical_id, article_number) for statutes,
        # by source_fingerprint otherwise
        seen: set[str] = set()
        final: list[EvidenceRecord] = []
        for rec in verified_records:
            if rec.source_type == SourceType.STATUTE:
                key = f"{rec.canonical_id}|{rec.article_number}"
            else:
                key = rec.source_fingerprint or rec.snippet_text[:80]
            if key in seen:
                continue
            seen.add(key)
            final.append(rec)

        # Sort: authority first, then relevance
        final.sort(key=lambda r: (int(r.authority_rank), r.relevance_score),
                    reverse=True)

        es.records = final[:self.MAX_FINAL]
        es.stage_e_selected = len(es.records)

        log.info(
            "[retriever] domain=%s candidates=%d→adjudicated=%d→verified=%d→final=%d",
            classification.primary_domain.value,
            es.stage_a_candidates, es.stage_c_adjudicated,
            es.stage_d_verified, es.stage_e_selected,
        )

        return es


# ═════════════════════════════════════════════════════════════════
# Convenience / singleton
# ═════════════════════════════════════════════════════════════════

_retriever: Optional[EvidenceRetriever] = None


def get_retriever() -> EvidenceRetriever:
    global _retriever
    if _retriever is None:
        _retriever = EvidenceRetriever()
    return _retriever


def retrieve_evidence(query: str,
                       classification: ClassificationResult,
                       fact_pattern: FactPattern,
                       issue_keywords: Optional[list[str]] = None,
                       requested_remedies: Optional[list[str]] = None,
                       party_roles: Optional[list[str]] = None,
                       ) -> EvidenceSet:
    """Top-level convenience: run the retriever singleton."""
    return get_retriever().retrieve(
        query, classification, fact_pattern,
        issue_keywords, requested_remedies, party_roles,
    )
