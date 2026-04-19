#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
knowledge_map.py — الخريطة المعرفية الشاملة
=============================================
فهرس ذكي لكل شيء في DB — بديل لـ embedding search للجداول والأرقام.
يُبنى مرة واحدة → يُحفظ في JSON → يُحمّل عند كل تشغيل.
"""
import re, json, os, logging
from typing import Optional

log = logging.getLogger("knowledge_map")

INDEX_PATH = "/app/core/knowledge_index.json"

# ════════════════════════════════════════════════════════════════
# خرائط ثابتة — لا تحتاج DB
# ════════════════════════════════════════════════════════════════

LAW_DETECT = {
    "%أسرة%": ["أسرة","اسرة","الأسرة","الاسرة","حضانة","طلاق","نفقة","زواج","خلع","ميراث"],
    "%عقوبات%11%2004%": ["عقوبات","العقوبات"],
    "%عمل%14%": ["عمل","العمل"],
    "%مخدر%": ["مخدر","مخدرات","المخدرات"],
    "%مرافعات%": ["مرافعات","المرافعات"],
    "%إجراءات%جنائ%": ["إجراءات جنائية","الإجراءات الجنائية"],
    "%مدني%22%2004%": ["القانون المدني","المدني"],
    "%تجار%27%": ["التجارة","تجاري"],
    "%موارد%بشرية%": ["موارد بشرية","الموارد البشرية"],
    "%بيئة%": ["بيئة","البيئة"],
    "%مرور%": ["مرور","المرور"],
    "%إيجار%": ["إيجار","الإيجار"],
    "%شركات%": ["شركات","الشركات"],
}

TABLE_DETECT = {
    "مخدرات": ["مخدر","مؤثر عقلي","نبات"],
    "رواتب": ["راتب","رواتب","درجة","درجات","سلم"],
    "كيميائية": ["كيميائ","سام","خطر","محظور"],
    "رسوم": ["رسوم","رسم"],
}

ARTICLE_TEXT_TRIGGERS = [
    "نص المادة","نص الماده","عطني نص","عطني المادة",
    "اكتب نص","اقرأ المادة","المادة كامل","نص كامل",
]

TABLE_TRIGGERS = [
    "جدول رقم","الجدول الملحق","ملحق رقم","عدد لي","اذكر لي",
    "المواد المحظورة","المواد الكيميائية","سلم الرواتب",
    "جدول المخدرات","جدول الرواتب","درجة مالية",
    "جدول الدرجات","المواد المدرجة",
    # salary-specific triggers
    "كم راتب","راتب موظف","راتب درجة","كم الراتب",
    "رواتب الموظفين","راتب الدرجة","الدرجة المالية",
    "سلم الدرجات","كم يكون الراتب","رواتب الدرجات",
]


# ════════════════════════════════════════════════════════════════
# المحرّك
# ════════════════════════════════════════════════════════════════

def detect_law(query: str) -> Optional[str]:
    """يكتشف القانون من السؤال"""
    q = query.lower()
    for pattern, keywords in LAW_DETECT.items():
        if any(kw in q for kw in keywords):
            return pattern
    return None


def detect_table_type(query: str) -> Optional[str]:
    """يكتشف نوع الجدول المطلوب"""
    q = query.lower()
    for ttype, keywords in TABLE_DETECT.items():
        if any(kw in q for kw in keywords):
            return ttype
    return None


def find_answer_source(query: str) -> dict:
    """
    يحدد أين الإجابة بالضبط في DB — بدون embedding search.
    """
    q = query.lower()

    # 1. نص مادة
    art_match = re.search(r'(?:المادة|الماده|م\.?\s*)(\d+)', q)
    if art_match and any(t in q for t in ARTICLE_TEXT_TRIGGERS):
        return {
            "type": "article_text",
            "article_number": art_match.group(1),
            "law_pattern": detect_law(q) or "%",
        }

    # 2. جدول/ملحق — explicit trigger
    if any(t in q for t in TABLE_TRIGGERS):
        ttype = detect_table_type(q)
        return {
            "type": "table",
            "table_type": ttype or "عام",
        }

    # 2b. salary detection — implicit (كم راتب درجة سابعة، راتب موظف درجة ثالثة)
    if re.search(r'(كم|راتب|رواتب|سلم).{0,15}(درجة|موظف|سلم|رواتب|راتب)', q):
        return {
            "type": "table",
            "table_type": "رواتب",
        }

    # 3. عام
    return {"type": "rag"}


async def smart_fetch(pool, source: dict) -> Optional[str]:
    """يسحب البيانات من DB حسب نتيجة find_answer_source"""

    if source["type"] == "article_text":
        art_num = source["article_number"]
        law_pat = source.get("law_pattern", "%")
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT content, law_name FROM chunks "
                "WHERE is_active=true AND article_number = $1 "
                "AND law_name ILIKE $2 "
                "AND law_name NOT ILIKE '%أحكام محكمة التمييز%' "
                "AND law_name NOT ILIKE '%قرار وزار%' "
                "AND law_name NOT ILIKE '%أمر أميري%' "
                "AND length(content) > 50 "
                "ORDER BY length(content) DESC LIMIT 1",
                art_num, law_pat
            )
            if not row and law_pat != "%":
                # fallback بدون تحديد القانون
                row = await conn.fetchrow(
                    "SELECT content, law_name FROM chunks "
                    "WHERE is_active=true AND article_number = $1 "
                    "AND law_name NOT ILIKE '%أحكام محكمة التمييز%' "
                    "AND law_name NOT ILIKE '%قرار وزار%' "
                    "AND law_name NOT ILIKE '%أمر أميري%' "
                    "AND length(content) > 50 "
                    "ORDER BY length(content) DESC LIMIT 1",
                    art_num
                )
        if row:
            return f"📜 المادة {art_num} من {row['law_name']}:\n\n{row['content'][:2000]}"
        return f"⚠️ لم أجد المادة {art_num} في قاعدة البيانات."

    elif source["type"] == "table":
        ttype = source.get("table_type", "عام")
        keywords = TABLE_DETECT.get(ttype, [])
        if not keywords:
            return None

        like_clauses = " OR ".join([f"content ILIKE '%{kw}%'" for kw in keywords])

        # For salary tables: also search for chunks with numbers + درجة (actual schedules)
        if ttype == "رواتب":
            async with pool.acquire() as conn:
                # Strategy 1: chunks explicitly labeled as جدول/ملحق with salary keywords
                rows = await conn.fetch(f"""
                    SELECT content, law_name FROM chunks
                    WHERE is_active=true
                    AND (content ILIKE '%جدول%' OR content ILIKE '%ملحق%' OR content ILIKE '%سلم%')
                    AND ({like_clauses})
                    AND length(content) > 100
                    ORDER BY length(content) DESC LIMIT 3
                """)
                # Strategy 2: if not found, search for chunks with درجة + numbers (actual salary data)
                if not rows:
                    rows = await conn.fetch("""
                        SELECT content, law_name FROM chunks
                        WHERE is_active=true
                        AND content ILIKE '%درجة%'
                        AND (content ILIKE '%راتب%' OR content ILIKE '%رواتب%' OR content ILIKE '%علاوة%' OR content ILIKE '%بدل%')
                        AND content ~ '[0-9]{3,}'
                        AND length(content) > 100
                        AND law_name ILIKE '%موارد%بشرية%'
                        ORDER BY length(content) DESC LIMIT 5
                    """)
                # Strategy 3: broader search in any law with salary + numbers
                if not rows:
                    rows = await conn.fetch("""
                        SELECT content, law_name FROM chunks
                        WHERE is_active=true
                        AND (content ILIKE '%راتب%' OR content ILIKE '%رواتب%' OR content ILIKE '%درجة%')
                        AND content ~ '[0-9]{3,}'
                        AND length(content) > 150
                        ORDER BY length(content) DESC LIMIT 5
                    """)
        else:
            async with pool.acquire() as conn:
                rows = await conn.fetch(f"""
                    SELECT content, law_name FROM chunks
                    WHERE is_active=true
                    AND (content ILIKE '%جدول%' OR content ILIKE '%ملحق%')
                    AND ({like_clauses})
                    AND length(content) > 100
                    ORDER BY length(content) DESC LIMIT 3
                """)

        if rows:
            parts = []
            for r in rows:
                parts.append(f"من {r['law_name']}:\n{r['content'][:2000]}")
            return "\n\n---\n\n".join(parts)
        return f"⚠️ لم أجد جدول {ttype} في قاعدة البيانات."

    return None
