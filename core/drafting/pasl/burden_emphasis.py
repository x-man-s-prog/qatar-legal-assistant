# -*- coding: utf-8 -*-
"""
PASL — Burden-of-Proof Emphasis.

The burden-of-proof section is one of the highest-leverage persuasion
tools in Qatari and Gulf legal memos. PASL ensures it:

  • Explicitly states WHO bears the burden
  • Notes WHAT they must prove
  • Notes WHAT the record is SILENT about
  • Uses decisive legal register ("خلو الأوراق مما يفيد...", "ولم يقدم...")

If the MQE burden section is generic, PASL adds one of the four
high-impact lines below — without inventing any facts.
"""
from __future__ import annotations


_HIGH_IMPACT_LINES = [
    "ولم يقدِّم الخصم ما يثبت ركن القصد على وجه الجزم.",
    "وخلوُّ الأوراق مما يفيد قيام الشرط المتفَّق عليه قرينة لصالح الموكّل.",
    "ولمّا كان الإثبات عبئاً على من ادَّعى، فإن عجزه عنه يُسقِط دعواه.",
    "ولا يكفي في هذا المقام مجرد الاحتمال ما لم يقم عليه دليل قاطع.",
]


_WEAK_BURDEN_SIGNALS = (
    "قرينة الأصل",
    "تحكم لصالح الموكّل",
)


def _has_high_impact(body: str) -> bool:
    low = body or ""
    triggers = (
        "ولم يقدِّم", "خلوُّ الأوراق", "خلو الأوراق",
        "ولمّا كان الإثبات", "عجزه عنه",
        "مجرد الاحتمال",
    )
    return any(t in low for t in triggers)


def polish_burden_block(body: str, *, client_side: str = "neutral",
                          base_idx: int = 0) -> str:
    """Strengthen the burden-of-proof paragraph without adding facts."""
    if not body or not body.strip():
        return body
    if _has_high_impact(body):
        return body
    # Add ONE high-impact line (rotated) — never more
    extra = _HIGH_IMPACT_LINES[base_idx % len(_HIGH_IMPACT_LINES)]
    # Only for defense-side do we want the silence argument emphasized
    if client_side in {"defendant", "accused", "respondent"}:
        return body.rstrip() + " " + extra
    # For claimants, emphasize the opposite
    return body.rstrip() + " وما دام الموكّل قد أوفى بما أوجبه عليه النص، " \
        "فإن عبء الدفع ينتقل إلى خصمه."


def count_weak_burden_sections(body: str) -> int:
    """A burden paragraph that lacks high-impact phrasing counts as weak."""
    if not body:
        return 0
    return 0 if _has_high_impact(body) else 1
