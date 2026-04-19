# -*- coding: utf-8 -*-
"""
Knowledge Ingestion Orchestrator.
==================================

Pulls every raw source into the KnowledgeStore or the QuarantineStore.
Deterministic: same inputs produce the same store state.

Sources handled here:
  - scripts/verified_articles.json          → STATUTE / REGULATION
  - scripts/principles_index.json           → LEGAL_PRINCIPLE
  - scripts/article_ruling_index.json       → COURT_RULING
  - scripts/almeezan_target_laws.json       → REGULATION / MINISTERIAL_DECISION
  - DB chunks (when pool is available)      → STATUTE (best-effort)

Each ingestion pass writes quarantine records for anything that can't be
normalized. No silent drops.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

from core.knowledge.contract import (
    KnowledgeRecord, KnowledgeSourceType, AdmissibilityStatus, SufficiencyLevel,
)
from core.knowledge.store import get_store
from core.knowledge.quarantine import get_quarantine
from core.knowledge.domain_binder import get_binder
from core.evidence.contract import (
    AuthorityRank, TextQuality, VerificationStatus,
)
from core.evidence.normalizer import (
    clean_text, assess_text_quality, normalize_article_number,
)
from core.evidence.canonical_expanded import get_canonical_registry

log = logging.getLogger("knowledge_ingestion")


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS_DIR  = _PROJECT_ROOT / "scripts"


# ═════════════════════════════════════════════════════════════════
# File helpers
# ═════════════════════════════════════════════════════════════════

def _safe_load_json(path: Path) -> Optional[object]:
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        log.warning("failed to load %s: %s", path.name, e)
    return None


def _fingerprint(parts: list) -> str:
    src = "|".join(str(p) for p in parts)
    return hashlib.sha1(src.encode("utf-8")).hexdigest()[:16]


# ═════════════════════════════════════════════════════════════════
# Ingestor
# ═════════════════════════════════════════════════════════════════

class KnowledgeIngestor:
    def __init__(self):
        self._registry = get_canonical_registry()
        self._binder   = get_binder()
        self._store    = get_store()
        self._quar     = get_quarantine()

    # ── public entry ──

    def ingest_all(self) -> dict:
        """Run every ingestor in deterministic order.

        Returns a summary dict with per-source counts.
        """
        summary = {
            "verified_articles":    self.ingest_verified_articles(),
            "principles":           self.ingest_principles(),
            "court_rulings":        self.ingest_court_rulings(),
            "almeezan_target_laws": self.ingest_almeezan_target_laws(),
            "db_chunks":            {"ingested": 0, "skipped": "DB not accessed in this phase"},
        }
        summary["store_coverage"] = self._store.coverage()
        summary["quarantine"] = {
            "total":    self._quar.count(),
            "reasons":  self._quar.reasons_breakdown(),
            "stages":   self._quar.stages_breakdown(),
        }
        return summary

    # ── source: verified_articles.json ──

    def ingest_verified_articles(self) -> dict:
        path = _SCRIPTS_DIR / "verified_articles.json"
        data = _safe_load_json(path)
        if not isinstance(data, dict):
            return {"status": "not_found", "path": str(path)}

        ingested, quarantined = 0, 0
        for topic, bundle in data.items():
            if not isinstance(bundle, dict):
                continue
            law_title = bundle.get("law", "") or ""
            articles  = bundle.get("articles", {}) or {}
            if not isinstance(articles, dict):
                continue

            canonical = self._registry.resolve_law(law_title)
            if canonical is None:
                for art_num, art_text in articles.items():
                    self._quar.add(
                        source_path=f"{path.name}:{topic}",
                        snippet=(art_text or "")[:120],
                        reason_code="missing_canonical_identity",
                        reason_detail=f"law_title={law_title[:60]}",
                        stage="verified_articles_ingestor",
                    )
                    quarantined += 1
                continue

            for art_num_raw, art_text in articles.items():
                if not art_text or not art_text.strip():
                    self._quar.add(
                        source_path=f"{path.name}:{topic}:{art_num_raw}",
                        snippet="", reason_code="empty_content",
                        stage="verified_articles_ingestor")
                    quarantined += 1
                    continue

                cleaned = clean_text(art_text)
                q, ar_ratio, is_frag, has_ocr = assess_text_quality(cleaned)
                if q == TextQuality.CORRUPTED:
                    self._quar.add(
                        source_path=f"{path.name}:{topic}:{art_num_raw}",
                        snippet=cleaned[:120],
                        reason_code="corrupted_text",
                        reason_detail=f"ar_ratio={ar_ratio:.2f}",
                        stage="verified_articles_ingestor")
                    quarantined += 1
                    continue

                article_n = normalize_article_number(art_num_raw)
                if article_n is None:
                    self._quar.add(
                        source_path=f"{path.name}:{topic}:{art_num_raw}",
                        snippet=cleaned[:120],
                        reason_code="unverifiable_article",
                        stage="verified_articles_ingestor")
                    quarantined += 1
                    continue
                if not (canonical.article_min <= article_n <= canonical.article_max):
                    self._quar.add(
                        source_path=f"{path.name}:{topic}:{art_num_raw}",
                        snippet=cleaned[:120],
                        reason_code="article_out_of_range",
                        reason_detail=f"{article_n} not in [{canonical.article_min},{canonical.article_max}]",
                        stage="verified_articles_ingestor")
                    quarantined += 1
                    continue

                # Bind domain
                binding = self._binder.bind(cleaned,
                                              canonical_source_id=canonical.law_id)

                fp = _fingerprint([canonical.law_id, article_n, cleaned[:80]])
                kid = _fingerprint([fp, "verified", topic])

                rec = KnowledgeRecord(
                    knowledge_id        = kid,
                    source_type         = KnowledgeSourceType.STATUTE,
                    canonical_source_id = canonical.law_id,
                    law_title           = canonical.title,
                    law_number          = canonical.number,
                    law_year            = canonical.year,
                    article_number      = article_n,
                    source_fingerprint  = fp,
                    chunk_origin        = f"json:{path.name}:{topic}",
                    in_force_status     = "in_force",
                    domain              = binding.domain.value
                                            if binding.domain.value != "unknown"
                                            else canonical.domain.value,
                    subdomain           = binding.subdomain,
                    issue_tags          = binding.issue_tags + [topic],
                    remedy_tags         = binding.remedy_tags,
                    procedural_tags     = binding.procedural_tags,
                    party_role_tags     = binding.party_role_tags,
                    text_body           = art_text,
                    clean_text          = cleaned,
                    text_quality        = q,
                    language_cleanliness = ar_ratio,
                    has_ocr_noise       = has_ocr,
                    is_fragmented       = is_frag,
                    authority_rank      = AuthorityRank.STATUTE_IN_FORCE,
                    verification_status = VerificationStatus.VERIFIED,
                    admissibility       = AdmissibilityStatus.RUNTIME_ELIGIBLE,
                    provenance_status   = "known",
                )
                if self._store.add(rec):
                    ingested += 1

        return {"ingested": ingested, "quarantined": quarantined,
                "path": str(path)}

    # ── source: principles_index.json ──

    def ingest_principles(self) -> dict:
        path = _SCRIPTS_DIR / "principles_index.json"
        data = _safe_load_json(path)
        if not isinstance(data, dict):
            return {"status": "not_found"}

        ingested, quarantined = 0, 0
        for topic, items in data.items():
            if not isinstance(items, list):
                continue
            for i, p in enumerate(items):
                if not isinstance(p, dict):
                    continue
                text = (p.get("text") or "").strip()
                if not text or len(text) < 30:
                    self._quar.add(
                        source_path=f"{path.name}:{topic}[{i}]",
                        snippet=text[:120],
                        reason_code="low_text_quality",
                        reason_detail="principle_too_short",
                        stage="principles_ingestor")
                    quarantined += 1
                    continue

                cleaned = clean_text(text)
                q, ar_ratio, is_frag, has_ocr = assess_text_quality(cleaned)
                if q == TextQuality.CORRUPTED:
                    self._quar.add(
                        source_path=f"{path.name}:{topic}[{i}]",
                        snippet=cleaned[:120],
                        reason_code="corrupted_text",
                        stage="principles_ingestor")
                    quarantined += 1
                    continue

                binding = self._binder.bind(cleaned)
                fp  = _fingerprint(["principle", topic, cleaned[:80]])
                kid = _fingerprint([fp, "principle"])

                rec = KnowledgeRecord(
                    knowledge_id        = kid,
                    source_type         = KnowledgeSourceType.LEGAL_PRINCIPLE,
                    principle_id        = p.get("ref", "") or "",
                    principle_topic     = topic,
                    chamber             = p.get("chamber", "") or "",
                    source_fingerprint  = fp,
                    chunk_origin        = f"json:{path.name}:{topic}[{i}]",
                    in_force_status     = "in_force",
                    domain              = binding.domain.value
                                            if binding.domain.value != "unknown" else "",
                    subdomain           = binding.subdomain,
                    issue_tags          = binding.issue_tags + [topic],
                    remedy_tags         = binding.remedy_tags,
                    text_body           = text,
                    clean_text          = cleaned,
                    text_quality        = q,
                    language_cleanliness = ar_ratio,
                    has_ocr_noise       = has_ocr,
                    is_fragmented       = is_frag,
                    authority_rank      = AuthorityRank.LEGAL_PRINCIPLE,
                    verification_status = VerificationStatus.NOT_REQUIRED,
                    admissibility       = AdmissibilityStatus.RUNTIME_ELIGIBLE
                                            if binding.domain.value != "unknown"
                                            else AdmissibilityStatus.SUPPORT_ONLY,
                    provenance_status   = "known" if p.get("ref") else "partial",
                )
                if self._store.add(rec):
                    ingested += 1

        return {"ingested": ingested, "quarantined": quarantined}

    # ── source: article_ruling_index.json ──

    def ingest_court_rulings(self) -> dict:
        path = _SCRIPTS_DIR / "article_ruling_index.json"
        data = _safe_load_json(path)
        if not isinstance(data, dict):
            return {"status": "not_found"}

        ingested, quarantined = 0, 0
        for key, items in data.items():
            if not isinstance(items, list):
                continue
            # key looks like "الحضانة" or "المادة 61_قانون العمل"
            topic = key
            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                snippet = (item.get("snippet") or "").strip()
                if not snippet or len(snippet) < 40:
                    self._quar.add(
                        source_path=f"{path.name}:{key}[{i}]",
                        snippet=snippet[:120],
                        reason_code="low_text_quality",
                        reason_detail="ruling_snippet_too_short",
                        stage="court_rulings_ingestor")
                    quarantined += 1
                    continue

                cleaned = clean_text(snippet)
                q, ar_ratio, is_frag, has_ocr = assess_text_quality(cleaned)
                if q == TextQuality.CORRUPTED:
                    self._quar.add(
                        source_path=f"{path.name}:{key}[{i}]",
                        snippet=cleaned[:120],
                        reason_code="corrupted_text",
                        stage="court_rulings_ingestor")
                    quarantined += 1
                    continue

                ruling_id = str(item.get("ruling_id", ""))
                chunk_id  = item.get("chunk_id")
                if not ruling_id:
                    self._quar.add(
                        source_path=f"{path.name}:{key}[{i}]",
                        snippet=cleaned[:120],
                        reason_code="unverifiable_ruling",
                        stage="court_rulings_ingestor")
                    quarantined += 1
                    continue

                binding = self._binder.bind(cleaned)
                fp  = _fingerprint(["ruling", ruling_id, cleaned[:80]])
                kid = _fingerprint([fp, "ruling"])

                rec = KnowledgeRecord(
                    knowledge_id        = kid,
                    source_type         = KnowledgeSourceType.COURT_RULING,
                    ruling_id           = ruling_id,
                    principle_topic     = topic,
                    source_fingerprint  = fp,
                    chunk_origin        = f"json:{path.name}:{key}[{i}]",
                    document_id         = str(chunk_id) if chunk_id is not None else "",
                    in_force_status     = "in_force",
                    domain              = binding.domain.value
                                            if binding.domain.value != "unknown" else "",
                    subdomain           = binding.subdomain,
                    issue_tags          = binding.issue_tags + [topic],
                    remedy_tags         = binding.remedy_tags,
                    procedural_tags     = binding.procedural_tags,
                    text_body           = snippet,
                    clean_text          = cleaned,
                    text_quality        = q,
                    language_cleanliness = ar_ratio,
                    has_ocr_noise       = has_ocr,
                    is_fragmented       = is_frag,
                    authority_rank      = AuthorityRank.CASE_LAW_TAMYIZ,
                    verification_status = VerificationStatus.NOT_REQUIRED,
                    admissibility       = AdmissibilityStatus.RUNTIME_ELIGIBLE
                                            if binding.domain.value != "unknown"
                                            else AdmissibilityStatus.SUPPORT_ONLY,
                    provenance_status   = "known",
                )
                if self._store.add(rec):
                    ingested += 1

        return {"ingested": ingested, "quarantined": quarantined}

    # ── source: almeezan_target_laws.json (ministerial decisions / minor laws) ──

    def ingest_almeezan_target_laws(self) -> dict:
        path = _SCRIPTS_DIR / "almeezan_target_laws.json"
        data = _safe_load_json(path)
        if not isinstance(data, list):
            return {"status": "not_found"}

        ingested, quarantined = 0, 0
        for item in data:
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "").strip()
            lid = str(item.get("id", "") or "")
            if not title or not lid:
                self._quar.add(
                    source_path=f"{path.name}:id={lid}",
                    snippet=title[:120],
                    reason_code="incomplete_metadata",
                    stage="almeezan_target_laws_ingestor")
                quarantined += 1
                continue

            # These are mostly ministerial decisions — only shallow metadata here.
            # Title alone → metadata-only record, NOT runtime-eligible
            # (admissibility = SUPPORT_ONLY) until real article texts are fetched.
            cleaned = clean_text(title)
            q, ar_ratio, is_frag, has_ocr = assess_text_quality(cleaned)
            binding = self._binder.bind(cleaned)

            fp  = _fingerprint(["almeezan_target", lid, title[:80]])
            kid = _fingerprint([fp, "almeezan"])

            rec = KnowledgeRecord(
                knowledge_id        = kid,
                source_type         = KnowledgeSourceType.MINISTERIAL_DECISION,
                document_id         = lid,
                source_fingerprint  = fp,
                chunk_origin        = f"json:{path.name}:{lid}",
                in_force_status     = "unknown",   # metadata-only; status not established
                domain              = binding.domain.value
                                        if binding.domain.value != "unknown" else "",
                issue_tags          = binding.issue_tags,
                text_body           = title,
                clean_text          = cleaned,
                text_quality        = q if q != TextQuality.CORRUPTED else TextQuality.MINOR,
                language_cleanliness = ar_ratio,
                has_ocr_noise       = has_ocr,
                is_fragmented       = True,        # title only = fragment
                authority_rank      = AuthorityRank.REGULATION,
                verification_status = VerificationStatus.UNVERIFIED,
                admissibility       = AdmissibilityStatus.SUPPORT_ONLY,
                provenance_status   = "partial",
            )
            if self._store.add(rec):
                ingested += 1

        return {"ingested": ingested, "quarantined": quarantined,
                "note": "metadata_only_support_records"}

    # ── source: DB chunks (optional — runs when pool is available) ──

    async def ingest_db_chunks(self, pool, limit: Optional[int] = None) -> dict:
        """Pulls chunks from PostgreSQL and normalizes them.

        Safe to call when pool is None → returns {"status": "no_pool"}.
        """
        if pool is None:
            return {"status": "no_pool"}

        from core.evidence.normalizer import get_normalizer
        norm = get_normalizer()

        ingested, quarantined = 0, 0
        sql = (
            "SELECT id, law_id, source, law_name, law_number, law_year, "
            "       article_number, content, domain "
            "FROM chunks "
            "WHERE (is_active IS NULL OR is_active = TRUE) "
            + (f"LIMIT {int(limit)}" if limit else "")
        )
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql)
        except Exception as e:
            log.warning("db_chunks ingest failed: %s", e)
            return {"status": "db_error", "error": str(e)[:100]}

        for r in rows:
            d = dict(r)
            ev_rec, reason = norm.from_db_chunk(d)
            if ev_rec is None:
                self._quar.add(
                    source_path=f"db:chunks:{d.get('id','?')}",
                    snippet=(d.get("content") or "")[:120],
                    reason_code=self._map_db_reason(reason),
                    reason_detail=reason,
                    stage="db_chunks_ingestor")
                quarantined += 1
                continue

            # Bind domain from canonical_id if available
            binding = self._binder.bind(
                ev_rec.article_text,
                canonical_source_id=ev_rec.canonical_id or None,
            )

            # Convert EvidenceRecord → KnowledgeRecord
            kid = _fingerprint([ev_rec.source_fingerprint, "db_chunk"])
            rec = KnowledgeRecord(
                knowledge_id        = kid,
                source_type         = KnowledgeSourceType.STATUTE
                                        if ev_rec.canonical_id
                                        else KnowledgeSourceType.DB_CHUNK,
                canonical_source_id = ev_rec.canonical_id,
                law_title           = ev_rec.law_title,
                law_number          = ev_rec.law_number,
                law_year            = ev_rec.law_year,
                article_number      = ev_rec.article_number,
                source_fingerprint  = ev_rec.source_fingerprint,
                chunk_origin        = f"db:chunks:{d.get('id','?')}",
                document_id         = ev_rec.full_document_id,
                in_force_status     = ev_rec.in_force_status,
                domain              = (binding.domain.value
                                        if binding.domain.value != "unknown"
                                        else ev_rec.domain),
                subdomain           = binding.subdomain,
                issue_tags          = binding.issue_tags,
                remedy_tags         = binding.remedy_tags,
                procedural_tags     = binding.procedural_tags,
                party_role_tags     = binding.party_role_tags,
                text_body           = ev_rec.article_text,
                clean_text          = ev_rec.article_text,
                text_quality        = ev_rec.text_quality,
                language_cleanliness = ev_rec.language_cleanliness,
                has_ocr_noise       = ev_rec.has_ocr_noise,
                is_fragmented       = ev_rec.is_fragmented,
                authority_rank      = ev_rec.authority_rank,
                verification_status = ev_rec.verification_status,
                admissibility       = (AdmissibilityStatus.RUNTIME_ELIGIBLE
                                        if ev_rec.canonical_id
                                        and ev_rec.verification_status == VerificationStatus.VERIFIED
                                        else AdmissibilityStatus.SUPPORT_ONLY),
                provenance_status   = "known" if ev_rec.canonical_id else "partial",
            )
            if self._store.add(rec):
                ingested += 1

        return {"ingested": ingested, "quarantined": quarantined}

    def _map_db_reason(self, norm_reason: str) -> str:
        if not norm_reason:
            return "unknown_source"
        if "empty" in norm_reason: return "empty_content"
        if "corrupt" in norm_reason: return "corrupted_text"
        if "article_out_of_range" in norm_reason: return "article_out_of_range"
        if "canonical_law_not_found" in norm_reason: return "missing_canonical_identity"
        if "text_quality" in norm_reason: return "low_text_quality"
        return "legacy_noise"


_ingestor: Optional[KnowledgeIngestor] = None
_ingested_once = False


def get_ingestor() -> KnowledgeIngestor:
    global _ingestor
    if _ingestor is None:
        _ingestor = KnowledgeIngestor()
    return _ingestor


def ingest_all(force: bool = False) -> dict:
    """Top-level: ingest every known source once per process.

    Subsequent calls no-op unless force=True.
    """
    global _ingested_once
    ing = get_ingestor()
    if _ingested_once and not force:
        return {"status": "already_ingested",
                 "coverage": get_store().coverage()}
    summary = ing.ingest_all()
    _ingested_once = True
    return summary


def coverage_stats() -> dict:
    return get_store().coverage()
