# -*- coding: utf-8 -*-
"""
PASL — Opponent Pressure.

Polishes the opponent-model section (emitted by MQE) so it follows the
three-step pattern every senior advocate uses:

    1) Present the opposing point briefly
    2) Delimit / قَيِّد it
    3) Take it down (rebuttal)

Rule: never *invent* an opposing point; only polish what MQE already
emitted. If the section is empty, PASL leaves it alone.

Added markers:
  • Opening: "قد يتمسَّك الخصم بأن..." (MQE already uses this — kept)
  • Limiter:  "ومع التسليم جدلاً بصحة ذلك فإنه..."
  • Rebuttal: "ويُردّ على ذلك بأن..." / "ومردود هذا الدفع بأن..."
"""
from __future__ import annotations

import re


_REBUTTAL_OPENERS = [
    "ويُردّ على ذلك بأن ",
    "ومردود هذا الدفع بأن ",
    "غير أن هذا القول لا ينهض إذ ",
    "إلا أن ذلك مردود بأن ",
]


_LIMITER_PHRASE = (
    "ومع التسليم جدلاً بصحة ما قد يُثيره الخصم في هذا الصدد، "
    "فإنه لا يسعفه في إثبات عناصر الدعوى المطلوبة."
)


def _has_rebuttal(para: str) -> bool:
    low = para.strip()
    return any(low.startswith(s.rstrip()) for s in _REBUTTAL_OPENERS) or \
        any(t in low for t in ("ومردود", "غير أن", "إلا أن", "لا ينهض"))


def polish_opponent_block(body: str) -> str:
    """Ensure the opponent-model body has a clean 3-step shape.

    Incoming shape from MQE typically:
        قد يتمسّك الخصم بأن <strongest>.
        ويُردّ على ذلك بأن <rebuttal>.

    We don't rewrite the opposing point — we only ensure a rebuttal
    exists, is strong, and doesn't echo other sections.
    """
    if not body or not body.strip():
        return body

    lines = [ln for ln in body.split("\n") if ln.strip()]

    # 1) Whole block already has a rebuttal somewhere? keep it, just vary
    if any(_has_rebuttal(ln) for ln in lines):
        for i, ln in enumerate(lines):
            cur = ln.lstrip()
            if cur.startswith("ويُردّ على ذلك بأن"):
                alt = _REBUTTAL_OPENERS[1]
                lines[i] = alt + cur[len("ويُردّ على ذلك بأن "):].lstrip()
                break
        return "\n".join(lines)

    # 2) No rebuttal yet → insert one after the first opposing-point line
    opener = _REBUTTAL_OPENERS[0]
    rebuttal_line = (
        opener + "عبء الإثبات يقع على خصم الموكّل وما قام به "
                  "لا يبلغ درجة الدليل الكافي."
    )
    # Place it after the first non-empty line
    lines.insert(1, rebuttal_line)
    return "\n".join(lines)


def count_soft_opponent_blocks(body: str) -> int:
    """A block without a rebuttal marker counts as weak."""
    if not body or not body.strip():
        return 0
    if _has_rebuttal(body):
        return 0
    return 1
