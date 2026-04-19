# -*- coding: utf-8 -*-
"""
conversation_summarizer.py — ملخص المحادثة الذكي
=================================================
كل SUMMARY_INTERVAL رسائل (افتراضي: 6) يُلخّص المحادثة
في 3 جمل ويحفظها في جدول conversation_summaries.

يُضاف الملخص لـ system prompt كـ:
  【سياق المحادثة】 المستخدم يسأل عن نزاع عمالي في شركة...
النتيجة: المحادثة تحتفظ بالسياق إلى الأبد (بما يتجاوز maxlen=8).
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

SUMMARY_INTERVAL: int = 6   # كل N رسائل يُلخّص

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS conversation_summaries (
    session_id  TEXT PRIMARY KEY,
    summary     TEXT DEFAULT '',
    turn_count  INTEGER DEFAULT 0,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_conv_sum_updated
    ON conversation_summaries (updated_at DESC);
"""

_svc: Optional["ConversationSummarizer"] = None


def init_conversation_summarizer(pool, llm_fn=None) -> "ConversationSummarizer":
    global _svc
    _svc = ConversationSummarizer(pool, llm_fn)
    return _svc


def get_conversation_summarizer() -> Optional["ConversationSummarizer"]:
    return _svc


# ══════════════════════════════════════════════════════════════
class ConversationSummarizer:
    """تلخيص المحادثة وحفظها للاستخدام في system prompt."""

    def __init__(self, pool, llm_fn=None):
        self._pool   = pool
        self._llm_fn = llm_fn   # async fn(prompt: str) -> str

    # ── ensure_table ───────────────────────────────────────────
    async def ensure_table(self) -> bool:
        if not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(CREATE_TABLE_SQL)
            log.info("✓ conversation_summaries table ready")
            return True
        except Exception as e:
            log.warning("ensure_table failed: %s", e)
            return False

    # ── get_summary ────────────────────────────────────────────
    async def get_summary(self, session_id: str) -> str:
        """يُعيد ملخص المحادثة السابقة أو string فارغ."""
        if not self._pool or not session_id:
            return ""
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT summary FROM conversation_summaries WHERE session_id = $1",
                    str(session_id)[:100],
                )
            return row["summary"] if row and row["summary"] else ""
        except Exception as e:
            log.debug("get_summary: %s", e)
            return ""

    # ── maybe_summarize ────────────────────────────────────────
    async def maybe_summarize(
        self, session_id: str, history: list[dict]
    ) -> None:
        """يُلخّص إذا وصل عدد الرسائل لـ SUMMARY_INTERVAL."""
        if not session_id or not history:
            return
        if not should_summarize(history):
            return
        await self._do_summarize(session_id, history)

    async def _do_summarize(
        self, session_id: str, history: list[dict]
    ) -> None:
        """يُنفّذ التلخيص ويحفظ في DB."""
        summary = ""

        # محاولة LLM أولاً
        if self._llm_fn:
            try:
                raw     = await self._llm_fn(_build_summary_prompt(history))
                summary = (raw or "").strip()[:500]
            except Exception as e:
                log.debug("_do_summarize LLM: %s", e)

        # fallback: ملخص بسيط بدون LLM
        if not summary:
            summary = _extract_simple_summary(history)

        if not summary or not self._pool:
            return

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO conversation_summaries
                        (session_id, summary, turn_count)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (session_id) DO UPDATE SET
                        summary    = $2,
                        turn_count = $3,
                        updated_at = NOW()
                    """,
                    str(session_id)[:100],
                    summary,
                    len(history),
                )
        except Exception as e:
            log.debug("_do_summarize DB: %s", e)

    # ── build_context ──────────────────────────────────────────
    async def build_context(self, session_id: str) -> str:
        """يُعيد جملة السياق التي تُحقن في system prompt."""
        summary = await self.get_summary(session_id)
        if not summary:
            return ""
        return f"【سياق المحادثة】 {summary}"

    # ── get_stats ──────────────────────────────────────────────
    async def get_stats(self, session_id: str | None = None) -> dict:
        if not self._pool:
            return {"available": False}
        try:
            async with self._pool.acquire() as conn:
                total = await conn.fetchval(
                    "SELECT COUNT(*) FROM conversation_summaries"
                ) or 0
            result = {"available": True, "total_summaries": int(total)}
            if session_id:
                result["summary"] = await self.get_summary(session_id)
            return result
        except Exception as e:
            return {"available": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════
# Pure helpers — testable without DB or LLM
# ══════════════════════════════════════════════════════════════

def should_summarize(history: list[dict]) -> bool:
    """True إذا وصل عدد الرسائل لمضاعف SUMMARY_INTERVAL."""
    return len(history) > 0 and len(history) % SUMMARY_INTERVAL == 0


def _build_summary_prompt(history: list[dict]) -> str:
    """يبني prompt التلخيص للـ LLM — آخر 12 رسالة."""
    pairs: list[str] = []
    for msg in history[-12:]:
        role    = "المستخدم" if msg.get("role") == "user" else "المساعد"
        content = str(msg.get("content", ""))[:200]
        pairs.append(f"{role}: {content}")

    return (
        "لخّص المحادثة القانونية التالية في 3 جمل مختصرة باللغة العربية،"
        " مع ذكر الموضوع القانوني الرئيسي:\n\n"
        + "\n".join(pairs)
        + "\n\nالملخص (3 جمل فقط):"
    )


def _extract_simple_summary(history: list[dict]) -> str:
    """ملخص بسيط بدون LLM — يعتمد على أول سؤال من المستخدم."""
    for msg in history:
        if msg.get("role") == "user":
            content = str(msg.get("content", "")).strip()
            if content:
                return f"المستخدم يسأل عن: {content[:200]}"
    return ""
