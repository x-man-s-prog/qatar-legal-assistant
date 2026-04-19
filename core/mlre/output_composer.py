# -*- coding: utf-8 -*-
"""
MLRE Output Composer — rebuilds the final user answer from MLRE survivors.

NOT append. NOT decoration. REPLACES the pipeline's default text with a
structured output driven entirely by the surviving hypotheses.

Three output modes:
  MODE_A_ANALYSIS     — for analytical queries (default)
  MODE_B_ACTION       — for practical "what do I do" queries
  MODE_C_DRAFTING     — drafting handled by a separate engine (not here)

The composer returns user-safe Arabic text. NEVER exposes:
  • raw scores (0.59, 0.46, ...)
  • internal flags (low_issue_coverage, no_bound_evidence, ...)
  • hypothesis_type enum values
  • reason codes
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from core.mlre.orchestrator import MLREResult, DraftingV2Mode
from core.mlre.synthesis import LegalReality, PathView
from core.mlre.hypothesis import Hypothesis, HypothesisType
from core.ux.user_intent import UserIntent


class OutputMode(str, Enum):
    ANALYSIS = "analysis"      # التكييف الأقوى + البديل + حاسم
    ACTION   = "action"        # ماذا أفعل — خطوات عملية
    DRAFTING = "drafting"      # handled by drafting engine


@dataclass
class ComposedOutput:
    mode:              OutputMode
    text:              str = ""
    used_mlre:         bool = False
    used_survivors:    int = 0
    pivots_exposed:    int = 0
    show_alternative:  bool = False
    # Safe internal trace (NEVER rendered to user)
    trace:             dict = field(default_factory=dict)


# ═════════════════════════════════════════════════════════════════
# Natural-language phrasing for confidence levels (no raw numbers)
# ═════════════════════════════════════════════════════════════════

def _strength_phrase(score: float) -> str:
    if score >= 0.65:
        return "قوي"
    if score >= 0.45:
        return "معتبر"
    if score >= 0.30:
        return "محتمل"
    return "ضعيف"


def _risk_phrase(risk: str) -> str:
    return {
        "low":      "منخفضة",
        "medium":   "متوسطة",
        "high":     "مرتفعة",
        "critical": "جسيمة",
    }.get(risk, "متوسطة")


def _hypothesis_label_ar(h: Hypothesis) -> str:
    """Arabic label describing a hypothesis type — no raw enum names."""
    return {
        HypothesisType.PRIMARY_EXPECTED:    "التكييف المرجَّح",
        HypothesisType.CLOSEST_ALTERNATIVE: "البديل الأقرب",
        HypothesisType.HYBRID_CROSS_DOMAIN: "تكييف مزدوج",
        HypothesisType.DEFENSIVE:           "تفسير دفاعي",
        HypothesisType.AGGRESSIVE:          "تكييف مشدَّد",
        HypothesisType.MINIMALIST_CIVIL:    "مسار مدني محدود",
        HypothesisType.WORST_CASE_EXPOSURE: "أسوأ احتمالات المخاطرة",
        HypothesisType.EDGE_CASE:           "حالة استثنائية",
    }.get(h.hypothesis_type, "مسار")


# ═════════════════════════════════════════════════════════════════
# MODE A — Analysis
# Shows: primary + secondary + pivot + decisive tests
# ═════════════════════════════════════════════════════════════════

def _compose_mode_a(mlre: MLREResult) -> str:
    reality = mlre.reality
    if reality is None or not reality.paths:
        return ""

    parts: list[str] = []
    primary = reality.paths[0]
    parts.append(f"**التكييف المرجَّح:** {primary.legal_theory} "
                 f"(وصف {primary.domain}) — موقف {_strength_phrase(primary.score)}.")
    parts.append("")

    if primary.what_must_be_proven:
        parts.append("**ما يلزم إثباته لتثبيت هذا المسار:**")
        for p in primary.what_must_be_proven:
            parts.append(f"• {p}")
        parts.append("")

    if primary.weakest_point:
        parts.append(f"**أخطر نقطة ضعف:** {primary.weakest_point}")
        parts.append("")

    # Show alternative if exists
    if len(reality.paths) >= 2:
        alt = reality.paths[1]
        parts.append(f"**لكن يوجد تكييف بديل معتبر:** {alt.legal_theory} "
                     f"(وصف {alt.domain}) — مخاطرته {_risk_phrase(alt.risk)}.")
        if alt.weakest_point:
            parts.append(f"• نقطة ضعفه: {alt.weakest_point}")
        parts.append("")

        # Pivot condition
        if reality.pivot_conditions:
            parts.append("**متى ينتقل المسار الأول إلى البديل:**")
            for pc in reality.pivot_conditions[:2]:
                parts.append(f"• {pc}")
            parts.append("")

        # Decisive tests
        if reality.decisive_tests:
            parts.append("**ما يحسم بين المسارين:**")
            for t in reality.decisive_tests[:3]:
                parts.append(f"• {t}")
            parts.append("")

    # Third path (fallback/exposure warning)
    if len(reality.paths) >= 3:
        fallback = reality.paths[2]
        parts.append(
            f"**مسار احتياطي يجب أخذه في الاعتبار:** {fallback.legal_theory} "
            f"— مخاطرة {_risk_phrase(fallback.risk)}."
        )

    return "\n".join(parts).strip()


# ═════════════════════════════════════════════════════════════════
# MODE B — Action guidance
# ═════════════════════════════════════════════════════════════════

def _compose_mode_b(mlre: MLREResult) -> str:
    reality = mlre.reality
    if reality is None or not reality.paths:
        return ""

    primary = reality.paths[0]
    parts: list[str] = []
    parts.append(f"**المسار الأقوى عملياً:** {primary.legal_theory}.")
    parts.append("")

    if primary.what_must_be_proven:
        parts.append("**ما تحتاج إثباته لتقوية الموقف:**")
        for p in primary.what_must_be_proven:
            parts.append(f"• {p}")
        parts.append("")

    # Next-step guidance
    parts.append("**الخطوات المقترحة:**")
    parts.append("• توثيق الوقائع والأدلة فوراً (رسائل، شهود، مستندات).")
    parts.append("• الحصول على استشارة محامٍ مختص قبل رفع الدعوى.")
    if primary.domain in ("criminal",):
        parts.append("• تقديم بلاغ في مركز الشرطة إن كانت الجريمة مستمرة.")
    elif primary.domain in ("civil", "commercial"):
        parts.append("• توجيه إنذار رسمي قبل رفع الدعوى.")
    parts.append("")

    # Risk warning
    if primary.weakest_point:
        parts.append(f"**تحذير — ثغرة قد تُسقط الموقف:** {primary.weakest_point}")
        parts.append("")

    # Alternative path (if exists)
    if len(reality.paths) >= 2:
        alt = reality.paths[1]
        parts.append(f"**إن لم يكتمل المسار الأول، المسار البديل هو:** "
                     f"{alt.legal_theory}.")
        if reality.pivot_conditions:
            parts.append(f"• يتحول إليه إذا: {reality.pivot_conditions[0]}")

    return "\n".join(parts).strip()


# ═════════════════════════════════════════════════════════════════
# Main composer entry
# ═════════════════════════════════════════════════════════════════

def compose_output(
    mlre: MLREResult,
    user_intent: Optional[UserIntent] = None,
) -> ComposedOutput:
    """Produce the final user-facing text from MLRE survivors."""
    mode = _mode_from_intent(user_intent)
    out = ComposedOutput(mode=mode)

    reality = mlre.reality
    if reality is None or not reality.paths:
        # Fail-safe — no survivors → unresolved message (user-safe)
        if reality and not reality.can_be_answered:
            out.text = reality.unresolved_message
        out.used_mlre = bool(reality and reality.paths)
        out.trace = {
            "mlre_output_used": False,
            "output_mode":       mode.value,
            "survivors_count":   0,
            "pivots_exposed":    0,
            "legacy_blocked":    False,
        }
        return out

    # Compose based on mode
    if mode == OutputMode.ACTION:
        text = _compose_mode_b(mlre)
    else:
        text = _compose_mode_a(mlre)

    out.text = text
    out.used_mlre = True
    out.used_survivors = len(reality.paths)
    out.pivots_exposed = len(reality.pivot_conditions)
    out.show_alternative = len(reality.paths) >= 2
    out.trace = {
        "mlre_output_used": True,
        "output_mode":       mode.value,
        "survivors_count":   out.used_survivors,
        "pivots_exposed":    out.pivots_exposed,
        "show_alternative":  out.show_alternative,
    }
    return out


def _mode_from_intent(intent: Optional[UserIntent]) -> OutputMode:
    if intent == UserIntent.ACTION:
        return OutputMode.ACTION
    if intent == UserIntent.DRAFTING:
        return OutputMode.DRAFTING
    return OutputMode.ANALYSIS
