# -*- coding: utf-8 -*-
"""
Synthesis Engine v2 — Structured Legal Reality Output.

NOT a single answer. NOT vague probabilities.

Output structure:
  1. التكييف الأقوى (Primary)
  2. التكييف البديل (Secondary)
  3. متى يتحول الأول إلى الثاني (pivot conditions)
  4. ما يحسم بينهما (decisive tests)
  5. أخطر نقطة ضعف في كل مسار
  6. ما يحتاج إثباته لكل مسار
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.mlre.hypothesis import Hypothesis, HypothesisType
from core.mlre.scoring import ScoreBreakdown
from core.mlre.adversarial import AdversarialAttack
from core.mlre.context_lock import ContextLockMatrix


@dataclass
class PathView:
    """User-facing view of a single surviving hypothesis path."""
    rank:                 int = 0
    label:                str = ""             # "التكييف الأقوى" / "البديل" / ...
    hypothesis_id:        str = ""
    domain:               str = ""
    legal_theory:         str = ""
    weakest_point:        str = ""
    what_must_be_proven:  list[str] = field(default_factory=list)
    score:                float = 0.0
    risk:                 str = ""

    def to_dict(self) -> dict:
        return {
            "rank":                 self.rank,
            "label":                self.label,
            "hypothesis_id":        self.hypothesis_id,
            "domain":               self.domain,
            "legal_theory":         self.legal_theory,
            "weakest_point":        self.weakest_point,
            "what_must_be_proven":  self.what_must_be_proven,
            "score":                round(self.score, 3),
            "risk":                 self.risk,
        }


@dataclass
class LegalReality:
    paths:                list[PathView] = field(default_factory=list)
    pivot_conditions:     list[str] = field(default_factory=list)
    decisive_tests:       list[str] = field(default_factory=list)
    rendered_text:        str = ""
    surviving_count:      int = 0
    total_hypotheses:     int = 0
    rejected_count:       int = 0
    rejection_reasons:    list[str] = field(default_factory=list)
    # Fail-safe message when nothing survives
    unresolved_message:   str = ""
    can_be_answered:      bool = True

    def to_dict(self) -> dict:
        return {
            "paths":              [p.to_dict() for p in self.paths],
            "pivot_conditions":   self.pivot_conditions,
            "decisive_tests":     self.decisive_tests,
            "surviving_count":    self.surviving_count,
            "total_hypotheses":   self.total_hypotheses,
            "rejected_count":     self.rejected_count,
            "rejection_reasons":  self.rejection_reasons[:5],
            "can_be_answered":    self.can_be_answered,
        }


# ═════════════════════════════════════════════════════════════════
# Pivot / test templates per domain-pair
# ═════════════════════════════════════════════════════════════════

_PIVOT_TEMPLATES = {
    ("criminal", "civil"): [
        "إذا ثبت انتفاء القصد الجنائي → تتحول القضية إلى مسؤولية مدنية فقط.",
        "إذا ظهر اتفاق مكتوب ينفي نية الإضرار → يرجَّح التكييف المدني.",
    ],
    ("civil", "commercial"): [
        "إذا تبين أن الطرفين تاجران والمعاملة تجارية بطبيعتها → ينتقل الاختصاص للقضاء التجاري.",
    ],
    ("commercial", "criminal"): [
        "إذا ثبت تدليس متعمد في البيانات → يُضاف وصف جنائي للاحتيال.",
    ],
    ("banking", "criminal"): [
        "إذا ثبت إساءة استعمال أو تزوير توقيع → يتحول لتكييف جنائي.",
    ],
    ("family", "inheritance"): [
        "إذا ثبت أن التحويل وقع في مرض الموت → تطبَّق أحكام الوصية لا الهبة.",
    ],
    ("employment", "criminal"): [
        "إذا ثبت تسريب معلومات سرية بقصد الإضرار → ينضم وصف جنائي.",
    ],
}


def _pivot_between(primary_dom: str, secondary_dom: str) -> list[str]:
    direct = _PIVOT_TEMPLATES.get((primary_dom, secondary_dom))
    if direct:
        return list(direct)
    reverse = _PIVOT_TEMPLATES.get((secondary_dom, primary_dom))
    if reverse:
        return [f"(مسار معكوس) {t}" for t in reverse]
    return [
        f"إذا ثبتت وقائع مغيّرة للتكييف → قد ينتقل من {primary_dom} إلى {secondary_dom}.",
    ]


def _decisive_tests(primary: Hypothesis, secondary: Hypothesis) -> list[str]:
    tests = []
    if primary.issue_graph and primary.issue_graph.primary_issue:
        prim_node = primary.issue_graph.nodes.get(primary.issue_graph.primary_issue)
        if prim_node and prim_node.required_proof:
            for p in prim_node.required_proof[:2]:
                tests.append(f"إثبات: {p}")
    if secondary and secondary.issue_graph and secondary.issue_graph.primary_issue:
        sec_node = secondary.issue_graph.nodes.get(secondary.issue_graph.primary_issue)
        if sec_node and sec_node.required_proof:
            for p in sec_node.required_proof[:1]:
                tests.append(f"إثبات عكسي: {p}")
    return tests[:4]


def _what_must_be_proven(h: Hypothesis) -> list[str]:
    out: list[str] = []
    if h.issue_graph:
        for node in h.issue_graph.nodes.values():
            for p in (node.required_proof or [])[:1]:
                if p and p not in out:
                    out.append(p)
            if len(out) >= 3:
                break
    return out[:3]


def _weakest_point(h: Hypothesis, atk: AdversarialAttack) -> str:
    if atk.dismissal_paths:
        return atk.dismissal_paths[0]
    if h.high_risk_missing_evidence:
        return "غياب الأدلة الأساسية المطلوبة لهذا المسار."
    if h.contradiction_risk > 0.5:
        return "تناقض بين الوقائع الظاهرة والوصف القانوني المقترح."
    return "عدم وجود نقطة ضعف واضحة — لكن يبقى قابلاً للطعن."


# ═════════════════════════════════════════════════════════════════
# Main synthesizer
# ═════════════════════════════════════════════════════════════════

def synthesize_reality(
    survivors: list[tuple[Hypothesis, ScoreBreakdown, AdversarialAttack]],
    all_attacked: Optional[list[tuple[Hypothesis, ScoreBreakdown,
                                        AdversarialAttack]]] = None,
    context_lock: Optional[ContextLockMatrix] = None,
) -> LegalReality:
    """Compose a structured Legal Reality from surviving hypotheses."""
    reality = LegalReality()
    reality.total_hypotheses = len(all_attacked) if all_attacked else len(survivors)
    reality.surviving_count = len(survivors)
    reality.rejected_count = reality.total_hypotheses - reality.surviving_count

    if all_attacked:
        for (h, _, atk) in all_attacked:
            if not atk.survives:
                reality.rejection_reasons.extend(atk.collapse_reasons)

    # ── Fail-safe: no survivors ──
    if not survivors:
        reality.can_be_answered = False
        reality.unresolved_message = (
            "**تعذّر حسم التكييف القانوني الأفضل بين التفسيرات المتنافسة.**\n\n"
            "**لماذا لا يمكن الحسم حالياً:**\n"
            "• كل التفسيرات المرشَّحة تحمل نقاط ضعف جوهرية.\n"
            "• الأدلة المتوفرة غير كافية لترجيح تفسير على آخر.\n\n"
            "**ما ينقص تحديداً:**\n"
            "• توثيق أقوى للوقائع المحورية.\n"
            "• أدلة مستقلة (شهود / وثائق / تقارير فنية).\n\n"
            "**السيناريوهات المحتملة:**\n"
            "• إن تعزّزت الأدلة → يمكن حسم التكييف لاحقاً.\n"
            "• إن بقيت ناقصة → خيار التسوية الودية قد يكون أفضل من التقاضي."
        )
        reality.rendered_text = reality.unresolved_message
        return reality

    # ── Build path views ──
    labels = [
        "التكييف الأقوى",
        "التكييف البديل",
        "تكييف احتياطي",
    ]
    for i, (h, score, atk) in enumerate(survivors[:3]):
        pv = PathView(
            rank=i + 1,
            label=labels[i] if i < len(labels) else f"مسار #{i+1}",
            hypothesis_id=h.hypothesis_id,
            domain=h.domain,
            legal_theory=h.legal_theory,
            weakest_point=_weakest_point(h, atk),
            what_must_be_proven=_what_must_be_proven(h),
            score=score.composite,
            risk=h.legal_risk_level,
        )
        reality.paths.append(pv)

    # ── Pivot conditions (between primary and secondary) ──
    if len(survivors) >= 2:
        primary = survivors[0][0]
        secondary = survivors[1][0]
        reality.pivot_conditions = _pivot_between(
            primary.domain, secondary.domain
        )
        reality.decisive_tests = _decisive_tests(primary, secondary)

    # ── Render Arabic text ──
    reality.rendered_text = _render_arabic(reality)
    return reality


def _render_arabic(r: LegalReality) -> str:
    """Compose the user-facing Arabic text block."""
    if not r.can_be_answered:
        return r.unresolved_message

    parts: list[str] = ["**الواقع القانوني للقضية (تفسيرات متنافسة):**", ""]

    for p in r.paths:
        parts.append(f"**{p.label}** — {p.domain}")
        parts.append(f"• النظرية القانونية: {p.legal_theory}")
        parts.append(f"• درجة القوة: {p.score:.2f} | مستوى المخاطرة: {p.risk}")
        parts.append(f"• أخطر نقطة ضعف: {p.weakest_point}")
        if p.what_must_be_proven:
            parts.append("• ما يلزم إثباته:")
            for pp in p.what_must_be_proven:
                parts.append(f"  ‐ {pp}")
        parts.append("")

    if r.pivot_conditions:
        parts.append("**متى يتحول المسار الأول إلى البديل:**")
        for pc in r.pivot_conditions:
            parts.append(f"• {pc}")
        parts.append("")

    if r.decisive_tests:
        parts.append("**ما يحسم بين المسارات:**")
        for t in r.decisive_tests:
            parts.append(f"• {t}")
        parts.append("")

    parts.append(
        f"*ملخص تقني: {r.surviving_count} تفسير نجا من "
        f"{r.total_hypotheses} فرضية أولية، "
        f"{r.rejected_count} أُقصيت بعد الاختبار الخصومي.*"
    )
    return "\n".join(parts)
