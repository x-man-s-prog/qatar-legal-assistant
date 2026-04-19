# -*- coding: utf-8 -*-
"""
Feedback Learner — يحلل تقييمات المستخدمين ويستخرج insights.
يعمل فوق learning_log الموجود (لا يكرر التسجيل).
"""
import json, logging
from collections import defaultdict
log = logging.getLogger(__name__)

INSIGHTS_PATH = "/app/data/feedback_insights.json"


class FeedbackLearner:

    @staticmethod
    async def analyze(pool):
        """يحلل learning_log ويستخرج insights"""
        if not pool:
            return {"total": 0}

        async with pool.acquire() as conn:
            # إجمالي
            total = await conn.fetchval("SELECT count(*) FROM learning_log") or 0
            # إيجابي / سلبي
            positive = await conn.fetchval(
                "SELECT count(*) FROM learning_log WHERE feedback_score > 0") or 0
            negative = await conn.fetchval(
                "SELECT count(*) FROM learning_log WHERE feedback_score < 0") or 0
            # أسوأ الأسئلة
            worst = await conn.fetch(
                "SELECT query FROM learning_log WHERE feedback_score < 0 "
                "ORDER BY created_at DESC LIMIT 10")
            # حسب النوع
            by_type = await conn.fetch(
                "SELECT query_type, "
                "  count(*) as cnt, "
                "  count(*) FILTER (WHERE feedback_score > 0) as pos, "
                "  count(*) FILTER (WHERE feedback_score < 0) as neg "
                "FROM learning_log WHERE feedback_score IS NOT NULL "
                "GROUP BY query_type ORDER BY cnt DESC LIMIT 10")

        route_perf = {}
        for r in by_type:
            t = r["cnt"]
            rate = r["pos"] / max(t, 1) * 100
            route_perf[r["query_type"]] = "%d%% (%d)" % (rate, t)

        insights = {
            "total_feedback": positive + negative,
            "total_queries": total,
            "satisfaction": "%d%%" % (positive / max(positive + negative, 1) * 100),
            "route_performance": route_perf,
            "problem_queries": [r["query"][:100] for r in worst],
        }

        try:
            import os
            os.makedirs("/app/data", exist_ok=True)
            with open(INSIGHTS_PATH, "w", encoding="utf-8") as f:
                json.dump(insights, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.debug("insights save: %s", e)

        return insights
