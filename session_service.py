# -*- coding: utf-8 -*-
"""
Session Service — خدمة الجلسات الدائمة
========================================
يحل محل الـ in-memory dict في main.py بتخزين دائم في PostgreSQL.

المزايا مقارنة بالحل القديم:
  • الجلسات تبقى عند إعادة تشغيل السيرفر
  • تدعم multi-worker (Gunicorn / Uvicorn workers)
  • تنظيف تلقائي للجلسات القديمة
  • بحث سريع بـ session_id

يستخدم asyncpg مباشرةً (متسق مع بقية الكود).
لا يحتاج SQLAlchemy — يعمل مع نفس pool قاعدة البيانات الموجودة.

الجدول المُنشأ تلقائياً:
  chat_sessions (
    session_id   TEXT PRIMARY KEY,
    user_id      TEXT,
    messages     JSONB DEFAULT '[]',
    summary      TEXT DEFAULT '',
    legal_facts  JSONB DEFAULT '[]',
    created_at   TIMESTAMPTZ DEFAULT now(),
    updated_at   TIMESTAMPTZ DEFAULT now(),
    expires_at   TIMESTAMPTZ
  )

الأداء:
  - get:    ~1ms (single key lookup)
  - save:   ~2ms (upsert by primary key)
  - cleanup:~5ms (DELETE WHERE expires_at < now())
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
# DDL — إنشاء الجدول إن لم يكن موجوداً
# ══════════════════════════════════════════════════════════
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id   TEXT        PRIMARY KEY,
    user_id      TEXT,
    messages     JSONB       NOT NULL DEFAULT '[]'::jsonb,
    summary      TEXT        NOT NULL DEFAULT '',
    legal_facts  JSONB       NOT NULL DEFAULT '[]'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id
    ON chat_sessions (user_id)
    WHERE user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_chat_sessions_expires_at
    ON chat_sessions (expires_at)
    WHERE expires_at IS NOT NULL;
"""


# ══════════════════════════════════════════════════════════
# SessionService — الفئة الرئيسية
# ══════════════════════════════════════════════════════════
class SessionService:
    """
    خدمة إدارة الجلسات عبر PostgreSQL.

    الاستخدام:
        # عند بدء التطبيق:
        svc = SessionService(pool, ttl_hours=24)
        await svc.init_db()

        # في كل طلب:
        messages = await svc.get_messages(session_id)
        await svc.add_message(session_id, "user", "سؤالي...")
        await svc.add_message(session_id, "assistant", "الإجابة...")
    """

    def __init__(self, pool, ttl_hours: int = 24, max_messages: int = 20):
        """
        Args:
            pool:         asyncpg connection pool (نفس _pool في main.py)
            ttl_hours:    عمر الجلسة بالساعات قبل الحذف
            max_messages: أقصى عدد رسائل محفوظة في الجلسة
        """
        self._pool        = pool
        self.ttl_hours    = ttl_hours
        self.max_messages = max_messages

    async def init_db(self) -> bool:
        """
        يُنشئ جدول chat_sessions وفهارسه إن لم تكن موجودة.
        آمن للاستدعاء مرات متعددة (IF NOT EXISTS).

        Returns:
            True إذا نجح، False إذا فشل (الـ app يكمل بدون جلسات دائمة)
        """
        if not self._pool:
            log.warning("SessionService: لا يوجد pool — الجلسات ستُحفظ في الذاكرة فقط")
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(_CREATE_TABLE_SQL)
            log.info("✓ SessionService: جدول chat_sessions جاهز")
            return True
        except Exception as e:
            log.error("SessionService.init_db فشل: %s", e)
            return False

    # ────────────────────────────────────────────────────
    # قراءة الجلسة
    # ────────────────────────────────────────────────────

    async def get_messages(self, session_id: str) -> list[dict]:
        """
        يُعيد قائمة الرسائل للجلسة.
        يُعيد [] إذا لم تكن الجلسة موجودة أو انتهت.

        Performance: ~1ms (SELECT by PK)
        """
        if not self._pool or not session_id:
            return []
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT messages, expires_at
                    FROM   chat_sessions
                    WHERE  session_id = $1
                    """,
                    session_id,
                )
            if not row:
                return []
            # تحقق من انتهاء صلاحية الجلسة
            if row["expires_at"] and row["expires_at"] < datetime.now(timezone.utc):
                await self.delete_session(session_id)
                return []
            msgs = row["messages"]
            # asyncpg يُعيد JSONB كـ str في بعض الإصدارات
            if isinstance(msgs, str):
                msgs = json.loads(msgs)
            return msgs or []
        except Exception as e:
            log.debug("SessionService.get_messages: %s", e)
            return []

    async def get_session_data(self, session_id: str) -> Optional[dict]:
        """
        يُعيد بيانات الجلسة الكاملة (رسائل + ملخص + حقائق).
        مفيد لـ ctx_manager.
        """
        if not self._pool or not session_id:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT session_id, user_id, messages, summary,
                           legal_facts, created_at, updated_at
                    FROM   chat_sessions
                    WHERE  session_id = $1
                      AND  (expires_at IS NULL OR expires_at > now())
                    """,
                    session_id,
                )
            if not row:
                return None
            return {
                "session_id":  row["session_id"],
                "user_id":     row["user_id"],
                "messages":    _parse_json(row["messages"]),
                "summary":     row["summary"] or "",
                "legal_facts": _parse_json(row["legal_facts"]),
                "created_at":  row["created_at"].isoformat() if row["created_at"] else None,
                "updated_at":  row["updated_at"].isoformat() if row["updated_at"] else None,
            }
        except Exception as e:
            log.debug("SessionService.get_session_data: %s", e)
            return None

    # ────────────────────────────────────────────────────
    # كتابة / تحديث الجلسة
    # ────────────────────────────────────────────────────

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: Optional[str] = None,
    ) -> bool:
        """
        يُضيف رسالة للجلسة. ينشئ الجلسة تلقائياً إن لم تكن موجودة.

        Args:
            session_id: معرف الجلسة
            role:       "user" | "assistant"
            content:    نص الرسالة (يُقطع عند 2000 حرف)
            user_id:    معرف المستخدم (اختياري)

        Performance: ~2ms (UPSERT + jsonb_append)
        """
        if not self._pool or not session_id:
            return False
        content = content[:2000]   # حد أقصى لكل رسالة
        expires = datetime.now(timezone.utc) + timedelta(hours=self.ttl_hours)
        new_msg = json.dumps({"role": role, "content": content}, ensure_ascii=False)
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO chat_sessions (session_id, user_id, messages, expires_at)
                    VALUES ($1, $2, jsonb_build_array($3::jsonb), $4)
                    ON CONFLICT (session_id) DO UPDATE SET
                        messages   = (
                            CASE
                                -- إذا تجاوز العدد الأقصى، أزل الأقدم
                                WHEN jsonb_array_length(chat_sessions.messages) >= $5
                                THEN (chat_sessions.messages - 0) || jsonb_build_array($3::jsonb)
                                ELSE chat_sessions.messages || jsonb_build_array($3::jsonb)
                            END
                        ),
                        updated_at = now(),
                        expires_at = $4,
                        user_id    = COALESCE(chat_sessions.user_id, $2)
                    """,
                    session_id,
                    user_id,
                    new_msg,
                    expires,
                    self.max_messages,
                )
            return True
        except Exception as e:
            log.debug("SessionService.add_message: %s", e)
            return False

    async def save_messages(
        self,
        session_id: str,
        messages: list[dict],
        user_id: Optional[str] = None,
    ) -> bool:
        """
        يحفظ قائمة رسائل كاملة (للتحديث الدفعي).
        يستبدل الرسائل الموجودة بالكامل.
        """
        if not self._pool or not session_id:
            return False
        expires  = datetime.now(timezone.utc) + timedelta(hours=self.ttl_hours)
        messages = messages[-self.max_messages:]   # حفظ آخر N رسالة فقط
        msgs_json = json.dumps(messages, ensure_ascii=False)
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO chat_sessions (session_id, user_id, messages, expires_at)
                    VALUES ($1, $2, $3::jsonb, $4)
                    ON CONFLICT (session_id) DO UPDATE SET
                        messages   = $3::jsonb,
                        updated_at = now(),
                        expires_at = $4,
                        user_id    = COALESCE(chat_sessions.user_id, $2)
                    """,
                    session_id,
                    user_id,
                    msgs_json,
                    expires,
                )
            return True
        except Exception as e:
            log.debug("SessionService.save_messages: %s", e)
            return False

    async def update_summary(
        self,
        session_id: str,
        summary: str,
        legal_facts: Optional[list] = None,
    ) -> bool:
        """يحدّث الملخص والحقائق القانونية للجلسة."""
        if not self._pool or not session_id:
            return False
        facts_json = json.dumps(legal_facts or [], ensure_ascii=False)
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE chat_sessions
                    SET    summary     = $2,
                           legal_facts = $3::jsonb,
                           updated_at  = now()
                    WHERE  session_id  = $1
                    """,
                    session_id,
                    summary[:1000],
                    facts_json,
                )
            return True
        except Exception as e:
            log.debug("SessionService.update_summary: %s", e)
            return False

    # ────────────────────────────────────────────────────
    # حذف وتنظيف
    # ────────────────────────────────────────────────────

    async def delete_session(self, session_id: str) -> bool:
        """يحذف جلسة واحدة."""
        if not self._pool or not session_id:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM chat_sessions WHERE session_id = $1",
                    session_id,
                )
            return True
        except Exception as e:
            log.debug("SessionService.delete_session: %s", e)
            return False

    async def cleanup_expired(self) -> int:
        """
        يحذف الجلسات المنتهية الصلاحية.
        يُشغَّل بشكل دوري من lifespan loop في main.py.

        Returns:
            عدد الجلسات المحذوفة
        """
        if not self._pool:
            return 0
        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM chat_sessions WHERE expires_at < now()"
                )
            # asyncpg يُعيد "DELETE N"
            count = int(result.split()[-1]) if result else 0
            if count:
                log.info("SessionService: %d جلسة منتهية حُذفت", count)
            return count
        except Exception as e:
            log.debug("SessionService.cleanup_expired: %s", e)
            return 0

    async def cleanup_old_sessions(self, days: int = 30) -> int:
        """يحذف الجلسات الأقدم من N يوم (بغض النظر عن expires_at)."""
        if not self._pool:
            return 0
        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM chat_sessions WHERE updated_at < now() - $1::interval",
                    f"{days} days",
                )
            count = int(result.split()[-1]) if result else 0
            log.info("SessionService: %d جلسة قديمة (>%dd) حُذفت", count, days)
            return count
        except Exception as e:
            log.debug("SessionService.cleanup_old_sessions: %s", e)
            return 0

    # ────────────────────────────────────────────────────
    # إحصاءات
    # ────────────────────────────────────────────────────

    async def get_stats(self) -> dict:
        """يُعيد إحصاءات الجلسات للـ /api/v1/system_status endpoint."""
        if not self._pool:
            return {"available": False}
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*)                             AS total,
                        COUNT(*) FILTER (WHERE expires_at > now()) AS active,
                        COUNT(*) FILTER (WHERE expires_at <= now()) AS expired,
                        AVG(jsonb_array_length(messages))   AS avg_messages
                    FROM chat_sessions
                    """
                )
            return {
                "available":    True,
                "total":        row["total"]        or 0,
                "active":       row["active"]       or 0,
                "expired":      row["expired"]      or 0,
                "avg_messages": round(float(row["avg_messages"] or 0), 1),
                "ttl_hours":    self.ttl_hours,
            }
        except Exception as e:
            return {"available": False, "error": str(e)}


# ══════════════════════════════════════════════════════════
# Global instance (يُهيَّأ في lifespan بعد إنشاء _pool)
# ══════════════════════════════════════════════════════════
_session_svc: Optional[SessionService] = None


def init_session_service(pool, ttl_hours: int = 24) -> SessionService:
    """يُنشئ instance عالمي من SessionService ويحفظه."""
    global _session_svc
    _session_svc = SessionService(pool, ttl_hours=ttl_hours)
    return _session_svc


def get_session_service() -> Optional[SessionService]:
    """يُعيد الـ instance العالمي."""
    return _session_svc


# ══════════════════════════════════════════════════════════
# دوال مساعدة
# ══════════════════════════════════════════════════════════
def _parse_json(value) -> list:
    """يُحوّل JSONB string أو list للـ Python list بأمان."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return []
    return []
