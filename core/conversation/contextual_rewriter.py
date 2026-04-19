# -*- coding: utf-8 -*-
"""
Contextual Query Rewriter — injects prior conversation state into a
terse follow-up so the pipeline sees a self-contained query.

NOT an LLM. Pure string composition + rule-based focus decoration.

Input:
    raw_query           = "وإذا كان في تويتر؟"
    state (prior turn)  = domain=criminal, offense=defamation, last_focus=offense
    intent              = MEDIUM_CHANGE (twitter)
    focus_shift         = MEDIUM_ADDED

Output:
    rewritten_query = "في قضية سب/قذف سابقة، وإذا كان النشر في تويتر — ما التكييف الإلكتروني؟"
    contextual_header  = evidence-layer hints injected into pipeline
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.conversation.state_engine import LegalConversationState
from core.conversation.followup_intent import FollowUpIntent, FollowUpVerdict
from core.conversation.issue_evolution import FocusShift, FocusShiftVerdict


# ── Arabic labels for offense keys ──
_OFFENSE_AR = {
    "defamation": "السب/القذف/الشتم",
    "assault":    "الاعتداء/الضرب",
    "threat":     "التهديد",
    "drugs":      "التعاطي/حيازة المخدرات",
    "theft":      "السرقة",
    "fraud":      "النصب/الاحتيال",
    "cyber":      "الابتزاز/الجرائم الإلكترونية",
    "harassment": "التحرش",
    "forgery":    "التزوير",
}

_MEDIUM_AR = {
    "digital_twitter":  "عبر تويتر",
    "digital_social":   "عبر وسائل التواصل الاجتماعي",
    "digital_web":      "عبر موقع إلكتروني",
    "digital_generic":  "بوسيلة إلكترونية",
    "call":             "عبر مكالمة هاتفية",
    "sms":              "عبر رسائل نصية",
    "street":           "في مكان عام",
    "broadcast":        "عبر بث عام",
    "print":            "في مطبوعة",
}

_FOCUS_AR = {
    "offense":      "تعريف الجريمة",
    "punishment":   "العقوبة المقررة",
    "proof":        "الإثبات والأدلة",
    "defense":      "الدفوع وأسباب البراءة",
    "procedure":    "الإجراءات والاختصاص",
    "medium_application":        "التكييف بالوسيلة",
    "conditional_fact_variant":  "الفرضية المضافة",
}


@dataclass
class ConversationTurnResult:
    """Output of the CLI pre-pipeline layer."""
    is_followup:        bool = False
    intent:             str = ""
    focus_shift:        str = ""
    new_focus:          str = ""
    rewritten_query:    str = ""
    inherited_domain:   str = ""
    inherited_offense:  str = ""
    added_medium:       str = ""
    carried_facts:      list[str] = field(default_factory=list)
    answer_mode:        str = "direct_short"
    # Synthesis hints for fail_closed_pipeline
    synthesis_hints:    dict = field(default_factory=dict)

    def to_trace(self) -> dict:
        return {
            "is_followup":       self.is_followup,
            "intent":            self.intent,
            "focus_shift":       self.focus_shift,
            "new_focus":         self.new_focus,
            "inherited_domain":  self.inherited_domain,
            "inherited_offense": self.inherited_offense,
            "added_medium":      self.added_medium,
            "carried_facts_n":   len(self.carried_facts),
            "answer_mode":       self.answer_mode,
            "rewritten":         (self.rewritten_query or "")[:120],
        }


def rewrite_for_context(
    raw_query: str,
    state: Optional[LegalConversationState],
    verdict: FollowUpVerdict,
    shift: FocusShiftVerdict,
) -> ConversationTurnResult:
    """Compose a self-contained query + synthesis hints from prior state."""
    out = ConversationTurnResult(
        is_followup = bool(state and state.turn_count > 0
                            and verdict.intent not in (
                                FollowUpIntent.NO_PRIOR_CONTEXT,
                                FollowUpIntent.NEW_CASE,
                            )),
        intent      = verdict.intent.value,
        focus_shift = shift.shift.value,
        new_focus   = shift.new_focus,
        answer_mode = shift.answer_mode,
    )

    # No follow-up → pass through raw
    if not out.is_followup or state is None:
        out.rewritten_query = raw_query
        return out

    # Inherit basics
    out.inherited_domain  = state.active_domain if shift.carry_domain else ""
    out.inherited_offense = state.active_offense_key if shift.carry_offense else ""
    out.added_medium      = shift.add_medium
    out.carried_facts     = list(state.active_facts) if shift.carry_facts else []

    # Build a focused rewritten query
    offense_ar = _OFFENSE_AR.get(out.inherited_offense, "")
    medium_ar  = _MEDIUM_AR.get(out.added_medium, "")
    focus_ar   = _FOCUS_AR.get(out.new_focus, "")

    context_prefix = ""
    if offense_ar and state.turn_count > 0:
        context_prefix = f"سياق سابق: قضية {offense_ar}. "

    # Specific templates per intent
    raw = (raw_query or "").strip()
    if verdict.intent == FollowUpIntent.MEDIUM_CHANGE and medium_ar:
        out.rewritten_query = (
            f"{context_prefix}"
            f"السؤال الحالي: ما التكييف القانوني والأساس إذا كان الفعل {medium_ar}؟ "
            f"(الأصل: {offense_ar or 'الجريمة ذاتها'}) "
            f"النص الحرفي من المستخدم: «{raw}»"
        )
    elif verdict.intent == FollowUpIntent.DEFENSE_SHIFT:
        out.rewritten_query = (
            f"{context_prefix}"
            f"السؤال الحالي: ما الدفوع وأسباب البراءة المحتملة في قضية "
            f"{offense_ar or 'كهذه'}؟ "
            f"النص الحرفي من المستخدم: «{raw}»"
        )
    elif verdict.intent == FollowUpIntent.EVIDENCE_SHIFT:
        out.rewritten_query = (
            f"{context_prefix}"
            f"السؤال الحالي: ما طرق الإثبات وحجية الأدلة "
            f"(شهود / تسجيلات / لقطات شاشة / رسائل) في قضية "
            f"{offense_ar or 'كهذه'}؟ "
            f"النص الحرفي من المستخدم: «{raw}»"
        )
    elif verdict.intent == FollowUpIntent.PROCEDURAL_SHIFT:
        out.rewritten_query = (
            f"{context_prefix}"
            f"السؤال الحالي: ما الإجراءات والاختصاص القضائي في قضية "
            f"{offense_ar or 'كهذه'}؟ "
            f"النص الحرفي من المستخدم: «{raw}»"
        )
    elif verdict.intent == FollowUpIntent.REMEDY_SHIFT:
        out.rewritten_query = (
            f"{context_prefix}"
            f"السؤال الحالي: ما العقوبة المقررة في "
            f"{offense_ar or 'الجريمة المذكورة'}؟ "
            f"النص الحرفي من المستخدم: «{raw}»"
        )
    elif verdict.intent == FollowUpIntent.FACT_CHANGE:
        out.rewritten_query = (
            f"{context_prefix}"
            f"فرضية مضافة: «{raw}» — كيف يتغير التكييف القانوني لـ"
            f"{offense_ar or 'القضية'} بناءً على هذه الفرضية؟"
        )
    elif verdict.intent == FollowUpIntent.SAME_ISSUE_REPHRASE:
        out.rewritten_query = (
            f"{context_prefix}"
            f"إعادة صياغة: «{raw}» — نفس النقطة السابقة حول "
            f"{focus_ar or offense_ar}."
        )
    else:
        # Narrowing / clarification
        out.rewritten_query = (
            f"{context_prefix}"
            f"استفسار ضمن نفس القضية: «{raw}»"
        )

    # Build synthesis hints for the pipeline
    out.synthesis_hints = {
        "focus":              out.new_focus,
        "answer_mode":        out.answer_mode,
        "inherited_offense":  out.inherited_offense,
        "added_medium":       out.added_medium,
        "add_issue_tags":     list(shift.add_issue_tags),
        "drop_issue_tags":    list(shift.drop_issue_tags),
        "skip_full_reanalysis": verdict.intent != FollowUpIntent.NEW_CASE,
        "dedupe_against":     state.last_answer_text_short,
    }
    return out
