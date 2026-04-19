# -*- coding: utf-8 -*-
"""
routers/admin_router.py — Admin/diagnostic API endpoints.
"""
import time, logging, os
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel as _BM
from core import app_state
from core.timing import get_stats as _get_timing_stats
from core.config import (
    ANTHROPIC_KEY, GEMINI_KEY, OPENAI_KEY, PRIMARY_MODEL,
)
from core.nlp_utils import extract_kw, extract_phrases, _check_retrieval_relevance
from services.llm_service import chain_of_thought, search, keyword_search, stream_ollama

log = logging.getLogger(__name__)
router = APIRouter()

MODEL_OLLAMA_LLM = os.getenv("MODEL_OLLAMA_LLM", "qwen2.5:1.5b")

@router.get("/api/v1/cache/stats")
async def cache_stats_endpoint():
    """
    إحصائيات Cache Service (الخطوة 14):
    hit_rate, total_hits, total_misses, cached_queries, semantic_entries
    """
    result: dict = {"service": "cache_service", "available": app_state.SCS_AVAILABLE}
    if app_state.SCS_AVAILABLE and app_state.get_cache_service:
        _scs = app_state.get_cache_service()
        if _scs:
            result.update(_scs.get_stats())
        else:
            result["note"] = "لم يُهيَّأ بعد (يحتاج DB connection)"
    # أضف إحصائيات DB cache أيضاً
    if app_state.pool:
        try:
            async with app_state.pool.acquire() as _cc:
                db_count = await _cc.fetchval("SELECT COUNT(*) FROM answer_cache WHERE expires_at > NOW()")
                db_hits  = await _cc.fetchval("SELECT COALESCE(SUM(hit_count),0) FROM answer_cache")
                result["db_cache"] = {"cached_queries": db_count, "total_hits": int(db_hits or 0)}
        except Exception:
            pass
    return result


@router.get("/api/v1/analytics")
async def analytics_endpoint(days: int = 1):
    """
    تحليلات الاستعلامات (الخطوة 18):
    - إجمالي الاستعلامات اليوم
    - متوسط وقت الاستجابة
    - نسبة الـ cache hit
    - أكثر provider استخداماً
    - متوسط مستوى الثقة
    - عدد استعلامات الثقة المنخفضة
    """
    if app_state.LS_AVAILABLE and app_state.get_logger_service:
        _ls_inst = app_state.get_logger_service()
        if _ls_inst:
            return await _ls_inst.get_analytics(days=days)
    # Fallback: بيانات بسيطة من learning_log
    if app_state.pool:
        try:
            async with app_state.pool.acquire() as conn:
                total = await conn.fetchval(
                    "SELECT COUNT(*) FROM learning_log "
                    "WHERE created_at > NOW() - ($1 || ' days')::INTERVAL",
                    str(days)
                ) or 0
                avg_ms = await conn.fetchval(
                    "SELECT ROUND(AVG(latency_ms))::INT FROM learning_log "
                    "WHERE created_at > NOW() - ($1 || ' days')::INTERVAL AND latency_ms > 0",
                    str(days)
                ) or 0
                return {
                    "total_queries_today"    : int(total),
                    "avg_response_ms"        : int(avg_ms),
                    "cache_hit_rate"         : "—",
                    "top_provider"           : "—",
                    "avg_confidence"         : 0,
                    "low_confidence_queries" : 0,
                    "days_period"            : days,
                    "source"                 : "learning_log_fallback",
                }
        except Exception as _ae:
            log.debug("analytics fallback error: %s", _ae)
    return {
        "total_queries_today": 0, "avg_response_ms": 0,
        "cache_hit_rate": "0%",   "top_provider": "—",
        "avg_confidence": 0,      "low_confidence_queries": 0,
        "days_period": days,      "note": "logger_service غير متاح",
    }


@router.get("/api/v1/debug_search")
async def debug_search(q: str = "زوجتي تريد الطلاق"):
    """debug: يُظهر ما تُعيده search() + relevance check بدون توليد إجابة"""
    from fastapi.responses import JSONResponse
    try:
        # query_engine
        if app_state.QE_AVAILABLE:
            rb = app_state.query_engine._rule_based_expand(q)
            legal_terms = rb.get("legal_terms", [])[:5]
            fast_qs = await app_state.query_engine.expand_fast(q)
        else:
            legal_terms, fast_qs = [], []

        # CoT
        cot = await chain_of_thought(q, model="ollama")
        queries = cot.get("search_queries", [q])
        key_terms = cot.get("law_areas", [])
        queries = list(dict.fromkeys(queries + legal_terms[:3] + fast_qs))[:6]

        # بحث
        chunks = await search(queries, key_terms, 15)
        relevant = [c for c in chunks
                    if float(c["score"]) > 0.55
                    or (c.get("keyword_match") and c.get("match_count", 0) > 0)][:12]

        # فحص الصلة — ندمج legal_terms + law_areas من COT لتوسيع التغطية
        _debug_check_terms = list(dict.fromkeys(
            legal_terms + cot.get("law_areas", []) + [cot.get("primary_law", ""), cot.get("legal_characterization", "")]
        ))
        _debug_check_terms = [t for t in _debug_check_terms if t]
        relevance_ok = _check_retrieval_relevance(q, relevant, extra_terms=_debug_check_terms) if relevant else False

        # ── تطبيق DRE لإظهار النتائج قبل/بعد ──
        dre_top3 = []
        dre_domain = None
        if app_state.DRE_AVAILABLE and relevant:
            try:
                app_state.dre_hint = cot.get("law_domain") or cot.get("primary_law", "")[:25] or None
                app_state.dre_extra = list(dict.fromkeys((legal_terms + cot.get("law_areas", []))[:8]))
                dre_result = app_state.dre.rerank(q, relevant, extra_terms=app_state.dre_extra or None,
                                          domain_hint=app_state.dre_hint)
                dre_domain = dre_result[0].get("dre_domain", "") if dre_result else ""
                dre_top3 = [
                    {"law": c["law_name"][:45], "art": c["article_number"],
                     "year": c["law_year"],
                     "score_before": round(float(c.get("dre_score", c.get("score", 0))), 3),
                     "dre_score": round(float(c.get("dre_score", 0)), 4)}
                    for c in dre_result[:3]
                ]
            except Exception as _de:
                dre_top3 = [{"error": str(_de)}]

        return JSONResponse({
            "q": q,
            "legal_terms_from_qe": legal_terms,
            "final_queries": queries,
            "key_terms": key_terms,
            "cot_domain": cot.get("law_domain", ""),
            "cot_primary_law": cot.get("primary_law", ""),
            "chunks_raw": len(chunks),
            "relevant_after_score_filter": len(relevant),
            "relevance_check": relevance_ok,
            "top3_beforeapp_state.dre": [
                {"law": c["law_name"][:45], "art": c["article_number"],
                 "year": c["law_year"], "score": round(float(c["score"]), 3),
                 "kw_match": c.get("keyword_match", False)}
                for c in relevant[:3]
            ],
            "top3_afterapp_state.dre": dre_top3,
            "dre_detected_domain": dre_domain,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)})

# ══════════════════════════════════════════════════════════
@router.get("/api/v1/test_ollama")
async def test_ollama_speed():
    """Diagnostic — GUARDED behind ALLOW_DEV_LLM_PROBE env flag.

    UNIFICATION NOTE: this was a direct stream_ollama probe. It is now
    disabled in production. In dev, set ALLOW_DEV_LLM_PROBE=true to enable.
    Output is explicitly marked non_authoritative and cannot be used as
    an answer to a user query.
    """
    import os, time
    if os.getenv("ALLOW_DEV_LLM_PROBE", "").lower() not in ("1", "true", "yes"):
        return {
            "status": "disabled",
            "reason": "llm_probe_disabled_in_production",
            "authoritative_path": "non_authoritative",
            "llm_used": False,
        }
    t0 = time.time()
    try:
        msgs = [{"role": "user", "content": "قل: مرحبا فقط"}]
        parts = []
        async for chunk in stream_ollama("أنت مساعد.", msgs, max_tokens=10):
            parts.append(chunk)
            if len(parts) >= 1:
                break
        elapsed = round(time.time() - t0, 2)
        return {"status": "ok", "first_token_sec": elapsed,
                "model": MODEL_OLLAMA_LLM, "text": "".join(parts)[:30],
                "authoritative_path": "non_authoritative",
                "disclaimer": "diagnostic_only_no_answer_authority"}
    except Exception as e:
        return {"status": "error", "error": str(e), "elapsed": round(time.time()-t0,2),
                 "authoritative_path": "non_authoritative"}

@router.get("/api/v1/health")
async def health():
    import time as _time_mod
    _t0 = _time_mod.time()

    # ── Database ──────────────────────────────────────────────
    db_info: dict = {"connected": bool(app_state.pool)}
    if app_state.pool:
        try:
            _db_t0 = _time_mod.time()
            async with app_state.pool.acquire() as conn:
                active_laws   = await conn.fetchval("SELECT COUNT(*) FROM laws WHERE is_active = TRUE OR is_active IS NULL") or 0
                active_chunks = await conn.fetchval("SELECT COUNT(*) FROM chunks WHERE is_active = TRUE OR is_active IS NULL") or 0
            db_info.update({
                "connected"   : True,
                "chunks_count": int(active_chunks),
                "laws_count"  : int(active_laws),
                "response_ms" : round((_time_mod.time() - _db_t0) * 1000),
            })
        except Exception as _dbe:
            db_info.update({"connected": False, "error": str(_dbe)[:80]})

    # ── LLM Providers ─────────────────────────────────────────
    llm_providers = {
        "openai" : bool(OPENAI_KEY),
        "gemini" : bool(GEMINI_KEY),
        "claude" : bool(ANTHROPIC_KEY),
        "ollama" : True,   # محلي — دائماً محاوَل
    }

    # ── Cache ──────────────────────────────────────────────────
    cache_info: dict = {"available": app_state.SCS_AVAILABLE}
    if app_state.SCS_AVAILABLE and app_state.get_cache_service:
        _scs_h = app_state.get_cache_service()
        if _scs_h:
            _sc_stats = _scs_h.get_stats()
            cache_info.update({
                "hit_rate"      : _sc_stats["hit_rate"],
                "cached_queries": _sc_stats["cached_queries"],
                "total_hits"    : _sc_stats["total_hits"],
            })

    # ── Search ─────────────────────────────────────────────────
    search_info: dict = {
        "hybrid_enabled": app_state.SS_AVAILABLE,
        "fts_index"     : app_state.SS_AVAILABLE,   # يعتمد على SearchService
        "query_expander": app_state.QEXP_AVAILABLE,
    }

    # ── Modules ────────────────────────────────────────────────
    db_stats = {"active_laws": db_info.get("laws_count", 0), "active_chunks": db_info.get("chunks_count", 0)}
    # إحصائيات الوحدات المتقدمة
    advanced_modules = {
        # Phase 1-6 new modules
        "unified_analyzer":        "✓ نشط (−1 LLM call/req)" if app_state.UA_AVAILABLE  else "✗ غير متاح",
        "deep_reasoning_engine":   "✓ نشط (6-step reasoning)" if app_state.DR_AVAILABLE  else "✗ غير متاح",
        "language_perfection":     "✓ نشط (native Arabic)"   if app_state.LP_AVAILABLE  else "✗ غير متاح",
        "citation_guard":          "✓ نشط (MMR+anti-halluc)"  if app_state.CG_AVAILABLE  else "✗ غير متاح",
        "legal_reasoning_engine":  "✓ نشط (unified decision+IRAC)" if app_state.LRE_AVAILABLE else "✗ غير متاح",
        "production_hardening":    "✓ نشط (rate+cache+health)" if app_state.PH_AVAILABLE else "✗ غير متاح",
        # Legacy modules
        "context_manager":         "✓ نشط" if app_state.CTX_AVAILABLE        else "✗ غير متاح",
        "query_engine":            "✓ نشط" if app_state.QE_AVAILABLE         else "✗ غير متاح",
        "intelligence_layer":      "✓ نشط" if app_state.IL_AVAILABLE         else "✗ غير متاح",
        "domain_relevance_engine": "✓ نشط" if app_state.DRE_AVAILABLE        else "✗ غير متاح",
        "confidence_scoring":      "✓ نشط" if app_state.CS_AVAILABLE         else "✗ غير متاح",
        "clarification_engine":    "✓ نشط" if app_state.CE_AVAILABLE         else "✗ غير متاح",
        "answer_compressor":       "✓ نشط" if app_state.COMPRESSOR_AVAILABLE else "✗ غير متاح",
        "quality_logger":          "✓ نشط" if app_state.QL_AVAILABLE         else "✗ غير متاح",
        "legal_decision_engine":   "✓ نشط (legacy)" if app_state.LDE_AVAILABLE else "✗ غير متاح",
        "legal_argumentation_engine": "✓ نشط (legacy)" if app_state.LAE_AVAILABLE else "✗ غير متاح",
    }
    if app_state.CTX_AVAILABLE:
        advanced_modules["ctx_manager_stats"] = app_state.ctx_manager.stats()
    if app_state.QE_AVAILABLE:
        advanced_modules["query_engine_cache"] = app_state.query_engine.get_cache_stats()
    if app_state.DRE_AVAILABLE:
        advanced_modules["dre_stats"] = app_state.dre.get_stats()

    return {
        "status"       : "healthy" if db_info.get("connected") else "degraded",
        "version"      : "2.0.0",
        "database"     : db_info,
        "llm_providers": llm_providers,
        "cache"        : cache_info,
        "search"       : search_info,
        # توافق مع الإصدار القديم
        "db_stats"     : db_stats,
        "primary_model": PRIMARY_MODEL,
        "advanced_modules": advanced_modules,
        "response_ms"  : round((_time_mod.time() - _t0) * 1000),
    }


@router.get("/api/v1/quality_stats")
async def quality_stats():
    """إحصائيات جودة الإجابات من quality_logger (آخر 200 سجل)"""
    if not app_state.QL_AVAILABLE:
        return {"error": "quality_logger غير متاح"}
    try:
        stats = app_state.ql_stats(200)
        return {"status": "ok", **stats}
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/v1/system_status")
async def system_status():
    """
    Phase 6: Full system status — modules, cache, rate limiter, log rotation.
    Powered by production_hardening module.
    """
    status: dict = {"version": "10.0", "timestamp": time.time()}

    # Module health
    if app_state.PH_AVAILABLE:
        status["modules"] = app_state.ph_health(force_refresh=False)
        status["rate_limiter"] = app_state.ph_rate_stats()
        status["cache"] = app_state.ph_cache.get_stats() if hasattr(app_state.ph_cache, "get_stats") else {}
    else:
        # Fallback: manual flags
        status["modules"] = {
            "unified_analyzer":       app_state.UA_AVAILABLE,
            "deep_reasoning_engine":  app_state.DR_AVAILABLE,
            "language_perfection":    app_state.LP_AVAILABLE,
            "citation_guard":         app_state.CG_AVAILABLE,
            "legal_reasoning_engine": app_state.LRE_AVAILABLE,
            "production_hardening":   app_state.PH_AVAILABLE,
            "confidence_scoring":     app_state.CS_AVAILABLE,
            "clarification_engine":   app_state.CE_AVAILABLE,
            "quality_logger":         app_state.QL_AVAILABLE,
        }

    # Quality log stats
    if app_state.QL_AVAILABLE:
        try:
            status["quality_log"] = app_state.ql_stats(100)
        except Exception:
            pass

    return {"status": "ok", **status}


@router.post("/api/v1/cache/invalidate")
async def cache_invalidate(query: str = ""):
    """Phase 6: Manually invalidate a cached response by query string."""
    if not app_state.PH_AVAILABLE:
        return {"error": "production_hardening غير متاح"}
    if not query:
        app_state.ph_cache.clear()
        return {"status": "ok", "action": "cache_cleared_all"}
    app_state.ph_cache.invalidate(query)
    return {"status": "ok", "action": "invalidated", "query": query[:80]}


@router.get("/api/v1/active_laws")
async def active_laws_stats():
    """إحصائيات القوانين النافذة في قاعدة البيانات — للتحقق من جودة البيانات"""
    if not app_state.pool:
        return {"error": "DB غير متصل"}
    try:
        async with app_state.pool.acquire() as conn:
            # إحصائيات عامة
            total = await conn.fetchval("SELECT COUNT(*) FROM laws")
            active = await conn.fetchval("SELECT COUNT(*) FROM laws WHERE is_active = TRUE OR is_active IS NULL")
            inactive = await conn.fetchval("SELECT COUNT(*) FROM laws WHERE is_active = FALSE")
            active_chunks = await conn.fetchval("SELECT COUNT(*) FROM chunks WHERE is_active = TRUE OR is_active IS NULL")

            # توزيع حسب السنة
            year_dist = await conn.fetch("""
                SELECT law_year, COUNT(*) as cnt
                FROM laws
                WHERE (is_active = TRUE OR is_active IS NULL)
                  AND law_year ~ '^[0-9]{4}$'
                GROUP BY law_year
                ORDER BY law_year::int DESC
                LIMIT 15
            """)

            # أنواع القوانين
            type_dist = await conn.fetch("""
                SELECT law_type, COUNT(*) as cnt
                FROM laws
                WHERE (is_active = TRUE OR is_active IS NULL)
                GROUP BY law_type
                ORDER BY cnt DESC
                LIMIT 10
            """)

        return {
            "total_laws": total,
            "active_laws": active,
            "inactive_laws": inactive,
            "active_chunks": active_chunks,
            "coverage_pct": round(active / max(total, 1) * 100, 1),
            "recent_years": [{"year": r["law_year"], "count": r["cnt"]} for r in year_dist],
            "by_type": [{"type": r["law_type"] or "غير محدد", "count": r["cnt"]} for r in type_dist],
        }
    except Exception as e:
        return {"error": str(e)}

# ── Compare Laws (الخطوة 23) ──────────────────────────────────
class _CompareRequest(_BM):
    law_a:  str
    law_b:  str
    aspect: str = ""

@router.post("/api/v1/compare")
async def compare_laws(req: _CompareRequest):
    """Law comparison — GUARDED behind ALLOW_DEV_LLM_PROBE.

    UNIFICATION NOTE: compare previously invoked call_ollama freely —
    an unauthorized authority path. Disabled in production. Use the
    unified /api/v1/query/ endpoint for any answer-producing request.
    """
    import os
    if os.getenv("ALLOW_DEV_LLM_PROBE", "").lower() not in ("1", "true", "yes"):
        return {
            "status": "disabled",
            "reason": "compare_llm_disabled_in_production",
            "hint": "Use POST /api/v1/query/ with a comparative question instead.",
            "authoritative_path": "non_authoritative",
        }
    if not app_state.pool:
        return {"error": "قاعدة البيانات غير متصلة"}
    if not req.law_a.strip() or not req.law_b.strip():
        return {"error": "يجب تحديد اسمَي القانونين"}

    async def _llm(prompt: str) -> str:
        try:
            from services.llm_service import call_ollama
            return await call_ollama(prompt, max_tokens=800)
        except Exception:
            return ""

    from compare_service import CompareService
    svc = CompareService(app_state.pool, llm_fn=_llm)
    out = await svc.compare(
        req.law_a.strip(), req.law_b.strip(), req.aspect.strip()
    )
    if isinstance(out, dict):
        out["authoritative_path"] = "non_authoritative"
        out["disclaimer"] = "dev_only_not_answer_to_user"
    return out


@router.get("/api/v1/user/preferences")
async def get_user_preferences(session_id: str = ""):
    """إحصائيات تفضيلات المستخدم — user_memory الخطوة 22"""
    if not app_state.UM_AVAILABLE or not app_state.get_user_memory:
        return {"available": False, "reason": "user_memory غير محمّل"}
    _um = app_state.get_user_memory()
    if not _um:
        return {"available": False, "reason": "user_memory لم يُهيَّأ بعد"}
    return await _um.get_stats(session_id or None)


@router.get("/api/v1/debug_keyword")
async def debug_keyword(q: str = "شروط الطلاق وحضانة الأطفال"):
    """نقطة تشخيص بسيطة — يُعيد نتائج keyword_search الخام فقط"""
    if not app_state.pool:
        return {"error": "قاعدة البيانات غير متصلة"}
    kws = extract_kw(q)
    phrases = extract_phrases(q)
    async with app_state.pool.acquire() as conn:
        results = await keyword_search(conn, kws, top_k=15, phrases=phrases)
    return {
        "query": q, "kws": kws,
        "results": [
            {"law": r["law_name"][:50], "article": r["article_number"],
             "score": round(float(r["score"]),4),
             "content_snippet": r["content"][:80]}
            for r in results[:15]
        ]
    }


# ══════════════════════════════════════════════════════════════
# الخطوة 38 — Feedback endpoints
# ══════════════════════════════════════════════════════════════

class _FeedbackRequest(_BM):
    rating:      int             # +1 | -1
    query_id:    int  = 0
    session_id:  str  = ""
    comment:     str  = ""
    query_text:  str  = ""
    answer_text: str  = ""


@router.post("/api/v1/feedback")
async def submit_feedback(req: _FeedbackRequest):
    if req.rating not in (-1, 1):
        return JSONResponse({"error": "rating يجب أن يكون 1 أو -1"}, status_code=400)
    if not app_state.FB_AVAILABLE or not app_state.get_feedback_service:
        return JSONResponse({"error": "feedback_service غير متاح"}, status_code=503)
    svc = app_state.get_feedback_service()
    if not svc:
        return JSONResponse({"error": "feedback_service غير مُهيَّأ"}, status_code=503)
    result = await svc.submit(
        rating=req.rating,
        query_id=req.query_id or None,
        session_id=req.session_id,
        comment=req.comment,
        query_text=req.query_text,
        answer_text=req.answer_text,
    )
    return result


@router.get("/api/v1/feedback/stats")
async def feedback_stats(days: int = 7):
    if not app_state.FB_AVAILABLE or not app_state.get_feedback_service:
        return {"available": False}
    svc = app_state.get_feedback_service()
    if not svc:
        return {"available": False}
    daily   = await svc.get_daily_stats(days)
    summary = await svc.get_summary()
    worst   = await svc.get_worst_answers(10)
    needs   = await svc.get_topic_needs(10)
    return {
        "available":   True,
        "summary":     summary,
        "daily":       daily,
        "worst":       worst,
        "needs_improvement": needs,
    }


# ══════════════════════════════════════════════════════════════
# الخطوة 42 — Performance stats endpoint
# ══════════════════════════════════════════════════════════════

@router.get("/api/v1/performance")
async def performance_stats():
    """
    إحصائيات أداء Pipeline:
    avg_ms, p95_ms, p99_ms لكل خطوة (cot, search, rerank, llm_stream).
    """
    stats = _get_timing_stats()

    # Bottleneck analysis
    bottlenecks = []
    if stats.get("search", {}).get("avg_ms", 0) > 300:
        bottlenecks.append("search > 300ms — تحقق من وجود HNSW index")
    if stats.get("cot", {}).get("avg_ms", 0) > 800:
        bottlenecks.append("cot > 800ms — فكر في caching نتائج CoT")
    if stats.get("rerank", {}).get("avg_ms", 0) > 500:
        bottlenecks.append("rerank > 500ms — استخدم heuristic mode")

    return {
        "timings":     stats,
        "bottlenecks": bottlenecks,
        "targets": {
            "search_ms":  "< 300ms",
            "cot_ms":     "< 800ms",
            "rerank_ms":  "< 200ms (heuristic)",
            "llm_ms":     "1000-4000ms (streaming — acceptable)",
        },
    }
