# -*- coding: utf-8 -*-
"""
compare_service.py — خدمة مقارنة القوانين
==========================================
مدخلات : {law_a, law_b, aspect}
مخرجات : {aspect, law_a:{text,article,summary}, law_b:{text,article,summary}, difference}

الدوال النقية (testable بدون DB):
  _format_chunks, _build_compare_prompt, _parse_result, _empty_result
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

log = logging.getLogger(__name__)

_svc: Optional["CompareService"] = None


def init_compare_service(pool, llm_fn=None) -> "CompareService":
    global _svc
    _svc = CompareService(pool, llm_fn)
    return _svc


def get_compare_service() -> Optional["CompareService"]:
    return _svc


# ══════════════════════════════════════════════════════════════
class CompareService:
    """مقارنة قانونين حول جانب محدد."""

    def __init__(self, pool, llm_fn=None):
        self._pool   = pool
        self._llm_fn = llm_fn   # async fn(prompt: str) -> str

    # ── search ─────────────────────────────────────────────────
    async def search_law_chunks(
        self, law_name: str, aspect: str, top_k: int = 5
    ) -> list[dict]:
        """يبحث في جدول chunks عن نصوص مرتبطة بالقانون والجانب المطلوب."""
        if not self._pool or not law_name.strip():
            return []
        try:
            tokens = [
                w for w in re.split(r"\s+", f"{aspect} {law_name}".strip())
                if len(w) > 2
            ][:6]
            kw_pattern = "|".join(re.escape(t) for t in tokens) if tokens else law_name
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT law_name, article_number, content
                    FROM chunks
                    WHERE law_name ILIKE $1 OR content ~* $2
                    ORDER BY length(content) DESC
                    LIMIT $3
                    """,
                    f"%{law_name}%",
                    kw_pattern,
                    top_k,
                )
            return [
                {
                    "law":     r["law_name"],
                    "article": str(r["article_number"] or ""),
                    "text":    r["content"][:400],
                }
                for r in rows
            ]
        except Exception as e:
            log.debug("search_law_chunks(%s): %s", law_name, e)
            return []

    # ── compare ────────────────────────────────────────────────
    async def compare(
        self, law_a: str, law_b: str, aspect: str = ""
    ) -> dict:
        """يُجري المقارنة ويُعيد النتيجة المنظمة."""
        if not law_a or not law_b:
            return _empty_result(law_a, law_b, aspect, "يجب تحديد اسمَي القانونين")

        chunks_a = await self.search_law_chunks(law_a, aspect)
        chunks_b = await self.search_law_chunks(law_b, aspect)

        ctx_a = _format_chunks(chunks_a)
        ctx_b = _format_chunks(chunks_b)

        if not ctx_a and not ctx_b:
            return _empty_result(
                law_a, law_b, aspect,
                "لا توجد بيانات لهذين القانونين في قاعدة البيانات"
            )

        raw = ""
        if self._llm_fn:
            try:
                raw = await self._llm_fn(
                    _build_compare_prompt(law_a, law_b, aspect, ctx_a, ctx_b)
                )
            except Exception as e:
                log.warning("compare LLM error: %s", e)

        return _parse_result(raw, law_a, law_b, aspect, chunks_a, chunks_b)


# ══════════════════════════════════════════════════════════════
# Pure helpers — testable without DB or LLM
# ══════════════════════════════════════════════════════════════

def _format_chunks(chunks: list[dict]) -> str:
    """يُحوّل قائمة chunks إلى نص سياق."""
    if not chunks:
        return ""
    parts = []
    for c in chunks[:4]:
        art = f"المادة {c['article']}" if c.get("article") else ""
        parts.append(f"[{art}] {c['text']}" if art else c["text"])
    return "\n---\n".join(parts)


def _build_compare_prompt(
    law_a: str, law_b: str, aspect: str,
    ctx_a: str, ctx_b: str
) -> str:
    """يبني prompt المقارنة للـ LLM."""
    aspect_text = f"حول: {aspect.strip()}" if aspect.strip() else "بشكل عام"
    return (
        f"أنت مساعد قانوني متخصص. قارن بين القانونين التاليين {aspect_text}.\n\n"
        f"== {law_a} ==\n{ctx_a or 'لا توجد بيانات متاحة'}\n\n"
        f"== {law_b} ==\n{ctx_b or 'لا توجد بيانات متاحة'}\n\n"
        "أجب فقط بـ JSON صالح بهذا الشكل بدون أي نص إضافي قبله أو بعده:\n"
        "{\n"
        f'  "aspect": "{aspect.strip() or "مقارنة عامة"}",\n'
        '  "law_a": {"text": "النص الرئيسي", "article": "رقم المادة", "summary": "الملخص"},\n'
        '  "law_b": {"text": "النص الرئيسي", "article": "رقم المادة", "summary": "الملخص"},\n'
        '  "difference": "الفرق الجوهري بين القانونين"\n'
        "}"
    )


def _parse_result(
    raw: str,
    law_a: str, law_b: str, aspect: str,
    chunks_a: list, chunks_b: list,
) -> dict:
    """يُحلّل رد اللم ويُعيد النتيجة. يتراجع للـ chunks عند الفشل."""
    result = _empty_result(law_a, law_b, aspect)

    if raw:
        try:
            m = re.search(r"\{[\s\S]*\}", raw)
            if m:
                parsed = json.loads(m.group())
                result["aspect"]     = parsed.get("aspect", aspect or "مقارنة عامة")
                result["law_a"].update(
                    {k: str(v) for k, v in parsed.get("law_a", {}).items()}
                )
                result["law_b"].update(
                    {k: str(v) for k, v in parsed.get("law_b", {}).items()}
                )
                result["difference"] = parsed.get("difference", "")
                result["source"]     = "llm"
                return result
        except Exception:
            pass

    # fallback: قيم مباشرة من chunks
    if chunks_a:
        result["law_a"]["text"]    = chunks_a[0]["text"]
        result["law_a"]["article"] = chunks_a[0].get("article", "")
        result["law_a"]["summary"] = chunks_a[0]["text"][:150]
    if chunks_b:
        result["law_b"]["text"]    = chunks_b[0]["text"]
        result["law_b"]["article"] = chunks_b[0].get("article", "")
        result["law_b"]["summary"] = chunks_b[0]["text"][:150]

    result["source"] = "chunks"
    return result


def _empty_result(
    law_a: str, law_b: str, aspect: str, error: str = ""
) -> dict:
    return {
        "aspect":     aspect or "مقارنة عامة",
        "law_a":      {"text": "", "article": "", "summary": "", "name": law_a},
        "law_b":      {"text": "", "article": "", "summary": "", "name": law_b},
        "difference": "",
        "error":      error,
        "source":     "empty",
    }
