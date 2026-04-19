# -*- coding: utf-8 -*-
"""
Conditional Outcome Framing — NEVER prediction. ONLY conditional language.

Output uses "إذا/إن/ما لم" framing exclusively. No "ستربح" / "ستخسر" / "أكيد".

Built from:
  - sufficiency_level (from FailClosedPipeline)
  - decisive findings (from DecisiveEvidenceDetector)
  - opponent posture
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.evidence.contract import EvidenceSet
from core.knowledge.contract import SufficiencyLevel
from core.courtroom.decisive_evidence import DecisiveFinding


# Verdict-language blocklist — these MUST never appear in output
_FORBIDDEN = (
    "ستربح", "ستفوز", "ستخسر", "محسومة", "أكيد ينجح",
    "أكيد يفشل", "نسبة النجاح", "النتيجة مضمونة",
)


@dataclass
class OutcomeFraming:
    posture:           str           # strong | defensible | weak | insufficient
    conditional_lines: list[str] = field(default_factory=list)
    required_proofs:   list[str] = field(default_factory=list)
    fatal_gaps:        list[str] = field(default_factory=list)

    def to_public(self) -> dict:
        return {
            "posture":           self.posture,
            "conditional_lines": self.conditional_lines[:5],
            "required_proofs":   self.required_proofs[:5],
            "fatal_gaps":        self.fatal_gaps[:3],
        }

    def render_arabic(self) -> str:
        parts = ["**إطار النتيجة المشروط (لا جزم):**"]
        parts.append(f"الموقف الراهن: **{self._posture_arabic()}**.")
        if self.conditional_lines:
            parts.append("\n**المسارات المشروطة:**")
            for line in self.conditional_lines[:4]:
                parts.append(f"• {line}")
        if self.required_proofs:
            parts.append("\n**ما يُحتاج إثباته لتقوية الموقف:**")
            for p in self.required_proofs[:4]:
                parts.append(f"• {p}")
        if self.fatal_gaps:
            parts.append("\n**فجوات قد تُسقط الدعوى:**")
            for g in self.fatal_gaps[:3]:
                parts.append(f"• {g}")
        out = "\n".join(parts)
        # Defensive scrub — never let forbidden words slip through
        for f in _FORBIDDEN:
            out = out.replace(f, "—")
        return out

    def _posture_arabic(self) -> str:
        return {
            "strong":       "قوي",
            "defensible":   "قابل للدفاع",
            "weak":         "ضعيف",
            "insufficient": "ناقص — يحتاج أدلة إضافية",
        }.get(self.posture, "غير محدد")


def build_conditional_framing(
    evidence_set: Optional[EvidenceSet],
    sufficiency: SufficiencyLevel,
    decisive: list[DecisiveFinding],
    opponent_weak_spots: Optional[list[str]] = None,
) -> OutcomeFraming:
    """Pure function — no I/O, no LLM."""
    framing = OutcomeFraming(posture="insufficient")

    # Determine posture from sufficiency + decisive count
    if sufficiency == SufficiencyLevel.SUFFICIENT_DIRECT and decisive:
        framing.posture = "strong"
    elif sufficiency == SufficiencyLevel.SUFFICIENT_LIMITED and decisive:
        framing.posture = "defensible"
    elif sufficiency == SufficiencyLevel.SUFFICIENT_LIMITED:
        framing.posture = "defensible"
    elif sufficiency in (SufficiencyLevel.WEAK,
                          SufficiencyLevel.UNVERIFIED_ONLY):
        framing.posture = "weak"
    else:
        framing.posture = "insufficient"

    # Conditional lines — one per decisive finding
    for d in decisive[:3]:
        cite = d.record.public_citation()[:80]
        if d.is_decisive:
            framing.conditional_lines.append(
                f"إذا توفّر سند يثبت تطبيق {cite} على الوقائع → الموقف يتعزز."
            )
        else:
            framing.conditional_lines.append(
                f"السند {cite} داعم لكنه لا يحسم وحده."
            )

    # Required proofs — derived from opponent weak spots
    if opponent_weak_spots:
        for ws in opponent_weak_spots[:3]:
            framing.required_proofs.append(
                f"تجاوز نقطة ضعفك: {ws}"
            )

    # Fatal gaps — when sufficiency is insufficient
    if framing.posture == "insufficient":
        framing.fatal_gaps.append(
            "غياب أدلة موثَّقة كافية للحسم القانوني."
        )
    if framing.posture == "weak":
        framing.fatal_gaps.append(
            "الأدلة المتوفرة لا تنهض بعبء الإثبات وحدها."
        )

    return framing
