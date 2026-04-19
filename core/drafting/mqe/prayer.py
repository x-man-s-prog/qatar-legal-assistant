# -*- coding: utf-8 -*-
"""
Memorandum Quality Engine — Prayer / Requests Engine.

Replaces generic prayers ("اتخاذ اللازم", "إنصافي") with precise, court-
actionable requests anchored to:
  • document type
  • client's procedural position
  • remedy nodes in the issue graph
  • MLRE survivors (for conditional / alternative prayers)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.drafting.drafting_engine import DocumentType, ClientSide
from core.domain_pipeline.issue_graph import IssueGraph, IssueKind


@dataclass
class Prayer:
    primary:      list[str] = field(default_factory=list)
    alternative:  list[str] = field(default_factory=list)   # احتياطي
    fallback:     list[str] = field(default_factory=list)   # احتياط كلي


# ═════════════════════════════════════════════════════════════════
# Banned vague prayer phrases (firewall)
# ═════════════════════════════════════════════════════════════════

_BANNED_PHRASES = [
    "اتخاذ اللازم", "اتخاذ ما يلزم",
    "إنصافي", "الإنصاف",
    "ما يحقق العدالة", "تحقيق العدالة",
    "النظر بعين الاعتبار",
    "ما ترونه مناسباً",
    "الحكم بما ترونه",
]


def is_vague_prayer(text: str) -> bool:
    if not text:
        return True
    low = (text or "").strip()
    if len(low) < 10:
        return True
    return any(p in low for p in _BANNED_PHRASES)


# ═════════════════════════════════════════════════════════════════
# Per-document-type prayers (precise)
# ═════════════════════════════════════════════════════════════════

def _defense_prayers(graph: Optional[IssueGraph],
                        client_side: ClientSide) -> Prayer:
    """For defendants: dismissal → alternatives → fallback."""
    p = Prayer()
    defenses = graph.by_kind(IssueKind.DEFENSE) if graph else []
    threshold = graph.by_kind(IssueKind.THRESHOLD) if graph else []

    # Procedural dismissal first (strongest if applicable)
    if threshold:
        p.primary.append("الحكم بعدم قبول الدعوى لانتفاء شرطها الإجرائي.")

    if client_side == ClientSide.ACCUSED:
        p.primary.append("الحكم ببراءة المتّهم مما أُسند إليه لانتفاء الأركان.")
    else:
        p.primary.append("الحكم برفض الدعوى موضوعاً لانتفاء سندها القانوني.")
    p.primary.append("إلزام الطرف الآخر بالمصاريف ومقابل أتعاب المحاماة.")

    # Alternatives from defense nodes (if present)
    for d in defenses[:2]:
        q = (d.question or "").strip().rstrip("؟?")
        if q:
            p.alternative.append(f"الحكم بالاعتداد بدفع: {q}.")
    if not p.alternative:
        p.alternative.append(
            "ندب خبير مختص لتحقيق الواقعة المتنازع عليها."
        )

    p.fallback.append(
        "إعادة القضية إلى سلطة التحقيق لاستكمال التحريات قبل الفصل."
    )
    return p


def _claim_prayers(graph: Optional[IssueGraph],
                      client_side: ClientSide) -> Prayer:
    """For claimants: acceptance + specific remedy + costs."""
    p = Prayer()
    p.primary.append("قبول الدعوى شكلاً.")

    remedies = graph.by_kind(IssueKind.REMEDY) if graph else []
    for r in remedies[:2]:
        q = (r.question or "").strip().rstrip("؟?")
        if q:
            p.primary.append(f"الحكم بـ: {q}.")
    if not remedies:
        p.primary.append(
            "الحكم بإلزام المدّعى عليه بالوفاء بالتزامه المنبثق عن العقد."
        )

    p.primary.append("إلزام المدّعى عليه بالمصاريف ومقابل أتعاب المحاماة.")

    p.alternative.append(
        "ندب خبير مختص لتقدير قيمة المطلوب عند الاقتضاء."
    )
    return p


def _reply_prayers(graph: Optional[IssueGraph],
                     client_side: ClientSide) -> Prayer:
    """For replies: stay on course + request rejection of opposing prayers."""
    p = Prayer()
    p.primary.append(
        "التمسك بما جاء في المذكرة الأصلية وعدم الاعتداد بدفوع الخصم."
    )
    p.primary.append(
        "رفض طلبات الخصم لقيامها على سند غير صحيح وواقع غير ثابت."
    )
    if client_side in {ClientSide.CLAIMANT, ClientSide.APPELLANT}:
        p.primary.append("الحكم بالطلبات الواردة في المذكرة السابقة.")
    elif client_side in {ClientSide.DEFENDANT, ClientSide.RESPONDENT,
                           ClientSide.ACCUSED}:
        p.primary.append("الحكم برفض الدعوى/الاستئناف موضوعاً.")
    return p


def _checklist_prayers(graph: Optional[IssueGraph]) -> Prayer:
    """For checklist: each defense is a precise request."""
    p = Prayer()
    defenses = graph.by_kind(IssueKind.DEFENSE) if graph else []
    if defenses:
        for d in defenses[:4]:
            q = (d.question or "").strip().rstrip("؟?")
            if q:
                p.primary.append(f"الاعتداد بدفع: {q}.")
    else:
        p.primary.extend([
            "الدفع بانتفاء الركن المادي للواقعة المسندة.",
            "الدفع بانتفاء الركن المعنوي (القصد).",
            "الدفع بضعف الإثبات وعدم كفايته.",
        ])
    return p


def _petition_prayers(graph: Optional[IssueGraph],
                         explicit_requests: list[str]) -> Prayer:
    """For petitions: explicit request + enforcement request."""
    p = Prayer()
    if explicit_requests:
        for r in explicit_requests[:3]:
            r = r.strip()
            if r and not is_vague_prayer(r):
                p.primary.append(r if r.endswith(".") else r + ".")
    if not p.primary:
        p.primary.append(
            "الأمر بإجابة الطلب المقدَّم وترتيب آثاره القانونية."
        )
    return p


def _pleading_points_prayers(graph: Optional[IssueGraph],
                                 client_side: ClientSide) -> Prayer:
    """For pleading points: compact, decisive asks."""
    p = Prayer()
    if client_side in {ClientSide.DEFENDANT, ClientSide.ACCUSED,
                         ClientSide.RESPONDENT}:
        p.primary.append("رفض الدعوى/الاستئناف لعدم قيامها على سند.")
    else:
        p.primary.append("الحكم بطلبات الموكّل وفق ما تقدّم.")
    p.primary.append("إلزام الخصم بالمصاريف.")
    return p


# ═════════════════════════════════════════════════════════════════
# Public API
# ═════════════════════════════════════════════════════════════════

def build_prayer(
    doc_type: DocumentType,
    client_side: ClientSide,
    graph: Optional[IssueGraph] = None,
    explicit_requests: Optional[list[str]] = None,
    mlre_survivors: int = 0,
) -> Prayer:
    """Build a precise, court-actionable prayer block."""
    explicit_requests = list(explicit_requests or [])

    if doc_type == DocumentType.DEFENSE_MEMO:
        p = _defense_prayers(graph, client_side)
    elif doc_type == DocumentType.CLAIM_BRIEF:
        p = _claim_prayers(graph, client_side)
    elif doc_type == DocumentType.REPLY_MEMO:
        p = _reply_prayers(graph, client_side)
    elif doc_type == DocumentType.DEFENSE_CHECKLIST:
        p = _checklist_prayers(graph)
    elif doc_type == DocumentType.PETITION_MEMO:
        p = _petition_prayers(graph, explicit_requests)
    elif doc_type == DocumentType.PLEADING_POINTS:
        p = _pleading_points_prayers(graph, client_side)
    elif doc_type == DocumentType.EXPLANATORY_MEMO:
        p = Prayer(primary=[
            "عرض ما تقدّم على المحكمة للفصل وفق النصوص المذكورة.",
        ])
    elif doc_type == DocumentType.CASE_SUMMARY:
        p = Prayer(primary=[
            "الإحاطة بما تقدّم لاعتماده مرجعاً في نظر الملف.",
        ])
    else:
        p = Prayer(primary=["الفصل في الطلبات المتقدمة وفق النصوص المذكورة."])

    # Append explicit requests (filtered)
    for r in explicit_requests:
        r = (r or "").strip()
        if r and not is_vague_prayer(r):
            if r not in p.primary:
                p.primary.append(r if r.endswith(".") else r + ".")

    # If MLRE shows multiple viable paths, ensure at least one alternative
    if mlre_survivors >= 2 and not p.alternative:
        p.alternative.append(
            "الأخذ بالتكييف البديل إذا رأت المحكمة عدم الأخذ "
            "بالمسار المتقدم."
        )

    # Final firewall: drop any vague prayers that slipped in
    p.primary = [r for r in p.primary if not is_vague_prayer(r)]
    p.alternative = [r for r in p.alternative if not is_vague_prayer(r)]
    p.fallback = [r for r in p.fallback if not is_vague_prayer(r)]
    return p


def render_prayer(prayer: Prayer) -> str:
    """Render the Prayer block in the final memo style."""
    lines: list[str] = []
    if prayer.primary:
        lines.append("— أصلياً:")
        for r in prayer.primary:
            lines.append(f"  • {r}")
    if prayer.alternative:
        lines.append("— احتياطياً:")
        for r in prayer.alternative:
            lines.append(f"  • {r}")
    if prayer.fallback:
        lines.append("— على سبيل الاحتياط الكلي:")
        for r in prayer.fallback:
            lines.append(f"  • {r}")
    return "\n".join(lines)
