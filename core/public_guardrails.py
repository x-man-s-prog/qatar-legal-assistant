# -*- coding: utf-8 -*-
"""
Public Release Guardrails — Final public-user protection layer.
Runs AFTER all other user layers, BEFORE final public response.
Hardens, escalates, or falls back when public safety requires it.
Does NOT replace validation, risk, or decision layers.
"""
from __future__ import annotations
import re, logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("public_guard")


# ══════════════════════════════════════════════════════════════
# Guardrail Result
# ══════════════════════════════════════════════════════════════

@dataclass
class PublicGuardrailResult:
    approved: bool = True
    hardening_applied: bool = False
    escalation_applied: bool = False
    fallback_applied: bool = False
    public_risk_summary: str = ""
    underwarning_detected: bool = False
    urgency_note_added: bool = False
    qualification_strengthened: bool = False
    output_mode: str = "pass"  # pass | harden | escalate | fallback
    notes_internal: list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════
# Deadline Safety Hardener
# ══════════════════════════════════════════════════════════════

_DEADLINE_SIGNALS = [
    "طعن", "استئناف", "مهلة", "ميعاد", "تقادم", "خلال",
    "مدة الطعن", "قبل انقضاء", "فترة", "موعد", "إشعار",
    "30 يوم", "60 يوم", "انتهاء المدة", "ينتهي",
]

_DEADLINE_PUBLIC_NOTE = (
    "تنبيه مهم: هذه المسألة قد تكون مرتبطة بموعد قانوني. "
    "تأكد من التاريخ والمستندات فوراً — التأخير قد يؤثر على حقك."
)


class DeadlineSafetyHardener:

    def detect_deadline(self, answer: str, query: str = "") -> bool:
        combined = (answer + " " + query).lower()
        return sum(1 for s in _DEADLINE_SIGNALS if s in combined) >= 1

    def needs_stronger_warning(self, answer: str) -> bool:
        has_deadline_context = self.detect_deadline(answer)
        has_warning = any(w in answer for w in ["تنبيه", "فوراً", "تأكد من التاريخ", "التأخير"])
        return has_deadline_context and not has_warning

    def apply(self, answer: str, query: str = "") -> tuple[str, bool]:
        if not self.detect_deadline(answer, query):
            return answer, False
        if not self.needs_stronger_warning(answer):
            return answer, False
        return answer.rstrip() + "\n\n" + _DEADLINE_PUBLIC_NOTE, True


# ══════════════════════════════════════════════════════════════
# Personal Action Sensitivity Detector
# ══════════════════════════════════════════════════════════════

_PERSONAL_SIGNALS = [
    "أنا", "أنا متهم", "تم فصلي", "فصلوني", "طردوني",
    "جاني حكم", "وصلني إشعار", "رفعت دعوى",
    "ماذا أفعل", "وش أسوي", "ايش اسوي",
]
_ACTION_SIGNALS = [
    "هل أرفع", "هل أستطيع الطعن", "هل يضيع حقي",
    "كيف أرفع", "أبي أرفع", "هل أقدر",
]
_IRREVERSIBLE_SIGNALS = [
    "يضيع حقي", "فات الموعد", "انتهت المدة",
    "ضاع حقي", "خسرت", "صدر حكم نهائي",
]


class PersonalActionSensitivityDetector:

    def detect_personal(self, query: str) -> bool:
        q = query.lower()
        return any(s in q for s in _PERSONAL_SIGNALS)

    def detect_action_request(self, query: str) -> bool:
        q = query.lower()
        return any(s in q for s in _ACTION_SIGNALS)

    def detect_irreversible_risk(self, query: str) -> bool:
        q = query.lower()
        return any(s in q for s in _IRREVERSIBLE_SIGNALS)

    def build_profile(self, query: str) -> dict:
        return {
            "is_personal": self.detect_personal(query),
            "requests_action": self.detect_action_request(query),
            "has_irreversible_risk": self.detect_irreversible_risk(query),
        }


# ══════════════════════════════════════════════════════════════
# Public Hardening Policy
# ══════════════════════════════════════════════════════════════

_ESCALATION_NOTE = "هذا الموضوع يحتاج مراجعة محامٍ مختص. المعلومات هنا للتوعية فقط."
_SAFE_FALLBACK = (
    "هذا السؤال يحتاج تفاصيل أكثر أو مراجعة متخصصة. "
    "أنصحك بمراجعة بوابة الميزان (almeezan.qa) أو التواصل مع محامٍ."
)

_PUBLIC_CAUTION_WEAK = "هذه معلومات عامة وقد تختلف حسب تفاصيل حالتك."
_PUBLIC_CAUTION_STRONG = "هذا الموضوع حساس. أنصحك بمراجعة محامٍ قبل اتخاذ أي إجراء."

_CAUTION_KEYWORDS = ["محامٍ", "محامي", "استشارة", "تنبيه", "مهم", "حساس"]
_UNDERWARNING_HIGH_DOMAINS = ["criminal", "family", "deadline"]


class PublicHardeningPolicy:

    def should_strengthen_caution(self, answer: str, risk_level: str,
                                   is_personal: bool) -> bool:
        if not risk_level.startswith("high"):
            return False
        has_caution = any(w in answer for w in _CAUTION_KEYWORDS)
        return not has_caution

    def should_force_escalation(self, risk_level: str, is_personal: bool,
                                 requests_action: bool, confidence: float) -> bool:
        if risk_level.startswith("high") and is_personal and requests_action:
            return True
        if risk_level.startswith("high") and confidence < 0.5:
            return True
        return False

    def should_force_fallback(self, risk_level: str, confidence: float,
                                has_irreversible: bool) -> bool:
        if has_irreversible and confidence < 0.4:
            return True
        return False


# ══════════════════════════════════════════════════════════════
# Public Guardrail Engine
# ══════════════════════════════════════════════════════════════

class PublicGuardrailEngine:

    def __init__(self):
        self._deadline = DeadlineSafetyHardener()
        self._personal = PersonalActionSensitivityDetector()
        self._policy = PublicHardeningPolicy()
        self._metrics = _GuardrailMetrics()

    def review(self, answer: str, query: str = "",
               risk_level: str = "low", confidence: float = 1.0,
               domain: str = "", is_public: bool = True) -> tuple[str, PublicGuardrailResult]:

        result = PublicGuardrailResult()

        if not is_public:
            result.output_mode = "pass"
            return answer, result

        profile = self._personal.build_profile(query)
        is_personal = profile["is_personal"]
        requests_action = profile["requests_action"]
        has_irreversible = profile["has_irreversible_risk"]

        # 1. Deadline hardening
        hardened_answer, deadline_applied = self._deadline.apply(answer, query)
        if deadline_applied:
            result.urgency_note_added = True
            result.hardening_applied = True
            self._metrics.deadline_hardenings += 1

        # 2. Underwarning check for high-risk personal cases
        if self._policy.should_strengthen_caution(hardened_answer, risk_level, is_personal):
            if domain in ("criminal", "family"):
                hardened_answer = hardened_answer.rstrip() + "\n\n" + _PUBLIC_CAUTION_STRONG
            else:
                hardened_answer = hardened_answer.rstrip() + "\n\n" + _PUBLIC_CAUTION_WEAK
            result.underwarning_detected = True
            result.qualification_strengthened = True
            result.hardening_applied = True
            self._metrics.underwarning_corrections += 1

        # 3. Escalation check
        if self._policy.should_force_escalation(risk_level, is_personal,
                                                  requests_action, confidence):
            if _ESCALATION_NOTE not in hardened_answer:
                hardened_answer = hardened_answer.rstrip() + "\n\n" + _ESCALATION_NOTE
            result.escalation_applied = True
            result.hardening_applied = True
            self._metrics.escalations += 1

        # 4. Fallback check
        if self._policy.should_force_fallback(risk_level, confidence, has_irreversible):
            hardened_answer = _SAFE_FALLBACK
            result.fallback_applied = True
            result.output_mode = "fallback"
            self._metrics.fallbacks += 1

        # Set final mode
        if not result.fallback_applied:
            if result.hardening_applied:
                result.output_mode = "harden"
            else:
                result.output_mode = "pass"

        result.approved = True
        result.public_risk_summary = (
            f"personal={is_personal} action={requests_action} "
            f"irreversible={has_irreversible} risk={risk_level}")

        self._metrics.total += 1
        if result.hardening_applied:
            self._metrics.hardenings += 1
        if is_personal and risk_level.startswith("high"):
            self._metrics.action_sensitive += 1

        log.info("[PUBLIC_GUARD] mode=%s hardened=%s escalated=%s",
                 result.output_mode, result.hardening_applied, result.escalation_applied)
        return hardened_answer, result

    def get_metrics(self) -> dict:
        return self._metrics.snapshot()


class _GuardrailMetrics:
    def __init__(self):
        self.total = 0
        self.hardenings = 0
        self.deadline_hardenings = 0
        self.escalations = 0
        self.fallbacks = 0
        self.underwarning_corrections = 0
        self.action_sensitive = 0

    def snapshot(self) -> dict:
        t = max(self.total, 1)
        return {
            "total": self.total,
            "hardening_rate": round(self.hardenings / t * 100, 1),
            "deadline_hardening_rate": round(self.deadline_hardenings / t * 100, 1),
            "escalation_rate": round(self.escalations / t * 100, 1),
            "fallback_rate": round(self.fallbacks / t * 100, 1),
            "underwarning_corrections": self.underwarning_corrections,
            "action_sensitive_cases": self.action_sensitive,
        }


# ══════════════════════════════════════════════════════════════
# Integration
# ══════════════════════════════════════════════════════════════

_engine: Optional[PublicGuardrailEngine] = None

def get_public_engine() -> PublicGuardrailEngine:
    global _engine
    if _engine is None:
        _engine = PublicGuardrailEngine()
    return _engine

def apply_public_guardrails(answer: str, query: str = "",
                             risk_level: str = "low", confidence: float = 1.0,
                             domain: str = "", is_public: bool = True) -> tuple[str, PublicGuardrailResult]:
    return get_public_engine().review(answer, query, risk_level, confidence, domain, is_public)
