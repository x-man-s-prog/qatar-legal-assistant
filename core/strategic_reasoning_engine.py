# -*- coding: utf-8 -*-
"""
Strategic Legal Reasoning Engine
==================================
Operates AFTER fail-closed gates approve.
Reads from EvidenceLedger + BurdenMap + FactPattern + LegalDecisionRecord.
Produces structured strategic analysis (internal) + natural Arabic output (user-facing).

Hard rules:
  - Operates ONLY on already-verified inputs (post fail-closed)
  - NO citation invention
  - NO new evidence
  - NO certain verdict prediction — only conditional ("IF X THEN Y") reasoning
  - NO LLM in the reasoning path
  - Internal structure (claim graph, defense graph, opponent model) is INTERNAL
  - User-facing output reads like senior-lawyer analysis, not technical breakdown
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from core.legal_gates import (
    LegalDomain, FactPattern, BurdenMap, EvidenceLedger,
    EvidenceEntry, EvidenceType,
)

log = logging.getLogger("strategic_reasoning")


# ══════════════════════════════════════════════════════════════
# Core taxonomies
# ══════════════════════════════════════════════════════════════

class CaseStrength(str, Enum):
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    INCOMPLETE = "incomplete"


class DefenseType(str, Enum):
    FORMAL = "formal"          # دفع شكلي
    SUBSTANTIVE = "substantive"  # دفع موضوعي
    PROCEDURAL = "procedural"   # دفع إجرائي


class EvidenceQuality(str, Enum):
    DIRECT = "direct"
    CORROBORATIVE = "corroborative"
    WEAK = "weak"
    CONTRADICTORY = "contradictory"
    MISSING_CRITICAL = "missing_critical"


class PartyRole(str, Enum):
    USER = "user"
    OPPONENT = "opponent"


# ══════════════════════════════════════════════════════════════
# Internal dataclasses (NOT exposed to user)
# ══════════════════════════════════════════════════════════════

@dataclass
class Claim:
    """A single legal claim within the dispute."""
    claim_id: str = ""
    text: str = ""
    raised_by: PartyRole = PartyRole.USER
    against: PartyRole = PartyRole.OPPONENT
    related_to: list[str] = field(default_factory=list)  # other claim_ids
    evidence_refs: list[str] = field(default_factory=list)


@dataclass
class Defense:
    """A defense raised against a claim."""
    defense_id: str = ""
    text: str = ""
    against_claim: str = ""
    defense_type: DefenseType = DefenseType.SUBSTANTIVE
    strength: str = "moderate"  # strong / moderate / weak
    requires_proof: str = ""


@dataclass
class ClaimGraph:
    claims: list[Claim] = field(default_factory=list)


@dataclass
class DefenseGraph:
    defenses: list[Defense] = field(default_factory=list)


@dataclass
class EvidenceIntelligence:
    """Classified evidence per quality."""
    direct: list[str] = field(default_factory=list)
    corroborative: list[str] = field(default_factory=list)
    weak: list[str] = field(default_factory=list)
    contradictory: list[str] = field(default_factory=list)
    missing_critical: list[str] = field(default_factory=list)

    def has_critical_gap(self) -> bool:
        return bool(self.missing_critical)


@dataclass
class PartyStrengthProfile:
    party: PartyRole = PartyRole.USER
    strongest_argument: str = ""
    weakest_point: str = ""
    fatal_weakness: Optional[str] = None    # only set if proven fatal


@dataclass
class OutcomeBranch:
    """Conditional branch — IF condition THEN outcome."""
    condition: str = ""             # "إذا ثبت X"
    outcome_frame: str = ""         # "يتقوى الموقف ..." or "يضعف الموقف ..."
    blocking_factors: list[str] = field(default_factory=list)
    requires_proof: str = ""
    likely_path: str = ""           # "advance to filing" / "negotiation" / "fallback"


@dataclass
class StrategicAssessment:
    case_strength: CaseStrength = CaseStrength.INCOMPLETE
    needs_additional_evidence: bool = False
    needs_strategy_change: bool = False
    needed_defense_type: Optional[DefenseType] = None
    rationale: str = ""


@dataclass
class OpponentModel:
    best_path_for_opponent: str = ""
    likely_attacks: list[str] = field(default_factory=list)
    will_exploit_weakness: list[str] = field(default_factory=list)


@dataclass
class CriticalEvidenceItem:
    evidence_text: str = ""           # what evidence
    if_present: str = ""              # how it strengthens
    if_absent: str = ""               # how it weakens


@dataclass
class StrategicReasoningPlan:
    """Full strategic analysis (internal — not exposed verbatim to user)."""
    issue_domain: str = ""
    claim_graph: ClaimGraph = field(default_factory=ClaimGraph)
    defense_graph: DefenseGraph = field(default_factory=DefenseGraph)
    evidence_intelligence: EvidenceIntelligence = field(
        default_factory=EvidenceIntelligence)
    user_strength: PartyStrengthProfile = field(
        default_factory=lambda: PartyStrengthProfile(party=PartyRole.USER))
    opponent_strength: PartyStrengthProfile = field(
        default_factory=lambda: PartyStrengthProfile(party=PartyRole.OPPONENT))
    outcome_branches: list[OutcomeBranch] = field(default_factory=list)
    strategic_assessment: StrategicAssessment = field(default_factory=StrategicAssessment)
    opponent_model: OpponentModel = field(default_factory=OpponentModel)
    critical_evidence: list[CriticalEvidenceItem] = field(default_factory=list)
    is_substantive: bool = False
    insufficiency_reason: str = ""
    notes_internal: list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════
# Per-issue strategic templates (deterministic)
# ══════════════════════════════════════════════════════════════

# Each template defines: claim, opposing-defense, party strengths/weaknesses,
# critical evidence, and conditional outcomes. All from existing knowledge —
# never invents new legal substance.

_STRATEGIC_TEMPLATES = {
    LegalDomain.EMPLOYMENT: {
        "primary_claim": "إثبات العلاقة العمالية والمطالبة بالحقوق",
        "primary_defense": "إنكار العلاقة أو ادعاء الاستقالة الطوعية",
        "user_strongest_basis": "تحويلات الراتب والمراسلات الرسمية",
        "user_weakest_typical": "غياب العقد المكتوب",
        "fatal_if_present": "إثبات الاستقالة الطوعية الموثّقة",
        "opponent_best_path": "إنكار العلاقة كلياً والاحتجاج بانعدام العقد",
        "opponent_likely_attacks": [
            "الطعن في صفة الوظيفة",
            "ادعاء انتهاء العقد طبيعياً",
            "الادعاء بتلقي المستحقات كاملة",
        ],
        "critical_evidence": [
            ("خطاب التعيين الرسمي",
              "يثبت العلاقة بشكل قاطع ويسقط دفع الإنكار",
              "غيابه يحوّل الإثبات إلى قرائن جانبية"),
            ("تأشيرة/إقامة عمل باسم الشركة",
              "قرينة قاطعة على وجود العلاقة",
              "غيابها لا يُسقط الحق لكن يُضعفه"),
        ],
        "primary_branch_condition": "إذا قُبلت تحويلات الراتب والمراسلات كدليل",
        "primary_branch_outcome": "يتقوى موقف العامل في إثبات العلاقة والمطالبة بحقوقه",
        "fallback_branch_condition": "إذا أنكر صاحب العمل العلاقة وبقيت الأدلة قرائنية فقط",
        "fallback_branch_outcome": "يضعف الموقف ويحتاج تعزيزاً بشهود وقرائن إضافية قبل الدعوى",
    },
    LegalDomain.CIVIL: {
        "primary_claim": "إثبات الدين/الالتزام واستحقاق الوفاء",
        "primary_defense": "إنكار الالتزام أو الادعاء بالسداد",
        "user_strongest_basis": "الاعتراف الكتابي + التحويلات البنكية",
        "user_weakest_typical": "الاعتماد على محادثات واتساب وحدها",
        "fatal_if_present": "إثبات السداد التام أو التقادم",
        "opponent_best_path": "الطعن في حجية الأدلة الإلكترونية + الادعاء بالسداد",
        "opponent_likely_attacks": [
            "الطعن في صحة محادثات واتساب",
            "الادعاء باختلاف القيمة الفعلية",
            "الدفع بالتقادم",
        ],
        "critical_evidence": [
            ("سند دين موقّع أو إيصال رسمي",
              "يحسم النزاع لصالح الدائن في الغالب",
              "غيابه يجعل النزاع يدور حول حجية الأدلة الإلكترونية"),
            ("توثيق رسمي لمحادثات واتساب عبر كاتب عدل",
              "يقوّي حجية الأدلة الإلكترونية أمام المحكمة",
              "بدونه قد يُطعن في الأدلة"),
        ],
        "primary_branch_condition": "إذا قُبل الاعتراف الكتابي وتم توثيق الأدلة الإلكترونية",
        "primary_branch_outcome": "يتقوى موقف الدائن في استرداد المبلغ",
        "fallback_branch_condition": "إذا طُعن في حجية واتساب ولم تُدعم بإثبات إضافي",
        "fallback_branch_outcome": "يضعف الموقف وقد يحتاج لتسوية بدلاً من الدعوى",
    },
    LegalDomain.RENTAL: {
        "primary_claim": "إخلاء المستأجر بسبب التأخر عن السداد",
        "primary_defense": "الطعن في الإنذار أو الادعاء بالإيداع",
        "user_strongest_basis": "الإنذار الرسمي + إثبات التأخر",
        "user_weakest_typical": "غياب الإنذار الرسمي قبل الدعوى",
        "fatal_if_present": "رفع الدعوى قبل الإنذار الرسمي",
        "opponent_best_path": "الدفع بعدم استلام إنذار رسمي + إيداع الأجرة",
        "opponent_likely_attacks": [
            "الدفع بعدم تلقي إنذار رسمي",
            "إيداع الأجرة لدى الجهة المختصة",
            "الادعاء بعيوب جوهرية في العين",
        ],
        "critical_evidence": [
            ("إنذار رسمي مُبلَّغ عبر كاتب العدل",
              "يحسم الدفع الشكلي ويفتح الطريق للإخلاء",
              "غيابه قد يُؤدي لرفض الدعوى شكلاً"),
        ],
        "primary_branch_condition": "إذا تم إرسال إنذار رسمي عبر كاتب العدل قبل الدعوى",
        "primary_branch_outcome": "يتقوى مسار الإخلاء وفق الإجراءات النظامية",
        "fallback_branch_condition": "إذا رُفعت الدعوى دون إنذار رسمي",
        "fallback_branch_outcome": "يتعطل المسار ويلزم إكمال الإنذار قبل المعاودة",
    },
    LegalDomain.FAMILY: {
        "primary_claim": "إثبات الأهلية للحضانة (أو طلب الحضانة)",
        "primary_defense": "ادعاء عدم الصلاحية أو تغير الظروف",
        "user_strongest_basis": "خلو السجل من السوابق + الاستقرار المعيشي",
        "user_weakest_typical": "ادعاء الطرف الآخر بعدم الصلاحية",
        "fatal_if_present": "إثبات سوابق مؤثرة على الأهلية",
        "opponent_best_path": "تقديم تقرير اجتماعي مضاد + إثارة الشكوك",
        "opponent_likely_attacks": [
            "الادعاء بعدم استقرار البيئة",
            "الطلب من المحكمة ندب باحث اجتماعي",
            "إثارة شكوك حول الأهلية النفسية أو السلوك",
        ],
        "critical_evidence": [
            ("تقرير اجتماعي مهني يؤيد الأهلية",
              "يقوّي طلب الحضانة بشكل كبير",
              "غيابه يفتح الباب للشك"),
            ("شهادات حسن سيرة + إثبات الدخل المستقر",
              "يدعم الموقف ويرد على الادعاءات",
              "غيابه يضعف موقف طلب الحضانة"),
        ],
        "primary_branch_condition": "إذا أيّد التقرير الاجتماعي صلاحية الحاضن",
        "primary_branch_outcome": "يتقوى طلب الحضانة وفق مصلحة المحضون",
        "fallback_branch_condition": "إذا قُدّمت قرائن مضادة دون رد موثّق",
        "fallback_branch_outcome": "يضعف الموقف ويحتاج تعزيزاً بأدلة إضافية",
    },
    LegalDomain.CRIMINAL: {
        "primary_claim": "نفي الواقعة أو إضعاف أدلة الاتهام",
        "primary_defense": "الادعاء بقوة الأدلة المتفقة + تضافر القرائن",
        "user_strongest_basis": "تناقض أقوال الشهود + ضعف الأدلة المباشرة",
        "user_weakest_typical": "وجود قرائن متعددة متراكبة",
        "fatal_if_present": "اعتراف موثّق أو دليل مادي قاطع",
        "opponent_best_path": "التركيز على الشهادات المتفقة + تضافر القرائن",
        "opponent_likely_attacks": [
            "إبراز الأقوال المتفقة من الشهود",
            "الاحتجاج بأن تضافر القرائن يُكوّن قناعة القاضي",
            "تجاهل التناقضات الفرعية",
        ],
        "critical_evidence": [
            ("توثيق منهجي لتناقضات أقوال الشهود",
              "يُضعف بشكل كبير دليل الشهادة في كل التهمة",
              "بدونه قد تستند المحكمة إلى الشهادات المتفقة"),
        ],
        "primary_branch_condition": "إذا وُثّقت تناقضات أقوال الشهود في مذكرة الدفاع",
        "primary_branch_outcome": "يتقوى موقف الدفاع في إضعاف الإثبات الأساسي",
        "fallback_branch_condition": "إذا اعتُبرت التناقضات ثانوية ولم تمس الواقعة الجوهرية",
        "fallback_branch_outcome": "يضعف موقف الدفاع ويحتاج لإيجاد قرائن نفي إضافية",
    },
    LegalDomain.PROCEDURAL: {
        "primary_claim": "قبول الطعن أو طلب التنفيذ شكلاً",
        "primary_defense": "الدفع بانقضاء الميعاد أو عدم اكتمال التبليغ",
        "user_strongest_basis": "وضوح تاريخ التبليغ الرسمي",
        "user_weakest_typical": "عدم معرفة تاريخ التبليغ الرسمي",
        "fatal_if_present": "إثبات تبليغ سابق + انقضاء الميعاد",
        "opponent_best_path": "التمسّك بفوات الميعاد بناءً على محضر التبليغ",
        "opponent_likely_attacks": [
            "إثبات تاريخ التبليغ من سجلات المحكمة",
            "التمسّك بفوات ميعاد الطعن وسقوط الحق",
        ],
        "critical_evidence": [
            ("محضر التبليغ الرسمي من قلم المحكمة",
              "يحدد بداية المدة بدقة ويفتح/يُغلق طريق الطعن",
              "بدونه لا يمكن البت في صحة الميعاد"),
        ],
        "primary_branch_condition": "إذا تبيّن أن مهلة الطعن لا تزال قائمة",
        "primary_branch_outcome": "يتقوى مسار الطعن العادي",
        "fallback_branch_condition": "إذا انقضت المهلة دون سبب استثنائي",
        "fallback_branch_outcome": "يتحول الطريق إلى وسائل استثنائية محدودة",
    },
    LegalDomain.ADMINISTRATIVE: {
        "primary_claim": "إلغاء أو تعديل القرار الإداري",
        "primary_defense": "مشروعية القرار + انقضاء ميعاد التظلم",
        "user_strongest_basis": "تقديم التظلم في الميعاد + عيب موضوعي/شكلي",
        "user_weakest_typical": "التأخر عن مهلة التظلم",
        "fatal_if_present": "ثبوت انقضاء المهلة بدون عذر مقبول",
        "opponent_best_path": "التمسّك بفوات المهلة + مشروعية القرار",
        "opponent_likely_attacks": [
            "الدفع بانقضاء ميعاد التظلم",
            "التمسّك بمشروعية القرار وعدم وجود عيب",
        ],
        "critical_evidence": [
            ("تاريخ العلم الموثّق بالقرار الإداري",
              "يحدد بداية المدة ويُحدد قبول التظلم",
              "بدونه يُحتسب التاريخ من النشر/الإخطار"),
        ],
        "primary_branch_condition": "إذا تبيّن أن المهلة قائمة من تاريخ العلم",
        "primary_branch_outcome": "يتقوى مسار التظلم ثم القضاء الإداري",
        "fallback_branch_condition": "إذا فاتت المهلة بدون عذر",
        "fallback_branch_outcome": "يضعف المسار العادي وتقتصر الخيارات على وسائل استثنائية",
    },
    LegalDomain.BANKING: {
        "primary_claim": "بطلان الخصم واسترداد المبلغ",
        "primary_defense": "البنك يُثبت سلامة التفويض",
        "user_strongest_basis": "غياب التفويض المسبق + التبليغ الفوري للبنك",
        "user_weakest_typical": "تأخر التبليغ أو تسريب بيانات الحساب",
        "fatal_if_present": "إثبات تسريب العميل لرمز التحقق",
        "opponent_best_path": "إثبات سلامة المصادقة وفق سجلات البنك",
        "opponent_likely_attacks": [
            "تقديم سجلات التفويض (logs)",
            "إثبات تأخر العميل في التبليغ",
            "الادعاء بإهمال العميل في حفظ البيانات",
        ],
        "critical_evidence": [
            ("سجل تفويضات البنك للعملية المحل النزاع",
              "يحسم النزاع — إن أثبت تفويضاً سليماً يضعف العميل",
              "غيابه يقوّي موقف العميل في إثبات الخصم بدون إذن"),
        ],
        "primary_branch_condition": "إذا عجز البنك عن إثبات التفويض السليم",
        "primary_branch_outcome": "يتقوى موقف العميل في استرداد المبلغ المخصوم",
        "fallback_branch_condition": "إذا أثبت البنك مصادقة سليمة أو تأخر العميل في التبليغ",
        "fallback_branch_outcome": "يضعف موقف العميل بسبب عبء حفظ البيانات",
    },
    LegalDomain.COMMERCIAL: {
        "primary_claim": "نفي الانفراد بالقرار + توزيع المسؤولية على الشركاء",
        "primary_defense": "الادعاء بانفراد شريك بقرار غير مرخّص",
        "user_strongest_basis": "محاضر اجتماعات الشركاء + المراسلات",
        "user_weakest_typical": "غياب محاضر موثّقة",
        "fatal_if_present": "ثبوت قرار فردي بدون موافقة الشركاء",
        "opponent_best_path": "التمسّك بانفراد الشريك بالقرار + غياب الإجماع",
        "opponent_likely_attacks": [
            "الادعاء بأن القرار اتُّخذ منفرداً",
            "إنكار الإجماع على توزيع الخسائر",
        ],
        "critical_evidence": [
            ("محاضر اجتماعات الشركاء الموقّعة",
              "تثبت الطابع الجماعي للقرار وتوزّع المسؤولية",
              "غيابها يُحوّل المسؤولية إلى من اتخذ القرار"),
        ],
        "primary_branch_condition": "إذا أثبتت المحاضر إجماع الشركاء على القرار",
        "primary_branch_outcome": "يتقوى موقف توزيع المسؤولية على جميع الشركاء",
        "fallback_branch_condition": "إذا غابت المحاضر",
        "fallback_branch_outcome": "تُحمَّل المسؤولية لمن اتخذ القرار حسب القرائن",
    },
    LegalDomain.INHERITANCE: {
        "primary_claim": "المطالبة بالنصيب الشرعي من التركة",
        "primary_defense": "الادعاء بنصيب شرعي محدد + ديون على التركة",
        "user_strongest_basis": "حصر إرث رسمي + شهادة وفاة",
        "user_weakest_typical": "غياب القسمة الرسمية",
        "fatal_if_present": "إثبات ديون على التركة تُسقط الأنصبة",
        "opponent_best_path": "التمسّك بأن ما أخذه هو نصيبه + ديون التركة",
        "opponent_likely_attacks": [
            "الادعاء بأن المأخوذ هو النصيب الشرعي",
            "إثارة ديون مزعومة على التركة",
        ],
        "critical_evidence": [
            ("حصر إرث رسمي صادر من محكمة الأسرة",
              "يحدد الورثة والأنصبة بدقة",
              "بدونه يصعب الفصل في النزاع"),
        ],
        "primary_branch_condition": "إذا صدر حصر إرث رسمي وتم تحديد الأنصبة",
        "primary_branch_outcome": "يتقوى موقف المطالبة بالنصيب الشرعي",
        "fallback_branch_condition": "إذا تأخر إصدار حصر الإرث",
        "fallback_branch_outcome": "يجب إكمال الإجراءات الرسمية أولاً",
    },
    LegalDomain.INTELLECTUAL_PROPERTY: {
        "primary_claim": "إثبات أسبقية الفكرة + المطالبة بوقف التعدي",
        "primary_defense": "الادعاء بتطوير مستقل + غياب اتفاقية سرية",
        "user_strongest_basis": "تاريخ إيداع/نشر سابق + اتفاقية سرية",
        "user_weakest_typical": "غياب اتفاقية السرية (NDA)",
        "fatal_if_present": "إثبات الطرف الآخر تطويراً مستقلاً مسبقاً",
        "opponent_best_path": "التمسّك بغياب الـNDA + ادعاء تطوير مستقل",
        "opponent_likely_attacks": [
            "الادعاء بأن الفكرة عامة لا تحظى بالحماية",
            "ادعاء التطوير المستقل بدون اطلاع",
        ],
        "critical_evidence": [
            ("توثيق رسمي لتاريخ الإيداع/النشر الأول",
              "يثبت الأسبقية ويفتح طريق الحماية",
              "بدونه يصعب إثبات التعدي"),
        ],
        "primary_branch_condition": "إذا وُثّقت أسبقية الإيداع/النشر للفكرة",
        "primary_branch_outcome": "يتقوى موقف صاحب الفكرة في وقف التعدي",
        "fallback_branch_condition": "إذا لم توجد اتفاقية سرية ولا توثيق سابق",
        "fallback_branch_outcome": "يضعف الموقف ويحتاج توثيقاً للأسبقية",
    },
}


# ══════════════════════════════════════════════════════════════
# StrategicReasoningEngine
# ══════════════════════════════════════════════════════════════

class StrategicReasoningEngine:
    """
    Builds strategic analysis from already-verified inputs.
    Operates ONLY after fail-closed gates approve.
    """

    MIN_QUERY_WORDS_FOR_DEEP_REASONING = 5

    # ── Public API ──

    def reason(self, fact_pattern: FactPattern,
                burden_map: BurdenMap,
                evidence_ledger: EvidenceLedger,
                domain: LegalDomain,
                query: str = "") -> StrategicReasoningPlan:
        """Main entry point — returns full strategic plan."""
        plan = StrategicReasoningPlan(issue_domain=domain.value)

        # Activation gate — strategic reasoning needs substance
        if not fact_pattern.has_substance:
            plan.is_substantive = False
            plan.insufficiency_reason = "fact_pattern_lacks_substance"
            return plan

        if query and len(query.split()) < self.MIN_QUERY_WORDS_FOR_DEEP_REASONING:
            plan.is_substantive = False
            plan.insufficiency_reason = "query_too_short_for_strategic_depth"
            return plan

        template = _STRATEGIC_TEMPLATES.get(domain)
        if not template:
            plan.is_substantive = False
            plan.insufficiency_reason = "no_template_for_domain"
            return plan

        # Build internal structures
        plan.claim_graph = self._build_claim_graph(template, fact_pattern)
        plan.defense_graph = self._build_defense_graph(template, fact_pattern)
        plan.evidence_intelligence = self._classify_evidence(
            fact_pattern, burden_map, evidence_ledger, template)
        plan.user_strength = self._build_user_strength(template, fact_pattern)
        plan.opponent_strength = self._build_opponent_strength(template, fact_pattern)
        plan.outcome_branches = self._build_branches(
            template, fact_pattern, plan.evidence_intelligence)
        plan.strategic_assessment = self._assess_strategy(
            plan.evidence_intelligence, fact_pattern, burden_map)
        plan.opponent_model = self._model_opponent(template)
        plan.critical_evidence = self._detect_critical_evidence(template)
        plan.is_substantive = True

        log.info("[STRATEGIC] domain=%s strength=%s claims=%d defenses=%d "
                 "branches=%d critical_ev=%d",
                 domain.value,
                 plan.strategic_assessment.case_strength.value,
                 len(plan.claim_graph.claims),
                 len(plan.defense_graph.defenses),
                 len(plan.outcome_branches),
                 len(plan.critical_evidence))
        return plan

    # ── Internal builders ──

    def _build_claim_graph(self, template: dict,
                             fact_pattern: FactPattern) -> ClaimGraph:
        graph = ClaimGraph()
        # Primary claim — derived from template + user role
        primary = Claim(
            claim_id="C1",
            text=template["primary_claim"],
            raised_by=PartyRole.USER if fact_pattern.user_role == "claimant"
                      else PartyRole.OPPONENT,
            against=PartyRole.OPPONENT if fact_pattern.user_role == "claimant"
                    else PartyRole.USER,
        )
        graph.claims.append(primary)
        return graph

    def _build_defense_graph(self, template: dict,
                                fact_pattern: FactPattern) -> DefenseGraph:
        graph = DefenseGraph()
        primary_defense = Defense(
            defense_id="D1",
            text=template["primary_defense"],
            against_claim="C1",
            defense_type=self._classify_defense(template["primary_defense"]),
            strength="strong" if fact_pattern.evidence_absent else "moderate",
        )
        graph.defenses.append(primary_defense)
        return graph

    def _classify_defense(self, defense_text: str) -> DefenseType:
        if any(k in defense_text for k in
                ["شكلي", "ميعاد", "إنذار", "تبليغ"]):
            return DefenseType.PROCEDURAL
        if any(k in defense_text for k in
                ["إنكار", "ادعاء", "مشروعية", "تطوير مستقل"]):
            return DefenseType.SUBSTANTIVE
        return DefenseType.SUBSTANTIVE

    def _classify_evidence(self, fact_pattern: FactPattern,
                              burden_map: BurdenMap,
                              ledger: EvidenceLedger,
                              template: dict) -> EvidenceIntelligence:
        intel = EvidenceIntelligence()

        # DIRECT — what's listed as direct in the ledger
        intel.direct = [e.text for e in ledger.entries
                         if e.evidence_type == EvidenceType.DIRECT][:5]

        # CORROBORATIVE — additional supporting markers (e.g. multiple types)
        if len(intel.direct) >= 2:
            intel.corroborative = intel.direct[1:]
            intel.direct = intel.direct[:1]

        # WEAK — single-source / fragile markers (e.g. WhatsApp only)
        weak_markers = ["محادثات واتساب", "ما عندي إلا"]
        for m in weak_markers:
            if any(m in e for e in fact_pattern.evidence_present):
                intel.weak.append(m)

        # CONTRADICTORY — markers that hurt the user
        for d in fact_pattern.disputed_facts:
            if "ينكر" in d or "يختلف" in d:
                intel.contradictory.append(d)

        # MISSING_CRITICAL — from burden map decisive gaps
        for item in burden_map.items:
            if item.is_decisive and item.gap:
                intel.missing_critical.append(item.required_proof)

        return intel

    def _build_user_strength(self, template: dict,
                                fact_pattern: FactPattern) -> PartyStrengthProfile:
        prof = PartyStrengthProfile(party=PartyRole.USER)
        # Strongest argument — pick from template based on what user has
        if fact_pattern.evidence_present:
            prof.strongest_argument = (
                f"{template['user_strongest_basis']} — "
                f"المتوفر فعلاً: {', '.join(fact_pattern.evidence_present[:2])}"
            )
        else:
            prof.strongest_argument = template["user_strongest_basis"]

        # Weakest point — typical from template, intersected with what's absent
        if fact_pattern.evidence_absent:
            prof.weakest_point = (
                f"{template['user_weakest_typical']} — "
                f"الفجوة الفعلية: {', '.join(fact_pattern.evidence_absent[:2])}"
            )
        else:
            prof.weakest_point = template["user_weakest_typical"]

        # Fatal weakness — only mark as fatal if specific marker present
        fatal_indicator = template.get("fatal_if_present", "")
        if fatal_indicator and any(
                kw in fact_pattern.disputed_facts +
                       fact_pattern.evidence_absent +
                       fact_pattern.admitted_facts
                for kw in [fatal_indicator[:15]]):
            prof.fatal_weakness = fatal_indicator
        return prof

    def _build_opponent_strength(self, template: dict,
                                    fact_pattern: FactPattern) -> PartyStrengthProfile:
        prof = PartyStrengthProfile(party=PartyRole.OPPONENT)
        prof.strongest_argument = template["opponent_best_path"]
        # Opponent's weakest point — when user has strong primary evidence
        if any("تحويلات" in e or "اعتراف" in e or "حصر إرث" in e
                for e in fact_pattern.evidence_present):
            prof.weakest_point = (
                "إنكار يصطدم بقرائن قوية موثّقة من جانب المستخدم")
        else:
            prof.weakest_point = "اعتمادهم على دفع شكلي قد يُكسر بإجراء بسيط"
        return prof

    def _build_branches(self, template: dict,
                          fact_pattern: FactPattern,
                          intel: EvidenceIntelligence) -> list[OutcomeBranch]:
        branches = []
        # Primary branch
        primary = OutcomeBranch(
            condition=template["primary_branch_condition"],
            outcome_frame=template["primary_branch_outcome"],
            blocking_factors=intel.missing_critical[:2],
            requires_proof=intel.missing_critical[0]
                            if intel.missing_critical else "",
            likely_path="advance",
        )
        branches.append(primary)
        # Fallback branch
        fallback = OutcomeBranch(
            condition=template["fallback_branch_condition"],
            outcome_frame=template["fallback_branch_outcome"],
            blocking_factors=fact_pattern.evidence_absent[:2],
            requires_proof=intel.missing_critical[0]
                            if intel.missing_critical else "",
            likely_path="strengthen_first",
        )
        branches.append(fallback)
        return branches

    def _assess_strategy(self, intel: EvidenceIntelligence,
                            fact_pattern: FactPattern,
                            burden_map: BurdenMap) -> StrategicAssessment:
        assess = StrategicAssessment()

        # Strength assessment based on evidence intelligence.
        # Order matters: WEAK-only-evidence takes precedence over INCOMPLETE
        # because the user actually has *something* but it's fragile.
        if intel.weak and not intel.direct:
            assess.case_strength = CaseStrength.WEAK
            assess.rationale = (
                "أدلة ضعيفة فقط — موقف هش يحتاج تعزيزاً جوهرياً")
            assess.needs_additional_evidence = True
            assess.needs_strategy_change = True
        elif intel.has_critical_gap():
            if intel.direct or intel.corroborative:
                assess.case_strength = CaseStrength.MODERATE
                assess.rationale = (
                    "أدلة مباشرة موجودة لكن تنقصها أدلة حاسمة لإكمال الإثبات")
            else:
                assess.case_strength = CaseStrength.INCOMPLETE
                assess.rationale = (
                    "الأدلة الحاسمة مفقودة — لا يمكن الجزم في المسار قبل توفيرها")
            assess.needs_additional_evidence = True
        elif intel.direct and len(intel.direct) >= 1:
            assess.case_strength = CaseStrength.STRONG
            assess.rationale = (
                "أدلة مباشرة قوية ومتعددة تدعم الموقف بشكل واضح")
        else:
            assess.case_strength = CaseStrength.MODERATE
            assess.rationale = "أدلة كافية لكن ليست قاطعة"

        # Recommend defense type — if procedural gap exists, procedural defense
        if any("تبليغ" in m or "إنذار" in m or "ميعاد" in m
               for m in intel.missing_critical):
            assess.needed_defense_type = DefenseType.PROCEDURAL

        return assess

    def _model_opponent(self, template: dict) -> OpponentModel:
        model = OpponentModel()
        model.best_path_for_opponent = template["opponent_best_path"]
        model.likely_attacks = list(template["opponent_likely_attacks"][:3])
        # What the opponent will exploit = the user's typical weakest point
        model.will_exploit_weakness = [template["user_weakest_typical"]]
        return model

    def _detect_critical_evidence(self, template: dict
                                     ) -> list[CriticalEvidenceItem]:
        items = []
        for ev_text, if_present, if_absent in template.get("critical_evidence", []):
            items.append(CriticalEvidenceItem(
                evidence_text=ev_text,
                if_present=if_present,
                if_absent=if_absent,
            ))
        return items[:3]


# ══════════════════════════════════════════════════════════════
# Output renderer — natural Arabic, hides internal structure
# ══════════════════════════════════════════════════════════════

def render_strategic_analysis(plan: StrategicReasoningPlan) -> str:
    """
    Convert the internal plan into natural senior-lawyer Arabic prose.
    Hides claim graph / defense graph / burden map labels.
    Output reads as legal analysis, not a technical breakdown.
    """
    if not plan.is_substantive:
        return ""

    parts = []
    parts.append("\n⚖️ التحليل القضائي:")

    # Strategic assessment in plain language
    strength_label = {
        CaseStrength.STRONG: "موقف قوي عموماً",
        CaseStrength.MODERATE: "موقف متوسط القوة",
        CaseStrength.WEAK: "موقف ضعيف يحتاج تعزيزاً",
        CaseStrength.INCOMPLETE: "موقف غير مكتمل قبل توفير الأدلة الحاسمة",
    }.get(plan.strategic_assessment.case_strength, "موقف بحاجة لتقييم إضافي")
    parts.append(f"• تقدير عام: {strength_label}.")
    if plan.strategic_assessment.rationale:
        parts.append(f"  ({plan.strategic_assessment.rationale})")

    # User strongest argument
    if plan.user_strength.strongest_argument:
        parts.append(
            f"• أقوى ما يدعمك: {plan.user_strength.strongest_argument}")

    # User weakest point
    if plan.user_strength.weakest_point:
        parts.append(
            f"• أبرز نقطة ضعف لديك: {plan.user_strength.weakest_point}")

    # Fatal weakness — only if confirmed
    if plan.user_strength.fatal_weakness:
        parts.append(
            f"⚠️ نقطة قاتلة محتملة: {plan.user_strength.fatal_weakness}")

    # Opponent expected strategy
    if plan.opponent_model.best_path_for_opponent:
        parts.append(
            f"• المسار المتوقع للطرف الآخر: "
            f"{plan.opponent_model.best_path_for_opponent}")
    if plan.opponent_model.likely_attacks:
        attacks = " — ".join(plan.opponent_model.likely_attacks[:2])
        parts.append(f"• الزوايا التي قد يستخدمها ضدك: {attacks}")

    # Conditional outcome branches (no certainty — only IF/THEN)
    if plan.outcome_branches:
        parts.append("\n📊 السيناريوهات المحتملة:")
        for b in plan.outcome_branches[:2]:
            parts.append(f"• {b.condition}: {b.outcome_frame}.")

    # Critical evidence — what would change the case
    if plan.critical_evidence:
        parts.append("\n🎯 الدليل الحاسم الذي قد يغيّر القضية:")
        for ce in plan.critical_evidence[:2]:
            parts.append(f"• {ce.evidence_text} — لو توفر: {ce.if_present}.")

    # Strategic recommendation
    if plan.strategic_assessment.needs_additional_evidence:
        parts.append(
            "\n🧭 التوصية الاستراتيجية: لا يُنصح بالمضي قُدماً قبل سدّ الفجوة "
            "في الأدلة الحاسمة المذكورة أعلاه."
        )
    elif plan.strategic_assessment.needs_strategy_change:
        parts.append(
            "\n🧭 التوصية الاستراتيجية: مراجعة الاستراتيجية المتبعة قبل "
            "اتخاذ خطوات إجرائية."
        )

    return "\n".join(parts)


def render_strategic_insufficiency(plan: StrategicReasoningPlan) -> str:
    """When strategic reasoning cannot proceed — transparent insufficiency."""
    return (
        "\n⚖️ تنبيه استراتيجي: الوقائع المذكورة لا تُمكّن من إجراء تحليل "
        "استراتيجي معمّق دون توضيحات إضافية للأطراف، الأدلة المتوفرة، "
        "والوقائع المتنازع عليها."
    )


# ══════════════════════════════════════════════════════════════
# Module-level singleton + integration API
# ══════════════════════════════════════════════════════════════

_engine: Optional[StrategicReasoningEngine] = None


def get_strategic_engine() -> StrategicReasoningEngine:
    global _engine
    if _engine is None:
        _engine = StrategicReasoningEngine()
    return _engine


def enhance_with_strategic_reasoning(base_text: str,
                                        fact_pattern: FactPattern,
                                        burden_map: BurdenMap,
                                        evidence_ledger: EvidenceLedger,
                                        domain: LegalDomain,
                                        query: str = ""
                                        ) -> tuple[str, StrategicReasoningPlan, bool]:
    """
    Append strategic analysis to base text when activation criteria are met.
    Returns (enhanced_text, plan, applied_flag).
    """
    engine = get_strategic_engine()
    plan = engine.reason(fact_pattern, burden_map, evidence_ledger,
                          domain, query)
    if not plan.is_substantive:
        return base_text, plan, False

    section = render_strategic_analysis(plan)
    if not section:
        return base_text, plan, False

    enhanced = (base_text or "").rstrip() + "\n" + section
    return enhanced, plan, True
