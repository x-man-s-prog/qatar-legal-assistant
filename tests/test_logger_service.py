# -*- coding: utf-8 -*-
"""
اختبارات logger_service
========================
تختبر: LoggerService، log_query()، get_analytics()، init/get، DDL، edge cases.

لا تحتاج اتصال DB حقيقي — تستخدم MagicMock/AsyncMock.
"""
import sys
import os
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from logger_service import (
    LoggerService,
    init_logger_service,
    get_logger_service,
    _empty_analytics,
    CREATE_TABLE_SQL,
)


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════

def _make_pool(fetchval_return=1, fetchrow_return=None, fetch_return=None):
    """ينشئ mock لـ asyncpg pool."""
    conn = AsyncMock()
    conn.execute   = AsyncMock(return_value=None)
    conn.fetchval  = AsyncMock(return_value=fetchval_return)
    conn.fetchrow  = AsyncMock(return_value=fetchrow_return)
    conn.fetch     = AsyncMock(return_value=fetch_return or [])

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__  = AsyncMock(return_value=False)
    return pool, conn


def _make_analytics_conn():
    """ينشئ mock لاتصال قاعدة بيانات يُعيد بيانات تحليلية."""
    conn = AsyncMock()

    async def fetchval_side(sql, *args, **kwargs):
        sql_lower = sql.strip().lower()
        if "count(*)" in sql_lower and "cache_hit" not in sql_lower and "< 60" not in sql_lower:
            return 142        # total_queries_today
        if "avg(response_ms)" in sql_lower:
            return 1840       # avg_response_ms
        if "cache_hit = true" in sql_lower:
            return 95         # cache_hits → 95/142 ≈ 67%
        if "avg(confidence_score)" in sql_lower:
            return 74         # avg_confidence
        if "< 60" in sql_lower:
            return 12         # low_confidence_queries
        return 0

    conn.fetchval = AsyncMock(side_effect=fetchval_side)
    conn.fetchrow = AsyncMock(return_value={"llm_provider": "openai", "cnt": 80})
    conn.fetch    = AsyncMock(return_value=[])

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__  = AsyncMock(return_value=False)
    return pool, conn


# ══════════════════════════════════════════════════════════════
# TestLoggerServiceInit — التهيئة والـ Singleton
# ══════════════════════════════════════════════════════════════
class TestLoggerServiceInit:

    def test_init_with_pool(self):
        """يُنشئ instance مع pool."""
        pool, _ = _make_pool()
        svc = LoggerService(pool)
        assert svc._pool is pool

    def test_init_without_pool(self):
        """يُنشئ instance بدون pool (None)."""
        svc = LoggerService(None)
        assert svc._pool is None

    def test_init_logger_service_returns_instance(self):
        """init_logger_service يُعيد LoggerService."""
        pool, _ = _make_pool()
        svc = init_logger_service(pool)
        assert isinstance(svc, LoggerService)

    def test_get_logger_service_after_init(self):
        """get_logger_service يُعيد نفس instance المُهيَّأ."""
        pool, _ = _make_pool()
        svc = init_logger_service(pool)
        assert get_logger_service() is svc

    def test_init_replaces_previous_instance(self):
        """استدعاء init مرتين يُحدّث الـ instance."""
        pool1, _ = _make_pool()
        pool2, _ = _make_pool()
        svc1 = init_logger_service(pool1)
        svc2 = init_logger_service(pool2)
        assert get_logger_service() is svc2
        assert svc1 is not svc2


# ══════════════════════════════════════════════════════════════
# TestEnsureTable — إنشاء الجدول
# ══════════════════════════════════════════════════════════════
class TestEnsureTable:

    @pytest.mark.asyncio
    async def test_ensure_table_with_pool_returns_true(self):
        """ensure_table مع pool → يُعيد True."""
        pool, conn = _make_pool()
        svc = LoggerService(pool)
        result = await svc.ensure_table()
        assert result is True

    @pytest.mark.asyncio
    async def test_ensure_table_executes_ddl(self):
        """ensure_table يُنفّذ الـ DDL."""
        pool, conn = _make_pool()
        svc = LoggerService(pool)
        await svc.ensure_table()
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_table_without_pool_returns_false(self):
        """ensure_table بدون pool → يُعيد False (no crash)."""
        svc = LoggerService(None)
        result = await svc.ensure_table()
        assert result is False

    @pytest.mark.asyncio
    async def test_ensure_table_db_error_returns_false(self):
        """ensure_table عند خطأ DB → يُعيد False (non-critical)."""
        pool, conn = _make_pool()
        conn.execute = AsyncMock(side_effect=Exception("connection error"))
        svc = LoggerService(pool)
        result = await svc.ensure_table()
        assert result is False

    def test_create_table_sql_has_required_columns(self):
        """CREATE_TABLE_SQL يحتوي على جميع الأعمدة المطلوبة."""
        required = [
            "id", "session_id", "query", "answer_length",
            "confidence_score", "llm_provider", "response_ms",
            "cache_hit", "citations_count", "created_at",
        ]
        for col in required:
            assert col in CREATE_TABLE_SQL, f"العمود '{col}' مفقود من DDL"

    def test_create_table_sql_has_indexes(self):
        """CREATE_TABLE_SQL يحتوي على فهارس."""
        assert "CREATE INDEX" in CREATE_TABLE_SQL


# ══════════════════════════════════════════════════════════════
# TestLogQuery — تسجيل الاستعلامات
# ══════════════════════════════════════════════════════════════
class TestLogQuery:

    @pytest.mark.asyncio
    async def test_log_query_returns_id(self):
        """log_query يُعيد id صحيح."""
        pool, conn = _make_pool(fetchval_return=42)
        svc = LoggerService(pool)
        result = await svc.log_query(
            session_id="s1",
            query="ما عقوبة السرقة؟",
            answer_length=400,
            confidence_score=82.0,
            llm_provider="openai",
            response_ms=1200,
            cache_hit=False,
            citations_count=3,
        )
        assert result == 42

    @pytest.mark.asyncio
    async def test_log_query_without_pool_returns_none(self):
        """log_query بدون pool → None بدون خطأ."""
        svc = LoggerService(None)
        result = await svc.log_query(query="سؤال")
        assert result is None

    @pytest.mark.asyncio
    async def test_log_query_db_error_returns_none(self):
        """log_query عند خطأ DB → None (non-critical)."""
        pool, conn = _make_pool()
        conn.fetchval = AsyncMock(side_effect=Exception("DB error"))
        svc = LoggerService(pool)
        result = await svc.log_query(query="سؤال")
        assert result is None

    @pytest.mark.asyncio
    async def test_log_query_truncates_long_query(self):
        """log_query يُقلّص الاستعلام الطويل إلى 500 حرف."""
        pool, conn = _make_pool(fetchval_return=1)
        svc = LoggerService(pool)
        long_query = "س" * 1000
        await svc.log_query(query=long_query)
        # تحقق أن الـ fetchval استُدعي مع قيمة < 500 حرف
        call_args = conn.fetchval.call_args
        assert len(call_args.args[1]) <= 500

    @pytest.mark.asyncio
    async def test_log_query_default_values(self):
        """log_query يعمل بالقيم الافتراضية فقط."""
        pool, conn = _make_pool(fetchval_return=5)
        svc = LoggerService(pool)
        result = await svc.log_query()
        assert result == 5

    @pytest.mark.asyncio
    async def test_log_query_passes_cache_hit_as_bool(self):
        """log_query يُمرّر cache_hit كـ bool."""
        pool, conn = _make_pool(fetchval_return=1)
        svc = LoggerService(pool)
        await svc.log_query(cache_hit=True)
        call_args = conn.fetchval.call_args
        # الوسيط السادس (index 6) هو cache_hit
        assert call_args.args[7] is True

    @pytest.mark.asyncio
    async def test_log_query_inserts_correct_sql(self):
        """log_query تستخدم INSERT ... RETURNING id."""
        pool, conn = _make_pool(fetchval_return=1)
        svc = LoggerService(pool)
        await svc.log_query(query="سؤال قانوني")
        sql_used = conn.fetchval.call_args.args[0]
        assert "INSERT INTO query_logs" in sql_used
        assert "RETURNING id" in sql_used


# ══════════════════════════════════════════════════════════════
# TestGetAnalytics — التحليلات
# ══════════════════════════════════════════════════════════════
class TestGetAnalytics:

    @pytest.mark.asyncio
    async def test_analytics_without_pool(self):
        """get_analytics بدون pool → empty analytics."""
        svc = LoggerService(None)
        result = await svc.get_analytics()
        assert result["total_queries_today"] == 0
        assert result["cache_hit_rate"] == "0%"

    @pytest.mark.asyncio
    async def test_analytics_returns_required_keys(self):
        """get_analytics يُعيد جميع المفاتيح المطلوبة."""
        svc = LoggerService(None)
        result = await svc.get_analytics()
        required_keys = [
            "total_queries_today", "avg_response_ms",
            "cache_hit_rate", "top_provider",
            "avg_confidence", "low_confidence_queries",
        ]
        for key in required_keys:
            assert key in result, f"مفتاح '{key}' مفقود"

    @pytest.mark.asyncio
    async def test_analytics_with_data(self):
        """get_analytics مع بيانات → قيم صحيحة."""
        pool, conn = _make_analytics_conn()
        svc = LoggerService(pool)
        result = await svc.get_analytics(days=1)

        assert result["total_queries_today"] == 142
        assert result["avg_response_ms"] == 1840
        assert result["top_provider"] == "openai"
        assert result["avg_confidence"] == 74
        assert result["low_confidence_queries"] == 12

    @pytest.mark.asyncio
    async def test_analytics_cache_rate_calculated(self):
        """نسبة الـ cache تُحسب صحيحة: 95/142 ≈ 66.9%."""
        pool, conn = _make_analytics_conn()
        svc = LoggerService(pool)
        result = await svc.get_analytics(days=1)
        rate = float(result["cache_hit_rate"].replace("%", ""))
        assert 65.0 < rate < 70.0

    @pytest.mark.asyncio
    async def test_analytics_zero_total_returns_empty(self):
        """عند total=0 → empty analytics."""
        pool, conn = _make_pool(fetchval_return=0)
        svc = LoggerService(pool)
        result = await svc.get_analytics()
        assert result["total_queries_today"] == 0

    @pytest.mark.asyncio
    async def test_analytics_db_error_returns_empty(self):
        """عند خطأ DB → empty analytics (non-critical)."""
        pool, conn = _make_pool()
        conn.fetchval = AsyncMock(side_effect=Exception("DB error"))
        svc = LoggerService(pool)
        result = await svc.get_analytics()
        assert result["total_queries_today"] == 0

    @pytest.mark.asyncio
    async def test_analytics_days_parameter(self):
        """days يُمرَّر صحيحاً للـ SQL."""
        pool, conn = _make_analytics_conn()
        svc = LoggerService(pool)
        await svc.get_analytics(days=7)
        # الـ fetchval الأول يُمرَّر له days_str
        first_call_sql = conn.fetchval.call_args_list[0].args[0]
        assert "days" in first_call_sql.lower() or "interval" in first_call_sql.lower()

    @pytest.mark.asyncio
    async def test_analytics_hourly_distribution_structure(self):
        """hourly_distribution قائمة من dicts."""
        svc = LoggerService(None)
        result = await svc.get_analytics()
        assert isinstance(result["hourly_distribution"], list)

    @pytest.mark.asyncio
    async def test_analytics_fastest_slowest_structure(self):
        """fastest_queries و slowest_queries قوائم."""
        svc = LoggerService(None)
        result = await svc.get_analytics()
        assert isinstance(result["fastest_queries"], list)
        assert isinstance(result["slowest_queries"], list)

    @pytest.mark.asyncio
    async def test_analytics_days_period_in_result(self):
        """days_period في النتيجة يساوي المُدخل."""
        svc = LoggerService(None)
        result = await svc.get_analytics(days=7)
        assert result["days_period"] == 7


# ══════════════════════════════════════════════════════════════
# TestEmptyAnalytics — هيكل البيانات الفارغة
# ══════════════════════════════════════════════════════════════
class TestEmptyAnalytics:

    def test_empty_analytics_structure(self):
        """_empty_analytics يُعيد هيكلاً صحيحاً."""
        result = _empty_analytics()
        assert result["total_queries_today"] == 0
        assert result["avg_response_ms"] == 0
        assert result["cache_hit_rate"] == "0%"
        assert result["top_provider"] == "—"
        assert result["avg_confidence"] == 0
        assert result["low_confidence_queries"] == 0
        assert result["hourly_distribution"] == []
        assert result["fastest_queries"] == []
        assert result["slowest_queries"] == []

    def test_empty_analytics_days_period(self):
        """_empty_analytics يحفظ days_period."""
        result = _empty_analytics(days=7)
        assert result["days_period"] == 7

    def test_empty_analytics_confidence_distribution(self):
        """_empty_analytics يحتوي confidence_distribution."""
        result = _empty_analytics()
        dist = result["confidence_distribution"]
        assert "high"   in dist
        assert "medium" in dist
        assert "low"    in dist
