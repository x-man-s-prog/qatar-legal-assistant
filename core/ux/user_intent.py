# -*- coding: utf-8 -*-
"""
User Intent Detector — what does the user actually want right now?

Five modes:
  ANALYSIS           — understand the legal situation
  ACTION             — what to do practically
  DRAFTING           — want a memo / pleading
  STANDING_ASSESSMENT — evaluate my position
  WIN_CHANCES        — chances of winning (we never predict — we map conditions)

Rule-based Arabic detection. No LLM.
"""
from __future__ import annotations

from enum import Enum


class UserIntent(str, Enum):
    ANALYSIS            = "analysis"
    ACTION              = "action"
    DRAFTING            = "drafting"
    STANDING_ASSESSMENT = "standing_assessment"
    WIN_CHANCES         = "win_chances"


_ACTION_MARKERS = (
    "وش اسوي", "ايش اسوي", "ماذا أفعل", "كيف أتصرف",
    "وش الخطوة", "ما الإجراء", "كيف أبلّغ", "أين أبلّغ",
    "هل أرفع دعوى", "متى أرفع دعوى",
)

_DRAFTING_MARKERS = (
    "اكتب لي مذكرة", "صيغ لي مذكرة", "نموذج مذكرة",
    "مذكرة دفاع", "مذكرة رد", "لائحة دعوى", "صحيفة دعوى",
    "اكتبها بصيغة", "حول الكلام إلى مذكرة", "حوّل الكلام إلى مذكرة",
    "قائمة دفوع",
)

_STANDING_MARKERS = (
    "تقييم موقفي", "هل موقفي قوي", "ما مدى قوة", "هل أنا على حق",
    "وش وضعي قانوناً", "موقفي القانوني", "هل عندي حجة",
)

_WIN_MARKERS = (
    "فرص الفوز", "احتمال الربح", "نسبة النجاح",
    "هل سأربح", "هل سأفوز", "هل سأخسر",
    "هل أنجح", "فرصي في",
)

_ANALYSIS_MARKERS = (
    "ما التكييف", "ما الوصف القانوني", "كيف يُكيَّف",
    "هل يُعتبر", "ما طبيعة", "هل يُعدّ",
    "ما الفرق بين", "ما هي العقوبة",
)


def detect_user_intent(query: str) -> UserIntent:
    q = (query or "").strip()
    if not q:
        return UserIntent.ANALYSIS

    # Priority: drafting > standing > win_chances > action > analysis
    if any(m in q for m in _DRAFTING_MARKERS):
        return UserIntent.DRAFTING
    if any(m in q for m in _STANDING_MARKERS):
        return UserIntent.STANDING_ASSESSMENT
    if any(m in q for m in _WIN_MARKERS):
        return UserIntent.WIN_CHANCES
    if any(m in q for m in _ACTION_MARKERS):
        return UserIntent.ACTION
    if any(m in q for m in _ANALYSIS_MARKERS):
        return UserIntent.ANALYSIS
    # Default to analysis
    return UserIntent.ANALYSIS
