# -*- coding: utf-8 -*-
"""
Plain-Arabic Explanation Engine
================================
Converts legally safe answers into highly readable user-facing explanations.
Works AFTER simplification + risk + guidance. Before final output.
Does NOT add unsupported content. Does NOT hide limitations.
"""
from __future__ import annotations
import re, logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("explanation")


# ══════════════════════════════════════════════════════════════
# Explanation Result
# ══════════════════════════════════════════════════════════════

@dataclass
class ExplanationResult:
    short_answer: str = ""
    simple_explanation: str = ""
    when_it_may_change: str = ""
    what_to_check: str = ""
    what_to_do_next: str = ""
    important_note: str = ""
    original: str = ""


# ══════════════════════════════════════════════════════════════
# Explanation Templates
# ══════════════════════════════════════════════════════════════

@dataclass
class ExplanationTemplate:
    allowed: list[str] = field(default_factory=list)
    required: list[str] = field(default_factory=list)
    max_sections: int = 4
    wording_style: str = "direct"  # "direct" | "cautious" | "empathetic"


_TEMPLATES = {
    "direct": ExplanationTemplate(
        allowed=["short_answer", "simple_explanation", "what_to_do_next"],
        required=["short_answer"], max_sections=3, wording_style="direct"),
    "qualified": ExplanationTemplate(
        allowed=["short_answer", "simple_explanation", "when_it_may_change", "important_note"],
        required=["short_answer", "when_it_may_change"], max_sections=4, wording_style="cautious"),
    "limitation": ExplanationTemplate(
        allowed=["short_answer", "simple_explanation", "important_note", "what_to_check"],
        required=["short_answer", "important_note"], max_sections=3, wording_style="cautious"),
    "refusal": ExplanationTemplate(
        allowed=["short_answer", "simple_explanation", "what_to_do_next"],
        required=["short_answer", "what_to_do_next"], max_sections=3, wording_style="empathetic"),
    "guided": ExplanationTemplate(
        allowed=["short_answer", "simple_explanation"],
        required=["short_answer"], max_sections=2, wording_style="direct"),
    "high_risk": ExplanationTemplate(
        allowed=["short_answer", "simple_explanation", "important_note", "what_to_do_next", "what_to_check"],
        required=["short_answer", "important_note", "what_to_do_next"], max_sections=5, wording_style="empathetic"),
}


class ExplanationTemplateRegistry:
    def get(self, answer_type: str) -> ExplanationTemplate:
        return _TEMPLATES.get(answer_type, _TEMPLATES["direct"])


# ══════════════════════════════════════════════════════════════
# Readability Policy
# ══════════════════════════════════════════════════════════════

class UserReadabilityPolicy:

    def split_dense(self, text: str) -> str:
        """Break sentences > 80 chars at natural Arabic break points."""
        result = []
        for line in text.split("\n"):
            if len(line) > 80:
                parts = re.split(r"(،\s+|؛\s+|\.\s+)", line)
                current = ""
                for p in parts:
                    if len(current + p) > 80 and current:
                        result.append(current.strip())
                        current = p
                    else:
                        current += p
                if current.strip():
                    result.append(current.strip())
            else:
                result.append(line)
        return "\n".join(result)

    def remove_redundancy(self, text: str) -> str:
        """Remove repeated sentences or near-identical lines."""
        lines = text.split("\n")
        seen = set()
        cleaned = []
        for line in lines:
            normalized = line.strip().lower()[:50]
            if normalized and normalized in seen:
                continue
            if normalized:
                seen.add(normalized)
            cleaned.append(line)
        return "\n".join(cleaned)

    def improve_flow(self, text: str) -> str:
        text = self.split_dense(text)
        text = self.remove_redundancy(text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


# ══════════════════════════════════════════════════════════════
# Safe Next Step Builder
# ══════════════════════════════════════════════════════════════

_DOMAIN_NEXT_STEPS = {
    "salary": "تأكد من مسمّاك الوظيفي ودرجتك من إدارة الموارد البشرية في جهتك.",
    "employment": "احتفظ بنسخة من عقد العمل وأي مراسلات رسمية بينك وبين صاحب العمل.",
    "criminal": "لا تدلي بأي أقوال دون حضور محامٍ. هذا حقك القانوني.",
    "family": "اجمع المستندات المتعلقة (عقد الزواج، شهادات الميلاد، أحكام سابقة).",
    "rental": "تأكد من وجود عقد الإيجار المكتوب وأي إشعارات رسمية استلمتها.",
    "deadline": "تحقق من التاريخ الدقيق — التأخير قد يُسقط حقك في الطعن أو الاعتراض.",
}


class SafeNextStepBuilder:

    def build(self, domain: str = "", has_deadline: bool = False) -> str:
        if has_deadline:
            return _DOMAIN_NEXT_STEPS.get("deadline", "")
        return _DOMAIN_NEXT_STEPS.get(domain, "")


# ══════════════════════════════════════════════════════════════
# Difference Explainer
# ══════════════════════════════════════════════════════════════

_KNOWN_DISTINCTIONS = {
    "salary_vs_allowances": (
        "الراتب الأساسي (المربوط) هو المبلغ المحدد في الجدول لكل درجة.",
        "الإجمالي يشمل الأساسي + البدلات (سكن، نقل، اجتماعية) ويختلف حسب الجهة."
    ),
    "general_vs_personal": (
        "المعلومات العامة مبنية على نصوص القانون كما هي.",
        "حالتك الشخصية قد تختلف بسبب تفاصيل العقد أو ظروف القضية."
    ),
    "possible_vs_certain": (
        "الحق المحتمل يعتمد على ظروف وتفاصيل قد تغيّر النتيجة.",
        "الحق المؤكد ثابت بنص القانون بغض النظر عن التفاصيل."
    ),
    "penalty_vs_sentence": (
        "العقوبة المذكورة في القانون هي الحد الأقصى أو النطاق العام.",
        "الحكم النهائي في قضيتك يحدده القاضي حسب الظروف."
    ),
}


class DifferenceExplainer:

    def detect_need(self, answer: str, domain: str = "") -> Optional[str]:
        a = answer.lower()
        if domain == "salary" and ("المربوط" in a or "بدل" in a):
            return "salary_vs_allowances"
        if "حالت" in a or "شخصي" in a or "عام" in a:
            return "general_vs_personal"
        if "عقوبة" in a and ("حكم" in a or "محكمة" in a):
            return "penalty_vs_sentence"
        if "محتمل" in a or "قد" in a or "يعتمد" in a:
            return "possible_vs_certain"
        return None

    def explain(self, distinction_key: str) -> str:
        pair = _KNOWN_DISTINCTIONS.get(distinction_key)
        if not pair:
            return ""
        return f"• {pair[0]}\n• {pair[1]}"


# ══════════════════════════════════════════════════════════════
# Main Explanation Engine
# ══════════════════════════════════════════════════════════════

class PlainArabicExplanationEngine:

    def __init__(self):
        self._templates = ExplanationTemplateRegistry()
        self._readability = UserReadabilityPolicy()
        self._next_steps = SafeNextStepBuilder()
        self._differences = DifferenceExplainer()

    def build_explanation(self, answer: str, answer_type: str = "direct",
                          domain: str = "", has_risk: bool = False,
                          has_deadline: bool = False,
                          limitations: list[str] = None) -> ExplanationResult:
        template = self._templates.get(answer_type)
        r = ExplanationResult(original=answer)

        # Short answer: first meaningful sentence
        r.short_answer = self._extract_short(answer)

        # Simple explanation: the full answer, improved for readability
        if "simple_explanation" in template.allowed:
            r.simple_explanation = self._readability.improve_flow(answer)

        # When it may change
        if "when_it_may_change" in template.allowed and answer_type in ("qualified", "limitation"):
            r.when_it_may_change = "هذه المعلومات قد تتغير حسب تفاصيل حالتك أو تحديثات القانون."

        # What to check
        if "what_to_check" in template.allowed:
            distinction = self._differences.detect_need(answer, domain)
            if distinction:
                r.what_to_check = self._differences.explain(distinction)

        # Next step
        if "what_to_do_next" in template.allowed:
            step = self._next_steps.build(domain, has_deadline)
            if step:
                r.what_to_do_next = step

        # Important note
        if "important_note" in template.allowed:
            if has_risk:
                r.important_note = "هذا الموضوع حساس. المعلومات هنا للتوعية — ليست بديلاً عن استشارة قانونية."
            elif limitations:
                r.important_note = " | ".join(limitations[:2])

        return r

    def compose_final(self, explanation: ExplanationResult) -> str:
        parts = []

        if explanation.short_answer:
            parts.append(explanation.short_answer)

        if explanation.simple_explanation and explanation.simple_explanation != explanation.short_answer:
            # Only add if it provides more than the short answer
            if len(explanation.simple_explanation) > len(explanation.short_answer) + 20:
                parts.append(explanation.simple_explanation)

        if explanation.what_to_check:
            parts.append(explanation.what_to_check)

        if explanation.when_it_may_change:
            parts.append(explanation.when_it_may_change)

        if explanation.what_to_do_next:
            parts.append(explanation.what_to_do_next)

        if explanation.important_note:
            parts.append(explanation.important_note)

        # Deduplicate and clean
        result = "\n\n".join(parts)
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result.strip()

    def _extract_short(self, text: str) -> str:
        for sep in [".", "،", "\n"]:
            idx = text.find(sep)
            if 10 < idx < 100:
                return text[:idx].strip()
        return text[:80].strip()


# ══════════════════════════════════════════════════════════════
# Integration
# ══════════════════════════════════════════════════════════════

def build_user_explanation(answer: str, answer_type: str = "direct",
                            domain: str = "", has_risk: bool = False,
                            has_deadline: bool = False,
                            limitations: list[str] = None) -> str:
    """
    Main integration point. Takes any legally safe answer
    and returns a well-structured user explanation.
    """
    engine = PlainArabicExplanationEngine()
    explanation = engine.build_explanation(
        answer, answer_type, domain, has_risk, has_deadline, limitations)
    result = engine.compose_final(explanation)
    log.info("[EXPLAIN] type=%s domain=%s sections=%d",
             answer_type, domain, sum(1 for x in [
                 explanation.short_answer, explanation.simple_explanation,
                 explanation.what_to_check, explanation.when_it_may_change,
                 explanation.what_to_do_next, explanation.important_note] if x))
    return result
