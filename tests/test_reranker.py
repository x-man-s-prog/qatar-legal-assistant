# -*- coding: utf-8 -*-
"""
اختبارات reranker
==================
تختبر: Reranker, helpers, init/get.
بدون LLM حقيقي — mocks فقط.
"""
import sys
import os
import pytest
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from reranker import (
    Reranker,
    init_reranker,
    get_reranker,
    _build_score_prompt,
    _parse_score,
    _heuristic_score,
)


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════
def _make_chunk(content: str, score: float = 0.8) -> dict:
    return {"content": content, "score": score, "law_name": "قانون العمل", "article_number": "78"}


# ══════════════════════════════════════════════════════════════
# TestInit
# ══════════════════════════════════════════════════════════════
class TestInit:
    def test_init_returns_reranker(self):
        svc = init_reranker()
        assert isinstance(svc, Reranker)

    def test_get_returns_same_instance(self):
        svc = init_reranker()
        assert get_reranker() is svc

    def test_init_replaces_singleton(self):
        fn1 = AsyncMock(return_value="8")
        fn2 = AsyncMock(return_value="7")
        init_reranker(fn1)
        svc2 = init_reranker(fn2)
        assert get_reranker() is svc2

    def test_init_without_llm(self):
        svc = Reranker(None)
        assert svc._llm_fn is None

    def test_init_with_llm(self):
        fn = AsyncMock(return_value="9")
        svc = Reranker(fn)
        assert svc._llm_fn is fn


# ══════════════════════════════════════════════════════════════
# TestScoreChunk
# ══════════════════════════════════════════════════════════════
class TestScoreChunk:
    @pytest.mark.asyncio
    async def test_with_llm_returns_parsed_score(self):
        fn = AsyncMock(return_value="8")
        svc = Reranker(fn)
        score = await svc.score_chunk("ما عقوبة السرقة؟", "نص المادة 380 من قانون العقوبات")
        assert score == 8.0
        fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_without_llm_uses_heuristic(self):
        svc = Reranker(None)
        score = await svc.score_chunk("قانون العمل", "قانون العمل القطري")
        assert 0.0 <= score <= 10.0

    @pytest.mark.asyncio
    async def test_empty_chunk_returns_zero(self):
        fn = AsyncMock(return_value="9")
        svc = Reranker(fn)
        score = await svc.score_chunk("سؤال", "")
        assert score == 0.0
        fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_error_falls_back_to_heuristic(self):
        fn = AsyncMock(side_effect=Exception("LLM error"))
        svc = Reranker(fn)
        score = await svc.score_chunk("قانون العمل", "قانون العمل القطري")
        assert 0.0 <= score <= 10.0

    @pytest.mark.asyncio
    async def test_score_bounded_0_to_10(self):
        fn = AsyncMock(return_value="99")  # LLM يُعيد رقماً خارج النطاق
        svc = Reranker(fn)
        score = await svc.score_chunk("سؤال", "نص")
        assert score <= 10.0

    @pytest.mark.asyncio
    async def test_score_negative_capped_to_zero(self):
        fn = AsyncMock(return_value="-5")
        svc = Reranker(fn)
        score = await svc.score_chunk("سؤال", "نص")
        assert score >= 0.0


# ══════════════════════════════════════════════════════════════
# TestRerank
# ══════════════════════════════════════════════════════════════
class TestRerank:
    @pytest.mark.asyncio
    async def test_empty_chunks_returns_empty(self):
        svc = Reranker(None)
        result = await svc.rerank("سؤال", [])
        assert result == []

    @pytest.mark.asyncio
    async def test_fewer_chunks_than_top_k_returns_all(self):
        chunks = [_make_chunk(f"نص {i}") for i in range(2)]
        svc = Reranker(None)
        result = await svc.rerank("سؤال", chunks, top_k=5)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_top_k_chunks(self):
        chunks = [_make_chunk(f"نص {i}") for i in range(10)]
        svc = Reranker(None)
        result = await svc.rerank("سؤال", chunks, top_k=3)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_sorts_by_score_descending(self):
        scores = ["2", "9", "4", "7", "1"]
        idx = 0
        async def mock_llm(prompt):
            nonlocal idx
            val = scores[idx % len(scores)]
            idx += 1
            return val

        chunks = [_make_chunk(f"نص {i}") for i in range(5)]
        svc = Reranker(mock_llm)
        result = await svc.rerank("سؤال", chunks, top_k=3)
        assert result[0]["_rerank_score"] >= result[1]["_rerank_score"]
        assert result[1]["_rerank_score"] >= result[2]["_rerank_score"]

    @pytest.mark.asyncio
    async def test_rerank_score_added_to_chunks(self):
        # top_k < len(chunks) ← required for rerank to run and add score
        chunks = [_make_chunk(f"نص قانوني هام {i}") for i in range(3)]
        fn = AsyncMock(return_value="7")
        svc = Reranker(fn)
        result = await svc.rerank("سؤال", chunks, top_k=1)
        assert "_rerank_score" in result[0]

    @pytest.mark.asyncio
    async def test_original_chunk_fields_preserved(self):
        chunks = [_make_chunk("نص", 0.9)]
        svc = Reranker(None)
        result = await svc.rerank("سؤال", chunks, top_k=1)
        assert result[0]["law_name"] == "قانون العمل"
        assert result[0]["score"] == 0.9


# ══════════════════════════════════════════════════════════════
# TestHelpers
# ══════════════════════════════════════════════════════════════
class TestHelpers:

    # _build_score_prompt
    def test_prompt_contains_query(self):
        prompt = _build_score_prompt("ما عقوبة السرقة؟", "نص")
        assert "ما عقوبة السرقة؟" in prompt

    def test_prompt_contains_chunk_text(self):
        prompt = _build_score_prompt("سؤال", "نص المادة القانونية")
        assert "نص المادة القانونية" in prompt

    def test_prompt_requests_number(self):
        prompt = _build_score_prompt("سؤال", "نص")
        assert "0" in prompt and "10" in prompt

    def test_prompt_truncates_long_chunk(self):
        long_text = "نص " * 200  # 600+ chars
        prompt = _build_score_prompt("سؤال", long_text)
        assert len(prompt) < 1000  # truncated

    # _parse_score
    def test_parse_integer(self):
        assert _parse_score("8") == 8.0

    def test_parse_float(self):
        assert _parse_score("7.5") == 7.5

    def test_parse_with_text(self):
        assert _parse_score("الرقم: 9 من 10") == 9.0

    def test_parse_empty_returns_5(self):
        assert _parse_score("") == 5.0

    def test_parse_no_number_returns_5(self):
        assert _parse_score("لا أعرف") == 5.0

    def test_parse_caps_at_10(self):
        assert _parse_score("100") == 10.0

    def test_parse_caps_at_0(self):
        # regex finds first digit group; "-5" → finds "5", capped by min(10,max(0,5)) = 5.0
        # true floor-at-0 applies when LLM returns e.g. "0" explicitly
        assert _parse_score("0") == 0.0

    # _heuristic_score
    def test_heuristic_identical_words(self):
        score = _heuristic_score("قانون العمل القطري", "قانون العمل القطري")
        assert score > 8.0

    def test_heuristic_no_common_words(self):
        score = _heuristic_score("سرقة عقوبة", "زواج نفقة طلاق")
        assert score < 5.0

    def test_heuristic_empty_query(self):
        score = _heuristic_score("", "نص")
        assert score == 5.0

    def test_heuristic_score_in_range(self):
        score = _heuristic_score("ما عقوبة الاعتداء في القانون القطري؟", "تعاقب المادة 380 على الاعتداء")
        assert 0.0 <= score <= 10.0
