# -*- coding: utf-8 -*-
"""
Guided Legal Scenario Engine
=============================
Detects vague/incomplete queries, guides users through minimal
domain-specific clarification. Deterministic, no LLM.
"""
from __future__ import annotations
import re, logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger("scenario")


# ══════════════════════════════════════════════════════════════
# Guidance Mode
# ══════════════════════════════════════════════════════════════

class GuidanceMode(str, Enum):
    NONE = "no_guidance"
    LIGHT = "light_guidance"       # 1 question, better answer possible
    REQUIRED = "required_guidance"  # answering now would be risky


# ══════════════════════════════════════════════════════════════
# Scenario Plan
# ══════════════════════════════════════════════════════════════

@dataclass
class ScenarioPlan:
    scenario_id: str = ""
    domain: str = ""
    trigger_reason: str = ""
    missing_facts: list[str] = field(default_factory=list)
    asked_questions: list[str] = field(default_factory=list)
    remaining_questions: list[dict] = field(default_factory=list)  # [{text, choices}]
    minimum_facts_required: int = 1
    safe_to_answer_now: bool = True
    guidance_mode: GuidanceMode = GuidanceMode.NONE
    notes_internal: list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════
# Guided Question Registry
# ══════════════════════════════════════════════════════════════

@dataclass
class GuidedQuestion:
    fact_key: str
    text_ar: str
    choices: list[str] = field(default_factory=list)
    priority: int = 1       # 1=high, 3=low
    required: bool = True


_DOMAIN_QUESTIONS: dict[str, list[GuidedQuestion]] = {
    "employment": [
        GuidedQuestion("termination_type", "ما نوع إنهاء العمل؟",
                        ["فصل من صاحب العمل", "استقالة", "انتهاء عقد", "غير متأكد"], 1, True),
        GuidedQuestion("service_years", "كم مدة خدمتك تقريباً؟",
                        ["أقل من سنة", "1-3 سنوات", "3-5 سنوات", "أكثر من 5 سنوات"], 2, True),
        GuidedQuestion("has_contract", "هل عندك عقد عمل مكتوب؟",
                        ["نعم", "لا", "غير متأكد"], 3, False),
    ],
    "criminal": [
        GuidedQuestion("query_type", "سؤالك يخص:",
                        ["اتهام موجه لي", "تحقيق جاري", "حكم صدر", "استفسار عام"], 1, True),
        GuidedQuestion("personal", "هل السؤال عن حالتك الشخصية أم معلومة عامة؟",
                        ["حالتي الشخصية", "معلومة عامة"], 2, True),
        GuidedQuestion("has_deadline", "هل هناك موعد قريب (جلسة / مهلة طعن)؟",
                        ["نعم", "لا", "لا أعرف"], 3, False),
    ],
    "family": [
        GuidedQuestion("issue_type", "الموضوع يخص:",
                        ["طلاق", "حضانة", "نفقة", "زيارة أطفال", "ميراث", "غير ذلك"], 1, True),
        GuidedQuestion("court_case", "هل في قضية مرفوعة في المحكمة؟",
                        ["نعم", "لا", "لا أعرف"], 2, False),
        GuidedQuestion("children", "هل يوجد أطفال؟",
                        ["نعم", "لا"], 3, False),
    ],
    "rental": [
        GuidedQuestion("issue_type", "المشكلة تخص:",
                        ["إخلاء", "إيجار متأخر", "تأمين / ضمان", "إنهاء عقد", "غير ذلك"], 1, True),
        GuidedQuestion("has_contract", "هل يوجد عقد إيجار مكتوب؟",
                        ["نعم", "لا"], 2, True),
        GuidedQuestion("notice", "هل استلمت إشعار رسمي؟",
                        ["نعم", "لا"], 3, False),
    ],
    "deadline": [
        GuidedQuestion("decision_type", "نوع القرار أو الحكم:",
                        ["حكم محكمة", "قرار إداري", "إشعار قانوني", "غير متأكد"], 1, True),
        GuidedQuestion("time_passed", "كم مضى من الوقت؟",
                        ["أقل من أسبوع", "أسبوع - شهر", "1-3 شهور", "أكثر من 3 شهور"], 2, True),
        GuidedQuestion("action_taken", "هل اتخذت أي إجراء لحد الآن؟",
                        ["نعم", "لا"], 3, False),
    ],
    "general": [
        GuidedQuestion("area", "سؤالك يخص أي مجال؟",
                        ["عمل / وظيفة", "قضية جنائية", "أحوال شخصية / عائلة", "إيجار / سكن", "غير ذلك"], 1, True),
        GuidedQuestion("urgency", "هل الموضوع عاجل؟",
                        ["نعم، عاجل", "لا، استفسار عام"], 2, False),
    ],
}


class GuidedQuestionRegistry:

    def get_questions(self, domain: str) -> list[GuidedQuestion]:
        return _DOMAIN_QUESTIONS.get(domain, _DOMAIN_QUESTIONS["general"])

    def get_required(self, domain: str) -> list[GuidedQuestion]:
        return [q for q in self.get_questions(domain) if q.required]

    def get_top_n(self, domain: str, n: int = 2) -> list[GuidedQuestion]:
        qs = sorted(self.get_questions(domain), key=lambda q: q.priority)
        return qs[:n]


# ══════════════════════════════════════════════════════════════
# Domain Detection for Scenarios
# ══════════════════════════════════════════════════════════════

_DOMAIN_SIGNALS = {
    "employment": [
        "فصل", "فصلوني", "فصلني", "تفصلني", "طردوني", "طردني",
        "استقالة", "استقلت", "استقال",
        "عقد عمل", "عقدي", "مكافأة", "إنهاء",
        "شغل", "وظيفة", "كفيل", "كفيلي", "شركة",
        "طلعوني من الدوام", "أنهو خدمتي", "حقوقي من الشركة",
        "عقدي انتهى", "استقالتي", "حقوقي",
        "إذن خروج", "نقل كفالة", "الدوام", "راتبي",
        "مديري", "العقد",
    ],
    "criminal": [
        "متهم", "تهمة", "قبض", "تحقيق", "شرطة", "نيابة",
        "محبوس", "سجن", "مخدرات", "سرقة", "ضرب",
        "متورط", "قضية", "مسكوني", "حكم علي", "اتهام",
        "حكموا", "يبتزني", "ابتزاز", "يهددني",
        "حشيش", "انمسك", "بيمسكوني", "بيحبسوه",
        "سرقوا", "وقعت على", "بصور", "تلفوني",
        "غيابي", "حكم غيابي", "جريمة",
    ],
    "family": [
        "طلاق", "حضانة", "نفقة", "زوج", "زوجتي", "زوجي",
        "طليقتي", "طليقي", "أولادي", "عدة", "خلع", "ميراث",
        "عيال", "عيالي", "زيارة",
        "ولدي", "بنتي", "أبوه", "أبوي", "أمي ",
        "تزوج ثانية", "ضربني", "طلقني",
        "أطلق", "آخذ عيالي", "أسافر بولدي",
    ],
    "rental": [
        "إيجار", "إيجاري", "مستأجر", "مالك", "المالك", "شقة",
        "إخلاء", "عقد إيجار", "ضمان",
        "يطلعني", "طردني من البيت", "العربون", "التأمين", "السكن",
        "يبي يطلعني", "رفع الإيجار", "قفل علي", "بدون عقد",
        "منعني أدخل",
    ],
    "deadline": [
        "إشعار", "إنذار", "مهلة", "طعن", "اعتراض",
        "جلسة", "قرار", "وصلني", "جاني",
        "فات الموعد", "يضيع حقي", "مدة",
        "صدر حكم", "حكم غيابي", "غيابياً",
        "ينتهي حقي", "فاتني", "لسه أقدر", "بعد سنتين",
        "تقادم", "مدة الطعن",
    ],
}


def _detect_domain(query: str) -> str:
    q = query
    for domain, signals in _DOMAIN_SIGNALS.items():
        if any(s in q for s in signals):
            return domain
    return ""


# ══════════════════════════════════════════════════════════════
# Vagueness Detection
# ══════════════════════════════════════════════════════════════

# Strong vague signals — can trigger guidance even WITHOUT a domain
_STRONG_VAGUE_SIGNALS = [
    "وش أسوي", "ايش اسوي", "شو أسوي", "ماذا أفعل", "شسوي",
    "ساعدني", "ساعدوني", "محتاج مساعدة", "ساعدني بسرعة",
    "كيف أتصرف", "شلون أتصرف", "وش الحل",
    "وش أسوي الحين", "الحين وش",
    "ندمت", "ما أدري", "ما فهمت",
    "أبي أعرف", "ابي اعرف", "أبغى أعرف",
    "وش حقي", "وش حقوقي",
]

# All vague signals (including strong ones)
_VAGUE_SIGNALS = _STRONG_VAGUE_SIGNALS + [
    "ما هي حقوقي", "ايش حقي", "أبي حقوقي", "ابي حقوقي", "ابغى حقوقي",
    "أبي", "ابغى",
    "مشكلة", "مشكلتي", "عندي مشكلة", "ورطة", "عندي قضية",
    "متورط", "جاني", "وصلني", "ما فهمت شي",
    "هل يضيع حقي", "والحين",
    "بس ما", "بس والله",
]


_SUFFICIENT_DETAIL_SIGNALS = [
    r"(شغلت|خدمة|خدمت|عملت)\s*\d+\s*سن[وةي]",  # employment duration (not age)
    r"عقد.*مكتوب",                        # written contract
    r"مادة\s*\d+",                        # article number
    r"قانون\s*رقم",                       # law number
    r"خلال\s*\d+",                        # within X
    r"راتب.*\d+",                         # salary amount
    r"درجة\s*(الأولى|الثانية|الثالثة|السابعة)",  # specific grade
    r"ما\s+عقوبة",                        # general knowledge: what is penalty
    r"(هل|ما)\s+\S+\s+جريمة",            # general knowledge: is X a crime
    r"(متأكد|قال\s*لي|سمعت)\s+[إا]ن",    # misconception patterns
    r"هل\s+أقدر\s+(أطعن|آخذ)",            # specific legal action
    r"كم\s+مد[ةه]",                       # specific duration question
]


def _is_vague(query: str) -> bool:
    q = query
    words = q.split()
    n = len(words)

    # 1. Any vague signal with generous word limit
    if n <= 14 and any(s in q for s in _VAGUE_SIGNALS):
        return True

    # 2. Short query + domain → vague (domain-dependent thresholds)
    domain = _detect_domain(q)
    if domain:
        thresh = {
            "employment": 9,
            "criminal": 9,
            "family": 6,
            "rental": 9,
            "deadline": 9,
        }
        if n <= thresh.get(domain, 7):
            return True

    return False


def _has_sufficient_detail(query: str) -> bool:
    for pattern in _SUFFICIENT_DETAIL_SIGNALS:
        if re.search(pattern, query):
            return True
    return len(query.split()) >= 15


# ══════════════════════════════════════════════════════════════
# Scenario Engine
# ══════════════════════════════════════════════════════════════

class ScenarioEngine:

    def __init__(self):
        self._registry = GuidedQuestionRegistry()

    def should_trigger(self, query: str, brain_route: str = "",
                        is_structured: bool = False) -> bool:
        if is_structured:
            return False
        if brain_route in ("greeting", "filler", "thanks", "self_info"):
            return False
        if _has_sufficient_detail(query):
            return False

        n = len(query.split())

        # Strong vague signals trigger even without domain
        if n <= 14 and any(s in query for s in _STRONG_VAGUE_SIGNALS):
            return True

        # Domain + vague → trigger
        domain = _detect_domain(query)
        if domain and _is_vague(query):
            return True

        return False

    def build_plan(self, query: str) -> ScenarioPlan:
        domain = _detect_domain(query)
        if not domain:
            domain = "general"

        is_vague = _is_vague(query)
        has_detail = _has_sufficient_detail(query)
        questions = self._registry.get_top_n(domain, 2)
        required = self._registry.get_required(domain)

        plan = ScenarioPlan(
            scenario_id=f"scenario_{domain}",
            domain=domain,
            missing_facts=[q.fact_key for q in required],
        )

        if has_detail:
            plan.guidance_mode = GuidanceMode.NONE
            plan.safe_to_answer_now = True
            return plan

        if not is_vague and not any(s in query for s in _STRONG_VAGUE_SIGNALS):
            plan.guidance_mode = GuidanceMode.NONE
            plan.safe_to_answer_now = True
            return plan

        # Determine guidance level
        if domain in ("criminal", "family", "deadline"):
            plan.guidance_mode = GuidanceMode.REQUIRED
            plan.safe_to_answer_now = False
            plan.trigger_reason = "سؤال حساس يحتاج تفاصيل"
        else:
            plan.guidance_mode = GuidanceMode.LIGHT
            plan.safe_to_answer_now = True
            plan.trigger_reason = "إجابة أدق ممكنة مع تفاصيل إضافية"

        plan.remaining_questions = [
            {"text": q.text_ar, "choices": q.choices, "fact_key": q.fact_key}
            for q in questions[:3]
        ]
        plan.minimum_facts_required = len(required)

        log.info("[SCENARIO] domain=%s mode=%s questions=%d",
                 domain, plan.guidance_mode.value, len(plan.remaining_questions))
        return plan


# ══════════════════════════════════════════════════════════════
# Choice Builder
# ══════════════════════════════════════════════════════════════

class ScenarioChoiceBuilder:

    def build_choices_text(self, choices: list[str]) -> str:
        if not choices:
            return ""
        lines = []
        for i, c in enumerate(choices, 1):
            lines.append(f"  {i}) {c}")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# Guided Response Builder
# ══════════════════════════════════════════════════════════════

_GUIDANCE_FOOTER = (
    "\n\nتنبيه: بعض المسائل القانونية لها موعد قانوني محدد. "
    "التأخير قد يؤثر على حقوقك.\n"
    "ننصحك باستشارة محامٍ مختص."
)

_CRIMINAL_EXTRA = "\nلا تدلي بأقوال بدون استشارة قانونية."


class GuidedUserResponseBuilder:

    def __init__(self):
        self._choices = ScenarioChoiceBuilder()

    def build_guidance_response(self, plan: ScenarioPlan) -> str:
        if plan.guidance_mode == GuidanceMode.NONE:
            return ""

        parts = []

        if plan.guidance_mode == GuidanceMode.REQUIRED:
            parts.append("حتى أقدر أساعدك بشكل صحيح، أحتاج أعرف بعض التفاصيل:")
        else:
            parts.append("حتى أجاوبك بشكل أدق:")

        for q in plan.remaining_questions[:3]:
            parts.append(f"\n{q['text']}")
            if q.get("choices"):
                parts.append(self._choices.build_choices_text(q["choices"]))

        if plan.guidance_mode == GuidanceMode.REQUIRED:
            parts.append("\nهذه التفاصيل ضرورية عشان ما أعطيك جواب قد يكون غير دقيق.")

        # Safety footer with caution + deadline + escalation signals
        parts.append(_GUIDANCE_FOOTER)
        if plan.domain == "criminal":
            parts.append(_CRIMINAL_EXTRA)

        return "\n".join(parts)


# ══════════════════════════════════════════════════════════════
# Integration
# ══════════════════════════════════════════════════════════════

def check_scenario_guidance(query: str, brain_route: str = "",
                             is_structured: bool = False) -> Optional[str]:
    """
    Main integration point. Returns guided question text or None.
    Runs AFTER intent detection, BEFORE answer generation.
    """
    engine = ScenarioEngine()
    if not engine.should_trigger(query, brain_route, is_structured):
        return None

    plan = engine.build_plan(query)
    if plan.guidance_mode == GuidanceMode.NONE:
        return None

    builder = GuidedUserResponseBuilder()
    response = builder.build_guidance_response(plan)

    log.info("[SCENARIO] triggered: domain=%s mode=%s",
             plan.domain, plan.guidance_mode.value)
    return response
