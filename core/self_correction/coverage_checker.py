# -*- coding: utf-8 -*-
"""
Coverage Checker V2 — verifies the answer addresses all parts of the question.
Supports compound questions and sub-question decomposition.
"""
import re, logging
from .schemas import CoverageResult

log = logging.getLogger(__name__)

_ASPECT_KEYWORDS = {
    "penalty":      ["عقوبة", "حبس", "سجن", "غرامة", "إعدام", "جزاء"],
    "ruling":       ["حكم", "قرار", "قضت", "حكمت"],
    "conditions":   ["شروط", "يشترط", "شرط", "شريطة"],
    "procedure":    ["إجراء", "خطوة", "يجب", "ترفع", "تقدم"],
    "steps":        ["أولاً", "ثانياً", "الخطوة", "يتم"],
    "rights":       ["حق", "يحق", "يستحق", "مستحق"],
    "obligations":  ["يلتزم", "يجب", "ملزم", "واجب"],
    "duration":     ["مدة", "خلال", "يوم", "شهر", "سنة"],
    "compensation": ["تعويض", "مقابل", "مبلغ", "يستحق"],
    "comparison":   ["الفرق", "يختلف", "بينما", "على خلاف", "مقارنة"],
    "how":          ["يمكن", "طريقة", "كيفية", "يتم"],
    "when":         ["متى", "خلال", "عند", "بعد", "قبل"],
    "yes_no":       ["نعم", "لا ", "يحق", "لا يحق", "يجوز", "لا يجوز"],
}

_QUESTION_MARKERS = {
    "عقوبة": "penalty", "عقوبات": "penalty", "حكم": "ruling",
    "شروط": "conditions", "إجراءات": "procedure", "خطوات": "steps",
    "حقوق": "rights", "واجبات": "obligations", "مدة": "duration",
    "تعويض": "compensation", "فرق": "comparison", "كيف": "how",
    "متى": "when", "هل": "yes_no",
}

# Patterns that split compound questions
_COMPOUND_SPLITTERS = re.compile(
    r'\s+و(?:هل|كيف|متى|ما|كم|أين|لماذا)\s+|\?\s*(?:و)?', re.UNICODE
)


def _extract_sub_questions(query: str) -> list[str]:
    """Split compound questions into sub-questions."""
    parts = _COMPOUND_SPLITTERS.split(query)
    parts = [p.strip() for p in parts if len(p.strip()) > 5]
    return parts if len(parts) > 1 else [query]


def _extract_aspects(query: str) -> list[str]:
    aspects = []
    q_lower = query.lower()
    for marker, aspect in _QUESTION_MARKERS.items():
        if marker in q_lower:
            aspects.append(aspect)
    return aspects if aspects else ["general"]


def _answer_covers(answer: str, aspect: str) -> bool:
    a_lower = answer.lower()
    keywords = _ASPECT_KEYWORDS.get(aspect, [])
    if not keywords:
        return True
    return any(kw in a_lower for kw in keywords)


def check_coverage(query: str, answer: str) -> CoverageResult:
    if len(answer.strip()) < 20:
        return CoverageResult(covers_main_question=False,
                              missing_aspects=["الإجابة قصيرة جداً"],
                              coverage_pct=0.0, partial=True)

    # Decompose compound questions
    sub_questions = _extract_sub_questions(query)
    all_aspects: list[str] = []
    for sq in sub_questions:
        all_aspects.extend(_extract_aspects(sq))
    # Deduplicate preserving order
    seen = set()
    aspects = []
    for a in all_aspects:
        if a not in seen:
            seen.add(a)
            aspects.append(a)

    covered = [a for a in aspects if _answer_covers(answer, a)]
    missing = [a for a in aspects if not _answer_covers(answer, a)]

    pct = len(covered) / max(len(aspects), 1) * 100

    # Sub-question coverage check
    sub_q_missing = []
    if len(sub_questions) > 1:
        for sq in sub_questions:
            sq_words = set(re.findall(r"[\u0600-\u06FF]{3,}", sq.lower()))
            ans_words = set(re.findall(r"[\u0600-\u06FF]{3,}", answer.lower()))
            overlap = len(sq_words & ans_words) / max(len(sq_words), 1)
            if overlap < 0.25:
                sub_q_missing.append(sq[:50])
        if sub_q_missing:
            missing.extend([f"سؤال فرعي: {s}" for s in sub_q_missing])
            pct = max(0, pct - len(sub_q_missing) * 15)

    # Refusal detection
    apology_patterns = ["لا تتوفر", "لا أستطيع", "عذراً", "للأسف لا", "لم أتمكن"]
    is_refusal = any(p in answer[:100] for p in apology_patterns) and len(answer.split()) < 30

    return CoverageResult(
        covers_main_question=pct >= 50 and not is_refusal,
        missing_aspects=missing,
        coverage_pct=round(pct, 1),
        partial=0 < pct < 80 or bool(missing),
    )
