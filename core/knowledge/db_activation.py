# -*- coding: utf-8 -*-
"""
DB Knowledge Activation — the production startup trigger.
============================================================

Modes (env DB_KNOWLEDGE_ACTIVATION_MODE):
  skip          — do nothing (useful for tests / emergency)
  persisted     — load from disk snapshot ONLY (default in prod)
  incremental   — load snapshot + fetch rows newer than snapshot
  full          — ingest all rows from DB (slow, blocking)

Safety:
  - Startup NEVER fails because of activation errors — logs + continues.
  - Batched ingestion with configurable size (DB_KNOWLEDGE_BATCH_SIZE).
  - Row cap (DB_KNOWLEDGE_MAX_ROWS) protects against runaway pulls.
  - Metrics tracked per batch for observability.
  - Thread-safe singleton state.

Trace exposure:
  - get_activation_state() returns last activation summary (mode, counts,
    elapsed, errors) — consumed by /debug/knowledge-activation endpoint.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from core.knowledge.store import get_store
from core.knowledge.quarantine import get_quarantine
from core.knowledge.ingestion import get_ingestor
from core.knowledge.persistence import (
    save_snapshot, load_snapshot, snapshot_info,
)

log = logging.getLogger("db_activation")


# ═════════════════════════════════════════════════════════════════
# Config
# ═════════════════════════════════════════════════════════════════

def _activation_mode() -> str:
    m = (os.getenv("DB_KNOWLEDGE_ACTIVATION_MODE") or "persisted").strip().lower()
    if m not in ("skip", "persisted", "incremental", "full"):
        log.warning("invalid DB_KNOWLEDGE_ACTIVATION_MODE=%s → fallback to persisted", m)
        return "persisted"
    return m


def _batch_size() -> int:
    try:
        return max(100, int(os.getenv("DB_KNOWLEDGE_BATCH_SIZE") or "500"))
    except ValueError:
        return 500


def _max_rows() -> int:
    try:
        return max(1000, int(os.getenv("DB_KNOWLEDGE_MAX_ROWS") or "50000"))
    except ValueError:
        return 50000


# ═════════════════════════════════════════════════════════════════
# Activation state (inspectable)
# ═════════════════════════════════════════════════════════════════

@dataclass
class ActivationState:
    attempted:       bool  = False
    completed:       bool  = False
    mode:            str   = ""
    db_available:    bool  = False
    snapshot_loaded: bool  = False
    rows_read:       int   = 0
    batches:         int   = 0
    ingested:        int   = 0
    quarantined:     int   = 0
    duplicates:      int   = 0
    elapsed_seconds: float = 0.0
    errors:          list[str] = field(default_factory=list)
    source_mix_after: dict  = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "attempted":        self.attempted,
            "completed":        self.completed,
            "mode":             self.mode,
            "db_available":     self.db_available,
            "snapshot_loaded":  self.snapshot_loaded,
            "rows_read":        self.rows_read,
            "batches":          self.batches,
            "ingested":         self.ingested,
            "quarantined":      self.quarantined,
            "duplicates":       self.duplicates,
            "elapsed_seconds":  round(self.elapsed_seconds, 3),
            "errors":           list(self.errors),
            "source_mix_after": dict(self.source_mix_after),
        }


_state = ActivationState()


def get_activation_state() -> ActivationState:
    return _state


def reset_state() -> None:
    global _state
    _state = ActivationState()


# ═════════════════════════════════════════════════════════════════
# The activator
# ═════════════════════════════════════════════════════════════════

async def activate_db_knowledge(pool, mode: Optional[str] = None) -> dict:
    """Entry point called from startup.lifespan.

    Args:
        pool: asyncpg pool or None.
        mode: override env setting.

    Returns a summary dict (same as ActivationState.to_dict()).
    """
    global _state
    _state = ActivationState()
    mode = (mode or _activation_mode()).lower()
    _state.mode = mode
    _state.attempted = True
    _state.db_available = pool is not None

    t0 = time.time()

    if mode == "skip":
        log.info("[db_activation] mode=skip — no DB ingestion")
        _state.completed = True
        _state.elapsed_seconds = time.time() - t0
        return _state.to_dict()

    # ── Step 1: try to load snapshot (all modes except "full" benefit) ──
    store = get_store()
    if mode in ("persisted", "incremental"):
        payload = load_snapshot()
        if payload is not None:
            records = payload.get("records", [])
            header  = payload.get("header", {})
            for rec in records:
                store.add(rec)
            _state.snapshot_loaded = True
            _state.ingested = store.count()
            log.info("[db_activation] snapshot loaded: records=%d",
                     _state.ingested)
            if mode == "persisted":
                # Done — don't touch DB
                _state.completed = True
                _state.source_mix_after = store.coverage().get("per_source_type", {})
                _state.elapsed_seconds = time.time() - t0
                return _state.to_dict()

    # ── Step 2: DB fetch (incremental or full) ──
    if pool is None:
        _state.errors.append("db_pool_unavailable")
        _state.completed = True
        _state.elapsed_seconds = time.time() - t0
        _state.source_mix_after = store.coverage().get("per_source_type", {})
        log.warning("[db_activation] pool unavailable — cannot perform %s mode", mode)
        return _state.to_dict()

    # Ensure JSON knowledge ingested too (idempotent)
    try:
        from core.knowledge.ingestion import ingest_all
        ingest_all(force=False)
    except Exception as e:
        _state.errors.append(f"json_ingest_failed:{type(e).__name__}")

    batch_size = _batch_size()
    cap = _max_rows()

    # Fetch all chunks in batches
    try:
        summary = await _batched_db_ingest(pool, batch_size, cap)
        _state.rows_read = summary["rows_read"]
        _state.batches = summary["batches"]
        _state.ingested = store.count()
        _state.quarantined = summary["quarantined"]
        _state.duplicates = store.duplicates_count()
    except Exception as e:
        log.exception("[db_activation] batched ingest raised")
        _state.errors.append(f"ingest_exception:{type(e).__name__}:{str(e)[:100]}")

    # ── Step 3: persist snapshot ──
    if _state.ingested > 0:
        src_mix = store.coverage().get("per_source_type", {})
        save_result = save_snapshot(store, src_mix, ingestor_tag=f"mode={mode}")
        if save_result.get("ok"):
            log.info("[db_activation] snapshot persisted: %d bytes",
                     save_result.get("bytes", 0))
        else:
            _state.errors.append(f"snapshot_save_failed:{save_result.get('error','')[:80]}")

    _state.source_mix_after = store.coverage().get("per_source_type", {})
    _state.completed = True
    _state.elapsed_seconds = time.time() - t0
    log.info("[db_activation] done: mode=%s ingested=%d quarantined=%d elapsed=%.2fs",
             mode, _state.ingested, _state.quarantined, _state.elapsed_seconds)
    return _state.to_dict()


async def _batched_db_ingest(pool, batch_size: int, cap: int) -> dict:
    """Run the actual DB fetch in ordered batches.

    Strategy: keyset pagination on chunks.id (stable order, resumable).
    Quarantines anything the normalizer rejects.
    Deduplicates via KnowledgeStore fingerprint index.
    """
    from core.evidence.normalizer import get_normalizer
    from core.knowledge.domain_binder import get_binder
    from core.knowledge.contract import (
        KnowledgeRecord, KnowledgeSourceType, AdmissibilityStatus,
    )
    from core.evidence.contract import VerificationStatus
    import hashlib

    norm   = get_normalizer()
    binder = get_binder()
    store  = get_store()
    quar   = get_quarantine()

    rows_read = 0
    batches = 0
    quarantined = 0
    last_id = 0

    sql = (
        "SELECT id, law_id, source, law_name, law_number, law_year, "
        "       article_number, content, domain "
        "FROM chunks "
        "WHERE id > $1 "
        "  AND (is_active IS NULL OR is_active = TRUE) "
        "ORDER BY id ASC "
        "LIMIT $2"
    )

    while rows_read < cap:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, last_id, batch_size)
        except Exception as e:
            raise RuntimeError(f"db_fetch_failed:{e}") from e

        if not rows:
            break

        batches += 1
        for r in rows:
            d = dict(r)
            last_id = d.get("id") or last_id
            rows_read += 1

            ev_rec, reason = norm.from_db_chunk(d)
            if ev_rec is None:
                quar.add(
                    source_path=f"db:chunks:{d.get('id','?')}",
                    snippet=(d.get("content") or "")[:120],
                    reason_code=_map_reason(reason),
                    reason_detail=reason,
                    stage="db_batched_ingest",
                )
                quarantined += 1
                continue

            # ── STRICT: statute records with UNVERIFIED canonical are rejected ──
            # This catches: article number out of canonical range, law alias
            # resolved but article doesn't exist. No "support_only" for these —
            # they'd let fabricated identities into the store.
            if (ev_rec.canonical_id
                and ev_rec.verification_status == VerificationStatus.UNVERIFIED):
                quar.add(
                    source_path=f"db:chunks:{d.get('id','?')}",
                    snippet=ev_rec.article_text[:120],
                    reason_code="unverifiable_article",
                    reason_detail=(
                        f"canonical={ev_rec.canonical_id} "
                        f"article={ev_rec.article_number} unverified"
                    ),
                    stage="db_batched_ingest",
                )
                quarantined += 1
                continue

            # Domain binding (canonical lock when available)
            binding = binder.bind(
                ev_rec.article_text,
                canonical_source_id=ev_rec.canonical_id or None,
            )

            if binding.domain.value == "unknown" and not ev_rec.canonical_id:
                # No canonical, no domain → support-only at best
                quar.add(
                    source_path=f"db:chunks:{d.get('id','?')}",
                    snippet=ev_rec.article_text[:120],
                    reason_code="missing_domain_binding",
                    reason_detail="no_canonical_and_no_domain_vote",
                    stage="db_batched_ingest",
                )
                quarantined += 1
                continue

            fp = ev_rec.source_fingerprint or hashlib.sha1(
                f"db|{d.get('id')}".encode("utf-8")).hexdigest()[:16]
            kid = hashlib.sha1(f"{fp}|db_chunk".encode("utf-8")).hexdigest()[:16]

            admissibility = (
                AdmissibilityStatus.RUNTIME_ELIGIBLE
                if (ev_rec.canonical_id
                    and ev_rec.verification_status == VerificationStatus.VERIFIED)
                else AdmissibilityStatus.SUPPORT_ONLY
            )

            rec = KnowledgeRecord(
                knowledge_id        = kid,
                source_type         = (KnowledgeSourceType.STATUTE
                                        if ev_rec.canonical_id
                                        else KnowledgeSourceType.DB_CHUNK),
                canonical_source_id = ev_rec.canonical_id,
                law_title           = ev_rec.law_title,
                law_number          = ev_rec.law_number,
                law_year            = ev_rec.law_year,
                article_number      = ev_rec.article_number,
                source_fingerprint  = fp,
                chunk_origin        = f"db:chunks:{d.get('id','?')}",
                document_id         = str(d.get("law_id") or ""),
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
                admissibility       = admissibility,
                provenance_status   = "known" if ev_rec.canonical_id else "partial",
            )
            store.add(rec)

        # Yield to event loop between batches
        await asyncio.sleep(0)

        if len(rows) < batch_size:
            break

    return {"rows_read": rows_read, "batches": batches,
            "quarantined": quarantined, "last_id": last_id}


def _map_reason(norm_reason: str) -> str:
    if not norm_reason:
        return "unknown_source"
    r = norm_reason.lower()
    if "empty" in r:
        return "no_text"
    if "corrupt" in r:
        return "corrupted_text"
    if "article_out_of_range" in r:
        return "unverifiable_article"
    if "canonical_law_not_found" in r:
        return "missing_source_identity"
    if "quality" in r or "ar_ratio" in r:
        return "low_arabic_ratio"
    return "legacy_noise"


# ═════════════════════════════════════════════════════════════════
# Sync helper for tests with a mock pool
# ═════════════════════════════════════════════════════════════════

def activate_for_test(pool, mode: str = "full") -> dict:
    """Blocking helper for tests that drive a mock async pool."""
    return asyncio.run(activate_db_knowledge(pool, mode=mode))
