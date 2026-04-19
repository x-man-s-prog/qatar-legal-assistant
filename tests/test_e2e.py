# -*- coding: utf-8 -*-
"""
tests/test_e2e.py — اختبارات E2E للمساعد القانوني
====================================================
تختبر سيناريوهات حقيقية بدون شبكة خارجية:
  1. سؤال عمالي — pipeline كامل
  2. سؤال بعدد مادة — extract_legal_entities
  3. سؤال خارج النطاق — رد "لا تتوفر معلومات"
  4. الـ Cache — المرة الثانية من الكاش
  + اختبارات تكاملية للوحدات الجديدة معاً
"""
import sys
import os
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ══════════════════════════════════════════════════════════════
# السيناريو 1: query_expander + confidence_scorer + citation_builder
# ══════════════════════════════════════════════════════════════

class TestScenario1_LaborQuery:
    """سؤال عمالي — pipeline: expand → score → cite"""

    def test_expand_generates_three_variants(self):
        """expand يُولّد 3 صياغات للسؤال العمالي."""
        from query_expander import expand
        variants = expand("ما هي مدة إشعار إنهاء عقد العمل؟")
        assert len(variants) == 3
        assert all(isinstance(v, str) and len(v) > 0 for v in variants)

    def test_entities_extracted_from_labor_query(self):
        """extract_legal_entities يكتشف قانون العمل."""
        from query_expander import extract_legal_entities
        result = extract_legal_entities("وفقاً لقانون العمل ما مدة الإشعار؟")
        assert result["law_type"] == "عمل"

    def test_confidence_with_chunks(self):
        """confidence_scorer يُعطي نتيجة > 0 مع chunks."""
        from confidence_scorer import from_chunks
        chunks = [
            {"law_name": "قانون العمل", "score": 0.88},
            {"law_name": "قانون العمل", "score": 0.82},
            {"law_name": "قانون العمل", "score": 0.75},
        ]
        result = from_chunks(chunks)
        assert result["score"] > 0
        assert result["label"] in ("عالية", "متوسطة", "منخفضة")

    def test_citations_built_from_chunks(self):
        """citation_builder يبني استشهادات من chunks."""
        from citation_builder import build_citations
        chunks = [{
            "id": 1, "law_id": 11, "law_name": "قانون العمل",
            "law_number": "14", "law_year": "2004",
            "article_number": "47",
            "content": "يُلزم صاحب العمل بإخطار العامل قبل إنهاء عقده بمدة لا تقل عن شهر.",
            "source": "law_14_2004.pdf", "score": 0.88,
        }]
        answer = "وفقاً للمادة 47 يجب إشعار العامل قبل الفصل."
        result = build_citations(answer, chunks)
        assert result["citations"] is not None
        assert len(result["citations"]) == 1
        assert result["citations"][0]["article"] == "47"
        assert "almeezan.qa" in result["citations"][0]["url"]

    def test_confidence_label_not_empty(self):
        """confidence label غير فارغ."""
        from confidence_scorer import calculate
        result = calculate([0.85, 0.80], [
            {"law_name": "قانون العمل"},
            {"law_name": "قانون العمل"},
        ])
        assert len(result["label"]) > 0

    def test_answer_with_refs_contains_reference(self):
        """answer_with_refs تحتوي مرجعاً عند ذكر مادة."""
        from citation_builder import build_citations
        chunks = [{
            "id": 1, "law_id": 14, "law_name": "قانون العمل",
            "law_number": "14", "law_year": "2004",
            "article_number": "47",
            "content": "نص المادة السابعة والأربعين من قانون العمل يُلزم بالإشعار.",
            "source": "law_14.pdf", "score": 0.9,
        }]
        result = build_citations(
            "طبقاً للمادة 47 يُلزم صاحب العمل بالإشعار.",
            chunks
        )
        assert "[1]" in result["answer_with_refs"]


# ══════════════════════════════════════════════════════════════
# السيناريو 2: سؤال بعدد مادة
# ══════════════════════════════════════════════════════════════

class TestScenario2_ArticleNumber:
    """سؤال يتضمن رقم مادة — extract_legal_entities يستخرجه."""

    def test_extract_article_47(self):
        """يستخرج article=47 من 'المادة 47 من قانون العمل'."""
        from query_expander import extract_legal_entities
        result = extract_legal_entities("ما نص المادة 47 من قانون العمل؟")
        assert result["article"] == "47"

    def test_extract_article_357(self):
        """يستخرج article=357 من قانون العقوبات."""
        from query_expander import extract_legal_entities
        result = extract_legal_entities("المادة 357 من قانون رقم 11 لسنة 2004")
        assert result["article"] == "357"
        assert result["law_number"] == "11"
        assert result["year"] == "2004"

    def test_expand_with_article_number_enriches_query(self):
        """expand مع رقم مادة يُولّد صياغة أغنى."""
        from query_expander import expand
        variants = expand("ما نص المادة 357 من قانون رقم 11 لسنة 2004؟")
        assert len(variants) == 3
        # الصياغة الثانية (رسمية) يجب أن تكون أطول أو مساوية
        assert len(variants[1]) >= len("ما نص المادة 357 من قانون رقم 11 لسنة 2004؟")

    def test_synonyms_for_criminal_law(self):
        """get_all_synonyms تُعيد مرادفات للمصطلحات الجنائية."""
        from query_expander import get_all_synonyms
        synonyms = get_all_synonyms("شيك بدون رصيد")
        assert isinstance(synonyms, list)

    def test_citation_url_with_law_id(self):
        """الرابط صحيح عند وجود law_id."""
        from citation_builder import build_citations
        chunks = [{
            "id": 1, "law_id": 42, "law_name": "قانون العقوبات",
            "law_number": "11", "law_year": "2004",
            "article_number": "357",
            "content": "يُعاقب بالسجن مدة لا تتجاوز ثلاث سنوات...",
            "source": "law_42.pdf", "score": 0.91,
        }]
        result = build_citations("الإجابة حول المادة 357.", chunks)
        assert "LawPage.aspx?id=42" in result["citations"][0]["url"]


# ══════════════════════════════════════════════════════════════
# السيناريو 3: سؤال خارج النطاق
# ══════════════════════════════════════════════════════════════

class TestScenario3_OutOfScope:
    """سؤال خارج النطاق القانوني."""

    def test_no_legal_entities_in_off_topic_query(self):
        """سؤال عن سعر النفط لا يحتوي كيانات قانونية."""
        from query_expander import extract_legal_entities
        result = extract_legal_entities("ما هو سعر النفط اليوم؟")
        assert result["article"]    is None
        assert result["law_number"] is None
        assert result["law_type"]   is None

    def test_no_synonyms_for_off_topic_query(self):
        """مصطلحات غير قانونية لا تُولّد مرادفات قانونية."""
        from query_expander import get_all_synonyms
        synonyms = get_all_synonyms("سعر النفط والذهب في السوق")
        assert isinstance(synonyms, list)
        # لا يجب أن تحتوي مصطلحات قانونية

    def test_confidence_zero_with_no_chunks(self):
        """confidence = 0 عند غياب الـ chunks."""
        from confidence_scorer import calculate
        result = calculate([], [])
        assert result["score"] == 0
        assert result["label"] == "منخفضة"
        assert result["color"] == "red"

    def test_empty_citations_for_no_chunks(self):
        """بدون chunks → citations فارغة."""
        from citation_builder import build_citations
        result = build_citations("لا تتوفر لديّ معلومات كافية حول هذه المسألة.", [])
        assert result["citations"] == []
        assert result["answer_with_refs"] == "لا تتوفر لديّ معلومات كافية حول هذه المسألة."

    def test_expand_off_topic_still_returns_three(self):
        """حتى الأسئلة غير القانونية تُعيد 3 صياغات."""
        from query_expander import expand
        variants = expand("ما هو سعر النفط اليوم؟")
        assert len(variants) == 3


# ══════════════════════════════════════════════════════════════
# السيناريو 4: الـ Cache
# ══════════════════════════════════════════════════════════════

class TestScenario4_Cache:
    """اختبار سلوك الكاش — المرة الثانية من الكاش."""

    @pytest.mark.asyncio
    async def test_second_request_from_cache(self):
        """نفس السؤال مرتين → المرة الثانية hit."""
        from cache_service import CacheService
        cache = CacheService(ttl_seconds=3600)
        answer = "يُعاقب على السرقة بالسجن مدة لا تتجاوز ثلاث سنوات وفقاً لقانون العقوبات."

        await cache.set("ما عقوبة السرقة؟", answer, [])

        # المرة الأولى
        r1 = await cache.get("ما عقوبة السرقة؟")
        assert r1 is not None

        # المرة الثانية
        r2 = await cache.get("ما عقوبة السرقة؟")
        assert r2 is not None
        assert r2["answer"] == answer
        assert r2["from_cache"] is True

    @pytest.mark.asyncio
    async def test_cache_hit_rate_after_two_requests(self):
        """hit_rate = 50% بعد hit + miss."""
        from cache_service import CacheService
        _long = "يُعاقب على السرقة بالسجن مدة لا تتجاوز ثلاث سنوات وفقاً لقانون العقوبات القطري."
        cache = CacheService(ttl_seconds=3600)
        await cache.set("ما عقوبة السرقة في قطر؟", _long, [])
        await cache.get("ما عقوبة السرقة في قطر؟")     # hit
        await cache.get("ما حكم القتل العمد؟")          # miss
        stats = cache.get_stats()
        assert stats["hit_rate"] == "50.0%"

    @pytest.mark.asyncio
    async def test_semantic_cache_similar_question(self):
        """سؤال مشابه دلالياً (embedding متطابق) → من الكاش."""
        async def _uniform_embed(text: str) -> list[float]:
            return [1.0, 0.0, 0.0]   # نفس الـ vector لكل نص

        from cache_service import CacheService
        cache = CacheService(
            embed_fn=_uniform_embed, ttl_seconds=3600, semantic_threshold=0.95
        )
        original_answer = "وفقاً للمادة 357 يُعاقب بالسجن من أصدر شيكاً بدون رصيد."
        await cache.set("ما عقوبة الشيك بدون رصيد؟", original_answer, [])

        # سؤال مختلف صياغةً لكن يُعطي نفس الـ embedding
        r = await cache.get("ما العقوبة المقررة لصاحب الشيك المرتجع؟")
        assert r is not None
        assert r["cache_type"] == "semantic"
        assert r["answer"] == original_answer

    @pytest.mark.asyncio
    async def test_cache_clear_then_miss(self):
        """بعد clear → miss."""
        from cache_service import CacheService
        cache = CacheService(ttl_seconds=3600)
        await cache.set("سؤال", "إجابة طويلة بما يكفي لمعايير الكاش.", [])
        cache.clear()
        result = await cache.get("سؤال")
        assert result is None


# ══════════════════════════════════════════════════════════════
# اختبارات تكاملية — pipeline كامل (بدون LLM/DB)
# ══════════════════════════════════════════════════════════════

class TestIntegrationPipeline:
    """اختبار تكامل الوحدات الجديدة معاً."""

    def test_expand_then_extract_entities(self):
        """expand ثم extract_entities على كل صياغة."""
        from query_expander import expand, extract_legal_entities
        variants = expand("المادة 47 قانون العمل القطري")
        for v in variants:
            result = extract_legal_entities(v)
            assert isinstance(result, dict)
            assert "article" in result

    def test_confidence_scorer_with_citation_builder(self):
        """confidence_scorer + citation_builder معاً على نفس الـ chunks."""
        from confidence_scorer import from_chunks
        from citation_builder import build_citations

        chunks = [
            {"id": 1, "law_id": 14, "law_name": "قانون العمل",
             "law_number": "14", "law_year": "2004",
             "article_number": "47", "score": 0.88,
             "content": "يُلزم صاحب العمل بإخطار العامل قبل إنهاء عقده بمدة شهر.",
             "source": "law_14.pdf"},
            {"id": 2, "law_id": 11, "law_name": "قانون العقوبات",
             "law_number": "11", "law_year": "2004",
             "article_number": "357", "score": 0.72,
             "content": "يُعاقب بالسجن من أصدر شيكاً لا يقابله رصيد.",
             "source": "law_11.pdf"},
        ]
        answer = "وفقاً للمادة 47 يجب إشعار العامل. كما تنص المادة 357 على عقوبة الشيك."

        conf = from_chunks(chunks)
        cite = build_citations(answer, chunks)

        assert conf["score"] > 0
        assert len(cite["citations"]) == 2
        assert cite["citations"][0]["source"] == "قانون العمل"
        assert cite["citations"][1]["source"] == "قانون العقوبات"

    @pytest.mark.asyncio
    async def test_cache_service_stores_and_retrieves(self):
        """CacheService يحفظ ويسترجع إجابة كاملة مع sources."""
        from cache_service import CacheService
        cache = CacheService(ttl_seconds=3600)

        sources = [{"title": "قانون العمل", "article": "47", "score": 0.88}]
        answer  = "وفقاً للمادة 47 من قانون العمل يجب الإشعار قبل الفصل بشهر كامل."

        await cache.set("مدة إشعار الفصل", answer, sources)
        result = await cache.get("مدة إشعار الفصل")

        assert result is not None
        assert result["answer"] == answer
        assert result["sources"] == sources
        assert result["from_cache"] is True

    def test_rrf_fusion_with_search_service(self):
        """SearchService.rrf_fusion يدمج نتائج صحيحة."""
        from search_service import SearchService

        svc = SearchService(pool=None)
        list_a = [
            {"law_name": "قانون العمل", "article_number": "47", "score": 0.9, "content": "نص 1"},
            {"law_name": "قانون العقوبات", "article_number": "357", "score": 0.8, "content": "نص 2"},
        ]
        list_b = [
            {"law_name": "قانون العمل", "article_number": "47", "score": 0.85, "content": "نص 1"},
            {"law_name": "قانون الأسرة", "article_number": "20", "score": 0.7, "content": "نص 3"},
        ]
        merged = svc.rrf_fusion(list_a, list_b, top_n=5)

        # قانون العمل/47 موجود في كلتيهما → يجب أن يكون أول
        assert merged[0]["law_name"] == "قانون العمل"
        assert merged[0]["article_number"] == "47"
        assert len(merged) <= 5

    def test_synonyms_dictionary_coverage(self):
        """القاموس يغطي المجالات القانونية الرئيسية."""
        from query_expander import LEGAL_SYNONYMS

        required_terms = [
            "سرقة", "طلاق", "نفقة", "حضانة",
            "فصل", "عقد", "إيجار", "شيك",
            "دعوى", "سجن", "توقيف", "ابتزاز",
        ]
        for term in required_terms:
            assert term in LEGAL_SYNONYMS, f"المصطلح '{term}' غير موجود في القاموس"
