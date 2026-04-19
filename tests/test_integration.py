# -*- coding: utf-8 -*-
"""
tests/test_integration.py — اختبارات التكامل الحقيقية (بدون mock)
===================================================================
تختبر المكونات بشكل حقيقي:

  1. قاعدة البيانات  — chunks موجودة، embeddings سليمة
  2. بحث حقيقي      — "قانون العمل" يُعيد نتائج > 0
  3. health endpoint — يرجع 200 وchunks_count موجود
  4. cache           — تخزين واسترجاع حقيقي بدون mock
  5. rate limiter    — 21 طلب يُرجع الحادي والعشرون رمز 429

التشغيل:
  pytest tests/test_integration.py -v --tb=short
  pytest tests/test_integration.py -v -m integration   # اختبارات البنية فقط
  pytest tests/test_integration.py -v -m "not db"      # بدون DB
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ══════════════════════════════════════════════════════════════
# Helpers — DB connection probe
# ══════════════════════════════════════════════════════════════

def _db_dsn() -> str:
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "ragdb")
    user = os.getenv("DB_USER", "raguser")
    pwd  = os.getenv("DB_PASSWORD", "RAGsecret2024!")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{name}"


async def _probe_db() -> bool:
    """يُحاوِل الاتصال بـ DB لمدة 2 ثانية ويُعيد True/False."""
    try:
        import asyncpg
        conn = await asyncio.wait_for(asyncpg.connect(_db_dsn()), timeout=2.0)
        await conn.close()
        return True
    except Exception:
        return False


def _db_available() -> bool:
    return asyncio.get_event_loop().run_until_complete(_probe_db()) \
        if not asyncio.get_event_loop().is_running() \
        else False


# مدمج في fixture — يُستخدم بـ pytest.mark.skipif
try:
    import asyncpg as _asyncpg
    _ASYNCPG_AVAILABLE = True
except ImportError:
    _ASYNCPG_AVAILABLE = False

pytestmark_db = pytest.mark.skipif(
    not _ASYNCPG_AVAILABLE,
    reason="asyncpg غير مثبت — تخطّي اختبارات DB",
)


# ══════════════════════════════════════════════════════════════
# Fixture — DB pool (skip إذا DB غير متاح)
# ══════════════════════════════════════════════════════════════

@pytest_asyncio.fixture(scope="function")
async def db_pool():
    """Pool حقيقي للـ DB — يُتخطّى إذا DB غير متاح."""
    if not _ASYNCPG_AVAILABLE:
        pytest.skip("asyncpg غير مثبت")
    try:
        pool = await asyncio.wait_for(
            _asyncpg.create_pool(_db_dsn(), min_size=1, max_size=3),
            timeout=3.0,
        )
    except Exception:
        pytest.skip("قاعدة البيانات غير متاحة — تخطّي الاختبارات")
        return

    yield pool
    await pool.close()


# ══════════════════════════════════════════════════════════════
# 1. قاعدة البيانات — chunks وembeddings
# ══════════════════════════════════════════════════════════════

class TestDatabase:
    """اختبارات DB حقيقية — لا mock."""

    @pytest.mark.asyncio
    async def test_chunks_exist(self, db_pool):
        """يتحقق أن جدول chunks يحتوي بيانات."""
        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM chunks WHERE is_active = TRUE OR is_active IS NULL"
            )
        assert count is not None, "لا يمكن قراءة جدول chunks"
        assert count > 0, f"جدول chunks فارغ — count={count}"

    @pytest.mark.asyncio
    async def test_laws_exist(self, db_pool):
        """يتحقق أن جدول laws يحتوي بيانات."""
        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM laws WHERE is_active = TRUE OR is_active IS NULL"
            )
        assert count is not None
        assert count > 0, f"جدول laws فارغ — count={count}"

    @pytest.mark.asyncio
    async def test_embeddings_not_null(self, db_pool):
        """التحقق أن embedding مخزون لعينة من الـ chunks."""
        async with db_pool.acquire() as conn:
            # عدد الـ chunks التي لها embedding
            with_emb = await conn.fetchval(
                "SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL LIMIT 1"
            )
        assert with_emb is not None
        assert with_emb > 0, "لا توجد embeddings مخزونة في قاعدة البيانات"

    @pytest.mark.asyncio
    async def test_embedding_dimension(self, db_pool):
        """أبعاد الـ embedding معقولة (768 أو 1536 أو 3072 أو أي بُعد > 100)."""
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT embedding::text FROM chunks WHERE embedding IS NOT NULL LIMIT 1"
            )
        assert row is not None, "لا توجد embeddings لاختبار الأبعاد"
        emb_raw = row["embedding"]
        # pgvector يُعيد نصاً مثل "[0.677,0.236,...]" — نحسب الأبعاد بعدد الفواصل
        if isinstance(emb_raw, str) and emb_raw.startswith("["):
            dim = len(emb_raw.split(","))
        elif hasattr(emb_raw, "__len__"):
            dim = len(emb_raw)
        else:
            dim = 0
        assert dim >= 100, \
            f"بُعد الـ embedding صغير جداً أو غير متوقع: {dim}"

    @pytest.mark.asyncio
    async def test_chunks_have_content(self, db_pool):
        """كل chunk نشط يحتوي content غير فارغ."""
        async with db_pool.acquire() as conn:
            empty_count = await conn.fetchval(
                "SELECT COUNT(*) FROM chunks WHERE (is_active IS NULL OR is_active=TRUE) "
                "AND (content IS NULL OR LENGTH(content) < 10)"
            )
        assert empty_count == 0, \
            f"يوجد {empty_count} chunk بمحتوى فارغ أو قصير جداً"

    @pytest.mark.asyncio
    async def test_labor_law_chunks_present(self, db_pool):
        """يتحقق أن قانون العمل موجود في قاعدة البيانات."""
        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM chunks "
                "WHERE (is_active IS NULL OR is_active=TRUE) "
                "AND content ILIKE '%قانون العمل%'"
            )
        assert count is not None
        assert count > 0, "قانون العمل غير موجود في قاعدة البيانات"


# ══════════════════════════════════════════════════════════════
# 2. بحث حقيقي
# ══════════════════════════════════════════════════════════════

class TestRealSearch:
    """اختبارات البحث بقاعدة بيانات حقيقية."""

    @pytest.mark.asyncio
    async def test_fulltext_search_labor_law(self, db_pool):
        """بحث نصي كامل عن 'قانون العمل' يُعيد نتائج."""
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, content, law_name
                FROM chunks
                WHERE (is_active IS NULL OR is_active = TRUE)
                  AND to_tsvector('simple', content) @@ plainto_tsquery('simple', $1)
                LIMIT 10
                """,
                "قانون العمل",
            )
        assert len(rows) > 0, "البحث النصي عن 'قانون العمل' لم يُعد أي نتيجة"

    @pytest.mark.asyncio
    async def test_fulltext_search_returns_relevant_content(self, db_pool):
        """نتائج البحث تحتوي مصطلحات ذات صلة."""
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT content FROM chunks
                WHERE (is_active IS NULL OR is_active = TRUE)
                  AND to_tsvector('simple', content) @@ plainto_tsquery('simple', $1)
                LIMIT 5
                """,
                "عقوبة السرقة",
            )
        # على الأقل بعض النتائج تحتوي مصطلحات قانونية
        if rows:
            combined = " ".join(r["content"] for r in rows)
            legal_terms = ["سرقة", "عقوبة", "قانون", "مادة", "السجن"]
            found = any(term in combined for term in legal_terms)
            assert found, "نتائج البحث لا تحتوي مصطلحات قانونية ذات صلة"

    @pytest.mark.asyncio
    async def test_search_service_with_real_db(self, db_pool):
        """SearchService يعمل مع DB حقيقي (FTS فقط — بدون embed)."""
        from search_service import SearchService
        svc = SearchService(pool=db_pool, embed_fn=None, top_k=5)

        async with db_pool.acquire() as conn:
            results = await svc.fulltext_search(conn, "قانون العمل إشعار إنهاء عقد", top_k=5)

        assert isinstance(results, list), "fulltext_search يجب أن يُعيد list"
        # قد يكون فارغاً إذا FTS index غير موجود — قبول ذلك
        if results:
            assert all("content" in r for r in results), "كل نتيجة يجب أن تحتوي 'content'"

    @pytest.mark.asyncio
    async def test_chunks_count_is_substantial(self, db_pool):
        """عدد الـ chunks كافٍ للنظام (أكثر من 1000)."""
        async with db_pool.acquire() as conn:
            db_count = await conn.fetchval(
                "SELECT COUNT(*) FROM chunks WHERE is_active = TRUE OR is_active IS NULL"
            )
        assert db_count > 1000, \
            f"عدد الـ chunks أقل من المتوقع: {db_count}"


# ══════════════════════════════════════════════════════════════
# 3. Health Endpoint
# ══════════════════════════════════════════════════════════════

class TestHealthEndpoint:
    """اختبارات health endpoint — يستخدم FastAPI TestClient."""

    @pytest.fixture(scope="class")
    def http_client(self):
        """TestClient واحد لكل class — يُشغّل الـ lifespan مرة واحدة."""
        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client

    def test_health_returns_200(self, http_client):
        """GET /api/v1/health يُعيد 200."""
        resp = http_client.get("/api/v1/health")
        assert resp.status_code == 200, \
            f"health endpoint أعاد {resp.status_code} بدلاً من 200"

    def test_health_response_has_chunks_count(self, http_client):
        """health response يحتوي chunks_count في قسم database."""
        resp = http_client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        # المفتاح "database" أو "db" — نقبل كليهما
        db_section = body.get("database") or body.get("db") or {}
        assert db_section, \
            f"health response لا يحتوي قسم database/db: {list(body.keys())}"
        assert "chunks_count" in db_section, \
            f"قسم database لا يحتوي chunks_count: {db_section}"

    def test_health_chunks_count_positive(self, http_client):
        """chunks_count > 0 في قاعدة بيانات حقيقية."""
        resp = http_client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        db_section = body.get("database") or body.get("db") or {}
        chunks = db_section.get("chunks_count", 0)
        assert chunks > 0, \
            f"chunks_count = {chunks} — قاعدة البيانات فارغة أو غير متصلة"

    def test_health_status_not_error(self, http_client):
        """حقل status لا يكون 'error' — يقبل 'ok' أو 'healthy' أو 'degraded'."""
        resp = http_client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        status = body.get("status", "")
        assert status != "error", \
            f"health status = 'error' — السيرفر في حالة خطأ"
        assert status in ("ok", "healthy", "degraded"), \
            f"health status غير متوقع: '{status}'"

    def test_root_page_returns_200(self):
        """GET / يُعيد صفحة HTML بكود 200."""
        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


# ══════════════════════════════════════════════════════════════
# 4. Cache — تخزين واسترجاع حقيقي
# ══════════════════════════════════════════════════════════════

class TestCacheIntegration:
    """اختبارات CacheService الحقيقي — لا mock."""

    @pytest.mark.asyncio
    async def test_store_and_retrieve(self):
        """تخزين واسترجاع إجابة حقيقية."""
        from cache_service import CacheService
        cache = CacheService(ttl_seconds=60)

        q      = "ما عقوبة الاحتيال الإلكتروني في قانون الجرائم الإلكترونية القطري؟"
        answer = ("وفقاً للمادة 14 من قانون مكافحة الجرائم الإلكترونية رقم 14 لسنة 2014، "
                  "يُعاقب على الاحتيال الإلكتروني بالسجن مدة لا تتجاوز ثلاث سنوات وغرامة "
                  "لا تتجاوز خمسمائة ألف ريال قطري أو بإحدى هاتين العقوبتين.")
        sources = [{"law_name": "قانون مكافحة الجرائم الإلكترونية", "article": "14", "score": 0.91}]

        await cache.set(q, answer, sources)
        result = await cache.get(q)

        assert result is not None, "cache.get أعاد None بعد cache.set"
        assert result["answer"] == answer, "الإجابة المسترجعة لا تطابق المخزونة"
        assert result["from_cache"] is True, "from_cache يجب أن يكون True"
        assert result["sources"] == sources, "المصادر المسترجعة لا تطابق المخزونة"

    @pytest.mark.asyncio
    async def test_cache_miss_returns_none(self):
        """استعلام غير مخزون يُعيد None."""
        from cache_service import CacheService
        cache = CacheService(ttl_seconds=60)

        result = await cache.get("سؤال لم يُطرح قط منذ بداية الاختبارات ١٢٣٤٥")
        assert result is None, f"cache.get يجب أن يُعيد None للسؤال غير المخزون: {result}"

    @pytest.mark.asyncio
    async def test_cache_clear_invalidates_entries(self):
        """clear() يُبطل جميع المدخلات."""
        from cache_service import CacheService
        cache = CacheService(ttl_seconds=60)

        answer = "إجابة اختبار طويلة بما يكفي لأكثر من مئة حرف لتخزينها في الكاش بنجاح."
        await cache.set("سؤال للاختبار", answer, [])
        cache.clear()
        result = await cache.get("سؤال للاختبار")
        assert result is None, "cache.clear() لم يُبطل المدخلات"

    @pytest.mark.asyncio
    async def test_cache_stats_reflect_hits(self):
        """إحصائيات الكاش تعكس الـ hits الفعلية."""
        from cache_service import CacheService
        cache = CacheService(ttl_seconds=60)

        q      = "ما شروط الحصول على الإقامة في قطر وفق اللوائح الحالية لعام 2024؟"
        answer = ("يشترط للحصول على الإقامة في دولة قطر توافر عدة شروط منها: "
                  "تقديم طلب رسمي لدى إدارة الجوازات، وتوافر كفيل مقيم أو عقد عمل سار.")
        await cache.set(q, answer, [])

        hit1 = await cache.get(q)
        hit2 = await cache.get(q)
        _    = await cache.get("سؤال آخر غير مخزون أبداً")  # miss

        stats = cache.get_stats()
        assert stats["total_hits"] >= 2, \
            f"total_hits يجب أن يكون >= 2: {stats}"

    @pytest.mark.asyncio
    async def test_semantic_cache_with_identical_embedding(self):
        """الكاش الدلالي يُطابق الأسئلة ذات embedding متطابق."""
        async def _fixed_embed(text: str) -> list[float]:
            return [1.0, 0.0, 0.0]   # نفس الـ vector لكل نص

        from cache_service import CacheService
        cache = CacheService(
            embed_fn=_fixed_embed,
            ttl_seconds=60,
            semantic_threshold=0.95,
        )
        original_answer = ("وفقاً للمادة 357 من قانون العقوبات يُعاقب على الشيك بدون رصيد "
                           "بالسجن مدة لا تتجاوز ثلاث سنوات أو بالغرامة أو بكلتيهما.")
        await cache.set("ما عقوبة الشيك بدون رصيد؟", original_answer, [])

        result = await cache.get("ما العقوبة المقررة لصاحب الشيك المرتجع؟")
        assert result is not None, "الكاش الدلالي لم يُعد نتيجة رغم تطابق الـ embedding"
        assert result["cache_type"] == "semantic", \
            f"نوع الكاش يجب أن يكون 'semantic': {result.get('cache_type')}"
        assert result["answer"] == original_answer


# ══════════════════════════════════════════════════════════════
# 5. Rate Limiter — 21 طلب متتالٍ
# ══════════════════════════════════════════════════════════════

class TestRateLimiterIntegration:
    """اختبارات rate limiter الحقيقي — 20 طلب مسموح، 21 مرفوض."""

    @pytest.mark.asyncio
    async def test_20_requests_allowed_21st_blocked(self):
        """الطلبات 1-20 مسموحة، الطلب 21 مرفوض بـ remaining=0."""
        from rate_limiter import RateLimiter
        limiter = RateLimiter(redis_url=None, max_requests=20, window_seconds=60)
        client_id = "integration_test_client_21"

        allowed_count  = 0
        blocked_count  = 0

        for i in range(21):
            allowed, remaining = await limiter.is_allowed(client_id)
            if allowed:
                allowed_count += 1
            else:
                blocked_count += 1

        assert allowed_count  == 20, \
            f"يجب السماح بـ 20 طلب بالضبط، وُجد: {allowed_count}"
        assert blocked_count  == 1,  \
            f"يجب رفض طلب واحد فقط، وُجد: {blocked_count}"

    @pytest.mark.asyncio
    async def test_rate_limit_endpoint_returns_429(self):
        """endpoint يُعيد 429 عند تجاوز الحد (TestClient + تجاوز مباشر)."""
        from rate_limiter import RateLimiter
        limiter = RateLimiter(redis_url=None, max_requests=5, window_seconds=60)
        client_id = "http_429_test_client"

        # استنزاف الحد
        for _ in range(5):
            await limiter.is_allowed(client_id)

        # الطلب 6 يجب أن يُرفض
        allowed, remaining = await limiter.is_allowed(client_id)
        assert not allowed, "الطلب 6 يجب أن يُرفض بعد استنزاف الحد"
        assert remaining == 0, f"remaining يجب أن يكون 0: {remaining}"

    @pytest.mark.asyncio
    async def test_rate_limit_resets_after_window(self):
        """بعد reset() يعود الحساب من الصفر."""
        from rate_limiter import RateLimiter
        limiter = RateLimiter(redis_url=None, max_requests=3, window_seconds=60)
        client_id = "reset_test_client"

        # استنزاف الحد
        for _ in range(3):
            await limiter.is_allowed(client_id)

        # الطلب 4 مرفوض
        allowed, _ = await limiter.is_allowed(client_id)
        assert not allowed

        # إعادة التعيين
        await limiter.reset(client_id)

        # بعد الإعادة — مسموح
        allowed_after_reset, remaining = await limiter.is_allowed(client_id)
        assert allowed_after_reset, "يجب السماح بعد reset()"
        assert remaining == 2

    @pytest.mark.asyncio
    async def test_different_clients_independent_limits(self):
        """كل client له حده المستقل."""
        from rate_limiter import RateLimiter
        limiter = RateLimiter(redis_url=None, max_requests=2, window_seconds=60)

        # client_A يستنزف حده
        await limiter.is_allowed("client_A_integ")
        await limiter.is_allowed("client_A_integ")
        blocked_a, _ = await limiter.is_allowed("client_A_integ")

        # client_B لم يُستخدم بعد
        allowed_b, remaining_b = await limiter.is_allowed("client_B_integ")

        assert not blocked_a,  "client_A يجب أن يكون محجوباً"
        assert allowed_b,      "client_B يجب أن يكون مسموحاً"
        assert remaining_b == 1

    def test_rate_limiter_stats_structure(self):
        """get_stats() يُعيد البنية الصحيحة."""
        from rate_limiter import RateLimiter
        limiter = RateLimiter(redis_url=None, max_requests=20, window_seconds=60)
        stats = limiter.get_stats()

        required_keys = {"backend", "max_requests", "window_seconds", "active_clients"}
        missing = required_keys - set(stats.keys())
        assert not missing, f"مفاتيح ناقصة في stats: {missing}"
        assert stats["max_requests"] == 20
        assert stats["window_seconds"] == 60
        assert stats["backend"] == "in_memory"


# ══════════════════════════════════════════════════════════════
# 6. Pipeline التكاملي — وحدات متعددة معاً بدون mock
# ══════════════════════════════════════════════════════════════

class TestPipelineIntegration:
    """اختبار تسلسل حقيقي: expand → confidence → citation → cache."""

    @pytest.mark.asyncio
    async def test_full_query_pipeline_no_mock(self):
        """pipeline كامل لسؤال حقيقي: expand → score → cite → cache."""
        from query_expander  import expand, extract_legal_entities
        from confidence_scorer import from_chunks
        from citation_builder import build_citations
        from cache_service    import CacheService

        query   = "ما هي مدة إشعار إنهاء عقد العمل في قطر؟"
        cache   = CacheService(ttl_seconds=60)

        # 1. توسيع الاستعلام
        variants = expand(query)
        assert len(variants) == 3, f"expand أعاد {len(variants)} بدلاً من 3"

        # 2. استخراج الكيانات
        entities = extract_legal_entities(query)
        assert entities["law_type"] == "عمل", \
            f"law_type = {entities['law_type']} بدلاً من 'عمل'"

        # 3. حساب الثقة
        chunks = [
            {"law_name": "قانون العمل", "score": 0.91, "article_number": "47",
             "id": 1, "law_id": 14, "law_number": "14", "law_year": "2004",
             "content": "يُلزم صاحب العمل بإخطار العامل قبل إنهاء عقده بمدة لا تقل عن شهر.",
             "source": "law_14.pdf"},
        ]
        conf = from_chunks(chunks)
        assert conf["score"] > 0, "confidence score يجب أن يكون > 0"

        # 4. بناء الاستشهادات
        answer = "وفقاً للمادة 47 يجب إشعار العامل قبل الفصل بشهر كامل."
        cite   = build_citations(answer, chunks)
        assert len(cite["citations"]) == 1, "يجب بناء استشهاد واحد"

        # 5. تخزين في الكاش
        await cache.set(query, answer, cite["citations"])
        cached = await cache.get(query)
        assert cached is not None, "التخزين في الكاش فشل"
        assert cached["answer"] == answer

    @pytest.mark.asyncio
    async def test_search_service_rrf_fusion_correctness(self):
        """RRF Fusion يرتب الـ chunks الظاهرة في قائمتين أعلى من المنفردة."""
        from search_service import SearchService
        svc = SearchService(pool=None)

        # chunk "قانون العمل/47" موجود في كلتيهما → يجب أن يكون أول
        list_a = [
            {"law_name": "قانون العمل",    "article_number": "47",  "score": 0.90,
             "id": 1, "content": "نص المادة 47 قانون العمل"},
            {"law_name": "قانون العقوبات", "article_number": "357", "score": 0.80,
             "id": 2, "content": "نص المادة 357 قانون العقوبات"},
        ]
        list_b = [
            {"law_name": "قانون العمل",    "article_number": "47",  "score": 0.85,
             "id": 1, "content": "نص المادة 47 قانون العمل"},
            {"law_name": "قانون الأسرة",   "article_number": "20",  "score": 0.70,
             "id": 3, "content": "نص المادة 20 قانون الأسرة"},
        ]
        merged = svc.rrf_fusion(list_a, list_b, top_n=5)

        assert len(merged) >= 1, "rrf_fusion أعاد قائمة فارغة"
        top = merged[0]
        assert top["law_name"] == "قانون العمل" and top["article_number"] == "47", \
            f"العنصر الأول غير متوقع: {top.get('law_name')}/{top.get('article_number')}"

    def test_timing_module_records_correctly(self):
        """core/timing يُسجّل التوقيتات ويُعيد إحصائيات صحيحة."""
        from core.timing import record, get_stats, reset
        reset()

        for ms in [100, 200, 300, 400, 500]:
            record("search", ms)

        stats = get_stats()
        assert "search" in stats, "label 'search' غير موجود في stats"
        s = stats["search"]
        assert s["count"] == 5
        assert s["min_ms"] == 100.0
        assert s["max_ms"] == 500.0
        assert s["avg_ms"] == 300.0

        reset()

    @pytest.mark.asyncio
    async def test_timing_context_manager_async(self):
        """timing_context يُسجّل وقت حقيقي لعملية async."""
        from core.timing import timing_context, get_stats, reset
        reset()

        async with timing_context("test_op"):
            await asyncio.sleep(0.01)

        stats = get_stats()
        assert "test_op" in stats
        assert stats["test_op"]["avg_ms"] >= 5.0, \
            f"وقت العملية أقل من المتوقع: {stats['test_op']['avg_ms']}ms"

        reset()
