# -*- coding: utf-8 -*-
"""
logger_service.py — Professional Query Logging Service
=======================================================
يُسجّل كل استعلام في جدول query_logs بـ PostgreSQL
ويُوفّر تحليلات مجمّعة.

الجدول:
  query_logs (
    id               SERIAL PRIMARY KEY,
    session_id       TEXT,
    query            TEXT,
    answer_length    INTEGER,
    confidence_score FLOAT,
    llm_provider     TEXT,
    response_ms      INTEGER,
    cache_hit        BOOLEAN,
    citations_count  INTEGER,
    created_at       TIMESTAMPTZ DEFAULT NOW()
  )

الاستخدام:
    from logger_service import init_logger_service, get_logger_service

    # عند بدء التشغيل:
    svc = init_logger_service(pool)
    await svc.ensure_table()

    # بعد كل إجابة:
    await svc.log_query(
        session_id="abc123",
        query="ما عقوبة السرقة؟",
        answer_length=450,
        confidence_score=82.0,
        llm_provider="openai",
        response_ms=1240,
        cache_hit=False,
        citations_count=3,
    )
"""

from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger(__name__)

# ── DDL ──────────────────────────────────────────────────────
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS query_logs (
    id               SERIAL PRIMARY KEY,
    session_id       TEXT          DEFAULT '',
    query            TEXT          DEFAULT '',
    answer_length    INTEGER       DEFAULT 0,
    confidence_score FLOAT         DEFAULT 0.0,
    llm_provider     TEXT          DEFAULT '',
    response_ms      INTEGER       DEFAULT 0,
    cache_hit        BOOLEAN       DEFAULT FALSE,
    citations_count  INTEGER       DEFAULT 0,
    created_at       TIMESTAMPTZ   DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_query_logs_created_at
    ON query_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_query_logs_session
    ON query_logs (session_id);
CREATE INDEX IF NOT EXISTS idx_query_logs_provider
    ON query_logs (llm_provider);
"""

# ── Singleton ─────────────────────────────────────────────────
_service_instance: Optional["LoggerService"] = None


def init_logger_service(pool) -> "LoggerService":
    """ينشئ instance واحد ويحفظه عالمياً."""
    global _service_instance
    _service_instance = LoggerService(pool)
    return _service_instance


def get_logger_service() -> Optional["LoggerService"]:
    """يُعيد الـ instance المحفوظ."""
    return _service_instance


# ══════════════════════════════════════════════════════════════
# LoggerService
# ══════════════════════════════════════════════════════════════
class LoggerService:
    """
    خدمة تسجيل الاستعلامات بـ PostgreSQL.

    Parameters
    ----------
    pool : asyncpg pool (أو None — يعمل بدون تسجيل صامتاً)
    """

    def __init__(self, pool):
        self._pool = pool

    # ──────────────────────────────────────────────────────────
    # ensure_table
    # ──────────────────────────────────────────────────────────
    async def ensure_table(self) -> bool:
        """
        ينشئ جدول query_logs وفهارسه إذا لم تكن موجودة.
        يُعيد True عند النجاح، False عند الخطأ.
        """
        if not self._pool:
            log.debug("ensure_table: لا يوجد pool — تخطّي")
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(CREATE_TABLE_SQL)
            log.info("✓ query_logs table ready")
            return True
        except Exception as e:
            log.warning("ensure_table failed (non-critical): %s", e)
            return False

    # ──────────────────────────────────────────────────────────
    # log_query
    # ──────────────────────────────────────────────────────────
    async def log_query(
        self,
        session_id:       str   = "",
        query:            str   = "",
        answer_length:    int   = 0,
        confidence_score: float = 0.0,
        llm_provider:     str   = "",
        response_ms:      int   = 0,
        cache_hit:        bool  = False,
        citations_count:  int   = 0,
    ) -> Optional[int]:
        """
        يُسجّل استعلاماً واحداً ويُعيد الـ id.
        يُعيد None عند الخطأ (non-critical — لا يُوقف التطبيق).
        """
        if not self._pool:
            return None
        try:
            async with self._pool.acquire() as conn:
                row_id = await conn.fetchval(
                    """
                    INSERT INTO query_logs
                        (session_id, query, answer_length, confidence_score,
                         llm_provider, response_ms, cache_hit, citations_count)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING id
                    """,
                    str(session_id or "")[:100],
                    str(query or "")[:500],
                    int(answer_length or 0),
                    float(confidence_score or 0.0),
                    str(llm_provider or "")[:50],
                    int(response_ms or 0),
                    bool(cache_hit),
                    int(citations_count or 0),
                )
                log.debug("query_logs INSERT id=%s", row_id)
                return row_id
        except Exception as e:
            log.debug("log_query failed (non-critical): %s", e)
            return None

    # ──────────────────────────────────────────────────────────
    # get_analytics
    # ──────────────────────────────────────────────────────────
    async def get_analytics(self, days: int = 1) -> dict:
        """
        يُعيد إحصائيات مجمّعة عن الاستعلامات.

        Parameters
        ----------
        days : عدد الأيام للتحليل (1 = اليوم الحالي، 7 = أسبوع، ...)
        """
        if not self._pool:
            return _empty_analytics(days)
        try:
            async with self._pool.acquire() as conn:
                days_str = str(int(days))

                # ── إجمالي الاستعلامات ──────────────────────
                total: int = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM query_logs
                    WHERE created_at > NOW() - ($1 || ' days')::INTERVAL
                    """,
                    days_str,
                ) or 0

                if total == 0:
                    return _empty_analytics(days)

                # ── متوسط وقت الاستجابة ──────────────────────
                avg_ms: int = await conn.fetchval(
                    """
                    SELECT ROUND(AVG(response_ms))::INT
                    FROM query_logs
                    WHERE created_at > NOW() - ($1 || ' days')::INTERVAL
                      AND response_ms > 0
                    """,
                    days_str,
                ) or 0

                # ── نسبة الـ cache hit ────────────────────────
                cache_hits: int = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM query_logs
                    WHERE created_at > NOW() - ($1 || ' days')::INTERVAL
                      AND cache_hit = TRUE
                    """,
                    days_str,
                ) or 0
                cache_rate = round(cache_hits / total * 100, 1) if total > 0 else 0.0

                # ── أكثر provider استخداماً ───────────────────
                top_row = await conn.fetchrow(
                    """
                    SELECT llm_provider, COUNT(*) AS cnt
                    FROM query_logs
                    WHERE created_at > NOW() - ($1 || ' days')::INTERVAL
                      AND llm_provider != ''
                    GROUP BY llm_provider
                    ORDER BY cnt DESC LIMIT 1
                    """,
                    days_str,
                )
                top_provider = top_row["llm_provider"] if top_row else "—"

                # ── متوسط الثقة ───────────────────────────────
                avg_conf: int = await conn.fetchval(
                    """
                    SELECT ROUND(AVG(confidence_score))::INT
                    FROM query_logs
                    WHERE created_at > NOW() - ($1 || ' days')::INTERVAL
                      AND confidence_score > 0
                    """,
                    days_str,
                ) or 0

                # ── استعلامات الثقة المنخفضة (< 60) ──────────
                low_conf: int = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM query_logs
                    WHERE created_at > NOW() - ($1 || ' days')::INTERVAL
                      AND confidence_score > 0
                      AND confidence_score < 60
                    """,
                    days_str,
                ) or 0

                # ── توزيع بالساعة (آخر 24 ساعة) ──────────────
                hourly_rows = await conn.fetch(
                    """
                    SELECT date_trunc('hour', created_at) AS hour,
                           COUNT(*) AS cnt
                    FROM query_logs
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                    GROUP BY hour
                    ORDER BY hour
                    """
                )
                hourly = [
                    {"hour": str(r["hour"]), "count": int(r["cnt"])}
                    for r in hourly_rows
                ]

                # ── أسرع 5 استعلامات ──────────────────────────
                fast_rows = await conn.fetch(
                    """
                    SELECT query, response_ms FROM query_logs
                    WHERE created_at > NOW() - ($1 || ' days')::INTERVAL
                      AND response_ms > 0
                    ORDER BY response_ms ASC LIMIT 5
                    """,
                    days_str,
                )
                fastest = [
                    {"query": r["query"][:80], "ms": int(r["response_ms"])}
                    for r in fast_rows
                ]

                # ── أبطأ 5 استعلامات ──────────────────────────
                slow_rows = await conn.fetch(
                    """
                    SELECT query, response_ms FROM query_logs
                    WHERE created_at > NOW() - ($1 || ' days')::INTERVAL
                      AND response_ms > 0
                    ORDER BY response_ms DESC LIMIT 5
                    """,
                    days_str,
                )
                slowest = [
                    {"query": r["query"][:80], "ms": int(r["response_ms"])}
                    for r in slow_rows
                ]

                # ── توزيع مستوى الثقة ─────────────────────────
                conf_dist_rows = await conn.fetch(
                    """
                    SELECT
                        CASE
                            WHEN confidence_score >= 80 THEN 'high'
                            WHEN confidence_score >= 60 THEN 'medium'
                            ELSE 'low'
                        END AS band,
                        COUNT(*) AS cnt
                    FROM query_logs
                    WHERE created_at > NOW() - ($1 || ' days')::INTERVAL
                      AND confidence_score > 0
                    GROUP BY band
                    """,
                    days_str,
                )
                conf_dist = {r["band"]: int(r["cnt"]) for r in conf_dist_rows}

                return {
                    "total_queries_today"    : int(total),
                    "avg_response_ms"        : int(avg_ms),
                    "cache_hit_rate"         : f"{cache_rate}%",
                    "top_provider"           : top_provider,
                    "avg_confidence"         : int(avg_conf),
                    "low_confidence_queries" : int(low_conf),
                    "hourly_distribution"    : hourly,
                    "fastest_queries"        : fastest,
                    "slowest_queries"        : slowest,
                    "confidence_distribution": conf_dist,
                    "days_period"            : int(days),
                }

        except Exception as e:
            log.warning("get_analytics failed: %s", e)
            return _empty_analytics(days)


# ══════════════════════════════════════════════════════════════
# Helper
# ══════════════════════════════════════════════════════════════
def _empty_analytics(days: int = 1) -> dict:
    """يُعيد هيكل تحليلات فارغ."""
    return {
        "total_queries_today"    : 0,
        "avg_response_ms"        : 0,
        "cache_hit_rate"         : "0%",
        "top_provider"           : "—",
        "avg_confidence"         : 0,
        "low_confidence_queries" : 0,
        "hourly_distribution"    : [],
        "fastest_queries"        : [],
        "slowest_queries"        : [],
        "confidence_distribution": {"high": 0, "medium": 0, "low": 0},
        "days_period"            : int(days),
    }
