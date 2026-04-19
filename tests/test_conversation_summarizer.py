# -*- coding: utf-8 -*-
"""
اختبارات conversation_summarizer
===================================
تختبر: ConversationSummarizer, helpers, init/get, DB interactions.
بدون DB حقيقي — mocks فقط.
"""
import sys
import os
import pytest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from conversation_summarizer import (
    ConversationSummarizer,
    init_conversation_summarizer,
    get_conversation_summarizer,
    should_summarize,
    _build_summary_prompt,
    _extract_simple_summary,
    CREATE_TABLE_SQL,
    SUMMARY_INTERVAL,
)


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════
def _make_pool(fetchrow_return=None):
    conn = AsyncMock()
    conn.execute   = AsyncMock(return_value=None)
    conn.fetchrow  = AsyncMock(return_value=fetchrow_return)
    conn.fetchval  = AsyncMock(return_value=0)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__  = AsyncMock(return_value=False)
    return pool, conn


def _make_history(n: int, alternating: bool = True) -> list[dict]:
    history = []
    for i in range(n):
        role = "user" if (i % 2 == 0) else "assistant"
        history.append({"role": role, "content": f"رسالة {i}"})
    return history


def _make_summary_row(summary: str):
    row = MagicMock()
    row.__getitem__ = lambda self, k: {"summary": summary}[k]
    return row


# ══════════════════════════════════════════════════════════════
# TestInit
# ══════════════════════════════════════════════════════════════
class TestInit:
    def test_init_returns_service(self):
        pool, _ = _make_pool()
        svc = init_conversation_summarizer(pool)
        assert isinstance(svc, ConversationSummarizer)

    def test_get_returns_same_instance(self):
        pool, _ = _make_pool()
        svc = init_conversation_summarizer(pool)
        assert get_conversation_summarizer() is svc

    def test_init_replaces_singleton(self):
        pool1, _ = _make_pool()
        pool2, _ = _make_pool()
        init_conversation_summarizer(pool1)
        svc2 = init_conversation_summarizer(pool2)
        assert get_conversation_summarizer() is svc2

    def test_init_without_pool(self):
        svc = ConversationSummarizer(None)
        assert svc._pool is None


# ══════════════════════════════════════════════════════════════
# TestEnsureTable
# ══════════════════════════════════════════════════════════════
class TestEnsureTable:
    @pytest.mark.asyncio
    async def test_ensure_table_with_pool(self):
        pool, conn = _make_pool()
        svc = ConversationSummarizer(pool)
        result = await svc.ensure_table()
        assert result is True
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_table_without_pool(self):
        svc = ConversationSummarizer(None)
        result = await svc.ensure_table()
        assert result is False

    @pytest.mark.asyncio
    async def test_ensure_table_db_error(self):
        pool, conn = _make_pool()
        conn.execute = AsyncMock(side_effect=Exception("DB error"))
        svc = ConversationSummarizer(pool)
        result = await svc.ensure_table()
        assert result is False

    def test_ddl_has_required_columns(self):
        for col in ["session_id", "summary", "turn_count", "updated_at"]:
            assert col in CREATE_TABLE_SQL


# ══════════════════════════════════════════════════════════════
# TestGetSummary
# ══════════════════════════════════════════════════════════════
class TestGetSummary:
    @pytest.mark.asyncio
    async def test_returns_existing_summary(self):
        row = _make_summary_row("المستخدم يسأل عن قانون العمل")
        pool, _ = _make_pool(fetchrow_return=row)
        svc = ConversationSummarizer(pool)
        result = await svc.get_summary("s1")
        assert result == "المستخدم يسأل عن قانون العمل"

    @pytest.mark.asyncio
    async def test_no_row_returns_empty(self):
        pool, _ = _make_pool(fetchrow_return=None)
        svc = ConversationSummarizer(pool)
        result = await svc.get_summary("new_session")
        assert result == ""

    @pytest.mark.asyncio
    async def test_no_pool_returns_empty(self):
        svc = ConversationSummarizer(None)
        result = await svc.get_summary("s1")
        assert result == ""

    @pytest.mark.asyncio
    async def test_empty_session_id_returns_empty(self):
        pool, _ = _make_pool()
        svc = ConversationSummarizer(pool)
        result = await svc.get_summary("")
        assert result == ""

    @pytest.mark.asyncio
    async def test_db_error_returns_empty(self):
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(side_effect=Exception("DB error"))
        svc = ConversationSummarizer(pool)
        result = await svc.get_summary("s1")
        assert result == ""


# ══════════════════════════════════════════════════════════════
# TestMaybeSummarize
# ══════════════════════════════════════════════════════════════
class TestMaybeSummarize:
    @pytest.mark.asyncio
    async def test_below_threshold_no_db_call(self):
        pool, conn = _make_pool()
        svc = ConversationSummarizer(pool)
        history = _make_history(SUMMARY_INTERVAL - 1)
        await svc.maybe_summarize("s1", history)
        conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_at_threshold_calls_db(self):
        pool, conn = _make_pool()
        svc = ConversationSummarizer(pool)
        history = _make_history(SUMMARY_INTERVAL)
        await svc.maybe_summarize("s1", history)
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_history_no_crash(self):
        pool, conn = _make_pool()
        svc = ConversationSummarizer(pool)
        await svc.maybe_summarize("s1", [])
        conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_session_no_crash(self):
        pool, conn = _make_pool()
        svc = ConversationSummarizer(pool)
        await svc.maybe_summarize("", _make_history(SUMMARY_INTERVAL))
        conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_with_llm_fn_uses_llm(self):
        pool, conn = _make_pool()
        llm_fn = AsyncMock(return_value="ملخص المحادثة القانونية")
        svc = ConversationSummarizer(pool, llm_fn=llm_fn)
        history = _make_history(SUMMARY_INTERVAL)
        await svc.maybe_summarize("s1", history)
        llm_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_error_uses_simple_summary(self):
        pool, conn = _make_pool()
        llm_fn = AsyncMock(side_effect=Exception("LLM error"))
        svc = ConversationSummarizer(pool, llm_fn=llm_fn)
        history = _make_history(SUMMARY_INTERVAL)
        await svc.maybe_summarize("s1", history)
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_double_interval_also_summarizes(self):
        pool, conn = _make_pool()
        svc = ConversationSummarizer(pool)
        history = _make_history(SUMMARY_INTERVAL * 2)
        await svc.maybe_summarize("s1", history)
        conn.execute.assert_called_once()


# ══════════════════════════════════════════════════════════════
# TestBuildContext
# ══════════════════════════════════════════════════════════════
class TestBuildContext:
    @pytest.mark.asyncio
    async def test_returns_context_when_summary_exists(self):
        row = _make_summary_row("سياق قانوني هام")
        pool, _ = _make_pool(fetchrow_return=row)
        svc = ConversationSummarizer(pool)
        ctx = await svc.build_context("s1")
        assert "سياق قانوني هام" in ctx
        assert "سياق المحادثة" in ctx

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_summary(self):
        pool, _ = _make_pool(fetchrow_return=None)
        svc = ConversationSummarizer(pool)
        ctx = await svc.build_context("s1")
        assert ctx == ""

    @pytest.mark.asyncio
    async def test_returns_empty_without_pool(self):
        svc = ConversationSummarizer(None)
        ctx = await svc.build_context("s1")
        assert ctx == ""


# ══════════════════════════════════════════════════════════════
# TestHelpers
# ══════════════════════════════════════════════════════════════
class TestHelpers:

    # should_summarize
    def test_at_interval_returns_true(self):
        assert should_summarize(_make_history(SUMMARY_INTERVAL)) is True

    def test_below_interval_returns_false(self):
        assert should_summarize(_make_history(SUMMARY_INTERVAL - 1)) is False

    def test_empty_returns_false(self):
        assert should_summarize([]) is False

    def test_double_interval_returns_true(self):
        assert should_summarize(_make_history(SUMMARY_INTERVAL * 2)) is True

    def test_odd_count_returns_false(self):
        assert should_summarize(_make_history(SUMMARY_INTERVAL + 1)) is False

    # _build_summary_prompt
    def test_prompt_contains_user_content(self):
        history = [{"role": "user", "content": "سؤال قانوني"}]
        prompt = _build_summary_prompt(history)
        assert "سؤال قانوني" in prompt

    def test_prompt_requests_3_sentences(self):
        history = [{"role": "user", "content": "سؤال"}]
        prompt = _build_summary_prompt(history)
        assert "3" in prompt

    def test_prompt_limits_to_12_messages(self):
        history = _make_history(20)
        prompt = _build_summary_prompt(history)
        # 12 messages max = 12 ": " patterns
        assert prompt.count(": ") <= 12

    # _extract_simple_summary
    def test_extracts_first_user_message(self):
        history = [
            {"role": "user", "content": "ما حكم العقد؟"},
            {"role": "assistant", "content": "إجابة"},
        ]
        summary = _extract_simple_summary(history)
        assert "ما حكم العقد؟" in summary

    def test_empty_history_returns_empty(self):
        assert _extract_simple_summary([]) == ""

    def test_no_user_message_returns_empty(self):
        history = [{"role": "assistant", "content": "إجابة"}]
        assert _extract_simple_summary(history) == ""
