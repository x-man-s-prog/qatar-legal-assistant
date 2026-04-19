# -*- coding: utf-8 -*-
"""
routers/session_router.py — Session + learning endpoints (non-answer-producing).

UNIFICATION NOTE:
  The followup endpoint previously called services.llm_service._generate_answer
  directly — that was a legacy LLM bypass of the unified runtime. It has been
  neutralized: followup questions are now derived DETERMINISTICALLY from the
  query text and the unified runtime's sufficiency / issue_tags metadata.
  No LLM is called from this router.
"""
import asyncio, logging
from typing import Optional
from fastapi import APIRouter, Request
from pydantic import BaseModel
from core import app_state
from core.db_utils import submit_feedback, save_to_cache, get_learning_stats, run_weekly_analysis
# NOTE: services.llm_service._generate_answer intentionally NOT imported here.
# This file must not be able to trigger an LLM call.

log = logging.getLogger(__name__)
router = APIRouter()

class FeedbackRequest(BaseModel):
    log_id:  int
    value:   int
    note:    Optional[str] = ""
    query:   Optional[str] = ""
    answer:  Optional[str] = ""
    sources: Optional[list] = []
    model:   Optional[str] = ""

@router.delete("/api/v1/session/{session_id}")
async def clear_session(session_id: str):
    app_state.sessions.pop(session_id, None); app_state.session_ts.pop(session_id, None)
    return {"status": "ok"}

# ══════════════════════════════════════════════════════════
# مسارات نظام التعلم التراكمي
# ══════════════════════════════════════════════════════════

@router.post("/api/v1/feedback/")
async def feedback(req: FeedbackRequest):
    """يستقبل تقييم المستخدم (+1 إعجاب / -1 عدم إعجاب) ويحفظه"""
    if req.value not in (1, -1):
        return {"status": "error", "message": "القيمة يجب أن تكون 1 أو -1"}
    await submit_feedback(req.log_id, req.value, req.note or "")
    # عند الإعجاب: احفظ في الكاش وأضف للـ few-shot المرشحين
    if req.value == 1 and req.query and req.answer and len(req.answer) >= 200:
        asyncio.create_task(save_to_cache(req.query, req.answer, req.sources or [], req.model or ""))
        # إضافة للـ few-shot إذا كانت الإجابة طويلة بما يكفي
        if len(req.answer) >= 300:
            try:
                async with app_state.pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO fewshot_examples (query, answer, quality_score)
                        VALUES ($1, $2, 0.9)
                        ON CONFLICT DO NOTHING
                    """, req.query[:300], req.answer[:800])
            except Exception:
                pass
    return {"status": "ok", "message": "تم حفظ تقييمك، شكراً لمساعدتك في تحسين النظام"}

@router.get("/api/v1/learning/stats")
async def learning_stats():
    """إحصائيات نظام التعلم"""
    return await get_learning_stats()

@router.post("/api/v1/learning/analyze")
async def trigger_weekly_analysis():
    """يُشغّل التحليل الأسبوعي — يحلل الفشل ويقترح تحسينات"""
    result = await run_weekly_analysis()
    return result

@router.get("/api/v1/learning/suggestions")
async def get_suggestions(limit: int = 5):
    """أحدث اقتراحات التحسين من Gemini"""
    try:
        async with app_state.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, period_start, period_end, total_queries, failed_queries,
                       failure_rate, root_causes, missing_keywords,
                       prompt_suggestion, examples_added, applied, created_at
                FROM improvement_suggestions
                ORDER BY created_at DESC LIMIT $1
            """, limit)
        return [dict(r) for r in rows]
    except Exception as e:
        return {"error": str(e)}

@router.post("/api/v1/followup")
async def get_followup_questions(request: Request):
    """Deterministic follow-up suggestions — NO LLM CALL.

    UNIFIED: follow-up questions are derived from the domain binder's
    issue_tags on the inbound query. No LLM is invoked here. The legacy
    implementation that called _generate_answer was deleted during
    Monolithic Runtime Unification.
    """
    try:
        body  = await request.json()
        query = (body.get("query", "") or "").strip()[:300]
        if not query:
            return {"questions": [], "authoritative_path": "unified_fail_closed",
                    "llm_used": False}

        # Deterministic: use DomainBinder issue_tags → canonical follow-up prompts
        from core.knowledge.domain_binder import get_binder
        binding = get_binder().bind(query)

        # Canonical follow-up templates per domain (deterministic)
        _TEMPLATES = {
            "employment": [
                "ما هي مدة الخدمة المعتبرة لحساب المستحقات؟",
                "هل تم توثيق الفصل بإنذار رسمي؟",
                "هل تمت الاستقالة أم الفصل؟",
            ],
            "family": [
                "ما عمر الأطفال المطلوب حضانتهم؟",
                "هل هناك حكم طلاق سابق؟",
                "ما الوضع الاقتصادي للأطراف؟",
            ],
            "criminal": [
                "هل يوجد شهود أو أدلة مادية؟",
                "هل صدر قرار اتهام أو محضر؟",
                "ما الأضرار الناتجة من الفعل؟",
            ],
            "civil": [
                "هل العقد مكتوب وموثق؟",
                "هل توجد مراسلات بين الطرفين؟",
                "ما قيمة المطالبة المقدرة؟",
            ],
            "commercial": [
                "ما نوع العلاقة التجارية بين الأطراف؟",
                "هل يوجد سجل تجاري أو عقد شراكة؟",
                "ما قيمة النزاع؟",
            ],
            "rental": [
                "هل العقد مسجل رسمياً؟",
                "ما مدة الإيجار المتبقية؟",
                "هل تم إنذار المستأجر؟",
            ],
            "banking": [
                "هل يوجد عقد قرض موقّع؟",
                "ما مدة التأخير في السداد؟",
                "هل وُجّه إنذار رسمي من البنك؟",
            ],
        }
        default_qs = [
            "ما الوقائع الأساسية للنزاع؟",
            "ما الأدلة المتوفرة حالياً؟",
            "هل توجد محاولات سابقة لحل النزاع ودياً؟",
        ]
        qs = _TEMPLATES.get(binding.domain.value, default_qs)
        return {
            "questions": qs[:3],
            "authoritative_path": "unified_fail_closed",
            "llm_used": False,
            "derived_from": "domain_binder",
            "domain": binding.domain.value,
        }
    except Exception as e:
        log.debug("followup endpoint error: %s", e)
        return {"questions": [], "authoritative_path": "unified_fail_closed",
                "llm_used": False}


@router.get("/api/v1/learning/failures")
async def get_top_failures(days: int = 7, limit: int = 20):
    """أكثر الأسئلة التي فشل النظام في الإجابة عليها"""
    try:
        async with app_state.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT query, result_type, COUNT(*) as cnt,
                       MAX(created_at) as last_seen
                FROM learning_log
                WHERE result_type IN ('not_found','low_relevance')
                  AND created_at > NOW() - ($1 || ' days')::INTERVAL
                GROUP BY query, result_type
                ORDER BY cnt DESC LIMIT $2
            """, str(days), limit)
        return [{"query": r["query"], "type": r["result_type"],
                 "count": r["cnt"], "last_seen": str(r["last_seen"])} for r in rows]
    except Exception as e:
        return {"error": str(e)}
