# -*- coding: utf-8 -*-
"""
PASL — Conditional Tone Control.

In memos that carry a conditional / fallback section, PASL softens the
fallback's tone SO IT DOES NOT COMPETE with the primary path:

  • No decisive "الثابت" in the fallback body (replaced with measured
    "يُمكن القول بأن" etc.)
  • Keeps the explicit احتياط frame
  • Prepends an unambiguous "وعلى سبيل الاحتياط، وحتى على فرض..." line
    if missing

Hard rule: the primary-path body is NEVER touched by this module.
"""
from __future__ import annotations

import re


_FALLBACK_FRAME_MARKERS = (
    "على سبيل الاحتياط",
    "وعلى سبيل الاحتياط",
    "احتياطياً",
)


_STRONG_WORDS_TO_SOFTEN = [
    # (strong phrase, softened phrase)
    ("الثابت أن", "يُمكن القول بأن"),
    ("من الثابت قانوناً أن", "يُحتمل قانوناً أن"),
    ("من المستقر أن", "قد يُحتج بأن"),
    ("يتعيَّن القول بأن", "قد يُقال بأن"),
    ("قام الدليل على", "يُستأنس لدى الاقتضاء بـ"),
]


_SOFT_LEAD = (
    "وعلى سبيل الاحتياط، وحتى على فرض عدم الأخذ بالمسار المتقدِّم، "
    "يُلتمس إعمال التكييف البديل وفقاً لما يلي:"
)


def is_conditional_block(body: str) -> bool:
    low = body or ""
    return any(m in low for m in _FALLBACK_FRAME_MARKERS)


def polish_conditional_block(body: str) -> str:
    """Soften tone inside the conditional section ONLY."""
    if not body or not body.strip():
        return body

    if not is_conditional_block(body):
        # This function is only safe on already-conditional text
        return body

    out = body
    for strong, soft in _STRONG_WORDS_TO_SOFTEN:
        out = out.replace(strong, soft)

    # Ensure the block opens with an explicit احتياط lead
    first_line = out.split("\n", 1)[0].lstrip()
    if not any(m in first_line for m in _FALLBACK_FRAME_MARKERS):
        out = _SOFT_LEAD + "\n" + out

    return out


def count_hard_phrases_in_conditional(body: str) -> int:
    if not body or not is_conditional_block(body):
        return 0
    return sum(1 for strong, _ in _STRONG_WORDS_TO_SOFTEN if strong in body)
