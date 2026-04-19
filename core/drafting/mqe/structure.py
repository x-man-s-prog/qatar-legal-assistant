# -*- coding: utf-8 -*-
"""
Memorandum Quality Engine — Structure Builder.

Constructs the SECTION plan for every memo type. Empty sections are
dropped — no placeholder headings. Each document type emphasizes what
matters for that type:

  DEFENSE_MEMO       → dismantle claim + burden of proof + strongest defenses first
  REPLY_MEMO         → respond to SPECIFIC opposing points; no full restatement
  CLAIM_BRIEF        → facts → legal grounding → precise requests
  PLEADING_POINTS    → short, decisive bullets only
  DEFENSE_CHECKLIST  → procedural defenses first, then substantive
  PETITION_MEMO      → request + legal basis + why granting it is justified
  EXPLANATORY_MEMO   → structured exposition for the court (facts + theory)
  CASE_SUMMARY       → compact record of the file
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.drafting.drafting_engine import DocumentType, ClientSide


@dataclass
class MemoSection:
    key:     str
    title:   str
    body:    str = ""
    priority: int = 0
    meta:    dict = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.body or not self.body.strip()


# ═════════════════════════════════════════════════════════════════
# Section ordering per document type
# ═════════════════════════════════════════════════════════════════

DEFENSE_MEMO_ORDER = [
    "header", "parties", "facts_summary",
    "issues", "statute_basis",
    "application",
    "opponent_model",
    "proof_burden",
    "conclusion",
    "prayer",
    "conditional_fallback",
    "assumptions",
]

REPLY_MEMO_ORDER = [
    "header", "parties", "opposing_points_summary",
    "point_by_point_reply",
    "statute_basis",
    "conclusion",
    "prayer",
    "assumptions",
]

CLAIM_BRIEF_ORDER = [
    "header", "parties", "facts_summary",
    "issues", "statute_basis",
    "application",
    "proof_burden",
    "conclusion",
    "prayer",
    "assumptions",
]

PLEADING_POINTS_ORDER = [
    "header", "issues", "application", "prayer",
]

DEFENSE_CHECKLIST_ORDER = [
    "header",
    "procedural_defenses",
    "substantive_defenses",
    "evidence_defenses",
]

PETITION_MEMO_ORDER = [
    "header", "parties", "facts_summary",
    "statute_basis",
    "application",
    "prayer",
    "assumptions",
]

EXPLANATORY_MEMO_ORDER = [
    "header", "parties", "facts_summary",
    "issues", "statute_basis",
    "application",
    "conclusion",
    "assumptions",
]

CASE_SUMMARY_ORDER = [
    "header", "parties", "facts_summary",
    "issues", "statute_basis",
    "conclusion",
]


_ORDER_BY_TYPE: dict[DocumentType, list[str]] = {
    DocumentType.DEFENSE_MEMO:      DEFENSE_MEMO_ORDER,
    DocumentType.REPLY_MEMO:        REPLY_MEMO_ORDER,
    DocumentType.CLAIM_BRIEF:       CLAIM_BRIEF_ORDER,
    DocumentType.PLEADING_POINTS:   PLEADING_POINTS_ORDER,
    DocumentType.DEFENSE_CHECKLIST: DEFENSE_CHECKLIST_ORDER,
    DocumentType.PETITION_MEMO:     PETITION_MEMO_ORDER,
    DocumentType.EXPLANATORY_MEMO:  EXPLANATORY_MEMO_ORDER,
    DocumentType.CASE_SUMMARY:      CASE_SUMMARY_ORDER,
}


# ═════════════════════════════════════════════════════════════════
# Section titles (Arabic) — numbering added by the renderer
# ═════════════════════════════════════════════════════════════════

_SECTION_TITLES = {
    "header":                "",     # rendered separately
    "parties":               "الأطراف والصفة الإجرائية",
    "facts_summary":         "موجز الوقائع ذات الصلة",
    "issues":                "المسائل القانونية المطروحة",
    "statute_basis":         "السند القانوني الحاكم",
    "application":           "التطبيق على الوقائع",
    "opponent_model":        "الرد على الدفع المتوقَّع",
    "proof_burden":          "عبء الإثبات",
    "conclusion":            "الخلاصة القانونية",
    "prayer":                "الطلبات",
    "conditional_fallback":  "على سبيل الاحتياط — المسار البديل",
    "assumptions":           "افتراضات الصياغة",
    "opposing_points_summary": "موجز دفوع الخصم",
    "point_by_point_reply":  "الرد التفصيلي",
    "procedural_defenses":   "دفوع إجرائية",
    "substantive_defenses":  "دفوع موضوعية",
    "evidence_defenses":     "دفوع الإثبات",
}


_ORDINAL_AR = [
    "أولاً", "ثانياً", "ثالثاً", "رابعاً", "خامساً",
    "سادساً", "سابعاً", "ثامناً", "تاسعاً", "عاشراً",
    "حادي عشر", "ثاني عشر",
]


def section_order(doc_type: DocumentType) -> list[str]:
    return list(_ORDER_BY_TYPE.get(doc_type, DEFENSE_MEMO_ORDER))


def section_title(key: str) -> str:
    return _SECTION_TITLES.get(key, key)


def format_section_header(idx_nonheader: int, title: str) -> str:
    """Arabic-ordinal section header like 'أولاً — العنوان:'."""
    if not title:
        return ""
    ordinal = (
        _ORDINAL_AR[idx_nonheader]
        if 0 <= idx_nonheader < len(_ORDINAL_AR)
        else f"بنداً {idx_nonheader + 1}"
    )
    return f"**{ordinal} — {title}:**"


# ═════════════════════════════════════════════════════════════════
# Client-side / parties line
# ═════════════════════════════════════════════════════════════════

_CLIENT_SIDE_AR = {
    ClientSide.CLAIMANT:   "مقدَّمة من المدّعي",
    ClientSide.DEFENDANT:  "مقدَّمة من المدّعى عليه",
    ClientSide.APPELLANT:  "مقدَّمة من المستأنف",
    ClientSide.RESPONDENT: "مقدَّمة من المستأنف ضدّه",
    ClientSide.ACCUSED:    "مقدَّمة من المتّهم",
    ClientSide.VICTIM:     "مقدَّمة من المجنيّ عليه",
    ClientSide.NEUTRAL:    "",
}


def parties_line(client_side: ClientSide) -> str:
    return _CLIENT_SIDE_AR.get(client_side, "") or ""
