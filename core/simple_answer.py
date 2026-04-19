# -*- coding: utf-8 -*-
"""
Simple Answer Adapter — User-Friendly Legal Response Layer
==========================================================
Transforms legally-safe answers into simpler Arabic for ordinary users.
Runs AFTER validation/decision/explainability. Does NOT weaken safety.
"""
from __future__ import annotations
import re, logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger("simple_answer")


# ══════════════════════════════════════════════════════════════
# Response Mode
# ══════════════════════════════════════════════════════════════

class SimpleResponseMode(str, Enum):
    MINIMAL = "simple_minimal"       # أقصر إجابة ممكنة
    STANDARD = "simple_standard"     # إجابة + شرح بسيط
    CAUTIOUS = "simple_cautious"     # إجابة + شرح + تحذير أقوى


# ══════════════════════════════════════════════════════════════
# Protected Legal Terms
# ══════════════════════════════════════════════════════════════

_PROTECTED_TERMS = {
    "مكافأة نهاية الخدمة": "مبلغ يحصل عليه الموظف عند انتهاء عمله",
    "المربوط": "الراتب الأساسي المحدد للدرجة",
    "بداية المربوط": "أقل راتب أساسي للدرجة",
    "نهاية المربوط": "أعلى راتب أساسي للدرجة",
    "البدلات": "مبالغ إضافية تُضاف على الراتب الأساسي مثل بدل السكن والنقل",
    "العلاوة الدورية": "زيادة سنوية تُضاف على الراتب",
    "الفصل التعسفي": "إنهاء عقد العمل بدون سبب قانوني مشروع",
    "الاختصاص": "الجهة المسؤولة قانونياً عن النظر في القضية",
    "التقادم": "انتهاء المدة القانونية لرفع الدعوى",
    "الحيازة": "وجود المادة في حوزة الشخص",
    "الاتجار": "بيع أو توزيع المواد المخدرة",
    "التعاطي": "استعمال المواد المخدرة شخصياً",
    "الإعدام": "أقسى عقوبة — إنهاء حياة المحكوم عليه",
    "السجن المؤبد": "السجن مدى الحياة",
    "اللائحة التنفيذية": "القواعد التفصيلية التي تشرح كيف يُطبّق القانون",
}


class ProtectedLegalTerms:

    def preserve_or_explain(self, text: str, mode: SimpleResponseMode) -> str:
        if mode == SimpleResponseMode.MINIMAL:
            return text  # Don't add explanations in minimal mode
        result = text
        for term, explanation in _PROTECTED_TERMS.items():
            if term in result:
                # Add parenthetical explanation on first occurrence only
                marker = f"{term} ({explanation})"
                if marker not in result:
                    result = result.replace(term, marker, 1)
        return result

    def detect_jargon(self, text: str) -> list[str]:
        found = []
        for term in _PROTECTED_TERMS:
            if term in text:
                found.append(term)
        return found


# ══════════════════════════════════════════════════════════════
# Plain Arabic Policy
# ══════════════════════════════════════════════════════════════

_SIMPLIFICATIONS = [
    ("وفقاً للنص القانوني", "بحسب القانون"),
    ("وفقاً للنصوص المتاحة", "حسب المعلومات المتوفرة"),
    ("بناءً على النصوص القانونية", "حسب القانون"),
    ("لا يمكن الجزم", "لا أقدر أقول بشكل مؤكد"),
    ("يخضع لسلطة تقديرية", "يعتمد على تقدير الجهة المختصة"),
    ("المصادر المتوفرة", "المعلومات اللي عندي"),
    ("استناداً إلى", "بناءً على"),
    ("بصرف النظر عن", "بغض النظر عن"),
    ("يترتب على ذلك", "معناه إن"),
    ("فيما يخص", "بخصوص"),
    ("ينص القانون على", "القانون يقول إن"),
    ("تنص المادة", "المادة تقول"),
    ("الضابط القانوني", "الشرط الأساسي"),
    ("ملاحظة:", "شيء مهم:"),
]


class PlainArabicPolicy:

    def simplify_phrase(self, text: str) -> str:
        result = text
        for formal, simple in _SIMPLIFICATIONS:
            result = result.replace(formal, simple)
        return result

    def simplify_paragraph(self, text: str) -> str:
        result = self.simplify_phrase(text)
        # Break very long sentences
        sentences = re.split(r'([.،؛])', result)
        cleaned = []
        for s in sentences:
            if len(s) > 120:
                # Try to break at "و" or "أو"
                parts = re.split(r'(\s+و\s+|\s+أو\s+)', s)
                cleaned.extend(parts)
            else:
                cleaned.append(s)
        return "".join(cleaned)

    def detect_legal_jargon(self, text: str) -> list[str]:
        jargon = []
        patterns = [
            r"بموجب\s+(?:القانون|المادة)",
            r"اللائحة\s+التنفيذية",
            r"سلطة\s+تقديرية",
            r"الأهلية\s+القانونية",
            r"حجية\s+الأمر\s+المقضي",
        ]
        for p in patterns:
            if re.search(p, text):
                jargon.append(re.search(p, text).group())
        return jargon


# ══════════════════════════════════════════════════════════════
# Simple Answer Adapter
# ══════════════════════════════════════════════════════════════

@dataclass
class SimpleResponse:
    answer_short: str = ""
    answer_simple: str = ""
    what_this_means: str = ""
    important_note: str = ""
    limitation_note: str = ""
    original_answer: str = ""


class SimpleAnswerAdapter:

    def __init__(self):
        self._policy = PlainArabicPolicy()
        self._terms = ProtectedLegalTerms()

    def build_simple_response(self, answer: str, decision_type: str = "",
                               mode: SimpleResponseMode = SimpleResponseMode.STANDARD,
                               limitations: list[str] = None) -> SimpleResponse:
        if decision_type == "refusal_insufficient_evidence":
            return self._adapt_refusal(answer, mode)
        if decision_type == "limitation_response":
            return self._adapt_limitation(answer, mode, limitations or [])
        if decision_type == "qualified_legal_answer":
            return self._adapt_qualified(answer, mode)
        return self._adapt_direct(answer, mode)

    def _adapt_direct(self, answer: str, mode: SimpleResponseMode) -> SimpleResponse:
        simplified = self._policy.simplify_paragraph(answer)
        simplified = self._terms.preserve_or_explain(simplified, mode)

        short = self._extract_first_sentence(simplified)

        r = SimpleResponse(
            answer_short=short,
            answer_simple=simplified,
            original_answer=answer,
        )

        if mode in (SimpleResponseMode.STANDARD, SimpleResponseMode.CAUTIOUS):
            r.what_this_means = self._generate_meaning(answer)

        if mode == SimpleResponseMode.CAUTIOUS:
            r.important_note = "هذه معلومات عامة مبنية على القانون القطري. كل حالة تختلف حسب ظروفها."

        return r

    def _adapt_qualified(self, answer: str, mode: SimpleResponseMode) -> SimpleResponse:
        simplified = self._policy.simplify_paragraph(answer)
        simplified = self._terms.preserve_or_explain(simplified, mode)
        short = self._extract_first_sentence(simplified)

        r = SimpleResponse(
            answer_short=short,
            answer_simple=simplified,
            original_answer=answer,
            important_note="هذه المعلومات مبنية على النصوص المتوفرة وقد تختلف حسب تفاصيل الحالة.",
        )

        if mode == SimpleResponseMode.CAUTIOUS:
            r.limitation_note = "أنصحك بمراجعة محامٍ مختص للحصول على استشارة دقيقة تناسب حالتك."

        return r

    def _adapt_limitation(self, answer: str, mode: SimpleResponseMode,
                          limitations: list[str]) -> SimpleResponse:
        simplified = self._policy.simplify_paragraph(answer)
        short = self._extract_first_sentence(simplified)

        limit_text = ""
        if limitations:
            limit_text = "شيء مهم: " + " | ".join(limitations[:2])

        return SimpleResponse(
            answer_short=short,
            answer_simple=simplified,
            original_answer=answer,
            limitation_note=limit_text or "بعض المعلومات قد لا تكون متوفرة بالكامل.",
        )

    def _adapt_refusal(self, answer: str, mode: SimpleResponseMode) -> SimpleResponse:
        simple_refusal = (
            "للأسف ما أقدر أجاوب على هذا السؤال بشكل مؤكد من المعلومات اللي عندي. "
            "أنصحك تراجع بوابة الميزان (almeezan.qa) أو تستشير محامي."
        )
        return SimpleResponse(
            answer_short="ما أقدر أجاوب بشكل مؤكد على هذا السؤال.",
            answer_simple=simple_refusal,
            original_answer=answer,
            important_note="هذا لا يعني إن ما في إجابة — بس المعلومات اللي عندي ما تكفي.",
        )

    def _extract_first_sentence(self, text: str) -> str:
        for sep in [".", "،", "\n"]:
            idx = text.find(sep)
            if 10 < idx < 100:
                return text[:idx].strip()
        return text[:80].strip()

    def _generate_meaning(self, answer: str) -> str:
        a = answer.lower()
        if "المربوط" in a or "راتب" in a:
            return "هذا المبلغ هو الراتب الأساسي فقط — الإجمالي مع البدلات يكون أكثر."
        if "مخدرات" in a or "عقوبة" in a:
            return "القانون القطري صارم جداً مع قضايا المخدرات."
        if "سرقة" in a or "حبس" in a:
            return "العقوبة تعتمد على ظروف القضية وتقدير المحكمة."
        return ""


# ══════════════════════════════════════════════════════════════
# Integration: apply after validation, before final output
# ══════════════════════════════════════════════════════════════

def simplify_for_user(answer: str, decision_type: str = "",
                       mode: SimpleResponseMode = SimpleResponseMode.STANDARD,
                       limitations: list[str] = None) -> str:
    """
    Main integration point. Takes a validated legal answer
    and returns user-friendly simplified version.
    """
    adapter = SimpleAnswerAdapter()
    response = adapter.build_simple_response(answer, decision_type, mode, limitations)

    # Build final text from SimpleResponse
    parts = []
    if response.answer_simple:
        parts.append(response.answer_simple)
    if response.what_this_means:
        parts.append(response.what_this_means)
    if response.important_note:
        parts.append(response.important_note)
    if response.limitation_note:
        parts.append(response.limitation_note)

    result = "\n\n".join(parts)
    log.info("[SIMPLE] mode=%s len=%d→%d", mode.value, len(answer), len(result))
    return result
