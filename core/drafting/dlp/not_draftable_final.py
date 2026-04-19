# -*- coding: utf-8 -*-
"""
DLP — Final NOT_DRAFTABLE message (last resort only).

Under DLP, NOT_DRAFTABLE_YET is reserved for the rare case where NO
legal structure exists — no domain, no issue graph, and no MLRE
survivors. In that case we STILL give the user a useful message:

  • WHY no draft (specific, humanized)
  • WHAT is missing
  • WHAT would unblock
  • A reminder that analysis is possible even when drafting is not

This complements MQE's `build_not_draftable_message` by being richer
when MLRE has context to offer.
"""
from __future__ import annotations

from typing import Optional

from core.drafting.drafting_engine import DocumentType
from core.drafting.mqe.not_draftable import (
    build_not_draftable_message as _mqe_not_draftable,
    _DOC_LABEL,
)
from core.drafting.dlp.humanize import humanize_gaps


def build_final_not_draftable_message(
    doc_type: DocumentType,
    raw_gaps: Optional[list[str]] = None,
    mlre=None,
) -> str:
    """Structured 'not draftable' with MLRE context + humanized gaps."""
    # Start from MQE's structured message (WHAT / WHY / WHAT-UNBLOCKS)
    base = _mqe_not_draftable(
        doc_type,
        missing=list(raw_gaps or ["issue_graph_unavailable",
                                     "no_bound_evidence"]),
    )

    parts = [base.rstrip()]

    # Add human-safe gap list on top of the MQE base (de-duplicated)
    user_safe = humanize_gaps(raw_gaps or [])
    if user_safe:
        parts.append("")
        parts.append("**العناصر التي يتعيّن استكمالها:**")
        for g in user_safe[:5]:
            parts.append(f"• {g}")

    # Surface any MLRE unresolved message for extra context
    if mlre is not None:
        reality = getattr(mlre, "reality", None)
        if reality is not None:
            msg = getattr(reality, "unresolved_message", "") or ""
            if msg:
                parts.append("")
                parts.append("**ملاحظة من محرك التكييف المتعدد:**")
                parts.append(msg.strip())

    # A closing nudge: even when drafting is blocked, ANALYSIS is not
    parts.append("")
    parts.append(
        "يمكن في هذه الأثناء تحليل القضية دون صياغة، أو إعادة عرضها "
        "بتفاصيل إضافية، ثم صياغة المذكرة حين يكتمل المسار القانوني أعلاه."
    )

    return "\n".join(parts).rstrip() + "\n"
