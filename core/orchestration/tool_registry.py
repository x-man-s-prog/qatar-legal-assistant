# -*- coding: utf-8 -*-
"""
Tool Registry — declares all available tools with schemas and execution functions.
Adding a new tool = one entry here. No other file needs to change.
"""
import re, logging
from typing import Any, Callable, Optional
from .schemas import ToolName

log = logging.getLogger("orchestration")

# ══════════════════════════════════════════════════════════════
# Tool implementations
# ══════════════════════════════════════════════════════════════

def _calc_end_of_service(salary: float, years: float, **_) -> dict:
    if salary <= 0 or years <= 0:
        return {"error": "الراتب وسنوات الخدمة يجب أكبر من صفر"}
    weekly = salary / 4.33
    reward = weekly * 3 * years
    return {
        "salary": salary, "years": years, "weekly_salary": round(weekly, 2),
        "reward": round(reward, 2),
        "formula": f"3 أسابيع × {int(years)} سنة = {reward:,.0f} ريال",
        "legal_basis": "المادة 54 من قانون العمل رقم 14 لسنة 2004",
    }


def _calc_unfair_dismissal(salary: float, years: float, notice_months: int = 1, **_) -> dict:
    if salary <= 0 or years <= 0:
        return {"error": "الراتب وسنوات الخدمة يجب أكبر من صفر"}
    dismissal = max(salary * 2, salary * years * 0.5)
    notice = salary * notice_months
    eos = _calc_end_of_service(salary, years)
    eos_r = eos.get("reward", 0)
    total = dismissal + notice + eos_r
    return {
        "dismissal_comp": round(dismissal, 2), "notice_comp": round(notice, 2),
        "end_of_service": round(eos_r, 2), "total": round(total, 2),
        "breakdown": (
            f"1. تعويض فصل تعسفي: {dismissal:,.0f} ريال (م49)\n"
            f"2. بدل إنذار: {notice:,.0f} ريال (م47)\n"
            f"3. مكافأة نهاية خدمة: {eos_r:,.0f} ريال (م54)\n"
            f"المجموع: {total:,.0f} ريال"
        ),
        "legal_basis": "المواد 47، 49، 54 من قانون العمل رقم 14 لسنة 2004",
    }


async def _article_lookup(pool, article_number: str, law_name: str = "", **_) -> dict:
    """Direct DB lookup for a specific article."""
    if not pool:
        return {"error": "قاعدة البيانات غير متاحة"}
    art = re.sub(r"\s+", "", article_number).strip()
    async with pool.acquire() as conn:
        if law_name:
            row = await conn.fetchrow(
                "SELECT content, law_name FROM chunks WHERE is_active=true "
                "AND article_number=$1 AND law_name ILIKE $2 "
                "ORDER BY length(content) DESC LIMIT 1", art, f"%{law_name}%"
            )
        else:
            row = await conn.fetchrow(
                "SELECT content, law_name FROM chunks WHERE is_active=true "
                "AND article_number=$1 ORDER BY length(content) DESC LIMIT 1", art
            )
    if row:
        return {"found": True, "content": row["content"][:2000], "law_name": row["law_name"]}
    return {"found": False, "error": f"المادة {art} غير موجودة"}


async def _table_lookup(pool, table_type: str = "", **_) -> dict:
    """Direct DB lookup for tables/schedules."""
    if not pool:
        return {"error": "قاعدة البيانات غير متاحة"}
    from core.knowledge_map import TABLE_DETECT
    keywords = TABLE_DETECT.get(table_type, [])
    if not keywords:
        return {"found": False, "error": f"نوع الجدول '{table_type}' غير معروف"}
    like_clauses = " OR ".join([f"content ILIKE '%{kw}%'" for kw in keywords])
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT content, law_name FROM chunks WHERE is_active=true
            AND (content ILIKE '%جدول%' OR content ILIKE '%ملحق%')
            AND ({like_clauses}) AND length(content) > 100
            ORDER BY length(content) DESC LIMIT 3
        """)
    if rows:
        parts = [f"📋 من {r['law_name']}:\n{r['content'][:2000]}" for r in rows]
        return {"found": True, "content": "\n\n---\n\n".join(parts)}
    return {"found": False, "error": f"لم يُعثر على جدول {table_type}"}


# ══════════════════════════════════════════════════════════════
# Registry
# ══════════════════════════════════════════════════════════════

class ToolSpec:
    def __init__(self, name: ToolName, fn: Callable, is_async: bool,
                 needs_pool: bool, description: str, required_args: list[str]):
        self.name = name
        self.fn = fn
        self.is_async = is_async
        self.needs_pool = needs_pool
        self.description = description
        self.required_args = required_args


TOOL_REGISTRY: dict[ToolName, ToolSpec] = {
    ToolName.END_OF_SERVICE: ToolSpec(
        ToolName.END_OF_SERVICE, _calc_end_of_service, False, False,
        "حساب مكافأة نهاية الخدمة", ["salary", "years"],
    ),
    ToolName.UNFAIR_DISMISSAL: ToolSpec(
        ToolName.UNFAIR_DISMISSAL, _calc_unfair_dismissal, False, False,
        "حساب تعويض الفصل التعسفي", ["salary", "years"],
    ),
    ToolName.ARTICLE_LOOKUP: ToolSpec(
        ToolName.ARTICLE_LOOKUP, _article_lookup, True, True,
        "البحث عن نص مادة قانونية", ["article_number"],
    ),
    ToolName.TABLE_LOOKUP: ToolSpec(
        ToolName.TABLE_LOOKUP, _table_lookup, True, True,
        "البحث عن جدول/ملحق", ["table_type"],
    ),
}
