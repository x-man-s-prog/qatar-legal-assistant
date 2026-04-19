# -*- coding: utf-8 -*-
"""
اختبارات compare_service
========================
تختبر: CompareService, helpers, init/get.
بدون DB حقيقي — mocks فقط.
"""
import sys
import os
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from compare_service import (
    CompareService,
    init_compare_service,
    get_compare_service,
    _format_chunks,
    _build_compare_prompt,
    _parse_result,
    _empty_result,
)


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════
def _make_pool(fetch_return=None):
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=fetch_return or [])
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__  = AsyncMock(return_value=False)
    return pool, conn


def _make_db_row(law="قانون العمل", article="78", content="نص المادة"):
    row = MagicMock()
    data = {"law_name": law, "article_number": article, "content": content}
    row.__getitem__ = lambda self, k: data[k]
    return row


# ══════════════════════════════════════════════════════════════
# TestInit
# ══════════════════════════════════════════════════════════════
class TestInit:
    def test_init_returns_service(self):
        pool, _ = _make_pool()
        svc = init_compare_service(pool)
        assert isinstance(svc, CompareService)

    def test_get_returns_same_instance(self):
        pool, _ = _make_pool()
        svc = init_compare_service(pool)
        assert get_compare_service() is svc

    def test_init_replaces_singleton(self):
        pool1, _ = _make_pool()
        pool2, _ = _make_pool()
        init_compare_service(pool1)
        svc2 = init_compare_service(pool2)
        assert get_compare_service() is svc2

    def test_init_without_pool(self):
        svc = CompareService(None)
        assert svc._pool is None

    def test_init_with_llm_fn(self):
        pool, _ = _make_pool()
        fn = AsyncMock(return_value="{}")
        svc = CompareService(pool, llm_fn=fn)
        assert svc._llm_fn is fn


# ══════════════════════════════════════════════════════════════
# TestSearchLawChunks
# ══════════════════════════════════════════════════════════════
class TestSearchLawChunks:
    @pytest.mark.asyncio
    async def test_returns_chunks(self):
        row = _make_db_row("قانون العمل", "78", "يُلزم صاحب العمل بإشعار مسبق")
        pool, conn = _make_pool(fetch_return=[row])
        svc = CompareService(pool)
        result = await svc.search_law_chunks("قانون العمل", "إشعار")
        assert len(result) == 1
        assert result[0]["law"] == "قانون العمل"
        assert result[0]["article"] == "78"

    @pytest.mark.asyncio
    async def test_no_pool_returns_empty(self):
        svc = CompareService(None)
        result = await svc.search_law_chunks("قانون العمل", "إشعار")
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_law_name_returns_empty(self):
        pool, _ = _make_pool()
        svc = CompareService(pool)
        result = await svc.search_law_chunks("", "إشعار")
        assert result == []

    @pytest.mark.asyncio
    async def test_whitespace_law_name_returns_empty(self):
        pool, _ = _make_pool()
        svc = CompareService(pool)
        result = await svc.search_law_chunks("   ", "إشعار")
        assert result == []

    @pytest.mark.asyncio
    async def test_db_error_returns_empty(self):
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(side_effect=Exception("DB error"))
        svc = CompareService(pool)
        result = await svc.search_law_chunks("قانون العمل", "")
        assert result == []

    @pytest.mark.asyncio
    async def test_article_number_coerced_to_string(self):
        row = _make_db_row("قانون العمل", 78, "نص")  # int not str
        pool, conn = _make_pool(fetch_return=[row])
        svc = CompareService(pool)
        result = await svc.search_law_chunks("قانون العمل", "")
        assert isinstance(result[0]["article"], str)


# ══════════════════════════════════════════════════════════════
# TestCompare
# ══════════════════════════════════════════════════════════════
class TestCompare:
    @pytest.mark.asyncio
    async def test_empty_law_a_returns_error(self):
        pool, _ = _make_pool()
        svc = CompareService(pool)
        result = await svc.compare("", "قانون العقوبات")
        assert result["error"] != ""

    @pytest.mark.asyncio
    async def test_empty_law_b_returns_error(self):
        pool, _ = _make_pool()
        svc = CompareService(pool)
        result = await svc.compare("قانون العمل", "")
        assert result["error"] != ""

    @pytest.mark.asyncio
    async def test_no_chunks_returns_error(self):
        pool, conn = _make_pool(fetch_return=[])
        svc = CompareService(pool)
        result = await svc.compare("قانون العمل", "قانون العقوبات")
        assert result["error"] != ""
        assert result["source"] == "empty"

    @pytest.mark.asyncio
    async def test_with_llm_fn_parses_response(self):
        row = _make_db_row("قانون العمل", "78", "يُلزم بإشعار مسبق")
        pool, conn = _make_pool(fetch_return=[row])
        llm_resp = json.dumps({
            "aspect":     "الإشعار",
            "law_a":      {"text": "شهر كامل", "article": "78", "summary": "إشعار مسبق"},
            "law_b":      {"text": "أسبوعان",  "article": "15", "summary": "إشعار أقصر"},
            "difference": "مدة الإشعار تختلف",
        })
        llm_fn = AsyncMock(return_value=llm_resp)
        svc = CompareService(pool, llm_fn=llm_fn)
        result = await svc.compare("قانون العمل", "قانون العقوبات", "الإشعار")
        llm_fn.assert_called_once()
        assert result["source"] == "llm"
        assert result["difference"] == "مدة الإشعار تختلف"

    @pytest.mark.asyncio
    async def test_llm_error_falls_back_to_chunks(self):
        row = _make_db_row("قانون العمل", "78", "نص المادة")
        pool, conn = _make_pool(fetch_return=[row])
        llm_fn = AsyncMock(side_effect=Exception("LLM down"))
        svc = CompareService(pool, llm_fn=llm_fn)
        result = await svc.compare("قانون العمل", "قانون الأسرة")
        assert result["source"] == "chunks"
        assert result["law_a"]["text"] != ""

    @pytest.mark.asyncio
    async def test_compare_without_aspect(self):
        row = _make_db_row()
        pool, _ = _make_pool(fetch_return=[row])
        svc = CompareService(pool)
        result = await svc.compare("قانون العمل", "قانون الأسرة")
        assert "aspect" in result

    @pytest.mark.asyncio
    async def test_result_has_required_keys(self):
        row = _make_db_row()
        pool, _ = _make_pool(fetch_return=[row])
        svc = CompareService(pool)
        result = await svc.compare("قانون العمل", "قانون الأسرة", "العقوبات")
        for key in ("aspect", "law_a", "law_b", "difference", "error", "source"):
            assert key in result


# ══════════════════════════════════════════════════════════════
# TestHelpers
# ══════════════════════════════════════════════════════════════
class TestHelpers:

    # _format_chunks
    def test_format_chunks_empty_list(self):
        assert _format_chunks([]) == ""

    def test_format_chunks_single(self):
        chunks = [{"law": "قانون العمل", "article": "78", "text": "نص المادة 78"}]
        result = _format_chunks(chunks)
        assert "نص المادة 78" in result

    def test_format_chunks_includes_article_number(self):
        chunks = [{"law": "قانون العمل", "article": "78", "text": "نص"}]
        result = _format_chunks(chunks)
        assert "78" in result

    def test_format_chunks_no_article_skips_bracket(self):
        chunks = [{"law": "قانون العمل", "article": "", "text": "نص"}]
        result = _format_chunks(chunks)
        assert "المادة" not in result

    def test_format_chunks_max_4(self):
        chunks = [{"law": "Q", "article": str(i), "text": f"نص{i}"} for i in range(10)]
        result = _format_chunks(chunks)
        assert result.count("---") <= 3  # max 4 chunks = 3 separators

    # _build_compare_prompt
    def test_prompt_contains_law_names(self):
        prompt = _build_compare_prompt("قانون العمل", "قانون الأسرة", "الإشعار", "ctx_a", "ctx_b")
        assert "قانون العمل" in prompt
        assert "قانون الأسرة" in prompt

    def test_prompt_contains_contexts(self):
        prompt = _build_compare_prompt("A", "B", "", "نص القانون أ", "نص القانون ب")
        assert "نص القانون أ" in prompt
        assert "نص القانون ب" in prompt

    def test_prompt_requests_json(self):
        prompt = _build_compare_prompt("A", "B", "", "ctx", "ctx")
        assert "JSON" in prompt

    def test_prompt_contains_aspect_when_given(self):
        prompt = _build_compare_prompt("A", "B", "العقوبات", "c", "c")
        assert "العقوبات" in prompt

    # _parse_result
    def test_parse_valid_json(self):
        raw = json.dumps({
            "aspect":     "الإشعار",
            "law_a":      {"text": "شهر", "article": "78", "summary": "موجز أ"},
            "law_b":      {"text": "أسبوع", "article": "15", "summary": "موجز ب"},
            "difference": "الفرق في المدة",
        })
        result = _parse_result(raw, "A", "B", "الإشعار", [], [])
        assert result["source"] == "llm"
        assert result["law_a"]["text"] == "شهر"
        assert result["difference"] == "الفرق في المدة"

    def test_parse_invalid_json_uses_chunks(self):
        chunks_a = [{"law": "A", "article": "1", "text": "نص من chunk أ"}]
        result = _parse_result("INVALID", "A", "B", "", chunks_a, [])
        assert result["source"] == "chunks"
        assert "نص من chunk أ" in result["law_a"]["text"]

    def test_parse_empty_raw_uses_chunks(self):
        chunks_b = [{"law": "B", "article": "5", "text": "نص chunk ب"}]
        result = _parse_result("", "A", "B", "", [], chunks_b)
        assert result["law_b"]["text"] == "نص chunk ب"

    def test_parse_json_wrapped_in_text(self):
        raw = 'بالطبع، إليك المقارنة:\n' + json.dumps({
            "aspect": "X", "law_a": {"text": "t", "article": "1", "summary": "s"},
            "law_b": {"text": "t2", "article": "2", "summary": "s2"},
            "difference": "d",
        })
        result = _parse_result(raw, "A", "B", "X", [], [])
        assert result["source"] == "llm"

    # _empty_result
    def test_empty_result_structure(self):
        r = _empty_result("A", "B", "C", "خطأ")
        assert r["aspect"] == "C"
        assert r["law_a"]["name"] == "A"
        assert r["law_b"]["name"] == "B"
        assert r["error"] == "خطأ"
        assert r["source"] == "empty"

    def test_empty_result_default_aspect(self):
        r = _empty_result("A", "B", "")
        assert r["aspect"] == "مقارنة عامة"
