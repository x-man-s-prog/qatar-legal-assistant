# -*- coding: utf-8 -*-
"""
core/db_utils.py — Database utility functions extracted from main.py.
"""
import json, logging, asyncio
from pathlib import Path
from core import app_state
from core.config import GEMINI_KEY
from core.nlp_utils import normalize_ar

log = logging.getLogger(__name__)

async def _ensure_learning_tables():
    """ينشئ جداول التعلم إذا لم تكن موجودة"""
    sql_path = Path(__file__).parent / "migrate_learning.sql"
    if not sql_path.exists():
        return
    sql = sql_path.read_text(encoding="utf-8")
    try:
        async with app_state.pool.acquire() as conn:
            await conn.execute(sql)
        log.info("✓ جداول التعلم جاهزة")
    except Exception as e:
        log.warning("migrate_learning: %s", e)

async def log_query(session_id: str, query: str, query_type: str,
                    result_type: str, answer: str = "", top_score: float = 0,
                    sources_count: int = 0, model_used: str = "", latency_ms: int = 0):
    """يسجّل كل محادثة في learning_log بشكل غير متزامن (لا يبطئ الاستجابة)"""
    try:
        async with app_state.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO learning_log
                    (session_id, query, query_type, result_type, answer,
                     top_score, sources_count, model_used, latency_ms)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            """, session_id, query[:500], query_type, result_type,
                answer[:1000], top_score, sources_count, model_used, latency_ms)
    except Exception as e:
        log.debug("log_query: %s", e)

async def save_to_cache(query: str, answer: str, sources: list, model: str):
    """يحفظ الإجابة في الكاش إذا كانت ذات جودة كافية"""
    if not answer or len(answer) < 100:
        return
    q_norm = normalize_ar(query.strip().lower())
    try:
        async with app_state.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO answer_cache (query_norm, query_orig, answer, sources_json, model_used)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (query_norm) DO UPDATE SET
                    answer = EXCLUDED.answer,
                    sources_json = EXCLUDED.sources_json,
                    hit_count = answer_cache.hit_count + 1,
                    last_hit_at = NOW(),
                    expires_at = NOW() + INTERVAL '30 days'
            """, q_norm, query[:500], answer[:3000],
                json.dumps(sources[:5], ensure_ascii=False), model)
    except Exception as e:
        log.debug("save_to_cache: %s", e)

async def check_cache(query: str) -> dict | None:
    """يبحث عن إجابة مخزّنة للسؤال — يُعيد None إذا لم يجد"""
    q_norm = normalize_ar(query.strip().lower())
    try:
        async with app_state.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT query_orig, answer, sources_json, model_used, hit_count
                FROM answer_cache
                WHERE query_norm = $1 AND expires_at > NOW()
                LIMIT 1
            """, q_norm)
            if row:
                # تحديث عداد الاستخدام
                await conn.execute(
                    "UPDATE answer_cache SET hit_count=hit_count+1, last_hit_at=NOW() WHERE query_norm=$1",
                    q_norm)
                return dict(row)
    except Exception as e:
        log.debug("check_cache: %s", e)
    return None

async def submit_feedback(log_id: int, feedback: int, note: str = ""):
    """يُحدِّث تقييم المستخدم (+1 إعجاب / -1 عدم إعجاب)"""
    try:
        async with app_state.pool.acquire() as conn:
            await conn.execute(
                "UPDATE learning_log SET feedback=$1, feedback_note=$2 WHERE id=$3",
                feedback, note[:200], log_id)
    except Exception as e:
        log.debug("submit_feedback: %s", e)

async def get_learning_stats() -> dict:
    """إحصائيات التعلم للعرض في الواجهة"""
    try:
        async with app_state.pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM learning_log") or 0
            found = await conn.fetchval(
                "SELECT COUNT(*) FROM learning_log WHERE result_type='found'") or 0
            cached = await conn.fetchval(
                "SELECT COUNT(*) FROM learning_log WHERE result_type='cached'") or 0
            liked = await conn.fetchval(
                "SELECT COUNT(*) FROM learning_log WHERE feedback=1") or 0
            disliked = await conn.fetchval(
                "SELECT COUNT(*) FROM learning_log WHERE feedback=-1") or 0
            cache_size = await conn.fetchval("SELECT COUNT(*) FROM answer_cache") or 0
            fewshot_count = await conn.fetchval(
                "SELECT COUNT(*) FROM fewshot_examples WHERE active=TRUE") or 0
            # أكثر الأسئلة الفاشلة (بدون نتائج)
            top_failures = await conn.fetch("""
                SELECT query, COUNT(*) as cnt
                FROM learning_log
                WHERE result_type IN ('not_found','low_relevance')
                  AND created_at > NOW() - INTERVAL '7 days'
                GROUP BY query ORDER BY cnt DESC LIMIT 5
            """)
        return {
            "total_queries": total,
            "found_rate": round(found / max(total, 1) * 100, 1),
            "cached_served": cached,
            "positive_feedback": liked,
            "negative_feedback": disliked,
            "satisfaction_rate": round(liked / max(liked + disliked, 1) * 100, 1),
            "cache_size": cache_size,
            "fewshot_examples": fewshot_count,
            "top_failures_7d": [{"query": r["query"][:80], "count": r["cnt"]}
                                 for r in top_failures],
        }
    except Exception as e:
        log.warning("get_learning_stats: %s", e)
        return {}

async def get_fewshot_examples(n: int = 3) -> str:
    """يجلب أمثلة few-shot عالية الجودة لحقنها في الـ prompt"""
    try:
        async with app_state.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT query, answer FROM fewshot_examples
                WHERE active=TRUE AND quality_score >= 0.7
                ORDER BY quality_score DESC, use_count ASC
                LIMIT $1
            """, n)
            if not rows:
                return ""
            # تحديث عداد الاستخدام
            await conn.execute("""
                UPDATE fewshot_examples SET use_count=use_count+1
                WHERE query = ANY($1::text[])
            """, [r["query"] for r in rows])
            parts = []
            for r in rows:
                parts.append(f"سؤال: {r['query']}\nإجابة: {r['answer'][:400]}")
            return "\n\n---\n\n".join(parts)
    except Exception:
        return ""

async def run_weekly_analysis() -> dict:
    """
    يُشغَّل أسبوعياً:
    1. يجمع المحادثات الفاشلة من آخر 7 أيام
    2. يُرسلها لـ Gemini للتحليل
    3. يحفظ الاقتراحات في improvement_suggestions
    4. يُضيف أمثلة few-shot من أفضل المحادثات الناجحة
    """
    if not GEMINI_KEY:
        return {"error": "GEMINI_KEY غير مُعيَّن"}

    try:
        async with app_state.pool.acquire() as conn:
            # اجمع الفشل
            failures = await conn.fetch("""
                SELECT query, result_type, COUNT(*) as cnt
                FROM learning_log
                WHERE result_type IN ('not_found','low_relevance')
                  AND created_at > NOW() - INTERVAL '7 days'
                GROUP BY query, result_type
                ORDER BY cnt DESC LIMIT 30
            """)
            # اجمع النجاح المُعجَب به
            successes = await conn.fetch("""
                SELECT query, answer
                FROM learning_log
                WHERE feedback = 1
                  AND result_type = 'found'
                  AND created_at > NOW() - INTERVAL '7 days'
                  AND LENGTH(answer) > 200
                ORDER BY created_at DESC LIMIT 10
            """)
            total_7d = await conn.fetchval(
                "SELECT COUNT(*) FROM learning_log WHERE created_at > NOW() - INTERVAL '7 days'") or 0
            failed_7d = len(failures)

        if not failures and not successes:
            return {"status": "لا توجد بيانات كافية للتحليل بعد"}

        # بناء طلب التحليل
        failure_list = "\n".join(
            f"- [{r['result_type']}] \"{r['query']}\" (تكرر {r['cnt']} مرة)"
            for r in failures[:20])
        analysis_prompt = f"""أنت محلل لأداء نظام استشاري قانوني قطري.

إليك إحصائيات آخر 7 أيام:
- إجمالي الاستعلامات: {total_7d}
- فشل في الإجابة: {failed_7d}
- معدل الفشل: {round(failed_7d/max(total_7d,1)*100,1)}%

الأسئلة التي فشل النظام في الإجابة عليها:
{failure_list}

مهمتك:
1. حدّد أكثر 3 أسباب جذرية للفشل (كلمات مفتاحية ناقصة؟ موضوع غير مغطى؟ صياغة غريبة؟)
2. اقترح 5 كلمات مفتاحية جديدة لإضافتها لقاموس البحث
3. اقترح جملة واحدة لإضافتها لـ system prompt تُحسّن الاستجابة

أخرج JSON فقط:
{{
  "root_causes": ["سبب 1", "سبب 2", "سبب 3"],
  "missing_keywords": ["كلمة1", "كلمة2", "كلمة3", "كلمة4", "كلمة5"],
  "prompt_suggestion": "جملة واحدة محددة للإضافة",
  "summary": "ملخص قصير"
}}"""

        parts = []
        from services.llm_service import stream_gemini
        async for t in stream_gemini("أنت محلل بيانات متخصص.",
                                     [{"role": "user", "content": analysis_prompt}],
                                     max_tokens=600):
            parts.append(t)
        raw = "".join(parts)

        m = re.search(r'\{.*\}', raw, re.DOTALL)
        analysis = json.loads(m.group()) if m else {"raw": raw}

        # أضف أمثلة few-shot من النجاحات
        examples_added = 0
        async with app_state.pool.acquire() as conn:
            for row in successes[:5]:
                try:
                    await conn.execute("""
                        INSERT INTO fewshot_examples (query, answer, quality_score)
                        VALUES ($1, $2, 0.8)
                        ON CONFLICT DO NOTHING
                    """, row["query"][:300], row["answer"][:800])
                    examples_added += 1
                except Exception:
                    pass

            # احفظ نتيجة التحليل
            await conn.execute("""
                INSERT INTO improvement_suggestions
                    (period_start, period_end, total_queries, failed_queries,
                     failure_rate, root_causes, missing_keywords,
                     prompt_suggestion, examples_added)
                VALUES (NOW()-INTERVAL '7 days', NOW(), $1, $2, $3, $4, $5, $6, $7)
            """, total_7d, failed_7d, round(failed_7d/max(total_7d,1)*100,1),
                json.dumps(analysis.get("root_causes", []), ensure_ascii=False),
                json.dumps(analysis.get("missing_keywords", []), ensure_ascii=False),
                analysis.get("prompt_suggestion", ""),
                examples_added)

        log.info("التحليل الأسبوعي اكتمل: %d أمثلة أضيفت", examples_added)
        return {
            "status": "اكتمل",
            "total_queries": total_7d,
            "failed_queries": failed_7d,
            "examples_added": examples_added,
            "analysis": analysis,
        }

    except Exception as e:
        log.exception("run_weekly_analysis: %s", e)
        return {"error": str(e)}

