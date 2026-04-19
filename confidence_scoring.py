# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║        Confidence Scoring Engine — المساعد القانوني القطري                   ║
║        يقيّم ثقة الإجابة ويُحدد الإجراء المناسب (تليين/fallback)             ║
╚══════════════════════════════════════════════════════════════════════════════╝

score_answer(answer, chunks, question) → float 0..100

Thresholds (قابلة للتعديل):
  < 60  → FALLBACK  (احتمال عالٍ للهلوسة — أعد الاستنتاج)
  60-79 → SOFTEN    (إجابة محتملة — أضِف تحفظاً)
  ≥ 80  → OK        (إجابة واثقة)
"""
from __future__ import annotations

import re
import logging
from typing import Optional

log = logging.getLogger(__name__)

# استيراد عتبات المجال من قاعدة المعرفة القطرية
try:
    from core.qatar_legal_knowledge import DOMAIN_THRESHOLDS as _DOMAIN_THRESHOLDS
except ImportError:
    _DOMAIN_THRESHOLDS: dict = {}

# ── عتبات الثقة ──────────────────────────────────────────────────────────────
THRESHOLD_FALLBACK = 60
THRESHOLD_SOFTEN   = 80

# ── مؤشرات الثقة المنخفضة في النص ───────────────────────────────────────────
_UNCERTAINTY_PHRASES = (
    "ربما", "قد يكون", "أعتقد", "أظن", "يُحتمل",
    "غير متأكد", "لا أعرف", "لست متأكداً", "من المحتمل",
    "يُشار إلى", "وفقاً لبعض التفسيرات",
)

# ── مؤشرات الاستشهاد القانوني الجيد ─────────────────────────────────────────
_CITATION_PATTERN = re.compile(
    r"(المادة\s*\(?\s*\d+\s*\)?|القانون\s+رقم\s*\(?\s*\d+\s*\)?|قانون\s+\w+\s+رقم|المرسوم\s+رقم|اللائحة\s+رقم)",
    re.UNICODE,
)


def _score_retrieval(chunks: list[dict]) -> float:
    """
    نقاط من 0-40 بناءً على جودة النتائج المسترجعة.
    - top score الأعلى يُعطي حتى 30 نقطة
    - عدد القطع ≥ 3 يُعطي 10 نقطة إضافية
    """
    if not chunks:
        return 0.0

    top_score = float(chunks[0].get("score", 0.0))
    base = min(top_score * 30.0, 30.0)   # 0–30

    count_bonus = 10.0 if len(chunks) >= 3 else (5.0 if len(chunks) >= 2 else 0.0)
    return base + count_bonus


def _score_citation(answer: str) -> float:
    """
    نقاط من 0-30: الإجابة تستشهد بمواد قانونية محددة.
    """
    if not answer:
        return 0.0
    matches = _CITATION_PATTERN.findall(answer)
    if len(matches) >= 3:
        return 30.0
    if len(matches) >= 1:
        return 18.0
    return 0.0


def _score_domain_match(chunks: list[dict], question: str) -> float:
    """
    نقاط من 0-20: هل المجال القانوني للقطع يتطابق مع السؤال؟
    يستخدم DOMAIN_THRESHOLDS من قاعدة المعرفة القطرية لتحديد المجالات الحساسة.
    """
    if not chunks or not question:
        return 0.0
    # اجمع أسماء القوانين الموجودة في القطع
    law_names = " ".join(ch.get("law_name", "") for ch in chunks[:5]).lower()
    q_lower = question.lower()

    # خريطة الكلمات المفتاحية للمجالات
    domain_keywords = {
        "criminal": ["جنائ", "عقوبات", "جريمة", "اغتصاب", "سرقة", "قتل", "اعتداء"],
        "labor":    ["عمل", "عامل", "راتب", "إجازة", "فصل", "توظيف"],
        "family":   ["طلاق", "زواج", "نفقة", "حضانة", "أسرة", "إرث", "ميراث"],
        "civil":    ["عقد", "تعويض", "ضرر", "مسؤولية", "إيجار", "ملكية"],
        "commercial": ["شركة", "تجارة", "بضاعة", "مشروع", "استثمار"],
    }

    # خريطة المجال → اسم عربي للمطابقة مع DOMAIN_THRESHOLDS
    _domain_ar = {
        "criminal": "جنائي",
        "labor":    "عمالي",
        "family":   "أسرة",
        "civil":    "مدني",
        "commercial": "تجاري",
    }

    for domain, kws in domain_keywords.items():
        in_q    = any(kw in q_lower for kw in kws)
        in_laws = any(kw in law_names for kw in kws)
        if in_q and in_laws:
            # المجالات الحساسة (جنائي) تحتاج نتيجة أعلى — نُعطي 20 كاملة
            return 20.0
        if in_q and not in_laws:
            # السؤال يمس مجالاً لكن القطع لا تطابقه
            # المجالات الحساسة: خصم أكبر
            ar_name = _domain_ar.get(domain, "")
            threshold = _DOMAIN_THRESHOLDS.get(ar_name, 0.35) if _DOMAIN_THRESHOLDS else 0.35
            if threshold >= 0.60:
                return 2.0   # مجال حساس ومصادر غير مطابقة → ثقة منخفضة جداً
            return 5.0       # مجال عادي ومصادر غير مطابقة

    return 10.0   # مجال محايد


def _penalty_uncertainty(answer: str) -> float:
    """
    خصم من -30 إلى 0: عبارات الشك في الإجابة تُقلل من الثقة.
    """
    if not answer:
        return 0.0
    hits = sum(1 for p in _UNCERTAINTY_PHRASES if p in answer)
    return min(hits * 8.0, 30.0)


def score_answer(
    answer: str,
    chunks: list[dict],
    question: str,
) -> float:
    """
    يُقيّم ثقة الإجابة ويُعيد رقماً من 0 إلى 100.

    المكوّنات:
      retrieval   : 0–40  (جودة النتائج المسترجعة)
      citation    : 0–30  (استشهادات بمواد قانونية)
      domain_match: 0–20  (تطابق المجال)
      - penalty   : 0–30  (عبارات شك في الإجابة)
    """
    if not answer or not answer.strip():
        return 0.0

    r  = _score_retrieval(chunks)
    c  = _score_citation(answer)
    d  = _score_domain_match(chunks, question)
    p  = _penalty_uncertainty(answer)

    score = max(0.0, min(100.0, r + c + d - p))
    log.info(
        "confidence_score=%.1f (retrieval=%.1f cite=%.1f domain=%.1f penalty=%.1f)",
        score, r, c, d, p,
    )
    return round(score, 1)


def check_answer_relevance(
    question: str,
    answer: str,
    chunks: list[dict],
    min_overlap: float = 0.20,
) -> dict:
    """
    يتحقق من أن الإجابة تتحدث عن نفس موضوع السؤال.

    Returns:
        {"relevant": True/False, "reason": str, "overlap": float}
    """
    if not question or not answer:
        return {"relevant": True, "reason": "empty_input", "overlap": 1.0}

    # استخرج كلمات السؤال (أكثر من 3 أحرف، مُرشَّحة)
    _STOP = {
        'ما', 'هو', 'هي', 'هل', 'كيف', 'متى', 'أين', 'من', 'في', 'عن',
        'على', 'إلى', 'مع', 'بين', 'كان', 'يكون', 'أن', 'لا', 'لم', 'قد',
        'أو', 'و', 'ف', 'ب', 'ل', 'ك', 'ذلك', 'هذا', 'هذه', 'تلك',
        'يجب', 'يمكن', 'التي', 'الذي', 'اللذان', 'اللتان', 'الذين',
    }

    def _kw(text: str) -> set:
        words = re.findall(r'[\u0600-\u06FF]{3,}', text)
        result = set()
        for w in words:
            if w in _STOP:
                continue
            # جذر بدون أداة التعريف "ال" للمقارنة
            root = w[2:] if w.startswith('ال') and len(w) > 4 else w
            result.add(root)
        return result

    q_kw   = _kw(question)
    ans_kw = _kw(answer[:400])  # أول 400 حرف من الإجابة

    if not q_kw:
        return {"relevant": True, "reason": "no_question_keywords", "overlap": 1.0}

    overlap_count = len(q_kw & ans_kw)
    overlap = overlap_count / len(q_kw)

    if overlap < min_overlap:
        # تحقق إضافي: هل keywords السؤال موجودة في chunks؟
        # (إذا كانت موجودة في chunks لكن ليست في الإجابة → الإجابة مشكوك بها)
        chunk_text = " ".join(c.get("content", "") for c in chunks[:3])
        chunk_kw   = _kw(chunk_text)
        chunk_overlap = len(q_kw & chunk_kw) / len(q_kw) if q_kw else 0
        if chunk_overlap < 0.15:
            # لا حتى الـ chunks تحتوي keywords السؤال → مشكلة في الاسترجاع
            return {"relevant": False, "reason": "poor_retrieval", "overlap": overlap}
        return {"relevant": False, "reason": "topic_mismatch", "overlap": overlap}

    return {"relevant": True, "reason": "ok", "overlap": overlap}


def get_confidence_action(score: float) -> str:
    """
    يُعيد الإجراء المناسب بناءً على النتيجة:
      'ok'       → إجابة كاملة
      'soften'   → أضِف تحفظاً
      'fallback' → أعد بناء الإجابة
    """
    if score < THRESHOLD_FALLBACK:
        return "fallback"
    if score < THRESHOLD_SOFTEN:
        return "soften"
    return "ok"


def apply_confidence_softening(answer: str, score: float) -> str:
    """
    يُضيف تحفظاً لطيفاً في بداية الإجابة إذا كانت الثقة متوسطة (60-79).
    """
    disclaimer = (
        f"\n> ⚠️ **ملاحظة**: هذه الإجابة مبنية على نصوص قانونية بدرجة ثقة {score:.0f}%. "
        "يُنصح بالتحقق مع مستشار قانوني متخصص لتأكيد التطبيق على حالتك.\n\n"
    )
    return disclaimer + answer
