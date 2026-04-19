# -*- coding: utf-8 -*-
"""
search_service.py — Hybrid Search Service
==========================================
يجمع بين:
  1. Vector Search  (pgvector cosine similarity)
  2. Full-Text Search (PostgreSQL tsvector / plainto_tsquery بـ simple config للعربية)
  3. RRF Fusion  (Reciprocal Rank Fusion: score = Σ 1/(60 + rank))
  4. Domain Filtering  (فلترة حسب المجال القانوني)
  5. Article Boosting  (تعزيز النتائج المُطابِقة لرقم المادة المذكورة)

الاستخدام:
    from search_service import SearchService, get_search_service, init_search_service

    # عند بدء التطبيق:
    svc = init_search_service(pool, embed_fn=embed)

    # في كل استعلام:
    results = await svc.hybrid_search("ما عقوبة السرقة؟", top_k=15, domain="جنائي")
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Callable, Awaitable, Optional

# نمط استخراج رقم المادة من الاستعلام
_ARTICLE_NUM_RE = re.compile(r"المادة\s*[(\[]?\s*(\d+)\s*[)\]]?", re.UNICODE)

# نسبة تعزيز النتيجة عند تطابق المجال أو رقم المادة
_DOMAIN_BOOST_FACTOR   = 1.25   # ×1.25 إذا تطابق المجال
_ARTICLE_BOOST_FACTOR  = 1.50   # ×1.50 إذا تطابق رقم المادة


def _extract_article_number(query: str) -> Optional[str]:
    """يستخرج رقم المادة من الاستعلام إن وُجد. مثال: 'المادة 300' → '300'."""
    m = _ARTICLE_NUM_RE.search(query or "")
    return m.group(1) if m else None


def _build_tsquery(query_text: str) -> str:
    """
    يبني tsquery مُحسَّناً للعربية.
    يجرّب websearch_to_tsquery أولاً (أكثر مرونة)، يعود لـ plainto_tsquery.
    للاستخدام المباشر في SQL — لكن هذه الدالة تُنشئ بديل fallback للـ OR.
    """
    # يُعيد العبارة النصية — الـ SQL سيتعامل مع التحويل
    return query_text.strip()


def _apply_boosts(
    results: list[dict],
    domain: Optional[str] = None,
    article_number: Optional[str] = None,
) -> list[dict]:
    """
    يُطبّق تعزيزات النتيجة:
    - تطابق المجال → ×DOMAIN_BOOST_FACTOR
    - تطابق رقم المادة → ×ARTICLE_BOOST_FACTOR
    """
    for r in results:
        score = float(r.get("score", 0))

        if domain and r.get("domain") == domain:
            score = min(score * _DOMAIN_BOOST_FACTOR, 1.0)

        if article_number and str(r.get("article_number", "")) == article_number:
            score = min(score * _ARTICLE_BOOST_FACTOR, 1.0)

        r["score"] = score
    return results

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────────────────────
_service_instance: Optional["SearchService"] = None


def init_search_service(
    pool,
    embed_fn: Callable[[str], Awaitable[list[float]]] | None = None,
    top_k: int = 15,
    rrf_k: int = 60,
) -> "SearchService":
    """ينشئ instance واحد ويحفظه عالمياً."""
    global _service_instance
    _service_instance = SearchService(pool=pool, embed_fn=embed_fn, top_k=top_k, rrf_k=rrf_k)
    return _service_instance


def get_search_service() -> Optional["SearchService"]:
    """يُعيد الـ instance المحفوظ (أو None إذا لم يُهيَّأ بعد)."""
    return _service_instance


# ──────────────────────────────────────────────────────────────
# SearchService
# ──────────────────────────────────────────────────────────────
class SearchService:
    """
    خدمة بحث هجينة تجمع Vector Search + Full-Text Search + RRF.

    Parameters
    ----------
    pool      : asyncpg pool (يُمرَّر من main.py)
    embed_fn  : دالة غير متزامنة تقبل نصاً وتُعيد list[float]
    top_k     : عدد النتائج الافتراضي
    rrf_k     : ثابت RRF (عادةً 60)
    """

    def __init__(
        self,
        pool,
        embed_fn: Callable[[str], Awaitable[list[float]]] | None = None,
        top_k: int = 15,
        rrf_k: int = 60,
    ):
        self.pool    = pool
        self._embed  = embed_fn
        self.top_k   = top_k
        self.rrf_k   = rrf_k

    # ──────────────────────────────────────────────────────
    # 1. Vector Search
    # ──────────────────────────────────────────────────────
    async def vector_search(
        self,
        conn,
        embedding: list[float],
        top_k: int | None = None,
        domain: str | None = None,
    ) -> list[dict]:
        """
        بحث cosine similarity عبر pgvector.
        يُعيد نتائج مرتّبة تنازلياً بالـ score.

        Parameters
        ----------
        domain : إذا مُحدَّد، يُعطي أولوية للـ chunks من هذا المجال (soft boost)
        """
        top_k = top_k or self.top_k
        emb_str = "[" + ",".join(map(str, embedding)) + "]"

        # نسترجع top_k*2 ثم نُطبّق boost ونُرجع top_k
        fetch_k = top_k * 2 if domain else top_k
        try:
            rows = await conn.fetch(
                """
                SELECT id, law_id, source, law_name, law_number, law_year,
                       article_number, content, domain,
                       1 - (embedding <=> $1::vector) AS score
                FROM   chunks
                WHERE  (is_active IS NULL OR is_active = TRUE)
                ORDER  BY embedding <=> $1::vector
                LIMIT  $2
                """,
                emb_str,
                fetch_k,
            )
        except Exception as exc:
            log.warning("vector_search خطأ: %s", exc)
            return []

        results = []
        for r in rows:
            d = dict(r)
            d["score"]        = float(d.get("score", 0))
            d["search_type"]  = "vector"
            results.append(d)
        return results

    # ──────────────────────────────────────────────────────
    # 2. Full-Text Search (PostgreSQL tsvector)
    # ──────────────────────────────────────────────────────
    async def fulltext_search(
        self,
        conn,
        query_text: str,
        top_k: int | None = None,
        domain: str | None = None,
    ) -> list[dict]:
        """
        بحث نصي كامل متعدد الاستراتيجيات:

        1. websearch_to_tsquery على content_tsv (أكثر مرونة — يدعم OR تلقائياً)
        2. plainto_tsquery على content_tsv (fallback)
        3. plainto_tsquery طيّار (بدون عمود content_tsv)

        Parameters
        ----------
        domain : إذا مُحدَّد، يُضاف فلتر اختياري للمجال في المحاولة الأولى.
        """
        top_k = top_k or self.top_k
        if not query_text or not query_text.strip():
            return []

        # دعم فلتر المجال: نُضيف شرط domain فقط في المحاولة الأولى
        domain_filter = ""
        domain_params_offset = 0
        if domain:
            # نُدرج مجال "عام" دائماً (catch-all) وكذلك NULL
            domain_filter = "AND (domain = $3 OR domain = 'عام' OR domain IS NULL)"
            domain_params_offset = 1

        # استراتيجيات البحث: (SQL, needs_content_tsv, use_websearch)
        queries_to_try = [
            # ① websearch_to_tsquery على content_tsv (الأفضل للعربية)
            (
                f"""
                SELECT id, law_id, source, law_name, law_number, law_year,
                       article_number, content, domain,
                       ts_rank_cd(content_tsv,
                           websearch_to_tsquery('simple', $1)) AS score
                FROM   chunks
                WHERE  content_tsv @@ websearch_to_tsquery('simple', $1)
                  AND  (is_active IS NULL OR is_active = TRUE)
                  {domain_filter}
                ORDER  BY score DESC
                LIMIT  $2
                """,
                True, True,
            ),
            # ② plainto_tsquery على content_tsv (بدون domain filter)
            (
                """
                SELECT id, law_id, source, law_name, law_number, law_year,
                       article_number, content, domain,
                       ts_rank_cd(content_tsv, plainto_tsquery('simple', $1)) AS score
                FROM   chunks
                WHERE  content_tsv @@ plainto_tsquery('simple', $1)
                  AND  (is_active IS NULL OR is_active = TRUE)
                ORDER  BY score DESC
                LIMIT  $2
                """,
                True, False,
            ),
            # ③ plainto_tsquery طيّار (on-the-fly)
            (
                """
                SELECT id, law_id, source, law_name, law_number, law_year,
                       article_number, content, domain,
                       ts_rank_cd(to_tsvector('simple', content),
                                  plainto_tsquery('simple', $1)) AS score
                FROM   chunks
                WHERE  to_tsvector('simple', content) @@ plainto_tsquery('simple', $1)
                  AND  (is_active IS NULL OR is_active = TRUE)
                ORDER  BY score DESC
                LIMIT  $2
                """,
                False, False,
            ),
        ]

        for sql, needs_column, use_websearch in queries_to_try:
            try:
                params = [query_text, top_k]
                if domain and needs_column and use_websearch and domain_filter:
                    params.append(domain)

                rows = await conn.fetch(sql, *params)
                results = []
                for r in rows:
                    d = dict(r)
                    d["score"]       = float(d.get("score", 0))
                    d["search_type"] = "fts"
                    results.append(d)
                log.debug(
                    "fulltext_search: %d نتيجة (websearch=%s, tsv_col=%s, domain=%s)",
                    len(results), use_websearch, needs_column, domain or "-",
                )
                return results
            except Exception as exc:
                if needs_column:
                    log.debug("FTS محاولة فاشلة (%s)، أجرب التالية: %s", "websearch" if use_websearch else "plainto", exc)
                    continue
                log.warning("fulltext_search خطأ: %s", exc)
                return []

        return []

    # ──────────────────────────────────────────────────────
    # 3. RRF Fusion
    # ──────────────────────────────────────────────────────
    def rrf_fusion(
        self,
        *ranked_lists: list[dict],
        k: int | None = None,
        top_n: int | None = None,
    ) -> list[dict]:
        """
        Reciprocal Rank Fusion: score = Σ 1/(k + rank + 1)

        Parameters
        ----------
        ranked_lists : قوائم نتائج مُرتَّبة (كل منها من مصدر بحث مختلف)
        k            : ثابت RRF (افتراضي self.rrf_k = 60)
        top_n        : عدد النتائج المُعادة (افتراضي self.top_k)

        Returns
        -------
        list[dict] مُرتَّب تنازلياً بـ rrf_score.
        كل عنصر يحتوي الحقول الأصلية + "rrf_score" + "score" (= rrf_score).
        """
        k     = k     or self.rrf_k
        top_n = top_n or self.top_k

        rrf_scores: dict[tuple, float] = {}
        best_item:  dict[tuple, dict]  = {}

        for ranked_list in ranked_lists:
            for rank, item in enumerate(ranked_list):
                key = (
                    item.get("law_name", ""),
                    item.get("article_number", ""),
                )
                contrib = 1.0 / (k + rank + 1)
                rrf_scores[key] = rrf_scores.get(key, 0.0) + contrib

                # احتفظ بأفضل نسخة (بـ raw score أعلى) لهذا العنصر
                raw_score = float(item.get("score", 0))
                if key not in best_item or raw_score > float(best_item[key].get("_raw_score", 0)):
                    best_item[key] = {**item, "_raw_score": raw_score}

        results = []
        for key, item in best_item.items():
            merged = {**item}
            merged.pop("_raw_score", None)
            merged["rrf_score"] = round(rrf_scores[key], 6)
            merged["score"]     = merged["rrf_score"]
            results.append(merged)

        return sorted(results, key=lambda x: x["rrf_score"], reverse=True)[:top_n]

    # ──────────────────────────────────────────────────────
    # 4. Hybrid Search (الواجهة الرئيسية)
    # ──────────────────────────────────────────────────────
    async def hybrid_search(
        self,
        query_text: str,
        extra_queries: list[str] | None = None,
        top_k: int | None = None,
        domain: str | None = None,
    ) -> list[dict]:
        """
        البحث الهجين: vector + FTS → RRF + Article Boosting.

        Parameters
        ----------
        query_text    : نص الاستعلام الأصلي
        extra_queries : استعلامات إضافية (من query expansion)
        top_k         : عدد النتائج (افتراضي self.top_k)
        domain        : المجال القانوني (جنائي|عمالي|أسري|...) — يُحسّن الترتيب

        Returns
        -------
        list[dict] مُرتَّب بـ rrf_score.
        كل عنصر يحتوي: id, law_name, article_number, content, domain, score, rrf_score
        """
        top_k = top_k or self.top_k

        if not self.pool:
            log.warning("hybrid_search: لا يوجد pool — تخطّى")
            return []

        # استخراج رقم المادة من الاستعلام (للـ article boosting)
        article_number = _extract_article_number(query_text)

        async with self.pool.acquire() as conn:
            # ── بحث FTS على الاستعلام الأصلي (مع domain soft-filter) ──
            fts_task = self.fulltext_search(conn, query_text, top_k * 2, domain=domain)

            # ── بحث Vector ──
            vec_task = self._run_vector_search(conn, query_text, extra_queries, top_k * 2, domain=domain)

            fts_results, vec_results = await asyncio.gather(fts_task, vec_task)

        log.info(
            "hybrid_search: fts=%d, vec=%d, domain=%s, article=%s, query='%s'",
            len(fts_results), len(vec_results),
            domain or "-", article_number or "-",
            query_text[:40],
        )

        # ── إذا كلا المصدران فارغان ──
        if not fts_results and not vec_results:
            return []

        # ── تطبيق domain boost و article boost قبل RRF ──
        if domain or article_number:
            fts_results = _apply_boosts(fts_results, domain, article_number)
            vec_results = _apply_boosts(vec_results, domain, article_number)

        # ── RRF fusion ──
        merged = self.rrf_fusion(fts_results, vec_results, top_n=top_k)
        return merged

    async def _run_vector_search(
        self,
        conn,
        query_text: str,
        extra_queries: list[str] | None,
        top_k: int,
        domain: str | None = None,
    ) -> list[dict]:
        """يُنفّذ vector search على النص الأصلي + أول استعلام إضافي."""
        if not self._embed:
            return []

        all_vec: dict[tuple, dict] = {}
        queries_to_embed = [query_text]
        if extra_queries:
            queries_to_embed.extend(extra_queries[:1])   # استعلام إضافي واحد فقط

        for q in queries_to_embed:
            try:
                emb     = await self._embed(q)
                results = await self.vector_search(conn, emb, top_k, domain=domain)
                for r in results:
                    key = (r.get("law_name", ""), r.get("article_number", ""))
                    if key not in all_vec or r["score"] > all_vec[key]["score"]:
                        all_vec[key] = r
            except Exception as exc:
                log.warning("vector search '%s': %s", q[:30], exc)

        return list(all_vec.values())

    # ──────────────────────────────────────────────────────
    # 5. إنشاء فهرس FTS (اختياري — يُنفَّذ مرة واحدة)
    # ──────────────────────────────────────────────────────
    async def create_fts_index(self, conn) -> bool:
        """
        يُنشئ:
          - عمود content_tsv مُولَّد (GENERATED ALWAYS AS)
          - فهرس GIN عليه

        آمن للتشغيل مرات متعددة (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS).
        """
        try:
            await conn.execute(
                """
                ALTER TABLE chunks
                ADD COLUMN IF NOT EXISTS content_tsv tsvector
                GENERATED ALWAYS AS (to_tsvector('simple', coalesce(content,''))) STORED
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chunks_content_tsv
                ON chunks USING gin(content_tsv)
                """
            )
            log.info("create_fts_index: عمود وفهرس FTS جاهزان")
            return True
        except Exception as exc:
            log.warning("create_fts_index خطأ (ربما غير مدعوم): %s", exc)
            return False

    # ──────────────────────────────────────────────────────
    # 6. إحصاءات
    # ──────────────────────────────────────────────────────
    def get_stats(self) -> dict:
        return {
            "top_k"        : self.top_k,
            "rrf_k"        : self.rrf_k,
            "embed_fn"     : self._embed.__name__ if self._embed else None,
            "pool_available": self.pool is not None,
        }
