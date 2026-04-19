# -*- coding: utf-8 -*-
"""
LegalFollowUpIntentEngine — deterministic follow-up classifier.

Maps a NEW message + prior conversation state to one of:
  SAME_ISSUE_REPHRASE, SAME_ISSUE_NARROWING,
  MEDIUM_CHANGE, FACT_CHANGE, DEFENSE_SHIFT,
  PROCEDURAL_SHIFT, EVIDENCE_SHIFT, REMEDY_SHIFT,
  NEW_CASE, CLARIFICATION_ONLY.

Rule-based. No LLM. Fully testable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from core.conversation.state_engine import LegalConversationState


class FollowUpIntent(str, Enum):
    SAME_ISSUE_REPHRASE    = "same_issue_rephrase"
    SAME_ISSUE_NARROWING   = "same_issue_narrowing"
    MEDIUM_CHANGE          = "medium_change"
    FACT_CHANGE            = "fact_change"
    DEFENSE_SHIFT          = "defense_shift"
    PROCEDURAL_SHIFT       = "procedural_shift"
    EVIDENCE_SHIFT         = "evidence_shift"
    REMEDY_SHIFT           = "remedy_shift"
    NEW_CASE               = "new_case"
    CLARIFICATION_ONLY     = "clarification_only"
    NO_PRIOR_CONTEXT       = "no_prior_context"   # first turn


@dataclass
class FollowUpVerdict:
    intent:         FollowUpIntent
    confidence:     float = 0.0
    signals:        list[str] = field(default_factory=list)
    detected_medium: str = ""
    detected_focus:  str = ""
    inherits_domain: bool = False
    new_case_reason: str = ""

    def to_trace(self) -> dict:
        return {
            "intent":          self.intent.value,
            "confidence":      round(self.confidence, 3),
            "signals":         self.signals,
            "detected_medium": self.detected_medium,
            "detected_focus":  self.detected_focus,
            "inherits_domain": self.inherits_domain,
        }


# ── Follow-up surface markers (strong signals of continuation) ──

_CONTINUATION_MARKERS = (
    "طيب", "طيّب", "ثم", "بعدين", "وبعدين",
    "وإذا", "واذا", "ولو", "وإن", "لو",
    "حتى لو", "حتى إذا", "حتى اذا",
    "يعني", "قصدي", "قصدك",
    "هل يمكن", "هل يصح", "هل",
    "وش", "شنو", "ايش", "أيش",
    "أيضاً", "كذلك", "أيضا",
)

_REPHRASE_MARKERS = (
    "يعني", "قصدي", "أقصد", "بمعنى",
)

_MEDIUM_MARKERS = {
    "digital_twitter":  ["تويتر", "twitter", "اكس", "x"],
    "digital_social":   ["فيسبوك", "انستقرام", "انستغرام", "سناب", "تيك توك",
                         "تيكتوك", "واتساب", "تلقرام", "تيليجرام",
                         "وسائل التواصل", "سوشيال ميديا"],
    "digital_web":      ["موقع", "موقع إلكتروني", "انترنت", "إنترنت", "موقع الكتروني",
                         "منتدى", "موقع ويب"],
    "digital_generic":  ["إلكتروني", "الكتروني", "رقمي", "عبر الإنترنت",
                         "اون لاين", "أونلاين"],
    "call":             ["مكالمة", "اتصال"],
    "sms":              ["رسالة نصية", "رسالة قصيرة", "رسائل نصية"],
    "street":           ["في الشارع", "وجهاً لوجه", "علناً", "أمام الناس"],
    "broadcast":        ["تلفزيون", "إذاعة", "بث مباشر", "قناة"],
    "print":            ["جريدة", "صحيفة", "مجلة", "منشور"],
}

_DEFENSE_MARKERS = (
    "براءة", "يطلع براءة", "يطلع بري",
    "دفاع", "حجة", "دفع",
    "هل يمكن الإفلات", "هل ممكن يفلت",
    "كيف ارد", "كيف اثبت براءتي",
)

_PROCEDURAL_MARKERS = (
    "اختصاص", "المحكمة المختصة", "طعن", "استئناف", "تمييز",
    "إجراءات", "البلاغ", "كيف ابلّغ", "وين ابلغ",
    "المهلة", "التقادم",
)

_EVIDENCE_MARKERS = (
    "شهود", "دليل", "أدلة", "إثبات", "أثبت",
    "سكرين شوت", "لقطة شاشة", "تسجيل", "رسائل",
    "تقرير طبي", "ما عندي دليل", "ما عندي شهود",
    "ما عندي إلا",
)

_REMEDY_MARKERS = (
    "عقوبة", "العقوبة", "وش العقوبة", "وش عقوبته",
    "الغرامة", "الحبس", "السجن", "التعويض",
    "ماذا أفعل", "وش اسوي",
)

_FACT_CHANGE_MARKERS = (
    "لو كان", "إذا كان", "لو ما كان", "لو هو",
    "ولو كان موظف", "لو كان قاصر",
)

_NEW_CASE_STRONG_MARKERS = (
    "سؤال ثاني", "موضوع ثاني", "قضية أخرى",
    "عندي سؤال", "غيّر الموضوع",
)


# ── helpers ──

def _detect_medium(q: str) -> str:
    for medium, markers in _MEDIUM_MARKERS.items():
        if any(m in q for m in markers):
            return medium
    return ""


def _has_any(q: str, markers) -> bool:
    return any(m in q for m in markers)


def _word_count(q: str) -> int:
    return len(q.split())


def _starts_with_continuation(q: str) -> bool:
    q = q.strip()
    for m in _CONTINUATION_MARKERS:
        if q.startswith(m + " ") or q.startswith(m + "\n") or q == m:
            return True
    return False


# ═════════════════════════════════════════════════════════════════
# Main classifier
# ═════════════════════════════════════════════════════════════════

def classify_followup(query: str,
                       state: Optional[LegalConversationState]) -> FollowUpVerdict:
    """Classify a new message against prior state."""
    verdict = FollowUpVerdict(intent=FollowUpIntent.NO_PRIOR_CONTEXT)
    q = (query or "").strip()

    # No prior state or stale state → new case path
    if state is None or state.turn_count == 0 or not state.active_domain:
        verdict.intent = FollowUpIntent.NO_PRIOR_CONTEXT
        return verdict

    # Explicit "new topic" markers
    if _has_any(q, _NEW_CASE_STRONG_MARKERS):
        verdict.intent = FollowUpIntent.NEW_CASE
        verdict.new_case_reason = "explicit_new_topic_marker"
        verdict.signals.append("explicit_new_topic")
        return verdict

    # Detect surface features
    starts_continuation = _starts_with_continuation(q)
    medium              = _detect_medium(q)
    has_defense         = _has_any(q, _DEFENSE_MARKERS)
    has_procedural      = _has_any(q, _PROCEDURAL_MARKERS)
    has_evidence        = _has_any(q, _EVIDENCE_MARKERS)
    has_remedy          = _has_any(q, _REMEDY_MARKERS)
    has_fact_change     = _has_any(q, _FACT_CHANGE_MARKERS)
    has_rephrase        = _has_any(q, _REPHRASE_MARKERS)

    wc = _word_count(q)
    short = wc <= 8

    # Short query starting with continuation → definitely follow-up
    if starts_continuation or short:
        verdict.inherits_domain = True

    # ── Priority ordering ──

    # 1. DEFENSE_SHIFT — asking about acquittal/defense
    if has_defense:
        verdict.intent = FollowUpIntent.DEFENSE_SHIFT
        verdict.detected_focus = "defense"
        verdict.inherits_domain = True
        verdict.confidence = 0.90
        verdict.signals.append("defense_markers")
        return verdict

    # 2. EVIDENCE_SHIFT
    if has_evidence:
        verdict.intent = FollowUpIntent.EVIDENCE_SHIFT
        verdict.detected_focus = "proof"
        verdict.inherits_domain = True
        verdict.confidence = 0.88
        verdict.signals.append("evidence_markers")
        return verdict

    # 3. PROCEDURAL_SHIFT
    if has_procedural:
        verdict.intent = FollowUpIntent.PROCEDURAL_SHIFT
        verdict.detected_focus = "procedure"
        verdict.inherits_domain = True
        verdict.confidence = 0.85
        verdict.signals.append("procedural_markers")
        return verdict

    # 4. REMEDY_SHIFT
    if has_remedy and short:
        verdict.intent = FollowUpIntent.REMEDY_SHIFT
        verdict.detected_focus = "punishment"
        verdict.inherits_domain = True
        verdict.confidence = 0.85
        verdict.signals.append("remedy_markers")
        return verdict

    # 5. MEDIUM_CHANGE — new medium + continuation marker
    if medium and (starts_continuation or short):
        verdict.intent = FollowUpIntent.MEDIUM_CHANGE
        verdict.detected_medium = medium
        verdict.detected_focus = "medium_specific_application"
        verdict.inherits_domain = True
        verdict.confidence = 0.88
        verdict.signals.append(f"medium:{medium}")
        return verdict

    # 6. FACT_CHANGE — "لو كان X"
    if has_fact_change and (starts_continuation or short):
        verdict.intent = FollowUpIntent.FACT_CHANGE
        verdict.detected_focus = "conditional_fact_variant"
        verdict.inherits_domain = True
        verdict.confidence = 0.80
        verdict.signals.append("fact_conditional")
        return verdict

    # 7. REPHRASE — "يعني X"
    if has_rephrase and short:
        verdict.intent = FollowUpIntent.SAME_ISSUE_REPHRASE
        verdict.inherits_domain = True
        verdict.confidence = 0.70
        verdict.signals.append("rephrase_marker")
        return verdict

    # 8. Starts with continuation + short → default SAME_ISSUE_NARROWING
    if starts_continuation and short:
        verdict.intent = FollowUpIntent.SAME_ISSUE_NARROWING
        verdict.inherits_domain = True
        verdict.confidence = 0.65
        verdict.signals.append("short_continuation")
        return verdict

    # 9. Clarification-only — very short, no markers, just punctuation or one word
    if wc <= 2 and not medium and not has_remedy:
        verdict.intent = FollowUpIntent.CLARIFICATION_ONLY
        verdict.inherits_domain = True
        verdict.confidence = 0.50
        verdict.signals.append("very_short")
        return verdict

    # 10. Default — likely new case unless prior state is strong
    verdict.intent = FollowUpIntent.NEW_CASE
    verdict.new_case_reason = "no_strong_continuation_signal"
    return verdict
