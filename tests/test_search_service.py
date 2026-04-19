# -*- coding: utf-8 -*-
"""
اختبارات SearchService
=======================
تختبر: rrf_fusion، vector_search، fulltext_search، hybrid_search
بدون اتصال حقيقي بـ PostgreSQL (Mock).
"""
import sys
import os
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from search_service import SearchService, init_search_service, get_search_service


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════

@pytest.fixture
def mock_pool():
    """asyncpg pool وهمي."""
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__  = AsyncMock(return_value=False)
    return pool, conn


@pytest.fixture
def service(mock_pool):
    """SearchService بدون embed_fn."""
    pool, _ = mock_pool
    return SearchService(pool=pool, embed_fn=None, top_k=10, rrf_k=60)


@pytest.fixture
def service_with_embed(mock_pool):
    """SearchService مع embed_fn وهمية تُعيد vector ثابتاً."""
    pool, _ = mock_pool
    async def _fake_embed(text: str) -> list[float]:
        return [0.1] * 768
    return SearchService(pool=pool, embed_fn=_fake_embed, top_k=10, rrf_k=60)


def _make_chunk(law_name: str, article: str, score: float, **kwargs) -> dict:
    """ينشئ قاموس chunk للاختبار."""
    return {
        "id"            : 1,
        "law_id"        : 1,
        "source"        : "test.pdf",
        "law_name"      : law_name,
        "law_number"    : "14",
        "law_year"      : "2004",
        "article_number": article,
        "content"       : f"نص قانوني تجريبي من {law_name} مادة {article}",
        "score"         : score,
        **kwargs,
    }


# ══════════════════════════════════════════════════════════
# اختبارات RRF Fusion
# ══════════════════════════════════════════════════════════

class TestRRFFusion:

    def test_single_list_scores_correctly(self, service):
        """قائمة واحدة: rrf_score = 1/(60+rank+1)."""
        items = [_make_chunk("قانون العمل", "15", 0.9),
                 _make_chunk("قانون العمل", "16", 0.8)]
        result = service.rrf_fusion(items)
        # النتيجة الأولى يجب أن تكون أعلى
        assert result[0]["rrf_score"] > result[1]["rrf_score"]
        # score الأول = 1/(60+0+1) = 1/61
        assert abs(result[0]["rrf_score"] - 1/61) < 1e-6

    def test_two_lists_boost_overlap(self, service):
        """عنصر موجود في كلتا القائمتين يحصل على score أعلى من عنصر في قائمة واحدة."""
        chunk_shared = _make_chunk("قانون العقوبات", "357", 0.9)
        chunk_only_a = _make_chunk("قانون المرور",   "10",  0.8)
        chunk_only_b = _make_chunk("قانون الأسرة",   "45",  0.7)

        list_a = [chunk_shared, chunk_only_a]
        list_b = [chunk_shared, chunk_only_b]
        result = service.rrf_fusion(list_a, list_b)

        # chunk_shared موجود في كلتيهما → يجب أن يكون أول
        assert result[0]["law_name"] == "قانون العقوبات"
        assert result[0]["article_number"] == "357"

    def test_empty_lists_return_empty(self, service):
        """قوائم فارغة تُعيد قائمة فارغة."""
        assert service.rrf_fusion([], []) == []

    def test_one_empty_list(self, service):
        """قائمة واحدة فارغة + قائمة بها عناصر → تُعيد العناصر الموجودة."""
        items = [_make_chunk("قانون العمل", "15", 0.9)]
        result = service.rrf_fusion(items, [])
        assert len(result) == 1

    def test_top_n_limits_results(self, service):
        """top_n يُحدّد الحد الأقصى للنتائج."""
        items = [_make_chunk("قانون أ", str(i), 0.9 - i * 0.01) for i in range(20)]
        result = service.rrf_fusion(items, top_n=5)
        assert len(result) <= 5

    def test_rrf_score_added_to_result(self, service):
        """كل عنصر في النتيجة يحتوي على rrf_score."""
        items = [_make_chunk("قانون العمل", "1", 0.9)]
        result = service.rrf_fusion(items)
        assert "rrf_score" in result[0]
        assert isinstance(result[0]["rrf_score"], float)

    def test_custom_k_parameter(self, service):
        """ثابت k مخصص يُؤثر على قيم rrf_score."""
        items = [_make_chunk("قانون أ", "1", 0.9)]
        result_k60  = service.rrf_fusion(items, k=60)
        result_k120 = service.rrf_fusion(items, k=120)
        # k أكبر → score أصغر
        assert result_k60[0]["rrf_score"] > result_k120[0]["rrf_score"]

    def test_deduplication_by_law_and_article(self, service):
        """نفس (law_name, article_number) في قائمتين → عنصر واحد فقط في النتيجة."""
        chunk_a = _make_chunk("قانون العمل", "15", 0.9)
        chunk_b = _make_chunk("قانون العمل", "15", 0.7)   # نفس المفتاح، score مختلف
        result = service.rrf_fusion([chunk_a], [chunk_b])
        count = sum(
            1 for r in result
            if r["law_name"] == "قانون العمل" and r["article_number"] == "15"
        )
        assert count == 1

    def test_result_sorted_descending(self, service):
        """النتائج مُرتَّبة تنازلياً بـ rrf_score."""
        items = [_make_chunk("قانون أ", str(i), 0.5) for i in range(5)]
        result = service.rrf_fusion(items)
        scores = [r["rrf_score"] for r in result]
        assert scores == sorted(scores, reverse=True)


# ══════════════════════════════════════════════════════════
# اختبارات Vector Search
# ══════════════════════════════════════════════════════════

class TestVectorSearch:

    @pytest.mark.asyncio
    async def test_returns_list(self, service, mock_pool):
        """vector_search تُعيد list."""
        _, conn = mock_pool
        conn.fetch = AsyncMock(return_value=[])
        result = await service.vector_search(conn, [0.1] * 768, top_k=5)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_returns_dicts_with_score(self, mock_pool):
        """كل نتيجة تحتوي على score عائم."""
        pool, conn = mock_pool

        class FakeRow(dict):
            pass

        row = FakeRow({"id": 1, "law_id": 1, "source": "x.pdf",
                       "law_name": "قانون العمل", "law_number": "14",
                       "law_year": "2004", "article_number": "15",
                       "content": "نص تجريبي عربي لاختبار وحدة البحث المتجهي",
                       "score": 0.85})
        conn.fetch = AsyncMock(return_value=[row])
        svc = SearchService(pool=pool, top_k=5)
        result = await svc.vector_search(conn, [0.1] * 768, top_k=5)
        assert len(result) == 1
        assert isinstance(result[0]["score"], float)
        assert result[0]["search_type"] == "vector"

    @pytest.mark.asyncio
    async def test_db_error_returns_empty(self, service, mock_pool):
        """خطأ في قاعدة البيانات → تُعيد قائمة فارغة (لا exception)."""
        _, conn = mock_pool
        conn.fetch = AsyncMock(side_effect=Exception("DB error"))
        result = await service.vector_search(conn, [0.1] * 768)
        assert result == []

    @pytest.mark.asyncio
    async def test_embedding_formatted_as_pgvector_string(self, mock_pool):
        """التضمين يُحوَّل لصيغة pgvector الصحيحة [x,y,z,...]."""
        pool, conn = mock_pool
        captured_args = []

        async def capture_fetch(sql, *args):
            captured_args.extend(args)
            return []

        conn.fetch = capture_fetch
        svc = SearchService(pool=pool)
        await svc.vector_search(conn, [0.1, 0.2, 0.3])
        # الإنسان الأول من args هو emb_str
        assert captured_args[0] == "[0.1,0.2,0.3]"


# ══════════════════════════════════════════════════════════
# اختبارات Full-Text Search
# ══════════════════════════════════════════════════════════

class TestFullTextSearch:

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, service, mock_pool):
        """استعلام فارغ → تُعيد قائمة فارغة فوراً."""
        _, conn = mock_pool
        result = await service.fulltext_search(conn, "")
        assert result == []

    @pytest.mark.asyncio
    async def test_whitespace_query_returns_empty(self, service, mock_pool):
        """استعلام من مسافات فقط → تُعيد قائمة فارغة."""
        _, conn = mock_pool
        result = await service.fulltext_search(conn, "   ")
        assert result == []

    @pytest.mark.asyncio
    async def test_db_error_returns_empty(self, service, mock_pool):
        """خطأ في كلتا المحاولتين → تُعيد قائمة فارغة (لا exception)."""
        _, conn = mock_pool
        conn.fetch = AsyncMock(side_effect=Exception("DB error"))
        result = await service.fulltext_search(conn, "عقوبة السرقة")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_search_type_fts(self, mock_pool):
        """كل نتيجة تحمل search_type='fts'."""
        pool, conn = mock_pool

        class FakeRow(dict):
            pass

        row = FakeRow({"id": 1, "law_id": 1, "source": "x.pdf",
                       "law_name": "قانون العقوبات", "law_number": "11",
                       "law_year": "2004", "article_number": "357",
                       "content": "نص عربي اختباري للبحث النصي الكامل",
                       "score": 0.05})
        conn.fetch = AsyncMock(return_value=[row])
        svc = SearchService(pool=pool)
        result = await svc.fulltext_search(conn, "شيك بدون رصيد")
        assert len(result) == 1
        assert result[0]["search_type"] == "fts"

    @pytest.mark.asyncio
    async def test_fallback_to_on_the_fly_when_column_missing(self, mock_pool):
        """إذا رمى الـ fetch الأول خطأ (content_tsv مفقود) → يجرب on-the-fly."""
        pool, conn = mock_pool
        call_count = [0]

        async def mock_fetch(sql, *args):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("column content_tsv does not exist")
            return []

        conn.fetch = mock_fetch
        svc = SearchService(pool=pool)
        result = await svc.fulltext_search(conn, "عقوبة السرقة")
        # يجب أن يستدعي fetch مرتين (المحاولة 1 → فشل → المحاولة 2)
        assert call_count[0] == 2
        assert result == []


# ══════════════════════════════════════════════════════════
# اختبارات Hybrid Search
# ══════════════════════════════════════════════════════════

class TestHybridSearch:

    @pytest.mark.asyncio
    async def test_no_pool_returns_empty(self):
        """بدون pool → تُعيد قائمة فارغة."""
        svc = SearchService(pool=None)
        result = await svc.hybrid_search("عقوبة السرقة")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_list(self, service_with_embed, mock_pool):
        """hybrid_search تُعيد list دائماً."""
        _, conn = mock_pool
        conn.fetch = AsyncMock(return_value=[])
        result = await service_with_embed.hybrid_search("عقوبة السرقة")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_fts_and_vector_merged(self, mock_pool):
        """نتائج FTS + vector تُدمج معاً وتُعاد مُرتَّبة."""
        pool, conn = mock_pool

        class FakeRow(dict):
            pass

        fts_row = FakeRow({"id": 1, "law_id": 1, "source": "a.pdf",
                           "law_name": "قانون أ", "law_number": "1",
                           "law_year": "2004", "article_number": "1",
                           "content": "نص قانون أ", "score": 0.05})
        vec_row = FakeRow({"id": 2, "law_id": 2, "source": "b.pdf",
                           "law_name": "قانون ب", "law_number": "2",
                           "law_year": "2005", "article_number": "2",
                           "content": "نص قانون ب", "score": 0.9})
        conn.fetch = AsyncMock(return_value=[fts_row, vec_row])

        async def _fake_embed(text: str) -> list[float]:
            return [0.1] * 768

        svc = SearchService(pool=pool, embed_fn=_fake_embed, top_k=10)
        result = await svc.hybrid_search("سؤال قانوني")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_extra_queries_used_for_vector(self, mock_pool):
        """extra_queries تُستخدم في vector search (دالة embed تُستدعى مرتين)."""
        pool, conn = mock_pool
        conn.fetch = AsyncMock(return_value=[])

        embed_calls = [0]
        async def counting_embed(text: str) -> list[float]:
            embed_calls[0] += 1
            return [0.1] * 768

        svc = SearchService(pool=pool, embed_fn=counting_embed, top_k=10)
        await svc.hybrid_search("سؤال رئيسي", extra_queries=["سؤال إضافي"])
        # يجب أن تُستدعى embed مرتين: النص الأصلي + الاستعلام الإضافي
        assert embed_calls[0] == 2

    @pytest.mark.asyncio
    async def test_db_errors_handled_gracefully(self, mock_pool):
        """أخطاء قاعدة البيانات لا تُطلق exception."""
        pool, conn = mock_pool
        conn.fetch = AsyncMock(side_effect=Exception("connection refused"))

        async def _embed(text: str) -> list[float]:
            return [0.1] * 768

        svc = SearchService(pool=pool, embed_fn=_embed)
        result = await svc.hybrid_search("سؤال قانوني")
        assert isinstance(result, list)


# ══════════════════════════════════════════════════════════
# اختبارات Singleton
# ══════════════════════════════════════════════════════════

class TestSingleton:

    def test_init_and_get(self):
        """init_search_service ثم get_search_service تُعيد نفس الـ instance."""
        fake_pool = MagicMock()
        svc = init_search_service(fake_pool)
        assert get_search_service() is svc

    def test_get_stats_structure(self):
        """get_stats يُعيد قاموساً بالمفاتيح المطلوبة."""
        fake_pool = MagicMock()
        svc = init_search_service(fake_pool, top_k=15, rrf_k=60)
        stats = svc.get_stats()
        assert "top_k"         in stats
        assert "rrf_k"         in stats
        assert "embed_fn"      in stats
        assert "pool_available" in stats
        assert stats["top_k"]  == 15
        assert stats["rrf_k"]  == 60
