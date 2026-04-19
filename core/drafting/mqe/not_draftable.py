# -*- coding: utf-8 -*-
"""
Memorandum Quality Engine — NOT_DRAFTABLE message builder.

When drafting is blocked, produce a USEFUL message, not a refusal:
  • WHAT is missing (human-readable)
  • WHY it blocks drafting
  • WHAT, if supplied, would unblock it
"""
from __future__ import annotations

from core.drafting.drafting_engine import DocumentType


_DOC_LABEL = {
    DocumentType.DEFENSE_MEMO:      "مذكرة دفاع",
    DocumentType.REPLY_MEMO:        "مذكرة رد",
    DocumentType.EXPLANATORY_MEMO:  "مذكرة شارحة",
    DocumentType.PETITION_MEMO:     "مذكرة بطلب",
    DocumentType.CLAIM_BRIEF:       "صحيفة دعوى",
    DocumentType.PLEADING_POINTS:   "نقاط مرافعة",
    DocumentType.DEFENSE_CHECKLIST: "قائمة الدفوع",
    DocumentType.CASE_SUMMARY:      "تلخيص ملف القضية",
}


# ── Missing-code → (human_what, human_why, human_unblock) ──
_EXPLAIN = {
    "issue_graph_unavailable": (
        "لم يتحدَّد المجال القانوني وتفرّعات المسألة بدقة كافية.",
        "الصياغة بدون تحديد المجال تنتج مذكرة عامة لا قيمة فعلية لها.",
        "تحديد طبيعة النزاع (جزائي / مدني / تجاري / عمالي ...) وموضوعه.",
    ),
    "no_primary_issue": (
        "لم تتضح المسألة المحورية في النزاع.",
        "بلا مسألة محورية، تبقى المذكرة سرداً لا حجّة قانونية.",
        "بيان: ماذا تطلب بالضبط، ومما تشكو، وما السؤال القانوني الجوهري.",
    ),
    "no_bound_evidence": (
        "لا يوجد سند قانوني قابل للتوثيق مربوط بمسائل القضية.",
        "بدون سند، أي صياغة ستكون قابلة للطعن بسهولة وتُسقط الموقف.",
        "تقديم مواد القانون ذات الصلة، أو واقعة معيَّنة تربط النص بالقضية.",
    ),
    "insufficient_facts": (
        "الوقائع المقدَّمة لا تكفي للصياغة المسؤولة.",
        "المذكرة تُبنى على وقائع ثابتة لا على عموميات.",
        "إضافة: الأطراف، التواريخ، المبالغ، والمستندات المتوفرة.",
    ),
    "claim_brief_needs_detailed_facts": (
        "صحيفة الدعوى تتطلب تفاصيل لا تتوفر حالياً.",
        "دون هذه التفاصيل لا تُقبَل شكلاً أمام المحكمة.",
        "تحديد: الأطراف بالكامل، تاريخ النزاع، محله، والمبلغ المطالب به.",
    ),
}


def build_not_draftable_message(
    doc_type: DocumentType,
    missing: list[str],
) -> str:
    """Build the NOT_DRAFTABLE explanation — actionable, not a refusal."""
    label = _DOC_LABEL.get(doc_type, "مذكرة قانونية")

    lines: list[str] = [
        f"**تعذّر صياغة {label} في الوقت الحالي — المسار غير مكتمل.**",
        "",
    ]

    # Structured breakdown of what's missing
    relevant = [m for m in (missing or []) if _first_key(m) in _EXPLAIN]
    unknown  = [m for m in (missing or []) if _first_key(m) not in _EXPLAIN]

    if relevant:
        lines.append("**ما ينقص حالياً:**")
        for m in relevant:
            what, _why, _unblock = _EXPLAIN[_first_key(m)]
            lines.append(f"• {what}")
        lines.append("")

        lines.append("**لماذا يمنع ذلك الصياغة:**")
        for m in relevant:
            _what, why, _unblock = _EXPLAIN[_first_key(m)]
            lines.append(f"• {why}")
        lines.append("")

        lines.append("**ما يجعلها قابلة للصياغة فور توفره:**")
        for m in relevant:
            _what, _why, unblock = _EXPLAIN[_first_key(m)]
            lines.append(f"• {unblock}")
        lines.append("")
    else:
        lines.append(
            "الصياغة القانونية المسؤولة تتطلب عناصر لم تكتمل بعد. "
            "يُرجى تقديم مزيد من تفاصيل القضية أو السند القانوني."
        )
        lines.append("")

    # Best next action
    lines.append(
        "يمكن تحليل القضية أولاً دون صياغة، ثم صياغة المذكرة حين يكتمل "
        "المسار المتقدم أعلاه."
    )

    return "\n".join(lines).rstrip() + "\n"


def _first_key(code: str) -> str:
    """low_issue_coverage:0.25 → low_issue_coverage."""
    if ":" in code:
        return code.split(":", 1)[0]
    return code
