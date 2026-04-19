# -*- coding: utf-8 -*-
"""
feedback_service.py — نظام تقييم الإجابات
==========================================
الجدول: feedback
  (id, query_id, session_id, rating, comment, created_at)

rating: +1 (إعجاب) | -1 (عدم إعجاب)
الإجابات المُقيَّمة بـ -1 تُحفظ لإعادة التدريب لاحقاً.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

log = logging.getLogger(__name__)

_CREATE_FEEDBACK_TABLE = """
CREATE TABLE IF NOT EXISTS feedback (
    id         SERIAL PRIMARY KEY,
    query_id   INTEGER,
    session_id TEXT    NOT NULL DEFAULT '',
    rating     INTEGER NOT NULL CHECK (rating IN (-1, 1)),
    comment    TEXT    DEFAULT '',
    query_text TEXT    DEFAULT '',
    answer_text TEXT   DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS feedback_created_idx ON feedback (created_at DESC);
CREATE INDEX IF NOT EXISTS feedback_rating_idx  ON feedback (rating);
CREATE INDEX IF NOT EXISTS feedback_query_id_idx ON feedback (query_id);
"""

_SINGLETON: Optional["FeedbackService"] = None


def init_feedback_service(pool) -> "FeedbackService":
    global _SINGLETON
    _SINGLETON = FeedbackService(pool)
    return _SINGLETON


def get_feedback_service() -> Optional["FeedbackService"]:
    return _SINGLETON


class FeedbackService:
    def __init__(self, pool):
        self._pool = pool

    async def ensure_table(self) -> bool:
        if not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(_CREATE_FEEDBACK_TABLE)
            log.info("✓ feedback table ready")
            return True
        except Exception as e:
            log.warning("ensure_table (feedback): %s", e)
            return False

    async def submit(
        self,
        rating: int,
        query_id: Optional[int] = None,
        session_id: str = "",
        comment: str = "",
        query_text: str = "",
        answer_text: str = "",
    ) -> dict:
        """Save a rating. Returns {"ok": True, "id": int}."""
        if rating not in (-1, 1):
            return {"ok": False, "error": "rating يجب أن يكون 1 أو -1"}
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """INSERT INTO feedback
                       (query_id, session_id, rating, comment, query_text, answer_text)
                       VALUES ($1, $2, $3, $4, $5, $6)
                       RETURNING id""",
                    query_id, session_id, rating,
                    comment[:500],
                    query_text[:300],
                    answer_text[:800],
                )
            return {"ok": True, "id": row["id"]}
        except Exception as e:
            log.warning("feedback.submit: %s", e)
            return {"ok": False, "error": "خطأ في قاعدة البيانات"}

    async def get_daily_stats(self, days: int = 7) -> dict:
        """Return daily avg rating, positive/negative counts."""
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT
                        DATE(created_at AT TIME ZONE 'Asia/Qatar') AS day,
                        COUNT(*) FILTER (WHERE rating = 1)  AS positive,
                        COUNT(*) FILTER (WHERE rating = -1) AS negative,
                        ROUND(AVG(rating::numeric), 2)      AS avg_rating
                    FROM feedback
                    WHERE created_at >= NOW() - ($1 || ' days')::INTERVAL
                    GROUP BY day ORDER BY day DESC
                    """,
                    str(days),
                )
            return {
                "days": [
                    {
                        "day":      str(r["day"]),
                        "positive": r["positive"],
                        "negative": r["negative"],
                        "avg":      float(r["avg_rating"] or 0),
                    }
                    for r in rows
                ],
                "total_days": days,
            }
        except Exception as e:
            log.warning("feedback.get_daily_stats: %s", e)
            return {"days": [], "total_days": days}

    async def get_worst_answers(self, limit: int = 10) -> list[dict]:
        """Return answers with the most negative feedback (for improvement)."""
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT query_text, answer_text, comment, created_at
                    FROM feedback
                    WHERE rating = -1
                      AND query_text != ''
                    ORDER BY created_at DESC
                    LIMIT $1
                    """,
                    limit,
                )
            return [
                {
                    "query":   r["query_text"],
                    "answer":  r["answer_text"][:200],
                    "comment": r["comment"],
                    "date":    r["created_at"].strftime("%Y-%m-%d") if r["created_at"] else "",
                }
                for r in rows
            ]
        except Exception as e:
            log.warning("feedback.get_worst_answers: %s", e)
            return []

    async def get_topic_needs(self, limit: int = 10) -> list[dict]:
        """Return topics (query keywords) that need improvement — from -1 feedback."""
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT query_text, COUNT(*) AS cnt
                    FROM feedback
                    WHERE rating = -1 AND query_text != ''
                    GROUP BY query_text
                    ORDER BY cnt DESC
                    LIMIT $1
                    """,
                    limit,
                )
            return [{"query": r["query_text"], "count": r["cnt"]} for r in rows]
        except Exception as e:
            log.warning("feedback.get_topic_needs: %s", e)
            return []

    async def get_summary(self) -> dict:
        """Overall feedback summary."""
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE rating = 1)  AS positive,
                        COUNT(*) FILTER (WHERE rating = -1) AS negative,
                        ROUND(AVG(rating::numeric) * 50 + 50, 1) AS satisfaction_pct
                    FROM feedback
                    """
                )
            return {
                "total":            row["total"],
                "positive":         row["positive"],
                "negative":         row["negative"],
                "satisfaction_pct": float(row["satisfaction_pct"] or 50),
            }
        except Exception as e:
            log.warning("feedback.get_summary: %s", e)
            return {"total": 0, "positive": 0, "negative": 0, "satisfaction_pct": 50.0}
