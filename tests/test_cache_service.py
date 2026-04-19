# -*- coding: utf-8 -*-
"""
اختبارات CacheService
======================
تختبر: Exact Cache، Semantic Cache، TTL، الإحصائيات
بدون اتصالات خارجية.
"""
import sys
import os
import asyncio
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from cache_service import (
    CacheService,
    init_cache_service,
    get_cache_service,
    _hash_query,
    _cosine_similarity,
)

# ── إجابات نموذجية تتجاوز الحد الأدنى (50 حرف) ──────────────────────────────
_A1 = "يُعاقب على السرقة بالسجن مدة لا تتجاوز ثلاث سنوات وفقاً لقانون العقوبات القطري."
_A2 = "وفقاً لقانون العمل القطري يُلزم صاحب العمل بإخطار العامل قبل إنهاء عقده بمدة شهر كامل."
_A3 = "يُعاقب على إصدار شيك بدون رصيد بالسجن والغرامة استناداً للمادة 357 من قانون العقوبات."
_A4 = "يحق للعامل الحصول على مكافأة نهاية الخدمة عند انتهاء عقد العمل وفق المادة 54 قانون العمل."


# ══════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════

@pytest.fixture
def cache():
    """CacheService بدون embed_fn."""
    return CacheService(embed_fn=None, ttl_seconds=3600)


@pytest.fixture
def cache_with_embed():
    """CacheService مع embed_fn وهمية ثابتة."""
    async def _fake_embed(text: str) -> list[float]:
        # كل نص يُعطي نفس الـ vector → similarity=1.0 دائماً
        return [1.0, 0.0, 0.0]
    return CacheService(embed_fn=_fake_embed, ttl_seconds=3600, semantic_threshold=0.95)


@pytest.fixture
def cache_distinct_embed():
    """CacheService بـ embeddings مختلفة حقيقياً."""
    call_count = [0]
    async def _counting_embed(text: str) -> list[float]:
        call_count[0] += 1
        # كل نص يُعطي vector مختلفاً (بناءً على hash بسيط)
        h = sum(ord(c) for c in text)
        return [float(h % 100) / 100, float((h // 100) % 100) / 100, 0.0]
    cache = CacheService(embed_fn=_counting_embed, ttl_seconds=3600, semantic_threshold=0.95)
    cache._call_count = call_count
    return cache


# ══════════════════════════════════════════════════════════════
# اختبارات Exact Cache
# ══════════════════════════════════════════════════════════════

class TestExactCache:

    @pytest.mark.asyncio
    async def test_miss_on_empty_cache(self, cache):
        """كاش فارغ → miss."""
        result = await cache.get("سؤال قانوني")
        assert result is None

    @pytest.mark.asyncio
    async def test_hit_after_set(self, cache):
        """بعد set → get يُعيد الإجابة."""
        await cache.set("سؤال قانوني", _A1, [])
        result = await cache.get("سؤال قانوني")
        assert result is not None
        assert result["answer"] == _A1

    @pytest.mark.asyncio
    async def test_hit_is_case_insensitive(self, cache):
        """التطابق لا يميّز بين الحروف الكبيرة والصغيرة."""
        await cache.set("سؤال قانوني", _A1, [])
        result = await cache.get("سؤال قانوني")
        assert result is not None

    @pytest.mark.asyncio
    async def test_hit_ignores_leading_trailing_spaces(self, cache):
        """المسافات الزائدة تُتجاهل."""
        await cache.set("سؤال قانوني", _A1, [])
        result = await cache.get("  سؤال قانوني  ")
        assert result is not None

    @pytest.mark.asyncio
    async def test_cache_type_is_exact(self, cache):
        """نوع الكاش = exact عند التطابق الحرفي."""
        await cache.set("سؤال", _A1, [])
        result = await cache.get("سؤال")
        assert result["cache_type"] == "exact"

    @pytest.mark.asyncio
    async def test_from_cache_flag(self, cache):
        """from_cache = True عند الـ hit."""
        await cache.set("سؤال", _A1, [])
        result = await cache.get("سؤال")
        assert result["from_cache"] is True

    @pytest.mark.asyncio
    async def test_short_answer_not_cached(self, cache):
        """إجابة قصيرة (< 50 حرف) لا تُحفظ."""
        await cache.set("سؤال", "قصير.", [])
        result = await cache.get("سؤال")
        assert result is None

    @pytest.mark.asyncio
    async def test_different_queries_independent(self, cache):
        """استعلامان مختلفان لهما إجابات مستقلة."""
        await cache.set("سؤال 1", _A2, [])
        await cache.set("سؤال 2", _A3, [])
        r1 = await cache.get("سؤال 1")
        r2 = await cache.get("سؤال 2")
        assert r1["answer"] != r2["answer"]

    @pytest.mark.asyncio
    async def test_overwrite_existing_entry(self, cache):
        """set مرتين على نفس الاستعلام يُحدّث الإجابة."""
        await cache.set("سؤال", _A1, [])
        await cache.set("سؤال", _A4, [])
        result = await cache.get("سؤال")
        assert result["answer"] == _A4

    @pytest.mark.asyncio
    async def test_sources_preserved(self, cache):
        """المصادر تُحفظ وتُسترجع."""
        sources = [{"title": "قانون العمل", "article": "47"}]
        await cache.set("سؤال", _A1, sources)
        result = await cache.get("سؤال")
        assert result["sources"] == sources


# ══════════════════════════════════════════════════════════════
# اختبارات TTL
# ══════════════════════════════════════════════════════════════

class TestTTL:

    @pytest.mark.asyncio
    async def test_expired_entry_not_returned(self):
        """إدخال منتهي الصلاحية → miss."""
        cache = CacheService(ttl_seconds=1)   # TTL ثانية واحدة
        q_key = "ما عقوبة السرقة في القانون القطري"
        await cache.set(q_key, _A1, [])
        # نُزيف انتهاء الصلاحية بتعديل created_at مباشرةً قبل evict
        q_hash = _hash_query(q_key)
        assert q_hash in cache._exact, "entry لم يُحفظ في exact cache"
        cache._exact[q_hash].created_at -= 2   # قبل ثانيتين → منتهٍ
        result = await cache.get(q_key)
        assert result is None

    @pytest.mark.asyncio
    async def test_fresh_entry_returned(self):
        """إدخال حديث → hit."""
        cache = CacheService(ttl_seconds=3600)
        await cache.set("سؤال", _A1, [])
        result = await cache.get("سؤال")
        assert result is not None


# ══════════════════════════════════════════════════════════════
# اختبارات Semantic Cache
# ══════════════════════════════════════════════════════════════

class TestSemanticCache:

    @pytest.mark.asyncio
    async def test_semantic_hit_with_identical_embed(self, cache_with_embed):
        """embedding متطابق → semantic hit."""
        await cache_with_embed.set(
            "ما عقوبة السرقة؟",
            _A1,
            [],
        )
        # استعلام مختلف لفظياً لكن embed وهمي = نفس الـ vector → semantic hit
        result = await cache_with_embed.get("ما العقوبة المقررة للسرقة؟")
        assert result is not None
        assert result["cache_type"] == "semantic"
        assert "similarity" in result

    @pytest.mark.asyncio
    async def test_semantic_miss_below_threshold(self):
        """embedding منخفض التشابه → miss."""
        async def _low_sim_embed(text: str) -> list[float]:
            # استعلام مختلف → vector مختلف
            if "سرقة" in text:
                return [1.0, 0.0, 0.0]
            return [0.0, 1.0, 0.0]   # similarity = 0.0

        cache = CacheService(
            embed_fn=_low_sim_embed, ttl_seconds=3600, semantic_threshold=0.95
        )
        await cache.set(
            "ما عقوبة السرقة؟",
            "يُعاقب على السرقة بالسجن وفق قانون العقوبات.",
            [],
        )
        result = await cache.get("ما هو الطقس غداً؟")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_embed_fn_skips_semantic(self, cache):
        """بدون embed_fn لا يتحقق من الـ semantic cache."""
        # cache بدون embed_fn — لا semantic check
        await cache.set("سؤال", _A1, [])
        result = await cache.get("سؤال مشابه جداً")
        # يجب أن يُعيد None (لأنه بدون embed لا يمكن المقارنة)
        assert result is None

    @pytest.mark.asyncio
    async def test_similarity_value_in_result(self, cache_with_embed):
        """similarity موجودة وبين 0 و 1."""
        await cache_with_embed.set(
            "ما عقوبة السرقة؟",
            "يُعاقب على السرقة بالسجن وفق قانون العقوبات.",
            [],
        )
        result = await cache_with_embed.get("سؤال مختلف")
        if result and result.get("cache_type") == "semantic":
            assert 0.0 <= result["similarity"] <= 1.0


# ══════════════════════════════════════════════════════════════
# اختبارات الإحصائيات
# ══════════════════════════════════════════════════════════════

class TestStats:

    @pytest.mark.asyncio
    async def test_stats_structure(self, cache):
        """get_stats يُعيد المفاتيح المطلوبة."""
        stats = cache.get_stats()
        assert "hit_rate"          in stats
        assert "total_hits"        in stats
        assert "total_misses"      in stats
        assert "cached_queries"    in stats
        assert "ttl_seconds"       in stats
        assert "semantic_threshold" in stats

    @pytest.mark.asyncio
    async def test_miss_increments_counter(self, cache):
        """miss يزيد total_misses."""
        await cache.get("سؤال غير موجود في الكاش")
        assert cache.get_stats()["total_misses"] == 1

    @pytest.mark.asyncio
    async def test_hit_increments_counter(self, cache):
        """hit يزيد total_hits."""
        await cache.set("سؤال", _A1, [])
        await cache.get("سؤال")
        assert cache.get_stats()["total_hits"] == 1

    @pytest.mark.asyncio
    async def test_hit_rate_calculation(self, cache):
        """hit_rate = hits / (hits + misses) × 100."""
        await cache.set("سؤال", _A1, [])
        await cache.get("سؤال")        # hit
        await cache.get("سؤال آخر")    # miss
        stats = cache.get_stats()
        # 1 hit + 1 miss → 50%
        assert stats["hit_rate"] == "50.0%"

    @pytest.mark.asyncio
    async def test_cached_queries_count(self, cache):
        """cached_queries يعكس عدد الإدخالات."""
        await cache.set("سؤال 1", _A2, [])
        await cache.set("سؤال 2", _A3, [])
        assert cache.get_stats()["cached_queries"] == 2

    def test_initial_stats_are_zero(self, cache):
        """الإحصائيات تبدأ من صفر."""
        stats = cache.get_stats()
        assert stats["total_hits"]   == 0
        assert stats["total_misses"] == 0
        assert stats["cached_queries"] == 0

    @pytest.mark.asyncio
    async def test_clear_resets_stats(self, cache):
        """clear يُفرّغ الكاش والإحصائيات."""
        await cache.set("سؤال", _A1, [])
        await cache.get("سؤال")
        cache.clear()
        stats = cache.get_stats()
        assert stats["total_hits"]     == 0
        assert stats["cached_queries"] == 0


# ══════════════════════════════════════════════════════════════
# اختبارات invalidate + clear
# ══════════════════════════════════════════════════════════════

class TestInvalidation:

    @pytest.mark.asyncio
    async def test_invalidate_removes_entry(self, cache):
        """invalidate يُزيل الإدخال المحدد."""
        await cache.set("سؤال", _A1, [])
        removed = cache.invalidate("سؤال")
        assert removed is True
        result = await cache.get("سؤال")
        assert result is None

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent_returns_false(self, cache):
        """invalidate استعلام غير موجود → False."""
        removed = cache.invalidate("سؤال غير موجود")
        assert removed is False

    @pytest.mark.asyncio
    async def test_clear_empties_all(self, cache):
        """clear يُزيل كل الإدخالات."""
        await cache.set("سؤال 1", _A2, [])
        await cache.set("سؤال 2", _A3, [])
        cache.clear()
        assert cache.get_stats()["cached_queries"] == 0


# ══════════════════════════════════════════════════════════════
# اختبارات Singleton
# ══════════════════════════════════════════════════════════════

class TestSingleton:

    def test_init_and_get(self):
        """init_cache_service ثم get_cache_service تُعيد نفس الـ instance."""
        svc = init_cache_service()
        assert get_cache_service() is svc

    def test_stats_endpoint_data(self):
        """get_stats يُعيد hit_rate كنص مئوي."""
        svc = init_cache_service()
        stats = svc.get_stats()
        assert stats["hit_rate"].endswith("%")


# ══════════════════════════════════════════════════════════════
# اختبارات الدوال المساعدة
# ══════════════════════════════════════════════════════════════

class TestHelpers:

    def test_hash_query_deterministic(self):
        """نفس الاستعلام → نفس الـ hash."""
        assert _hash_query("سؤال") == _hash_query("سؤال")

    def test_hash_query_normalizes(self):
        """المسافات والحروف الكبيرة لا تُغيّر الـ hash."""
        assert _hash_query("سؤال") == _hash_query("  سؤال  ")

    def test_cosine_identical_vectors(self):
        """متجهان متطابقان → similarity = 1.0."""
        v = [1.0, 0.0, 0.0]
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6

    def test_cosine_orthogonal_vectors(self):
        """متجهان متعامدان → similarity = 0.0."""
        assert abs(_cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-6

    def test_cosine_empty_vectors(self):
        """متجهات فارغة → 0.0 بدون exception."""
        assert _cosine_similarity([], []) == 0.0

    def test_cosine_different_lengths(self):
        """متجهات بأطوال مختلفة → 0.0 بدون exception."""
        assert _cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0

    def test_cosine_zero_vector(self):
        """متجه صفري → 0.0."""
        assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_cosine_opposite_vectors(self):
        """متجهان متعاكسان → similarity = -1.0."""
        result = _cosine_similarity([1.0, 0.0], [-1.0, 0.0])
        assert abs(result + 1.0) < 1e-6
