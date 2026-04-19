# -*- coding: utf-8 -*-
"""
Smart Legal Question Generator.

Every question is:
  - tied to a specific issue_id
  - derived from missing facts/evidence for that issue
  - phrased as a yes/no or short-answer question (Arabic)
  - deduplicated against session history
  - prioritized (HIGH → MEDIUM → LOW)

Max 3 questions per reply (anti-frustration).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Optional

from core.ux.missing_data import MissingDataReport, IssueGap, GapLevel


@dataclass
class LegalQuestion:
    question_id:     str
    text:            str
    issue_id:        str
    serves_gap:      str        # the specific gap this question fills
    criticality:     str        # HIGH / MEDIUM / LOW
    expected_type:   str = "yes_no"   # yes_no | short_answer | enumeration

    def to_dict(self) -> dict:
        return {
            "question_id":  self.question_id,
            "text":         self.text,
            "issue_id":     self.issue_id,
            "serves_gap":   self.serves_gap,
            "criticality":  self.criticality,
            "expected_type": self.expected_type,
        }


# ═════════════════════════════════════════════════════════════════
# Per-issue question templates
# Each key is an (domain, subdomain, issue_id) tuple.
# Value is a list of (gap_element_keyword, question_text, expected_type).
# ═════════════════════════════════════════════════════════════════

_Q_TEMPLATES: dict[tuple, list[tuple[str, str, str]]] = {
    # (domain, issue_id) → [(gap_keyword, question, type)]
    ("banking", "cheque_nature"): [
        ("اتفاق",    "هل يوجد عقد مكتوب يحدد أن الشيك للضمان فقط وليس للصرف؟",     "yes_no"),
        ("مراسلات",  "هل توجد رسائل أو واتساب تثبت أن الشيك سُلِّم كضمان؟",          "yes_no"),
        ("شهود",     "هل يوجد شهود حضور على التسليم والاتفاق بأنه ضمان؟",            "yes_no"),
    ],
    ("banking", "condition_fulfillment"): [
        ("الشرط",    "ما هو الشرط المتفق عليه قبل الصرف؟ (وصف موجز)",                "short_answer"),
        ("الأداء",   "هل تم تنفيذ الشرط قبل صرف الشيك أم بعده؟",                      "short_answer"),
    ],

    ("criminal", "offense_elements"): [
        ("العلانية", "هل حدث الفعل في مكان/وسيلة علنية يراها الغير؟",                  "yes_no"),
        ("القصد",    "هل يوجد ما يثبت أن الفعل كان بقصد الإساءة وليس عفوياً؟",        "yes_no"),
    ],
    ("criminal", "proof_requirements"): [
        ("شهود",     "هل يوجد شهود حضور على الواقعة؟ (عدد تقريبي)",                  "short_answer"),
        ("تسجيل",    "هل لديك تسجيل صوتي أو مرئي أو لقطة شاشة؟",                     "yes_no"),
    ],
    ("criminal", "medium_qualifier"): [
        ("وسيلة",    "ما هي الوسيلة التي جرى فيها الفعل؟ (عام/تويتر/واتساب/موقع)",   "short_answer"),
    ],
    ("criminal", "who_started"): [
        ("البادئ",    "من بدأ الاعتداء بالضبط؟ وهل يوجد شهود يثبتون ذلك؟",            "short_answer"),
    ],
    ("criminal", "self_defense"): [
        ("تناسب",    "هل كان ردك متناسباً مع الاعتداء الذي تعرضت له؟",                "yes_no"),
    ],

    ("civil", "defect_nature"): [
        ("تقرير",    "هل يوجد تقرير فني مستقل يصف طبيعة العيوب؟",                     "yes_no"),
        ("خبرة",    "هل طُلبت خبرة قضائية من المحكمة أم لا؟",                         "yes_no"),
    ],
    ("civil", "acceptance_refusal"): [
        ("إنذار",    "هل أُرسل إنذار خطّي للمقاول/للطرف الآخر برفض الاستلام؟",         "yes_no"),
        ("استعمال",  "هل تم استعمال المنشأ/الشيء فعلياً رغم الرفض المُعلن؟",           "yes_no"),
    ],
    ("civil", "contract_existence"): [
        ("وثيقة",    "هل يوجد عقد مكتوب موقَّع من الطرفين؟",                            "yes_no"),
        ("تنفيذ",    "هل نُفِّذ جزء من العقد فعلياً (دفع/تسليم جزئي)؟",                 "yes_no"),
    ],
    ("civil", "title_transfer"): [
        ("دفع",      "هل تم دفع كامل المبلغ للبائع مع وجود إثبات (تحويل/إيصال)؟",     "yes_no"),
        ("تسجيل",    "هل تم تسجيل العقار رسمياً باسم المشتري في السجل العقاري؟",      "yes_no"),
        ("حيازة",    "هل استلم المشتري الحيازة الفعلية للعقار؟",                        "yes_no"),
    ],

    ("commercial", "representation_nature"): [
        ("نص",       "هل العرض مكتوب ويستخدم لفظ «ضمان» أو مجرد «توقعات»؟",           "short_answer"),
        ("disclaim", "هل يتضمن العرض تحفظات (disclaimer) صريحة عن المخاطر؟",           "yes_no"),
    ],
    ("commercial", "misrepresentation"): [
        ("علم",      "هل لديك ما يثبت أن العارض كان يعلم بأن الأرقام غير ممكنة؟",     "yes_no"),
        ("بيانات",   "هل يوجد بيانات مالية حقيقية تخالف ما عُرض عليك؟",                "yes_no"),
    ],
    ("commercial", "service_nature"): [
        ("وصف",      "ما هو الوصف الدقيق للعمل المتفق عليه؟",                          "short_answer"),
        ("ساعات",    "هل تم تحديد ساعات عمل أم تسليم بنتيجة؟",                          "short_answer"),
    ],
    ("commercial", "partial_completion"): [
        ("توثيق",    "هل يوجد توثيق رسمي لما تم إنجازه (تقارير مرحلية/توقيع)؟",        "yes_no"),
    ],
    ("commercial", "agency_existence"): [
        ("تسجيل",    "هل الوكالة التجارية مسجَّلة رسمياً في السجل؟",                    "yes_no"),
    ],
    ("commercial", "termination_justification"): [
        ("سبب",      "ما هو السبب المُعلن للإنهاء؟ وهل وُجِّه إنذار مسبق؟",             "short_answer"),
    ],

    ("employment", "relationship"): [
        ("مراسلات",  "هل توجد مراسلات/إيميلات تثبت علاقة العمل؟",                      "yes_no"),
        ("راتب",     "هل توجد تحويلات راتب بنكية؟",                                      "yes_no"),
    ],
    ("employment", "termination_cause"): [
        ("إنذار",    "هل تلقيت إنذاراً خطّياً أو محضر مخالفة قبل الفصل؟",               "yes_no"),
        ("سبب",      "ما السبب المُعلن من الشركة للفصل؟",                                "short_answer"),
    ],
    ("employment", "end_of_service"): [
        ("مدة",      "ما مدة خدمتك الكاملة (سنوات وأشهر)؟",                              "short_answer"),
        ("أجر",      "ما آخر راتب شامل قبل الفصل؟",                                      "short_answer"),
    ],

    ("family", "eligibility"): [
        ("سلوك",     "هل يوجد ما يُطعن به في سلوك أحد الطرفين؟",                        "yes_no"),
        ("استقرار",  "هل البيئة المعيشية للحاضن مستقرة (سكن/دخل)؟",                     "yes_no"),
    ],
    ("family", "child_interest"): [
        ("تقرير",    "هل يوجد تقرير اجتماعي أو باحث اجتماعي أُعِدَّ للقضية؟",           "yes_no"),
    ],

    ("inheritance", "death_illness"): [
        ("مرض",      "هل كان المُورِّث مصاباً بمرض خطير وقت التصرف؟",                   "yes_no"),
        ("تقرير",    "هل يوجد تقرير طبي يثبت حالته الصحية قبل الوفاة؟",                 "yes_no"),
        ("مدة",      "كم المدة بين التصرف والوفاة؟",                                      "short_answer"),
    ],
    ("inheritance", "gift_or_bequest"): [
        ("مقابل",    "هل كان هناك مقابل مادي من الموهوب له، أم بلا مقابل؟",             "yes_no"),
        ("إجازة",    "هل وافق باقي الورثة على التصرف لاحقاً؟",                           "yes_no"),
    ],
}


# Generic fallback questions (issue-kind based)
_GENERIC_Q_BY_KIND = {
    "primary":    "هل يمكنك ذكر الواقعة الأساسية في القضية بجملة واحدة؟",
    "threshold":  "ما العنصر الأول الذي يجب إثباته في هذه القضية؟",
    "proof":      "ما الأدلة المتوفرة لديك حالياً؟",
    "defense":    "هل طُرح عليك أي دفع من الطرف الآخر؟",
    "procedural": "هل رُفعت الدعوى بالفعل أم ما زالت في مرحلة قبل التقاضي؟",
    "remedy":     "ما الذي تطلبه تحديداً من المحكمة؟",
}


def _question_id(issue_id: str, text: str) -> str:
    return hashlib.sha1(f"{issue_id}|{text}".encode("utf-8")).hexdigest()[:12]


def _questions_for_gap(gap: IssueGap, subdomain: str, domain: str
                         ) -> list[LegalQuestion]:
    """Look up template questions for a given issue gap."""
    out: list[LegalQuestion] = []
    key = (domain, gap.issue_id)
    templates = _Q_TEMPLATES.get(key, [])

    missing_combined = gap.missing_facts + gap.missing_evidence
    # Find template questions that match the gap keywords
    for (kw, text, qtype) in templates:
        matches = any(kw in m for m in missing_combined) or not missing_combined
        if matches:
            out.append(LegalQuestion(
                question_id=_question_id(gap.issue_id, text),
                text=text,
                issue_id=gap.issue_id,
                serves_gap=gap.missing_evidence[0] if gap.missing_evidence
                           else (gap.missing_facts[0] if gap.missing_facts else "gap"),
                criticality=gap.criticality.value,
                expected_type=qtype,
            ))

    # Fallback to generic-by-kind if no template matched
    if not out:
        generic = _GENERIC_Q_BY_KIND.get(gap.issue_kind)
        if generic:
            out.append(LegalQuestion(
                question_id=_question_id(gap.issue_id, generic),
                text=generic,
                issue_id=gap.issue_id,
                serves_gap="general",
                criticality=gap.criticality.value,
            ))
    return out


def generate_questions(
    report: "MissingDataReport",
    domain: str = "",
    subdomain: str = "",
    already_asked: Optional[set[str]] = None,
    max_questions: int = 3,
) -> list[LegalQuestion]:
    """Produce at most max_questions new questions, prioritized HIGH→MED→LOW,
    deduplicated against `already_asked` question_ids."""
    already_asked = already_asked or set()
    out: list[LegalQuestion] = []
    seen_question_ids: set[str] = set()

    # Iterate gaps in criticality order
    for gap in report.top_n_by_criticality(n=10):
        if len(out) >= max_questions:
            break
        candidates = _questions_for_gap(gap, subdomain, domain)
        for q in candidates:
            if len(out) >= max_questions:
                break
            if q.question_id in already_asked:
                continue
            if q.question_id in seen_question_ids:
                continue
            seen_question_ids.add(q.question_id)
            out.append(q)
    return out
