# -*- coding: utf-8 -*-
"""
cache_service.py — Semantic + Exact Cache Service
===================================================
طبقتا كاش متكاملتان:

  1. Exact Cache  : hash(normalize(query)) → إجابة مُخزَّنة (TTL 1 ساعة)
  2. Semantic Cache: cosine_similarity(q_embed, cached_embed) > 0.95 → نفس الإجابة

التخزين: in-memory dict (بدون تبعيات خارجية) مع دعم Redis اختياري.

الاستخدام:
    from cache_service import CacheService, get_cache_service, init_cache_service

    svc = init_cache_service(embed_fn=embed, ttl_seconds=3600)

    # قبل البحث:
    hit = await svc.get(query)
    if hit:
        return hit["answer"]

    # بعد الإجابة:
    await svc.set(query, answer, sources, embedding=q_embed)
"""

from __future__ import annotations

import hashlib
import logging
import time
import math
from typing import Callable, Awaitable, Optional

log = logging.getLogger(__name__)

# ── ثوابت ──────────────────────────────────────────────────
DEFAULT_TTL          = 3600           # ساعة واحدة بالثواني
DEFAULT_MAX_ENTRIES  = 500            # حد أقصى للـ exact cache
SEMANTIC_THRESHOLD   = 0.95           # حد التشابه الدلالي
SEMANTIC_MAX_ENTRIES = 100            # حد أقصى للـ semantic cache


# ══════════════════════════════════════════════════════════════
# Singleton
# ══════════════════════════════════════════════════════════════
_service_instance: Optional["CacheService"] = None


def init_cache_service(
    embed_fn: Callable[[str], Awaitable[list[float]]] | None = None,
    ttl_seconds: int = DEFAULT_TTL,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    semantic_threshold: float = SEMANTIC_THRESHOLD,
) -> "CacheService":
    """ينشئ instance واحد ويحفظه عالمياً."""
    global _service_instance
    _service_instance = CacheService(
        embed_fn           = embed_fn,
        ttl_seconds        = ttl_seconds,
        max_entries        = max_entries,
        semantic_threshold = semantic_threshold,
    )
    return _service_instance


def get_cache_service() -> Optional["CacheService"]:
    """يُعيد الـ instance المحفوظ (أو None إذا لم يُهيَّأ بعد)."""
    return _service_instance


# ══════════════════════════════════════════════════════════════
# CacheEntry
# ══════════════════════════════════════════════════════════════
class CacheEntry:
    """حاوية بيانات كاش واحدة."""
    __slots__ = ("query_orig", "answer", "sources", "embedding", "created_at", "hits")

    def __init__(
        self,
        query_orig: str,
        answer: str,
        sources: list,
        embedding: list[float] | None = None,
    ):
        self.query_orig = query_orig
        self.answer     = answer
        self.sources    = sources
        self.embedding  = embedding
        self.created_at = time.time()
        self.hits       = 0

    def is_expired(self, ttl: int) -> bool:
        return (time.time() - self.created_at) > ttl

    def to_dict(self) -> dict:
        return {
            "query_orig": self.query_orig,
            "answer"    : self.answer,
            "sources"   : self.sources,
            "hits"      : self.hits,
            "age_s"     : round(time.time() - self.created_at),
        }


# ══════════════════════════════════════════════════════════════
# CacheService
# ══════════════════════════════════════════════════════════════
class CacheService:
    """
    خدمة كاش ثنائية المستوى (Exact + Semantic).

    Parameters
    ----------
    embed_fn           : دالة async تُعيد embedding للنص (للـ semantic cache)
    ttl_seconds        : مدة الصلاحية بالثواني (default: 3600 = ساعة)
    max_entries        : حد أقصى للـ exact cache
    semantic_threshold : حد cosine similarity للـ semantic cache (default: 0.95)
    """

    def __init__(
        self,
        embed_fn           : Callable[[str], Awaitable[list[float]]] | None = None,
        ttl_seconds        : int   = DEFAULT_TTL,
        max_entries        : int   = DEFAULT_MAX_ENTRIES,
        semantic_threshold : float = SEMANTIC_THRESHOLD,
    ):
        self._embed            = embed_fn
        self.ttl               = ttl_seconds
        self.max_entries       = max_entries
        self.semantic_threshold = semantic_threshold

        # Exact cache: hash → CacheEntry
        self._exact:    dict[str, CacheEntry] = {}
        # Semantic cache: list[(embedding, CacheEntry)]
        self._semantic: list[tuple[list[float], CacheEntry]] = []

        # إحصائيات
        self._hits_exact    = 0
        self._hits_semantic = 0
        self._misses        = 0
        self._sets          = 0

    # ─────────────────────────────────────────────���────────────
    # get — البحث في الكاش
    # ──────────────────────────────────────────────────────────
    async def get(self, query: str) -> Optional[dict]:
        """
        يبحث في الكاش بالترتيب:
          1. Exact cache (فوري — O(1))
          2. Semantic cache (cosine similarity)

        يُعيد dict مع answer + sources + cache_type أو None.
        """
        self._evict_expired()
        q_hash = _hash_query(query)

        # 1. Exact cache
        if q_hash in self._exact:
            entry = self._exact[q_hash]
            entry.hits += 1
            self._hits_exact += 1
            log.debug("cache HIT [exact]: '%s'", query[:40])
            return {**entry.to_dict(), "cache_type": "exact", "from_cache": True}

        # 2. Semantic cache (يحتاج embed_fn)
        if self._embed and self._semantic:
            try:
                q_emb = await self._embed(query)
                best_sim, best_entry = self._find_semantic_match(q_emb)
                if best_entry is not None and best_sim >= self.semantic_threshold:
                    best_entry.hits += 1
                    self._hits_semantic += 1
                    log.debug(
                        "cache HIT [semantic=%.3f]: '%s'", best_sim, query[:40]
                    )
                    return {
                        **best_entry.to_dict(),
                        "cache_type"  : "semantic",
                        "similarity"  : round(best_sim, 3),
                        "from_cache"  : True,
                    }
            except Exception as exc:
                log.debug("semantic cache lookup error: %s", exc)

        self._misses += 1
        return None

    # ──────────────────────────────────────────────────────────
    # set — الحفظ في الكاش
    # ──────────────────────────────────────────────────────────
    async def set(
        self,
        query    : str,
        answer   : str,
        sources  : list,
        embedding: list[float] | None = None,
    ) -> None:
        """
        يحفظ الإجابة في كلا الكاشَين.

        إذا لم يُمرَّر embedding وكان embed_fn متاحاً → يحسبه تلقائياً.
        """
        if not answer or len(answer) < 50:
            return

        # احسب embedding إذا لم يُمرَّر
        if embedding is None and self._embed:
            try:
                embedding = await self._embed(query)
            except Exception as exc:
                log.debug("cache set: embed failed: %s", exc)

        entry   = CacheEntry(query, answer, sources, embedding)
        q_hash  = _hash_query(query)

        # Exact cache — تحكّم بالحجم
        if len(self._exact) >= self.max_entries:
            self._evict_oldest_exact()
        self._exact[q_hash] = entry

        # Semantic cache
        if embedding:
            if len(self._semantic) >= SEMANTIC_MAX_ENTRIES:
                self._semantic.pop(0)
            self._semantic.append((embedding, entry))

        self._sets += 1
        log.debug("cache SET: '%s' (embed=%s)", query[:40], embedding is not None)

    # ──────────────────────────────────────────────────────────
    # clear / reset
    # ──────────────────────────────────────────────────────────
    def clear(self) -> None:
        """يُفرّغ الكاش بالكامل."""
        self._exact.clear()
        self._semantic.clear()
        self._hits_exact = self._hits_semantic = self._misses = self._sets = 0

    def invalidate(self, query: str) -> bool:
        """يُزيل استعلاماً محدداً من الـ exact cache."""
        q_hash = _hash_query(query)
        if q_hash in self._exact:
            del self._exact[q_hash]
            return True
        return False

    # ──────────────────────────────────────────────────────────
    # stats
    # ──────────────────────────────────────────────────────────
    def get_stats(self) -> dict:
        """يُعيد إحصائيات الكاش الكاملة."""
        total_req  = self._hits_exact + self._hits_semantic + self._misses
        hit_rate   = (
            round((self._hits_exact + self._hits_semantic) / total_req * 100, 1)
            if total_req > 0 else 0.0
        )
        return {
            "hit_rate"         : f"{hit_rate}%",
            "total_hits"       : self._hits_exact + self._hits_semantic,
            "hits_exact"       : self._hits_exact,
            "hits_semantic"    : self._hits_semantic,
            "total_misses"     : self._misses,
            "total_sets"       : self._sets,
            "cached_queries"   : len(self._exact),
            "semantic_entries" : len(self._semantic),
            "ttl_seconds"      : self.ttl,
            "semantic_threshold": self.semantic_threshold,
            "embed_enabled"    : self._embed is not None,
        }

    # ──────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────
    def _find_semantic_match(
        self, query_emb: list[float]
    ) -> tuple[float, Optional[CacheEntry]]:
        """يجد أعلى تشابه cosine بين query_emb وجميع embedding مُخزَّنة."""
        best_sim   = 0.0
        best_entry = None
        for emb, entry in self._semantic:
            if entry.is_expired(self.ttl):
                continue
            sim = _cosine_similarity(query_emb, emb)
            if sim > best_sim:
                best_sim   = sim
                best_entry = entry
        return best_sim, best_entry

    def _evict_expired(self) -> None:
        """يُزيل الإدخالات المنتهية الصلاحية."""
        expired_keys = [k for k, e in self._exact.items() if e.is_expired(self.ttl)]
        for k in expired_keys:
            del self._exact[k]
        self._semantic = [
            (emb, e) for emb, e in self._semantic if not e.is_expired(self.ttl)
        ]

    def _evict_oldest_exact(self) -> None:
        """يُزيل أقدم إدخال في الـ exact cache."""
        if not self._exact:
            return
        oldest_key = min(self._exact, key=lambda k: self._exact[k].created_at)
        del self._exact[oldest_key]


# ══════════════════════════════════════════════════════════════
# دوال مساعدة
# ══════════════════════════════════════════════════════════════
def _hash_query(query: str) -> str:
    """SHA256 لنص الاستعلام بعد التطبيع."""
    normalized = query.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """
    حساب cosine similarity بين متجهَين.
    يُعيد 0.0 عند الخطأ أو المتجهات الصفرية.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot   = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)
