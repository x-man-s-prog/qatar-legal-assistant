# -*- coding: utf-8 -*-
"""
User Risk & Safety UX Layer
============================
Detects when a legally correct answer may still be risky for ordinary users.
Adds controlled caution, escalation, or deadline warnings — only when justified.
Does NOT replace legal decision or validation layers.
"""
from __future__ import annotations
import re, logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger("user_risk")


# ══════════════════════════════════════════════════════════════
# Risk Level
# ══════════════════════════════════════════════════════════════

class UserRiskLevel(str, Enum):
    LOW = "low_risk_informational"
    MODERATE = "moderate_risk_actionable"
    HIGH_CRIMINAL = "high_risk_criminal"
    HIGH_FAMILY = "high_risk_family"
    HIGH_EMPLOYMENT = "high_risk_employment"
    HIGH_DEADLINE = "high_risk_deadline_sensitive"
    HIGH_MONEY = "high_risk_money_or_rights_loss"


# ══════════════════════════════════════════════════════════════
# Risk Profile
# ══════════════════════════════════════════════════════════════

@dataclass
class UserRiskProfile:
    risk_level: UserRiskLevel = UserRiskLevel.LOW
    risk_categories: list[str] = field(default_factory=list)
    confidence_context: float = 1.0
    requires_caution: bool = False
    requires_human_escalation: bool = False
    requires_deadline_warning: bool = False
    requires_document_check: bool = False
    safe_user_mode: str = "simple_safe"
    notes_internal: list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════
# High-Risk Topic Registry
# ══════════════════════════════════════════════════════════════

_RISK_TOPICS = {
    UserRiskLevel.HIGH_CRIMINAL: [
        "مخدرات", "تعاطي", "حيازة", "اتجار", "سرقة", "قتل", "ضرب",
        "تزوير", "رشوة", "احتيال", "نصب", "ابتزاز", "تحرش", "اعتداء",
        "متهم", "تهمة", "جنائي", "جريمة", "حبس", "سجن", "إعدام",
    ],
    UserRiskLevel.HIGH_FAMILY: [
        "طلاق", "خلع", "حضانة", "نفقة", "زواج", "ميراث", "تركة",
        "وصاية", "حاضن", "محضون", "عدة", "مؤخر صداق",
    ],
    UserRiskLevel.HIGH_EMPLOYMENT: [
        "فصل", "فصل تعسفي", "إنهاء عقد", "مكافأة نهاية الخدمة",
        "تعويض الفصل", "استقالة", "إجبار على الاستقالة",
    ],
    UserRiskLevel.HIGH_DEADLINE: [
        "مدة الطعن", "مهلة", "خلال 30 يوم", "ميعاد", "تقادم",
        "قبل انقضاء", "مدة الاستئناف", "موعد", "ينتهي",
        "أطعن", "حكم ضدي", "صدر حكم",
    ],
    UserRiskLevel.HIGH_MONEY: [
        "تعويض", "غرامة", "مصادرة", "حجز", "إخلاء", "إفلاس",
        "دين", "شيك بدون رصيد", "رهن", "ضمان",
    ],
}


class HighRiskTopicRegistry:

    def detect(self, query: str, domain: str = "") -> list[UserRiskLevel]:
        q = query.lower()
        detected = []
        for level, keywords in _RISK_TOPICS.items():
            if any(kw in q for kw in keywords):
                if level not in detected:
                    detected.append(level)
        return detected


# ══════════════════════════════════════════════════════════════
# User Risk Guard
# ══════════════════════════════════════════════════════════════

_GENERAL_QUERY_PATTERNS = [
    r"^ما\s+عقوبة",
    r"^ما\s+حكم",
    r"^ما\s+هي",
    r"^كم\s+",
    r"^هل\s+\S+\s+جريمة",
    r"^هل\s+يعتبر",
]

_PERSONAL_RISK_MARKERS = [
    "ضدي", "علي", "فيني", "عندي", "حقي",
    "فصلوني", "حكموا", "طردوني", "ضربوني", "مسكوني",
    "أطعن", "أرفع", "أقدر",
    "عقدي", "قضيتي", "راتبي",
    "صدر حكم ضدي", "جاني", "وصلني",
]


def _is_general_info_query(query: str) -> bool:
    """General informational query with no personal stake."""
    has_personal = any(s in query for s in _PERSONAL_RISK_MARKERS)
    has_general_pattern = any(re.search(p, query) for p in _GENERAL_QUERY_PATTERNS)
    return has_general_pattern and not has_personal


class UserRiskGuard:

    def __init__(self):
        self._registry = HighRiskTopicRegistry()

    def build_risk_profile(self, query: str, domain: str = "",
                            confidence: float = 1.0,
                            decision_type: str = "") -> UserRiskProfile:
        detected = self._registry.detect(query, domain)
        profile = UserRiskProfile(confidence_context=confidence)

        if not detected:
            profile.risk_level = UserRiskLevel.LOW
            profile.safe_user_mode = "simple_safe"
            return profile

        # General informational queries → MODERATE (no heavy warnings)
        if _is_general_info_query(query):
            profile.risk_level = UserRiskLevel.MODERATE
            profile.risk_categories = [d.value for d in detected]
            profile.requires_caution = True
            profile.safe_user_mode = "simple_safe_caution"
            profile.notes_internal.append("general info query — lowered to moderate")
            log.info("[RISK] general info query, lowered to MODERATE")
            return profile

        # Pick highest risk
        severity_order = [
            UserRiskLevel.HIGH_CRIMINAL,
            UserRiskLevel.HIGH_FAMILY,
            UserRiskLevel.HIGH_EMPLOYMENT,
            UserRiskLevel.HIGH_DEADLINE,
            UserRiskLevel.HIGH_MONEY,
        ]
        highest = UserRiskLevel.MODERATE
        for level in severity_order:
            if level in detected:
                highest = level
                break

        profile.risk_level = highest
        profile.risk_categories = [d.value for d in detected]

        # Decision logic
        is_high = highest.value.startswith("high_risk")

        if is_high:
            profile.requires_caution = True
            profile.safe_user_mode = "simple_safe_escalate"
            profile.notes_internal.append(f"high risk detected: {highest.value}")

            if highest == UserRiskLevel.HIGH_CRIMINAL:
                profile.requires_human_escalation = True
            if highest == UserRiskLevel.HIGH_DEADLINE:
                profile.requires_deadline_warning = True
            if highest in (UserRiskLevel.HIGH_FAMILY, UserRiskLevel.HIGH_EMPLOYMENT):
                profile.requires_document_check = True

        else:
            profile.requires_caution = True
            profile.safe_user_mode = "simple_safe_caution"

        # Low confidence amplifies risk
        if confidence < 0.5 and is_high:
            profile.requires_human_escalation = True
            profile.notes_internal.append("low confidence amplifies risk")

        log.info("[RISK] level=%s categories=%s escalate=%s",
                 profile.risk_level.value, profile.risk_categories[:3],
                 profile.requires_human_escalation)
        return profile

    def should_add_caution(self, profile: UserRiskProfile) -> bool:
        return profile.requires_caution

    def should_recommend_human(self, profile: UserRiskProfile) -> bool:
        return profile.requires_human_escalation


# ══════════════════════════════════════════════════════════════
# Safe User Caution Builder
# ══════════════════════════════════════════════════════════════

class SafeUserCautionBuilder:

    def build_caution(self, profile: UserRiskProfile) -> str:
        if profile.risk_level == UserRiskLevel.LOW:
            return ""

        if profile.risk_level == UserRiskLevel.HIGH_CRIMINAL:
            return "قضايا المخدرات والجنائيات حساسة جداً. أنصحك بشدة بالتواصل مع محامٍ متخصص قبل اتخاذ أي إجراء."

        if profile.risk_level == UserRiskLevel.HIGH_FAMILY:
            return "قضايا الأسرة تعتمد بشكل كبير على تفاصيل الحالة. أنصحك بمراجعة محامٍ مختص بالأحوال الشخصية."

        if profile.risk_level == UserRiskLevel.HIGH_EMPLOYMENT:
            return "حقوقك العمالية تعتمد على تفاصيل العقد وظروف الإنهاء. احرص على الاحتفاظ بجميع المستندات."

        if profile.risk_level == UserRiskLevel.HIGH_MONEY:
            return "هذا الموضوع يتعلق بحقوق مالية. تأكد من مراجعة المستندات الأصلية قبل اتخاذ قرار."

        # MODERATE default
        return "هذه معلومات عامة. التفاصيل قد تختلف حسب حالتك."

    def build_deadline_warning(self, profile: UserRiskProfile) -> str:
        if not profile.requires_deadline_warning:
            return ""
        return "تنبيه مهم: قد تكون هناك مواعيد قانونية يجب الالتزام بها. تأخّرك قد يُفقدك حقك في الطعن أو الاعتراض."

    def build_document_note(self, profile: UserRiskProfile) -> str:
        if not profile.requires_document_check:
            return ""
        return "أنصحك بجمع جميع المستندات المتعلقة (عقود، إيصالات، مراسلات) قبل اتخاذ أي إجراء قانوني."

    def build_escalation_note(self, profile: UserRiskProfile) -> str:
        if not profile.requires_human_escalation:
            return ""
        return "هذا الموضوع يحتاج مراجعة محامٍ مختص. المعلومات هنا للتوعية فقط وليست بديلاً عن الاستشارة القانونية."

    def merge_with_answer(self, answer: str, profile: UserRiskProfile) -> str:
        if profile.risk_level == UserRiskLevel.LOW:
            return answer

        parts = [answer.rstrip()]

        caution = self.build_caution(profile)
        deadline = self.build_deadline_warning(profile)
        docs = self.build_document_note(profile)
        escalation = self.build_escalation_note(profile)

        # Add only non-empty, deduplicated notes
        notes = []
        for note in [caution, deadline, docs, escalation]:
            if note and note not in notes:
                notes.append(note)

        if notes:
            parts.append("\n".join(notes))

        return "\n\n".join(parts)


# ══════════════════════════════════════════════════════════════
# Integration Function
# ══════════════════════════════════════════════════════════════

def apply_user_risk_layer(answer: str, query: str, domain: str = "",
                           confidence: float = 1.0,
                           decision_type: str = "") -> tuple[str, UserRiskProfile]:
    """
    Main integration point.
    Runs AFTER simplification, BEFORE final output.
    Returns (possibly_modified_answer, risk_profile).
    """
    guard = UserRiskGuard()
    profile = guard.build_risk_profile(query, domain, confidence, decision_type)

    if not guard.should_add_caution(profile):
        return answer, profile

    builder = SafeUserCautionBuilder()
    result = builder.merge_with_answer(answer, profile)

    log.info("[RISK_UX] applied caution: level=%s escalate=%s",
             profile.risk_level.value, profile.requires_human_escalation)
    return result, profile
