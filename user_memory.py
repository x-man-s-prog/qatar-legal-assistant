# -*- coding: utf-8 -*-
"""
user_memory.py — User Memory & Personalization Service
=======================================================
يحفظ تفضيلات المستخدم عبر الجلسات ويُضيف context شخصي للـ system prompt.

الجدول:
  user_preferences (
    session_id          TEXT PRIMARY KEY,
    preferred_detail_level TEXT DEFAULT 'standard',
    common_topics       TEXT[] DEFAULT '{}',
    last_laws_cited     TEXT[] DEFAULT '{}',
    query_count         INTEGER DEFAULT 0,
    updated_at          TIMESTAMPTZ DEFAULT NOW()
  )
"""
from __future__ import annotations

import logging
import re
from typing import Optional

log = logging.getLogger(__name__)

# ── DDL ──────────────────────────────────────────────────────
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS user_preferences (
    session_id           TEXT PRIMARY KEY,
    preferred_detail_level TEXT DEFAULT 'standard',
    common_topics        TEXT[] DEFAULT '{}',
    last_laws_cited      TEXT[] DEFAULT '{}',
    query_count          INTEGER DEFAULT 0,
    updated_at           TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_user_prefs_updated
    ON user_preferences (updated_at DESC);
"""

# ── قوائم المواضيع والقوانين للاستخراج ─────────────────────
_TOPIC_KEYWORDS: dict[str, str] = {
    "عمل|عامل|راتب|أجر|إجازة|فصل|عقد عمل|نهاية خدمة": "قانون العمل",
    "طلاق|زواج|نفقة|حضانة|ميراث|وصية|أسرة|زوج|زوجة": "قانون الأسرة",
    "سرقة|اعتداء|جريمة|عقوبة|غرامة|سجن|جنحة|جناية": "قانون العقوبات",
    "شركة|تجارة|عقد|مقاولة|دين|إفلاس": "القانون التجاري",
    "إيجار|عقار|ملكية|تسجيل|رهن": "قانون الإيجارات",
    "مرور|سيارة|حادث|رخصة قيادة": "قانون المرور",
    "إقامة|جواز|تأشيرة|ترحيل|جنسية": "قانون الإقامة",
    "إجراءات|محكمة|دعوى|استئناف|تقاضي": "قانون الإجراءات",
    "موظف|خدمة مدنية|حكومة": "قانون الخدمة المدنية",
}

_LAW_NAMES_RE = re.compile(
    r'قانون\s+[\u0600-\u06FF\s]+(?:رقم\s+\d+)?|'
    r'المادة\s+\d+\s+من\s+[\u0600-\u06FF\s]+'
    r'(?:لسنة\s+\d{4})?',
    re.UNICODE
)

_DETAIL_PATTERNS = {
    "detailed": re.compile(r'اشرح|فصّل|بالتفصيل|شرح كامل|أريد أن أعرف كل', re.IGNORECASE),
    "brief":    re.compile(r'باختصار|مختصر|بإيجاز|فقط|بس', re.IGNORECASE),
}

# ── Singleton ─────────────────────────────────────────────────
_svc: Optional["UserMemoryService"] = None


def init_user_memory(pool) -> "UserMemoryService":
    global _svc
    _svc = UserMemoryService(pool)
    return _svc


def get_user_memory() -> Optional["UserMemoryService"]:
    return _svc


# ══════════════════════════════════════════════════════════════
class UserMemoryService:
    """
    خدمة ذاكرة المستخدم الشخصية.
    """

    def __init__(self, pool):
        self._pool = pool

    # ── ensure_table ──────────────────────────────────────────
    async def ensure_table(self) -> bool:
        if not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(CREATE_TABLE_SQL)
            log.info("✓ user_preferences table ready")
            return True
        except Exception as e:
            log.warning("ensure_table failed: %s", e)
            return False

    # ── get_preferences ───────────────────────────────────────
    async def get_preferences(self, session_id: str) -> dict:
        """يُعيد تفضيلات المستخدم أو dict فارغ إن لم توجد."""
        if not self._pool or not session_id:
            return _empty_prefs(session_id)
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM user_preferences WHERE session_id = $1",
                    str(session_id)[:100],
                )
            if row:
                return {
                    "session_id":            row["session_id"],
                    "preferred_detail_level": row["preferred_detail_level"],
                    "common_topics":         list(row["common_topics"] or []),
                    "last_laws_cited":       list(row["last_laws_cited"] or []),
                    "query_count":           row["query_count"],
                }
            return _empty_prefs(session_id)
        except Exception as e:
            log.debug("get_preferences error (non-critical): %s", e)
            return _empty_prefs(session_id)

    # ── update_after_answer ───────────────────────────────────
    async def update_after_answer(
        self,
        session_id: str,
        query: str,
        answer: str,
        citations: list | None = None,
        sources: list | None = None,
    ) -> None:
        """
        يستخرج الموضوع والقوانين من الإجابة ويُحدّث user_preferences.
        Non-critical — أي خطأ يُتجاهل.
        """
        if not self._pool or not session_id:
            return
        try:
            topic     = _extract_topic(query)
            laws      = _extract_cited_laws(answer, citations, sources)
            detail_pref = _detect_detail_preference(query)

            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO user_preferences
                        (session_id, preferred_detail_level, common_topics,
                         last_laws_cited, query_count)
                    VALUES ($1, $2, $3::text[], $4::text[], 1)
                    ON CONFLICT (session_id) DO UPDATE SET
                        preferred_detail_level = CASE
                            WHEN $2 != 'standard' THEN $2
                            ELSE user_preferences.preferred_detail_level
                        END,
                        common_topics = (
                            SELECT ARRAY(
                                SELECT DISTINCT unnest(
                                    user_preferences.common_topics || $3::text[]
                                ) LIMIT 10
                            )
                        ),
                        last_laws_cited = (
                            SELECT ARRAY(
                                SELECT DISTINCT unnest(
                                    $4::text[] || user_preferences.last_laws_cited
                                ) LIMIT 10
                            )
                        ),
                        query_count = user_preferences.query_count + 1,
                        updated_at  = NOW()
                    """,
                    str(session_id)[:100],
                    detail_pref,
                    [topic] if topic else [],
                    laws[:5],
                )
        except Exception as e:
            log.debug("update_after_answer (non-critical): %s", e)

    # ── build_user_context ────────────────────────────────────
    async def build_user_context(self, session_id: str) -> str:
        """
        يُعيد جملة context شخصي تُضاف لـ system prompt.
        مثال: "المستخدم يسأل كثيراً عن قانون العمل، يُفضّل إجابات مفصّلة."
        يُعيد "" إذا لا يوجد سياق مفيد.
        """
        prefs = await self.get_preferences(session_id)
        if prefs["query_count"] < 2:
            return ""

        parts: list[str] = []

        # المواضيع الشائعة
        topics = prefs["common_topics"][:3]
        if topics:
            parts.append(f"المستخدم يسأل كثيراً عن: {' و'.join(topics)}")

        # مستوى التفصيل
        lvl = prefs["preferred_detail_level"]
        if lvl == "detailed":
            parts.append("يُفضّل إجابات مفصّلة وشاملة")
        elif lvl == "brief":
            parts.append("يُفضّل إجابات مختصرة ومباشرة")

        # آخر القوانين المُستشهد بها
        laws = prefs["last_laws_cited"][:2]
        if laws:
            parts.append(f"سبق أن استُشهد له بـ: {' و'.join(laws)}")

        if not parts:
            return ""
        return "【ملاحظة شخصية للمساعد】 " + " — ".join(parts) + "."

    # ── get_stats ─────────────────────────────────────────────
    async def get_stats(self, session_id: str | None = None) -> dict:
        """إحصائيات للـ endpoint."""
        if not self._pool:
            return {"available": False}
        try:
            async with self._pool.acquire() as conn:
                total = await conn.fetchval("SELECT COUNT(*) FROM user_preferences") or 0
                active = await conn.fetchval(
                    "SELECT COUNT(*) FROM user_preferences WHERE query_count >= 3"
                ) or 0
            result = {"available": True, "total_sessions": int(total), "active_sessions": int(active)}
            if session_id:
                result["preferences"] = await self.get_preferences(session_id)
            return result
        except Exception as e:
            return {"available": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════
# Helpers (pure functions — testable without DB)
# ══════════════════════════════════════════════════════════════

def _extract_topic(query: str) -> str:
    """يستخرج الموضوع القانوني من السؤال."""
    q_lower = query.lower()
    for pattern, topic in _TOPIC_KEYWORDS.items():
        if re.search(pattern, q_lower, re.IGNORECASE | re.UNICODE):
            return topic
    return ""


def _extract_cited_laws(
    answer: str,
    citations: list | None,
    sources: list | None,
) -> list[str]:
    """يستخرج أسماء القوانين من الإجابة/المصادر."""
    laws: list[str] = []

    # من citations مباشرةً
    if citations:
        for c in citations:
            src = c.get("source", "")
            if src and src not in laws:
                laws.append(src)

    # من sources
    if sources:
        for s in sources:
            title = s.get("title", "") or s.get("law_name", "")
            if title and title not in laws:
                laws.append(title)

    # من نص الإجابة
    if not laws:
        matches = _LAW_NAMES_RE.findall(answer or "")
        for m in matches[:5]:
            m = m.strip()
            if m and m not in laws:
                laws.append(m)

    return list(dict.fromkeys(laws))[:10]   # deduplicate, max 10


def _detect_detail_preference(query: str) -> str:
    """يكتشف مستوى التفصيل المُفضَّل من نص السؤال."""
    if _DETAIL_PATTERNS["detailed"].search(query):
        return "detailed"
    if _DETAIL_PATTERNS["brief"].search(query):
        return "brief"
    return "standard"


def _empty_prefs(session_id: str) -> dict:
    return {
        "session_id":            session_id,
        "preferred_detail_level": "standard",
        "common_topics":         [],
        "last_laws_cited":       [],
        "query_count":           0,
    }
