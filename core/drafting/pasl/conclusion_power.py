# -*- coding: utf-8 -*-
"""
PASL — Conclusion Power.

Rewrites a bland concluding paragraph into a tight synthesis that
re-binds Facts → Statute → Consequence in one sentence — the advocate's
closing punch.

Rule: ONLY polishes the existing text. Never invents new grounds or
remedies. If the MQE conclusion already has a strong synthesis marker
("وبناءً على ما تقدَّم") the paragraph is passed through.
"""
from __future__ import annotations


_STRONG_SYNTHESIS_MARKERS = (
    "وبناءً على ما تقدَّم",
    "وبناءً على ما تقدّم",
    "بناءً على ذلك",
    "تأسيساً على ما تقدَّم",
    "يتعيّن القول بأن",
    "يتَعَيَّن",
    # MQE's own conclusion often opens with these — treat them as strong
    "يتبيّن مما تقدَّم",
    "يتبيّن مما تقدّم",
    "يتّضح مما تقدَّم",
    "يتّضح مما تقدّم",
    "يُستخلص مما تقدَّم",
    "يُستخلص مما تقدّم",
)


_DEFENSE_CLOSER = (
    "وبناءً على ما تقدَّم، ولثبوت انتفاء أركان ادعاء الخصم سواء من حيث "
    "النص الحاكم أو الدليل المطلوب، فإن الدفع يقوم على سند صحيح من الواقع "
    "والقانون، ويتعيَّن معه الأخذ به."
)

_CLAIM_CLOSER = (
    "وبناءً على ما تقدَّم، ولاكتمال عناصر الدعوى بنصها الحاكم ودليلها "
    "المؤيِّد، فإن طلبات الموكّل تقوم على سند صحيح من الواقع والقانون، "
    "ويتعيَّن إجابتها."
)

_NEUTRAL_CLOSER = (
    "وبناءً على ما تقدَّم، فإن المسألة على النحو المبيَّن أعلاه، "
    "وهو ما يلتمس الموكّل إعماله."
)


def _has_strong_marker(body: str) -> bool:
    low = body or ""
    return any(m in low for m in _STRONG_SYNTHESIS_MARKERS)


def polish_conclusion(body: str, *, client_side: str = "neutral") -> str:
    """Ensure the conclusion closes with a single strong synthesis line.

    If the MQE-emitted body already has one, it's preserved. Otherwise we
    prepend the appropriate closer.
    """
    if not body or not body.strip():
        return body

    if _has_strong_marker(body):
        return body

    closer = _NEUTRAL_CLOSER
    if client_side in {"defendant", "accused", "respondent"}:
        closer = _DEFENSE_CLOSER
    elif client_side in {"claimant", "appellant"}:
        closer = _CLAIM_CLOSER

    return closer + (" " + body.lstrip() if body.strip() else "")


def count_weak_conclusions(body: str) -> int:
    if not body:
        return 0
    return 0 if _has_strong_marker(body) else 1
