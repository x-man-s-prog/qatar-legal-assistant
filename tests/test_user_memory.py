# -*- coding: utf-8 -*-
"""
اختبارات user_memory
=====================
تختبر: UserMemoryService, helper functions, init/get, DB interactions.
لا تحتاج DB حقيقي — تستخدم mocks.
"""
import sys
import os
import pytest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from user_memory import (
    UserMemoryService,
    init_user_memory,
    get_user_memory,
    _extract_topic,
    _extract_cited_laws,
    _detect_detail_preference,
    _empty_prefs,
    CREATE_TABLE_SQL,
)


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════
def _make_pool(fetchrow_return=None, fetchval_return=0):
    conn = AsyncMock()
    conn.execute   = AsyncMock(return_value=None)
    conn.fetchval  = AsyncMock(return_value=fetchval_return)
    conn.fetchrow  = AsyncMock(return_value=fetchrow_return)
    conn.fetch     = AsyncMock(return_value=[])

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__  = AsyncMock(return_value=False)
    return pool, conn


def _make_row(session_id="s1", detail="standard", topics=None, laws=None, count=5):
    row = MagicMock()
    row.__getitem__ = lambda self, k: {
        "session_id":            session_id,
        "preferred_detail_level": detail,
        "common_topics":         topics or ["قانون العمل"],
        "last_laws_cited":       laws or ["قانون العقوبات"],
        "query_count":           count,
    }[k]
    return row


# ══════════════════════════════════════════════════════════════
# TestInit
# ══════════════════════════════════════════════════════════════
class TestInit:
    def test_init_with_pool(self):
        pool, _ = _make_pool()
        svc = UserMemoryService(pool)
        assert svc._pool is pool

    def test_init_without_pool(self):
        svc = UserMemoryService(None)
        assert svc._pool is None

    def test_init_user_memory_returns_service(self):
        pool, _ = _make_pool()
        svc = init_user_memory(pool)
        assert isinstance(svc, UserMemoryService)

    def test_get_user_memory_after_init(self):
        pool, _ = _make_pool()
        svc = init_user_memory(pool)
        assert get_user_memory() is svc

    def test_init_replaces_singleton(self):
        pool1, _ = _make_pool()
        pool2, _ = _make_pool()
        svc1 = init_user_memory(pool1)
        svc2 = init_user_memory(pool2)
        assert get_user_memory() is svc2


# ══════════════════════════════════════════════════════════════
# TestEnsureTable
# ══════════════════════════════════════════════════════════════
class TestEnsureTable:
    @pytest.mark.asyncio
    async def test_ensure_table_with_pool(self):
        pool, conn = _make_pool()
        svc = UserMemoryService(pool)
        result = await svc.ensure_table()
        assert result is True
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_table_without_pool(self):
        svc = UserMemoryService(None)
        result = await svc.ensure_table()
        assert result is False

    @pytest.mark.asyncio
    async def test_ensure_table_db_error_returns_false(self):
        pool, conn = _make_pool()
        conn.execute = AsyncMock(side_effect=Exception("DB error"))
        svc = UserMemoryService(pool)
        result = await svc.ensure_table()
        assert result is False

    def test_ddl_has_required_columns(self):
        for col in ["session_id", "preferred_detail_level", "common_topics",
                    "last_laws_cited", "query_count", "updated_at"]:
            assert col in CREATE_TABLE_SQL


# ══════════════════════════════════════════════════════════════
# TestGetPreferences
# ══════════════════════════════════════════════════════════════
class TestGetPreferences:
    @pytest.mark.asyncio
    async def test_get_preferences_existing_row(self):
        row = _make_row(session_id="s1", detail="detailed", count=10)
        pool, conn = _make_pool(fetchrow_return=row)
        svc = UserMemoryService(pool)
        prefs = await svc.get_preferences("s1")
        assert prefs["session_id"] == "s1"
        assert prefs["preferred_detail_level"] == "detailed"
        assert prefs["query_count"] == 10

    @pytest.mark.asyncio
    async def test_get_preferences_no_row_returns_empty(self):
        pool, conn = _make_pool(fetchrow_return=None)
        svc = UserMemoryService(pool)
        prefs = await svc.get_preferences("new_session")
        assert prefs["query_count"] == 0
        assert prefs["common_topics"] == []

    @pytest.mark.asyncio
    async def test_get_preferences_without_pool(self):
        svc = UserMemoryService(None)
        prefs = await svc.get_preferences("s1")
        assert prefs["query_count"] == 0

    @pytest.mark.asyncio
    async def test_get_preferences_db_error_returns_empty(self):
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(side_effect=Exception("DB error"))
        svc = UserMemoryService(pool)
        prefs = await svc.get_preferences("s1")
        assert prefs["common_topics"] == []


# ══════════════════════════════════════════════════════════════
# TestUpdateAfterAnswer
# ══════════════════════════════════════════════════════════════
class TestUpdateAfterAnswer:
    @pytest.mark.asyncio
    async def test_update_executes_upsert(self):
        pool, conn = _make_pool()
        svc = UserMemoryService(pool)
        await svc.update_after_answer(
            session_id="s1",
            query="ما عقوبة السرقة؟",
            answer="تُعاقب المادة 380 من قانون العقوبات على السرقة.",
        )
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_without_pool_no_crash(self):
        svc = UserMemoryService(None)
        await svc.update_after_answer("s1", "سؤال", "إجابة")
        # يجب ألا يرمي خطأ

    @pytest.mark.asyncio
    async def test_update_empty_session_id_no_crash(self):
        pool, conn = _make_pool()
        svc = UserMemoryService(pool)
        await svc.update_after_answer("", "سؤال", "إجابة")
        conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_db_error_no_crash(self):
        pool, conn = _make_pool()
        conn.execute = AsyncMock(side_effect=Exception("DB error"))
        svc = UserMemoryService(pool)
        await svc.update_after_answer("s1", "سؤال", "إجابة")
        # لا يجب أن يرمي خطأ


# ══════════════════════════════════════════════════════════════
# TestBuildUserContext
# ══════════════════════════════════════════════════════════════
class TestBuildUserContext:
    @pytest.mark.asyncio
    async def test_context_empty_for_new_user(self):
        """مستخدم جديد (query_count < 2) → context فارغ."""
        pool, conn = _make_pool(fetchrow_return=None)
        svc = UserMemoryService(pool)
        ctx = await svc.build_user_context("new_user")
        assert ctx == ""

    @pytest.mark.asyncio
    async def test_context_includes_topics(self):
        """مستخدم له مواضيع → تظهر في context."""
        row = _make_row(
            session_id="s1",
            topics=["قانون العمل"],
            count=5,
        )
        pool, conn = _make_pool(fetchrow_return=row)
        svc = UserMemoryService(pool)
        ctx = await svc.build_user_context("s1")
        assert "قانون العمل" in ctx

    @pytest.mark.asyncio
    async def test_context_includes_detail_preference(self):
        """مستخدم يفضّل مفصّل → يظهر في context."""
        row = _make_row(session_id="s1", detail="detailed", count=3)
        pool, conn = _make_pool(fetchrow_return=row)
        svc = UserMemoryService(pool)
        ctx = await svc.build_user_context("s1")
        assert "مفصّلة" in ctx

    @pytest.mark.asyncio
    async def test_context_without_pool_returns_empty(self):
        svc = UserMemoryService(None)
        ctx = await svc.build_user_context("s1")
        assert ctx == ""


# ══════════════════════════════════════════════════════════════
# TestHelperFunctions
# ══════════════════════════════════════════════════════════════
class TestHelperFunctions:

    # _extract_topic
    def test_extract_topic_labor(self):
        topic = _extract_topic("كم مدة إشعار إنهاء عقد العمل؟")
        assert topic == "قانون العمل"

    def test_extract_topic_criminal(self):
        topic = _extract_topic("ما عقوبة السرقة؟")
        assert topic == "قانون العقوبات"

    def test_extract_topic_family(self):
        topic = _extract_topic("ما إجراءات الطلاق في قطر؟")
        assert topic == "قانون الأسرة"

    def test_extract_topic_unknown_returns_empty(self):
        topic = _extract_topic("ما هو الطقس اليوم؟")
        assert topic == ""

    # _extract_cited_laws
    def test_extract_laws_from_citations(self):
        citations = [{"source": "قانون العمل", "article": "78"}]
        laws = _extract_cited_laws("", citations, None)
        assert "قانون العمل" in laws

    def test_extract_laws_from_sources(self):
        sources = [{"title": "قانون العقوبات القطري", "law_num": "11"}]
        laws = _extract_cited_laws("", None, sources)
        assert "قانون العقوبات القطري" in laws

    def test_extract_laws_deduplicates(self):
        citations = [
            {"source": "قانون العمل"},
            {"source": "قانون العمل"},
        ]
        laws = _extract_cited_laws("", citations, None)
        assert laws.count("قانون العمل") == 1

    def test_extract_laws_empty_inputs(self):
        laws = _extract_cited_laws("", None, None)
        assert isinstance(laws, list)

    # _detect_detail_preference
    def test_detect_detailed_preference(self):
        pref = _detect_detail_preference("اشرح لي بالتفصيل قانون العمل")
        assert pref == "detailed"

    def test_detect_brief_preference(self):
        pref = _detect_detail_preference("باختصار ما عقوبة السرقة؟")
        assert pref == "brief"

    def test_detect_standard_preference(self):
        pref = _detect_detail_preference("ما عقوبة السرقة؟")
        assert pref == "standard"

    # _empty_prefs
    def test_empty_prefs_structure(self):
        prefs = _empty_prefs("test_session")
        assert prefs["session_id"] == "test_session"
        assert prefs["query_count"] == 0
        assert prefs["common_topics"] == []
        assert prefs["last_laws_cited"] == []
        assert prefs["preferred_detail_level"] == "standard"
