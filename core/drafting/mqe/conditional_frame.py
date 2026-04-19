# -*- coding: utf-8 -*-
"""
Memorandum Quality Engine — Conditional / Dual Memo Frames.

Clean framing for multi-path drafts:
  • wrap_conditional: primary memo + a single clearly-framed fallback
  • wrap_dual       : two parallel memos, with an explicit separator

The primary path is NEVER weakened by the fallback. The fallback
introduces itself with an explicit "and on the way of precaution"
frame so a reader/judge immediately sees the conditional nature.
"""
from __future__ import annotations


_FALLBACK_FRAME = (
    "وعلى سبيل الاحتياط، وحتى على فرض عدم الأخذ بالمسار المتقدم، "
    "فإن الموقف القانوني يبقى مدعوماً وفق التكييف البديل التالي:"
)

_DUAL_SEPARATOR = "═══════════════════════════════════════"


def wrap_conditional(
    primary_text: str,
    fallback_theory: str,
    pivot_conditions: list[str] | None = None,
    fallback_body: str = "",
) -> str:
    """Add a clearly-framed conditional section to the primary memo.

    `fallback_body` is an optional short explanation of how the fallback
    theory would be pursued. `pivot_conditions` list when the shift
    happens (from MLRE.reality.pivot_conditions).
    """
    if not primary_text:
        primary_text = ""
    lines: list[str] = [primary_text.rstrip(), "", _FALLBACK_FRAME]
    lines.append(f"• التكييف البديل: {fallback_theory}")
    if pivot_conditions:
        lines.append("• يُلجأ إلى هذا المسار في الحالات الآتية:")
        for pc in pivot_conditions[:2]:
            lines.append(f"  – {pc}")
    if fallback_body.strip():
        lines.append("")
        lines.append(fallback_body.strip())
    lines.append("")
    lines.append(
        "ويبقى الطلب الأصلي قائماً في ضوء التكييف الأقوى المتقدم، "
        "ويُلتمس إعمال التكييف البديل على سبيل الاحتياط دون غيره."
    )
    return "\n".join(lines).rstrip() + "\n"


def wrap_dual(
    primary_text: str,
    secondary_text: str,
    primary_label: str = "المسار الأقوى",
    secondary_label: str = "المسار البديل",
) -> str:
    """Two parallel memos in one document, with an explicit separator.

    The primary is clearly labeled as preferred; the secondary as an
    alternative track.
    """
    parts = [
        f"**📜 المذكرة الأساسية — {primary_label}**",
        "",
        (primary_text or "").rstrip(),
        "",
        _DUAL_SEPARATOR,
        "",
        f"**📜 المذكرة الاحتياطية — {secondary_label}**",
        "",
        "يُقدَّم هذا الجزء على سبيل الاحتياط، ودون أن يُعتبر تنازلاً "
        "عن التمسك بالمسار الأساسي المتقدم:",
        "",
        (secondary_text or "").rstrip(),
    ]
    return "\n".join(parts).rstrip() + "\n"
