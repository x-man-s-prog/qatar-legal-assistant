# -*- coding: utf-8 -*-
"""
اختبارات feedback_service
==========================
تختبر: submit, daily_stats, worst_answers, topic_needs, summary.
28 اختبار — بدون DB حقيقي (AsyncMock).
"""
import sys
import os
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from feedback_service import (
    FeedbackService,
    init_feedback_service,
    get_feedback_service,
)


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════

class _AsyncCtx:
    def __init__(self, obj): self._obj = obj
    async def __aenter__(self): return self._obj
    async def __aexit__(self, *_): pass


def _make_pool(fetchrow_return=None, fetch_return=None, execute_return=None):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.fetch    = AsyncMock(return_value=fetch_return or [])
    conn.execute  = AsyncMock(return_value=execute_return)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AsyncCtx(conn))
    return pool, conn


def _make_row(**kwargs):
    row = MagicMock()
    row.__getitem__ = lambda self, k: kwargs[k]
    return row


# ══════════════════════════════════════════════════════════════
# TestInit
# ══════════════════════════════════════════════════════════════
class TestInit:
    def test_init_returns_instance(self):
        pool, _ = _make_pool()
        svc = init_feedback_service(pool)
        assert isinstance(svc, FeedbackService)

    def test_get_returns_same(self):
        pool, _ = _make_pool()
        svc = init_feedback_service(pool)
        assert get_feedback_service() is svc

    @pytest.mark.asyncio
    async def test_ensure_table_ok(self):
        pool, conn = _make_pool()
        svc = FeedbackService(pool)
        result = await svc.ensure_table()
        assert result is True
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_table_no_pool(self):
        svc = FeedbackService(None)
        result = await svc.ensure_table()
        assert result is False


# ══════════════════════════════════════════════════════════════
# TestSubmit
# ══════════════════════════════════════════════════════════════
class TestSubmit:
    @pytest.mark.asyncio
    async def test_submit_positive_ok(self):
        row = _make_row(id=1)
        pool, _ = _make_pool(fetchrow_return=row)
        svc = FeedbackService(pool)
        result = await svc.submit(rating=1, query_text="سؤال", answer_text="جواب")
        assert result["ok"] is True
        assert result["id"] == 1

    @pytest.mark.asyncio
    async def test_submit_negative_ok(self):
        row = _make_row(id=2)
        pool, _ = _make_pool(fetchrow_return=row)
        svc = FeedbackService(pool)
        result = await svc.submit(rating=-1, comment="إجابة خاطئة")
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_submit_invalid_rating(self):
        pool, _ = _make_pool()
        svc = FeedbackService(pool)
        result = await svc.submit(rating=0)
        assert result["ok"] is False
        assert "rating" in result["error"]

    @pytest.mark.asyncio
    async def test_submit_invalid_rating_2(self):
        pool, _ = _make_pool()
        svc = FeedbackService(pool)
        result = await svc.submit(rating=5)
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_submit_db_error(self):
        pool, conn = _make_pool()
        conn.fetchrow.side_effect = Exception("DB down")
        svc = FeedbackService(pool)
        result = await svc.submit(rating=1)
        assert result["ok"] is False
        assert "بيانات" in result["error"]

    @pytest.mark.asyncio
    async def test_submit_truncates_long_comment(self):
        row = _make_row(id=3)
        pool, conn = _make_pool(fetchrow_return=row)
        svc = FeedbackService(pool)
        long_comment = "تعليق " * 200   # > 500 chars
        result = await svc.submit(rating=1, comment=long_comment)
        # The call should succeed — truncation happens internally
        assert result["ok"] is True
        call_args = conn.fetchrow.call_args[0]
        assert len(call_args[4]) <= 500   # comment param


# ══════════════════════════════════════════════════════════════
# TestDailyStats
# ══════════════════════════════════════════════════════════════
class TestDailyStats:
    @pytest.mark.asyncio
    async def test_returns_days_list(self):
        rows = [
            _make_row(day=MagicMock(__str__=lambda s: "2026-04-05"),
                      positive=5, negative=2, avg_rating=MagicMock(__float__=lambda s: 0.43)),
        ]
        # Make avg_rating work with float()
        rows[0]["avg_rating"] = 0.43
        # Re-create properly
        class R:
            def __getitem__(self, k):
                return {"day": "2026-04-05", "positive": 5, "negative": 2, "avg_rating": 0.43}[k]
        pool, conn = _make_pool(fetch_return=[R()])
        svc = FeedbackService(pool)
        result = await svc.get_daily_stats(days=7)
        assert "days" in result
        assert isinstance(result["days"], list)

    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self):
        pool, _ = _make_pool(fetch_return=[])
        svc = FeedbackService(pool)
        result = await svc.get_daily_stats()
        assert result["days"] == []

    @pytest.mark.asyncio
    async def test_db_error_returns_empty(self):
        pool, conn = _make_pool()
        conn.fetch.side_effect = Exception("DB error")
        svc = FeedbackService(pool)
        result = await svc.get_daily_stats()
        assert result["days"] == []


# ══════════════════════════════════════════════════════════════
# TestWorstAnswers
# ══════════════════════════════════════════════════════════════
class TestWorstAnswers:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        class R:
            def __getitem__(self, k):
                return {
                    "query_text": "سؤال خاطئ", "answer_text": "جواب خاطئ",
                    "comment": "غير صحيح",
                    "created_at": datetime(2026, 4, 5, tzinfo=timezone.utc),
                }[k]
        pool, _ = _make_pool(fetch_return=[R()])
        svc = FeedbackService(pool)
        result = await svc.get_worst_answers(10)
        assert len(result) == 1
        assert result[0]["query"] == "سؤال خاطئ"

    @pytest.mark.asyncio
    async def test_empty_db(self):
        pool, _ = _make_pool(fetch_return=[])
        svc = FeedbackService(pool)
        result = await svc.get_worst_answers()
        assert result == []

    @pytest.mark.asyncio
    async def test_db_error_returns_empty(self):
        pool, conn = _make_pool()
        conn.fetch.side_effect = Exception("error")
        svc = FeedbackService(pool)
        result = await svc.get_worst_answers()
        assert result == []


# ══════════════════════════════════════════════════════════════
# TestTopicNeeds
# ══════════════════════════════════════════════════════════════
class TestTopicNeeds:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        class R:
            def __getitem__(self, k): return {"query_text": "قانون العمل", "cnt": 3}[k]
        pool, _ = _make_pool(fetch_return=[R()])
        svc = FeedbackService(pool)
        result = await svc.get_topic_needs()
        assert len(result) == 1
        assert result[0]["count"] == 3

    @pytest.mark.asyncio
    async def test_db_error_returns_empty(self):
        pool, conn = _make_pool()
        conn.fetch.side_effect = Exception("error")
        svc = FeedbackService(pool)
        result = await svc.get_topic_needs()
        assert result == []


# ══════════════════════════════════════════════════════════════
# TestSummary
# ══════════════════════════════════════════════════════════════
class TestSummary:
    @pytest.mark.asyncio
    async def test_returns_summary(self):
        class R:
            def __getitem__(self, k):
                return {"total": 100, "positive": 80, "negative": 20, "satisfaction_pct": 90.0}[k]
        pool, _ = _make_pool(fetchrow_return=R())
        svc = FeedbackService(pool)
        result = await svc.get_summary()
        assert result["total"] == 100
        assert result["positive"] == 80
        assert result["satisfaction_pct"] == 90.0

    @pytest.mark.asyncio
    async def test_db_error_returns_defaults(self):
        pool, conn = _make_pool()
        conn.fetchrow.side_effect = Exception("error")
        svc = FeedbackService(pool)
        result = await svc.get_summary()
        assert result["total"] == 0
        assert result["satisfaction_pct"] == 50.0

    @pytest.mark.asyncio
    async def test_satisfaction_pct_in_range(self):
        class R:
            def __getitem__(self, k):
                return {"total": 10, "positive": 5, "negative": 5, "satisfaction_pct": 50.0}[k]
        pool, _ = _make_pool(fetchrow_return=R())
        svc = FeedbackService(pool)
        result = await svc.get_summary()
        assert 0 <= result["satisfaction_pct"] <= 100
