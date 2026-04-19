# -*- coding: utf-8 -*-
"""
confidence_scorer.py — حاسبة درجة الثقة القائمة على الاسترداد
================================================================
تحسب درجة الثقة بناءً على ثلاثة مؤشرات لجودة نتائج RAG:

  retrieval  = avg(similarity_scores) × 100      [جودة المطابقة]
  coverage   = min(len(chunks) / 5, 1.0) × 100   [عدد المصادر]
  diversity  = min(unique_sources / 3, 1.0) × 100 [تنوع المصادر]

  final = retrieval × 0.5 + coverage × 0.3 + diversity × 0.2

الفئات:
  ≥ 80 → عالية  (لون أخضر)
  ≥ 60 → متوسطة (لون أصفر)
  < 60 → منخفضة (لون أحمر)

الاستخدام:
    from confidence_scorer import calculate, ConfidenceResult

    result = calculate(
        similarity_scores = [0.91, 0.88, 0.72],
        chunks            = relevant_chunks,
    )
    print(result["score"])   # 0..100
    print(result["label"])   # عالية / متوسطة / منخفضة
    print(result["color"])   # green / yellow / red
"""

from __future__ import annotations

import logging
from typing import TypedDict

log = logging.getLogger(__name__)

# ── عتبات الفئات ─────────────────────────────────────────────
THRESHOLD_HIGH   = 80
THRESHOLD_MEDIUM = 60

# ── أوزان المعادلة ───────────────────────────────────────────
WEIGHT_RETRIEVAL = 0.5
WEIGHT_COVERAGE  = 0.3
WEIGHT_DIVERSITY = 0.2


class ConfidenceBreakdown(TypedDict):
    retrieval : float   # 0..100
    coverage  : float   # 0..100
    diversity : float   # 0..100


class ConfidenceResult(TypedDict):
    score    : int              # 0..100
    label    : str              # عالية / متوسطة / منخفضة
    color    : str              # green / yellow / red
    breakdown: ConfidenceBreakdown


# ══════════════════════════════════════════════════════════════
# calculate — الدالة الرئيسية
# ══════════════════════════════════════════════════════════════
def calculate(
    similarity_scores: list[float],
    chunks: list[dict],
) -> ConfidenceResult:
    """
    يحسب درجة الثقة من نتائج RAG.

    Parameters
    ----------
    similarity_scores : نتائج الـ cosine similarity أو scores من البحث (0..1)
    chunks            : قائمة الـ chunks المُسترَدّة من قاعدة البيانات

    Returns
    -------
    ConfidenceResult مع score (0..100) و label و color و breakdown.
    """
    # ── 1. Retrieval Score: متوسط درجات التشابه ──
    if similarity_scores:
        # تأكد أن القيم في النطاق 0..1
        valid = [min(1.0, max(0.0, float(s))) for s in similarity_scores]
        retrieval = (sum(valid) / len(valid)) * 100
    else:
        retrieval = 0.0

    # ── 2. Coverage Score: كثافة المصادر (الهدف 5 chunks) ──
    if chunks:
        coverage = min(len(chunks) / 5, 1.0) * 100
    else:
        coverage = 0.0

    # ── 3. Diversity Score: تنوع المصادر (الهدف 3 قوانين مختلفة) ──
    if chunks:
        unique_sources = len({ch.get("law_name", "") for ch in chunks if ch.get("law_name")})
        diversity = min(unique_sources / 3, 1.0) * 100
    else:
        diversity = 0.0

    # ── 4. الدرجة النهائية ──
    final = (
        retrieval * WEIGHT_RETRIEVAL
        + coverage  * WEIGHT_COVERAGE
        + diversity * WEIGHT_DIVERSITY
    )
    score = max(0, min(100, round(final)))

    # ── 5. التصنيف واللون ──
    label, color = _classify(score)

    log.debug(
        "confidence_scorer: ret=%.1f cov=%.1f div=%.1f → final=%d (%s)",
        retrieval, coverage, diversity, score, label,
    )

    return ConfidenceResult(
        score     = score,
        label     = label,
        color     = color,
        breakdown = ConfidenceBreakdown(
            retrieval = round(retrieval, 1),
            coverage  = round(coverage,  1),
            diversity = round(diversity, 1),
        ),
    )


def _classify(score: int) -> tuple[str, str]:
    """يُعيد (label, color) بناءً على الدرجة."""
    if score >= THRESHOLD_HIGH:
        return "عالية", "green"
    if score >= THRESHOLD_MEDIUM:
        return "متوسطة", "yellow"
    return "منخفضة", "red"


# ══════════════════════════════════════════════════════════════
# from_chunks — اختصار: يستخرج similarity_scores من chunks تلقائياً
# ══════════════════════════════════════════════════════════════
def from_chunks(chunks: list[dict]) -> ConfidenceResult:
    """
    اختصار مريح: يستخرج similarity_scores من حقل "score" في كل chunk.

    Example:
        result = from_chunks(relevant)
    """
    scores = [float(ch.get("score", 0)) for ch in chunks if ch.get("score") is not None]
    return calculate(scores, chunks)
