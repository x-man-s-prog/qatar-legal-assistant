# -*- coding: utf-8 -*-
"""
Issue Graph Builder — structured issue decomposition per domain.

Deterministic. Rule-based. No LLM. Every issue carries:
  - primary / secondary / threshold / proof / procedural / remedy
  - dependencies
  - what element it needs proven

Replaces flat keyword lists with a CASE-STRUCTURE graph.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class IssueKind(str, Enum):
    PRIMARY     = "primary"         # the central legal question
    SECONDARY   = "secondary"       # related but not central
    THRESHOLD   = "threshold"       # must-be-answered first
    PROOF       = "proof"           # evidence / admissibility
    PROCEDURAL  = "procedural"      # jurisdiction / filing
    REMEDY      = "remedy"          # relief sought
    DEFENSE     = "defense"         # opposition's likely argument


@dataclass
class IssueNode:
    issue_id:        str
    kind:            IssueKind
    question:        str                         # the exact legal question
    required_proof:  list[str] = field(default_factory=list)
    depends_on:      list[str] = field(default_factory=list)  # issue_ids
    conflicts_with:  list[str] = field(default_factory=list)
    domain:          str = ""
    subdomain:       str = ""

    def to_dict(self) -> dict:
        return {
            "issue_id":        self.issue_id,
            "kind":            self.kind.value,
            "question":        self.question,
            "required_proof":  self.required_proof,
            "depends_on":      self.depends_on,
            "domain":          self.domain,
            "subdomain":       self.subdomain,
        }


@dataclass
class IssueGraph:
    domain:          str = ""
    subdomain:       str = ""
    primary_issue:   Optional[str] = None   # issue_id
    nodes:           dict[str, IssueNode] = field(default_factory=dict)
    contamination_signals: list[str] = field(default_factory=list)

    def add(self, node: IssueNode) -> None:
        self.nodes[node.issue_id] = node
        if node.kind == IssueKind.PRIMARY and self.primary_issue is None:
            self.primary_issue = node.issue_id

    def by_kind(self, kind: IssueKind) -> list[IssueNode]:
        return [n for n in self.nodes.values() if n.kind == kind]

    def to_dict(self) -> dict:
        return {
            "domain":          self.domain,
            "subdomain":       self.subdomain,
            "primary_issue":   self.primary_issue,
            "issue_count":     len(self.nodes),
            "by_kind": {
                kind.value: [n.issue_id for n in self.by_kind(kind)]
                for kind in IssueKind
            },
            "nodes":           [n.to_dict() for n in self.nodes.values()],
        }


# ═════════════════════════════════════════════════════════════════
# Per-domain subdomain → issue templates
# Each entry is parameterised later — this is the SKELETON only
# ═════════════════════════════════════════════════════════════════

_TEMPLATES: dict[tuple[str, str], list[tuple[str, IssueKind, str, list[str]]]] = {
    # domain, subdomain → list of (issue_id, kind, question, required_proof)
    ("criminal", "defamation"): [
        ("offense_elements", IssueKind.PRIMARY,
         "هل توفرت أركان جريمة السب/القذف؟",
         ["ثبوت العلانية", "إسناد واقعة مشينة", "القصد الجنائي"]),
        ("proof_requirements", IssueKind.PROOF,
         "ما الأدلة المقبولة؟",
         ["شهود حضور", "تسجيل صوتي/مرئي", "لقطات شاشة موثَّقة"]),
        ("medium_qualifier", IssueKind.THRESHOLD,
         "هل الفعل جرى في وسيلة إلكترونية؟",
         ["إثبات وسيلة النشر", "رابط/صورة/تسجيل"]),
        ("remedy", IssueKind.REMEDY,
         "العقوبة المقررة والتعويض المدني المحتمل.", []),
        ("procedure", IssueKind.PROCEDURAL,
         "البلاغ للشرطة ثم النيابة.", []),
    ],
    ("criminal", "drugs"): [
        ("offense_type", IssueKind.THRESHOLD,
         "تعاطٍ أم حيازة أم اتجار؟",
         ["كمية الضبط", "ظروف القبض"]),
        ("offense_elements", IssueKind.PRIMARY,
         "أركان الجريمة المقررة.",
         ["التحليل المخبري", "تقرير الضبط"]),
        ("remedy", IssueKind.REMEDY,
         "العقوبة المقررة + ظروف التشديد/التخفيف.", []),
    ],
    ("criminal", "assault"): [
        ("offense_elements", IssueKind.PRIMARY,
         "هل توفرت أركان جريمة الاعتداء؟",
         ["الفعل المادي", "إصابة", "القصد"]),
        ("who_started", IssueKind.THRESHOLD,
         "من هو البادئ بالاعتداء؟",
         ["شهود", "تسجيل كاميرا", "تقرير طبي"]),
        ("self_defense", IssueKind.DEFENSE,
         "هل يقوم الدفاع الشرعي؟",
         ["تناسب الفعل", "انعدام البديل"]),
        ("remedy", IssueKind.REMEDY,
         "العقوبة + تعويض مدني.", []),
    ],
    ("criminal", "cyber"): [
        ("offense_elements", IssueKind.PRIMARY,
         "هل الفعل جريمة إلكترونية منصوص عليها؟",
         ["إثبات الفعل في وسيلة إلكترونية"]),
        ("privacy_violation", IssueKind.SECONDARY,
         "هل حدث اعتداء على الخصوصية؟", []),
        ("proof", IssueKind.PROOF,
         "حجية الأدلة الرقمية.",
         ["تقرير فني", "توثيق الأصل", "سلسلة العهدة"]),
    ],

    ("employment", "termination"): [
        ("relationship", IssueKind.THRESHOLD,
         "هل تثبت علاقة العمل (حتى بلا عقد مكتوب)؟",
         ["كشف رواتب", "مراسلات", "شهود زملاء"]),
        ("termination_cause", IssueKind.PRIMARY,
         "هل الفصل مبرَّر قانوناً؟",
         ["إنذار خطّي", "محضر مخالفة", "سبب فصل تأديبي"]),
        ("end_of_service", IssueKind.REMEDY,
         "مستحقات نهاية الخدمة.",
         ["مدة الخدمة", "آخر أجر"]),
        ("jurisdiction", IssueKind.PROCEDURAL,
         "لجنة فض المنازعات العمالية.", []),
    ],
    ("employment", "wages"): [
        ("amount_claimed", IssueKind.PRIMARY,
         "ما قيمة المستحقات؟",
         ["عقد/كشوف رواتب"]),
        ("delay", IssueKind.THRESHOLD,
         "مدة التأخر وسببه.", []),
    ],

    ("civil", "construction_acceptance"): [
        ("defect_nature", IssueKind.PRIMARY,
         "هل العيب جوهري أم طفيف؟",
         ["تقرير فني معتمد", "خبرة محكمة"]),
        ("acceptance_refusal", IssueKind.THRESHOLD,
         "هل رفض الاستلام مشروع؟",
         ["إنذار خطّي", "عدم الاستعمال الفعلي"]),
        ("remedy", IssueKind.REMEDY,
         "فسخ أو إصلاح أو خصم من الأجر.", []),
    ],
    ("civil", "contract_breach"): [
        ("contract_existence", IssueKind.THRESHOLD,
         "هل ثبت العقد؟",
         ["وثيقة موقعة", "مراسلات", "تنفيذ جزئي"]),
        ("breach", IssueKind.PRIMARY,
         "هل وقع الإخلال؟",
         ["مطالبة سابقة", "إنذار رسمي"]),
        ("damages", IssueKind.REMEDY,
         "قيمة الضرر وعلاقته السببية.",
         ["تقدير مستقل", "فواتير"]),
    ],
    ("civil", "real_estate"): [
        ("contract_type", IssueKind.THRESHOLD,
         "عقد ابتدائي أم رسمي؟", []),
        ("title_transfer", IssueKind.PRIMARY,
         "هل يحق للمشتري إلزام البائع بنقل الملكية؟",
         ["دفع المبلغ", "عقد موقع", "حيازة"]),
        ("registration", IssueKind.PROCEDURAL,
         "التسجيل في السجل العقاري.", []),
    ],

    ("commercial", "investment_dispute"): [
        ("representation_nature", IssueKind.THRESHOLD,
         "هل العرض ضمان أم توقع اجتهادي؟",
         ["نص العرض المكتوب", "مراسلات"]),
        ("misrepresentation", IssueKind.PRIMARY,
         "هل يشكل تدليساً أو غلطاً جوهرياً؟",
         ["بيانات داخلية تناقض العرض", "علم العارض"]),
        ("remedy", IssueKind.REMEDY,
         "بطلان / تعويض / استرداد.", []),
    ],
    ("commercial", "agency"): [
        ("agency_existence", IssueKind.THRESHOLD,
         "هل ثبتت علاقة الوكالة التجارية؟",
         ["عقد وكالة مسجل"]),
        ("termination_justification", IssueKind.PRIMARY,
         "هل الإنهاء مبرَّر؟", []),
        ("compensation", IssueKind.REMEDY,
         "التعويض عن إنهاء الوكالة.", []),
    ],
    ("commercial", "startup_contract"): [
        ("service_nature", IssueKind.THRESHOLD,
         "عقد خدمات / مقاولة / عمل حر — أي تكييف؟",
         ["وصف العمل", "الاستقلالية", "الساعات", "الأجر المتفق"]),
        ("partial_completion", IssueKind.PRIMARY,
         "ما حقوق الطرفين عند الإنجاز الجزئي؟",
         ["توثيق ما أُنجز", "قبول مرحلي"]),
        ("ip_ownership", IssueKind.SECONDARY,
         "لمن الملكية الفكرية للمُنجز؟",
         ["نص العقد", "قرينة التسليم"]),
    ],

    ("banking", "cheque_guarantee"): [
        ("cheque_nature", IssueKind.THRESHOLD,
         "هل الشيك ضمان أم أداة وفاء؟",
         ["اتفاق مكتوب", "مراسلات", "شهود تسليم"]),
        ("condition_fulfillment", IssueKind.PRIMARY,
         "هل تحقق الشرط قبل الصرف؟",
         ["إثبات الشرط", "توثيق الأداء"]),
        ("misuse", IssueKind.SECONDARY,
         "هل الصرف قبل الشرط إساءة استعمال؟", []),
        ("civil_remedy", IssueKind.REMEDY,
         "استرداد + تعويض.", []),
    ],

    ("family", "custody"): [
        ("eligibility", IssueKind.PRIMARY,
         "أهلية الحاضن.",
         ["سلوك", "استقرار", "صحة"]),
        ("child_interest", IssueKind.THRESHOLD,
         "مصلحة المحضون.",
         ["تقرير اجتماعي", "بيئة معيشية"]),
        ("visitation", IssueKind.REMEDY,
         "نظام الرؤية.", []),
    ],
    ("family", "divorce"): [
        ("grounds", IssueKind.PRIMARY,
         "سبب الطلاق/الخلع.", []),
        ("alimony", IssueKind.REMEDY,
         "النفقة المستحقة.", []),
    ],

    ("inheritance", "pre_death_transfer"): [
        ("death_illness", IssueKind.THRESHOLD,
         "هل التحويل وقع في مرض الموت؟",
         ["تقرير طبي", "شهادات", "التاريخ"]),
        ("gift_or_bequest", IssueKind.PRIMARY,
         "هبة صحيحة أم وصية تتجاوز الثلث؟",
         ["ثبوت النية", "إجازة باقي الورثة"]),
        ("challenge", IssueKind.REMEDY,
         "طعن الورثة في التصرف.", []),
    ],
}


def build_issue_graph(domain: str, subdomain: str = "",
                        query: str = "") -> IssueGraph:
    """Build an IssueGraph from domain+subdomain templates.
    If subdomain unknown, returns a minimal graph with just the primary issue.
    """
    g = IssueGraph(domain=domain, subdomain=subdomain)

    # Look up specific template
    key = (domain, subdomain)
    template = _TEMPLATES.get(key)

    # Fallback: try domain-level generic template
    if template is None and domain:
        # Pick the first available subdomain for this domain
        for (d, sd), tmpl in _TEMPLATES.items():
            if d == domain:
                template = tmpl
                g.subdomain = sd + "_generic"
                break

    if template is None:
        # Last-resort generic issue
        g.add(IssueNode(
            issue_id="primary",
            kind=IssueKind.PRIMARY,
            question=f"ما المسألة القانونية الجوهرية في هذه القضية ({domain})؟",
            domain=domain,
        ))
        return g

    for (iid, kind, q, proof) in template:
        g.add(IssueNode(
            issue_id=iid,
            kind=kind,
            question=q,
            required_proof=list(proof),
            domain=domain,
            subdomain=g.subdomain,
        ))
    return g
