# -*- coding: utf-8 -*-
"""
query_classifier.py — تصنيف الاستعلامات القانونية
===================================================
يُصنّف كل سؤال قبل البحث في ثلاثة أبعاد:
  - النوع:    factual | procedural | comparative | hypothetical
  - المجال:   عمالي | أسري | جزائي | مدني | تجاري | إداري | أخرى
  - التعقيد:  بسيط | متوسط | معقد

ثم يُحدّد معاملات البحث بناءً على التصنيف:
  - factual + بسيط  → vector فقط (أسرع)
  - comparative     → تشغيل compare_service تلقائياً
  - معقد            → top_k = 15 بدل 10
"""
from __future__ import annotations

import re
from typing import TypedDict


class QueryClassification(TypedDict):
    query_type: str    # factual | procedural | comparative | hypothetical
    domain:     str    # عمالي | أسري | جزائي | مدني | تجاري | إداري | أخرى
    complexity: str    # بسيط | متوسط | معقد


# ── Type patterns — ordered: most specific first ───────────────
_TYPE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("comparative",  re.compile(
        r"مقارنة|قارن|الفرق بين|أيهما|مقابل|يختلف عن|الأفضل من",
        re.IGNORECASE | re.UNICODE
    )),
    ("procedural",   re.compile(
        r"\bكيف\b|إجراءات|خطوات|طريقة|كيفية|كيف يمكن|ما هي خطوات",
        re.IGNORECASE | re.UNICODE
    )),
    ("hypothetical", re.compile(
        r"\bإذا\b|\bلو\b|افترض|في حال\b|هل يمكن|ماذا لو|في حالة\b|لو كان",
        re.IGNORECASE | re.UNICODE
    )),
]

# ── Domain patterns ────────────────────────────────────────────
_DOMAIN_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("عمالي",   re.compile(
        r"عمل|عامل|راتب|أجر|إجازة|فصل|عقد عمل|نهاية خدمة|مكافأة|تأمين عمال",
        re.IGNORECASE | re.UNICODE
    )),
    ("أسري",    re.compile(
        r"طلاق|زواج|نفقة|حضانة|ميراث|وصية|أسرة|زوج|زوجة|مهر|خلع|تطليق",
        re.IGNORECASE | re.UNICODE
    )),
    ("جزائي",   re.compile(
        r"عقوبة|جريمة|سرقة|اعتداء|حبس|سجن|غرامة|جنحة|جناية|قصاص|إيذاء",
        re.IGNORECASE | re.UNICODE
    )),
    ("مدني",    re.compile(
        r"\bعقد\b|تعويض|مسؤولية|ضرر|دين|إيجار|ملكية|رهن|\bبيع\b|التزام",
        re.IGNORECASE | re.UNICODE
    )),
    ("تجاري",   re.compile(
        r"شركة|تجارة|إفلاس|مقاولة|تجاري|استثمار|بضاعة|صرف|شراكة",
        re.IGNORECASE | re.UNICODE
    )),
    ("إداري",   re.compile(
        r"حكومة|موظف|خدمة مدنية|ترخيص|جهة حكومية|إداري|وزارة|قرار إداري|مناقصة",
        re.IGNORECASE | re.UNICODE
    )),
]

# ── Complexity patterns — ordered: most complex first ──────────
_COMPLEXITY_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("معقد",  re.compile(
        r"تعارض|استثناء|شروط متعددة|حالات|استثنائي|خلاف|نزاع|تعدد|تفصيل"
        r"|متشعب|متداخل|دعوى|استئناف|تقاضي",
        re.IGNORECASE | re.UNICODE
    )),
    ("بسيط",  re.compile(
        r"^(ما|هل|كم|متى|أين|من)\b|تعريف\b|معنى\b|يعني\b|ماذا يعني",
        re.IGNORECASE | re.UNICODE
    )),
]


# ══════════════════════════════════════════════════════════════
def classify_query(query: str) -> QueryClassification:
    """يُصنّف الاستعلام ويُعيد التصنيف الكامل."""
    q = (query or "").strip()
    return QueryClassification(
        query_type=_classify_type(q),
        domain=_classify_domain(q),
        complexity=_classify_complexity(q),
    )


def get_search_params(classification: QueryClassification) -> dict:
    """
    يُحدّد معاملات البحث بناءً على التصنيف.
    المخرجات: {top_k, use_vector, use_keyword, trigger_compare}
    """
    params = {
        "top_k":           10,
        "use_vector":      True,
        "use_keyword":     True,
        "trigger_compare": False,
    }

    t = classification["query_type"]
    c = classification["complexity"]

    if t == "comparative":
        params["trigger_compare"] = True

    if t == "factual" and c == "بسيط":
        params["use_keyword"] = False    # vector only — أسرع
        params["top_k"]       = 8

    if c == "معقد":
        params["top_k"] = 15

    return params


def format_badge(classification: QueryClassification) -> str:
    """يُعيد نص badge مختصر للعرض في الواجهة."""
    icons = {
        "factual":     "📌",
        "procedural":  "📋",
        "comparative": "⚖️",
        "hypothetical":"💭",
    }
    icon = icons.get(classification["query_type"], "❓")
    return f"{icon} {classification['domain']} · {classification['complexity']}"


# ══════════════════════════════════════════════════════════════
# Pure helpers
# ══════════════════════════════════════════════════════════════

def _classify_type(query: str) -> str:
    for qtype, pattern in _TYPE_PATTERNS:
        if pattern.search(query):
            return qtype
    return "factual"


def _classify_domain(query: str) -> str:
    for domain, pattern in _DOMAIN_PATTERNS:
        if pattern.search(query):
            return domain
    return "أخرى"


def _classify_complexity(query: str) -> str:
    for level, pattern in _COMPLEXITY_PATTERNS:
        if pattern.search(query):
            return level
    return "متوسط"
