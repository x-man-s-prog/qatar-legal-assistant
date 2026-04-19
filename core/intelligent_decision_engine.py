# -*- coding: utf-8 -*-
"""
Intelligent Decision Engine — PHASE INTELLIGENT DECISION
==========================================================
Strategic branching layer on top of the deterministic LegalDecisionRecord.

For complex personal litigation queries, this engine produces controlled,
deterministic decision branches:
  • "المسار الأقوى إذا ثبتت النقطة الأساسية"
  • "المسار الأضعف إذا بقيت الفجوة كما هي"
  • "أخطر ما قد يغيّر النتيجة"
  • "الخيار الأكثر أمانًا الآن"
  • "ما الذي يجب حسمه أولاً"

Hard rules:
  - NO verdict prediction
  - NO probabilities / percentages
  - NO new legal substance — branches built ONLY from existing record fields
  - Bounded language ("يتقوى الموقف" / "يضعف الموقف" / not "ستفوز")

Operates on the LegalDecisionRecord — does NOT call any reasoning engine.
Single-pass, sub-millisecond.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from core.controlled_reasoning_core import (
    LegalDecisionRecord, RankedFact,
)
from core.legal_thinking_engine import IssueType

log = logging.getLogger("intelligent_decision")


# ══════════════════════════════════════════════════════════════
# Branch + Plan dataclasses
# ══════════════════════════════════════════════════════════════

class BranchType(str, Enum):
    PRIMARY = "primary"               # the strongest available path
    FALLBACK = "fallback"             # the safest path if primary blocked
    HIGH_RISK = "high_risk"           # what threatens the case most
    DEPENDENCY = "dependency"         # path that hinges on a single fact


class UrgencyLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class DecisionBranch:
    label: str = ""                          # Arabic label
    branch_type: BranchType = BranchType.PRIMARY
    trigger_condition: str = ""              # "إذا ثبت X"
    supporting_basis: list[str] = field(default_factory=list)
    blocking_factors: list[str] = field(default_factory=list)
    strongest_point: str = ""
    main_risk: str = ""
    required_proof: str = ""
    next_step: str = ""
    urgency: UrgencyLevel = UrgencyLevel.MEDIUM
    safe_outcome_frame: str = ""             # "يتقوى الموقف" / "يضعف الموقف"
    notes_internal: list[str] = field(default_factory=list)


@dataclass
class IntelligentDecisionPlan:
    primary_branch: Optional[DecisionBranch] = None
    fallback_branch: Optional[DecisionBranch] = None
    high_risk_branch: Optional[DecisionBranch] = None
    dependency_sensitive_branches: list[DecisionBranch] = field(default_factory=list)
    branch_priority_order: list[str] = field(default_factory=list)
    safest_next_move: str = ""
    strongest_available_move: str = ""
    notes_internal: list[str] = field(default_factory=list)

    def has_branches(self) -> bool:
        return any([self.primary_branch, self.fallback_branch,
                    self.high_risk_branch,
                    bool(self.dependency_sensitive_branches)])


# ══════════════════════════════════════════════════════════════
# Per-Issue Branch Templates (deterministic)
# ══════════════════════════════════════════════════════════════

# Each template provides the trigger conditions + framing per issue type.
# All fields are fed from the record at runtime — no invented content.

_BRANCH_TEMPLATES = {
    IssueType.EMPLOYMENT_DISMISSAL: {
        "primary_trigger": "إذا قُبلت تحويلات الراتب والمراسلات كدليل على العلاقة العمالية",
        "fallback_trigger": "إذا أنكر صاحب العمل العلاقة وبقيت الأدلة ضعيفة",
        "high_risk_trigger": "إذا اعتُبرت الاستقالة طوعية أو ثبت سبب مشروع للفصل",
        "primary_frame": "يتقوى موقف العامل في إثبات العلاقة والمطالبة بالحقوق",
        "fallback_frame": "يضعف الموقف ويحتاج تعزيزاً بقرائن إضافية قبل المطالبة",
    },
    IssueType.DEBT_MONEY_CLAIM: {
        "primary_trigger": "إذا قُبل الاعتراف الكتابي وتم توثيق الأدلة الإلكترونية رسمياً",
        "fallback_trigger": "إذا طُعن في حجية محادثات واتساب وبقي الإثبات ضعيفاً",
        "high_risk_trigger": "إذا ثبتت دفوع السداد أو التقادم",
        "primary_frame": "يتقوى موقف الدائن في استرداد المبلغ المعترَف به",
        "fallback_frame": "يضعف الموقف ويحتاج توثيقاً رسمياً للأدلة قبل رفع الدعوى",
    },
    IssueType.APPEAL_DEADLINE: {
        "primary_trigger": "إذا تبيّن أن مهلة الطعن لا تزال قائمة من تاريخ التبليغ الرسمي",
        "fallback_trigger": "إذا انقضت المهلة ولم يكن هناك سبب استثنائي للقبول",
        "high_risk_trigger": "إذا ثبت تبليغ سابق ولم تُبادر بالطعن في الميعاد",
        "primary_frame": "يتقوى الموقف ويُسمح بمسار الطعن العادي",
        "fallback_frame": "يضعف الموقف ويتحول إلى مسار بديل (تظلم/التماس إعادة نظر)",
    },
    IssueType.RENTAL_EVICTION: {
        "primary_trigger": "إذا تم إرسال الإنذار الرسمي عبر كاتب العدل قبل الدعوى",
        "fallback_trigger": "إذا رُفعت الدعوى بدون إنذار رسمي مسبق",
        "high_risk_trigger": "إذا أثبت المستأجر إيداع الأجرة أو وجود عيوب جوهرية بالعين",
        "primary_frame": "يتقوى موقف المؤجر في طلب الإخلاء وفق الإجراءات",
        "fallback_frame": "يضعف الموقف ويحتاج إتمام الخطوة الإجرائية الناقصة أولاً",
    },
    IssueType.FAMILY_CUSTODY: {
        "primary_trigger": "إذا أيّد التقرير الاجتماعي صلاحية الحاضن وتوافرت بيئة مناسبة",
        "fallback_trigger": "إذا قُدّمت قرائن مضادة على عدم الصلاحية ولم يُردّ عليها",
        "high_risk_trigger": "إذا ثبت تغير ظروف الحاضن أو مصلحة المحضون مع الطرف الآخر",
        "primary_frame": "يتقوى موقف طلب الحضانة بناءً على مصلحة المحضون",
        "fallback_frame": "يضعف الموقف ويحتاج تعزيزاً بتقارير وشهادات داعمة",
    },
    IssueType.ENFORCEMENT_PROCEDURAL: {
        "primary_trigger": "إذا تم إكمال تبليغ الطرف الثاني رسمياً عبر إدارة التنفيذ",
        "fallback_trigger": "إذا طُلب التنفيذ قبل اكتمال إجراءات التبليغ",
        "high_risk_trigger": "إذا قُدِّم إشكال في التنفيذ أو طُعن في الحكم بعد التبليغ",
        "primary_frame": "يتقوى موقف الدائن في طلب التنفيذ الفعلي",
        "fallback_frame": "يتوقف التنفيذ مؤقتاً حتى استكمال الخطوة الإجرائية الناقصة",
    },
    IssueType.CRIMINAL_ACCUSATION: {
        "primary_trigger": "إذا وُثّقت تناقضات أقوال الشهود في مذكرة الدفاع",
        "fallback_trigger": "إذا اعتُبرت التناقضات ثانوية ولم تُؤثّر في الواقعة الجوهرية",
        "high_risk_trigger": "إذا توافرت قرائن إضافية تعزز الاتهام",
        "primary_frame": "يتقوى موقف الدفاع بإبراز التناقض المؤثر في الإثبات",
        "fallback_frame": "يضعف موقف الدفاع ويحتاج قرائن مضادة إضافية",
    },
    IssueType.ADMINISTRATIVE_OBJECTION: {
        "primary_trigger": "إذا تبيّن أن مهلة التظلم لا تزال قائمة من تاريخ العلم بالقرار",
        "fallback_trigger": "إذا فاتت المهلة ولا يوجد سبب استثنائي للقبول",
        "high_risk_trigger": "إذا أثبتت الجهة الإدارية مشروعية القرار وعدم وجود عيب",
        "primary_frame": "يتقوى مسار التظلم الإداري ثم القضاء الإداري",
        "fallback_frame": "يضعف المسار العادي ويتحوّل لخيارات استثنائية محدودة",
    },
    IssueType.BANKING_UNAUTHORIZED_DEDUCTION: {
        "primary_trigger": "إذا عجز البنك عن إثبات التفويض السليم للعملية",
        "fallback_trigger": "إذا أثبت البنك مصادقة العميل أو تأخره في التبليغ",
        "high_risk_trigger": "إذا ثبت تسريب العميل لبيانات الحساب أو رمز التحقق",
        "primary_frame": "يتقوى موقف العميل في استرداد المبلغ المخصوم",
        "fallback_frame": "يضعف موقف العميل بسبب عبء حفظ البيانات",
    },
    IssueType.COMMERCIAL_PARTNERSHIP_DISPUTE: {
        "primary_trigger": "إذا أثبتت محاضر الاجتماعات أن القرار صدر بإجماع الشركاء",
        "fallback_trigger": "إذا غابت المحاضر وادّعى الشركاء بانفرادك بالقرار",
        "high_risk_trigger": "إذا ثبت سوء الإدارة المالية من جهة شريك بعينه",
        "primary_frame": "يتقوى موقف توزيع المسؤولية على جميع الشركاء بحسب الحصص",
        "fallback_frame": "يضعف الموقف ويحتاج إثبات طبيعة القرار قبل توزيع المسؤولية",
    },
    IssueType.INHERITANCE_DISTRIBUTION_DISPUTE: {
        "primary_trigger": "إذا صدر حصر الإرث الرسمي وتم تحديد الأنصبة الشرعية",
        "fallback_trigger": "إذا تأخر إصدار حصر الإرث أو نُوزع التركة قبل القسمة",
        "high_risk_trigger": "إذا ادّعى الطرف الآخر ديوناً على التركة تُسقط الأنصبة",
        "primary_frame": "يتقوى موقف المطالبة بالنصيب الشرعي ضمن إجراءات قسمة التركة",
        "fallback_frame": "يضعف الموقف ويحتاج إكمال الإجراءات الرسمية أولاً",
    },
    IssueType.IP_IDEA_MISAPPROPRIATION: {
        "primary_trigger": "إذا وُثّقت أسبقية الإيداع/النشر للفكرة بشكل رسمي",
        "fallback_trigger": "إذا لم توجد اتفاقية سرية ولم يُثبت تاريخ سابق للفكرة",
        "high_risk_trigger": "إذا ادّعى الطرف الآخر تطويراً مستقلاً موازياً للفكرة",
        "primary_frame": "يتقوى موقف صاحب الفكرة في حماية حقوقه ووقف التعدي",
        "fallback_frame": "يضعف الموقف ويحتاج توثيقاً للأسبقية قبل المطالبة",
    },
}


# Default templates for IssueType.UNKNOWN or types without a template
_DEFAULT_TEMPLATE = {
    "primary_trigger": "إذا توفرت الأدلة الكاملة على الواقعة المدّعاة",
    "fallback_trigger": "إذا بقيت فجوة في الإثبات",
    "high_risk_trigger": "إذا قُدِّمت أدلة مضادة تهدم الموقف",
    "primary_frame": "يتقوى الموقف عند توفر الأدلة الكاملة",
    "fallback_frame": "يضعف الموقف ويحتاج تعزيزاً قبل المضي قدماً",
}


# ══════════════════════════════════════════════════════════════
# DecisionStrategySelector
# ══════════════════════════════════════════════════════════════

class DecisionStrategySelector:
    """Chooses among safest / strongest / urgent / dependency-sensitive paths."""

    def select_safest_move(self, record: LegalDecisionRecord) -> str:
        """Return the action with lowest risk and highest fixability."""
        # Prefer the most fixable weakness's required-proof step
        for w in record.weaknesses:
            if w.fixable and record.most_important_proof:
                return record.most_important_proof
        if record.most_important_proof:
            return record.most_important_proof
        if record.next_step:
            return record.next_step
        return ""

    def select_strongest_move(self, record: LegalDecisionRecord) -> str:
        """Return the action that builds the strongest path."""
        # The next_step from the authority resolver is generally the strongest
        # path forward if no procedural blockers exist.
        if record.next_step:
            return record.next_step
        if record.most_important_proof:
            return record.most_important_proof
        return ""

    def is_dependency_sensitive(self, record: LegalDecisionRecord) -> bool:
        """True if outcome depends heavily on a single proof item or argument."""
        return (bool(record.most_important_proof)
                and (len(record.weaknesses) >= 1
                     and any(w.fixable for w in record.weaknesses)))

    def has_high_risk_factor(self, record: LegalDecisionRecord) -> bool:
        """True if there is at least one decisive opposing argument."""
        for opp in record.opposing_arguments:
            if opp.category in ("decisive", "important"):
                return True
        return False


# ══════════════════════════════════════════════════════════════
# IntelligentDecisionEngine
# ══════════════════════════════════════════════════════════════

class IntelligentDecisionEngine:
    """
    Builds an IntelligentDecisionPlan from a LegalDecisionRecord.
    Single-pass, deterministic, no LLM, no probability.
    """

    # Activation requires complex personal queries with substantive content
    MIN_QUERY_WORDS_FOR_BRANCHING = 8
    MIN_RECORD_ITEMS_FOR_BRANCHING = 3   # strengths + weaknesses + opposing combined

    def __init__(self):
        self._selector = DecisionStrategySelector()

    # ── Public API ──

    def should_activate(self, record: LegalDecisionRecord,
                          query: str = "") -> bool:
        """True only when branching adds value (complex queries with substance)."""
        if not record.is_substantive():
            return False
        if query and len(query.split()) < self.MIN_QUERY_WORDS_FOR_BRANCHING:
            return False
        items = (len(record.strengths) + len(record.weaknesses)
                  + len(record.opposing_arguments))
        if items < self.MIN_RECORD_ITEMS_FOR_BRANCHING:
            return False
        return True

    def build_decision_branches(self, record: LegalDecisionRecord
                                  ) -> IntelligentDecisionPlan:
        """Main entry point — returns the full plan."""
        plan = IntelligentDecisionPlan()

        if not record.is_substantive():
            plan.notes_internal.append("non_substantive_record")
            return plan

        plan.primary_branch = self.identify_primary_branch(record)
        plan.fallback_branch = self.identify_fallback_branch(record)
        plan.high_risk_branch = self.identify_high_risk_branch(record)
        plan.dependency_sensitive_branches = \
            self.identify_dependency_sensitive_branch(record)

        plan.safest_next_move = self._selector.select_safest_move(record)
        plan.strongest_available_move = self._selector.select_strongest_move(record)

        # Priority order: high_risk first (must address), then primary, fallback
        plan.branch_priority_order = []
        if plan.high_risk_branch:
            plan.branch_priority_order.append(plan.high_risk_branch.label)
        if plan.primary_branch:
            plan.branch_priority_order.append(plan.primary_branch.label)
        if plan.fallback_branch:
            plan.branch_priority_order.append(plan.fallback_branch.label)

        log.info("[INTELLIGENT_DECISION] plan built: primary=%s fallback=%s "
                 "high_risk=%s dependency=%d",
                 bool(plan.primary_branch), bool(plan.fallback_branch),
                 bool(plan.high_risk_branch),
                 len(plan.dependency_sensitive_branches))
        return plan

    def identify_primary_branch(self, record: LegalDecisionRecord
                                  ) -> DecisionBranch:
        """The strongest available path."""
        tmpl = self._template_for(record.issue_type)
        b = DecisionBranch(
            label="المسار الأقوى",
            branch_type=BranchType.PRIMARY,
            trigger_condition=tmpl["primary_trigger"],
            supporting_basis=[s.text for s in record.strengths[:3]],
            blocking_factors=[w.text for w in record.weaknesses[:2]
                              if w.category in ("decisive", "important")],
            strongest_point=(record.decisive_strengths[0]
                             if record.decisive_strengths
                             else (record.strengths[0].text
                                   if record.strengths else "")),
            main_risk=record.strongest_opposing,
            required_proof=record.most_important_proof,
            next_step=record.next_step,
            urgency=self._infer_urgency(record),
            safe_outcome_frame=tmpl["primary_frame"],
        )
        return b

    def identify_fallback_branch(self, record: LegalDecisionRecord
                                   ) -> DecisionBranch:
        """The safer fallback when the primary path is blocked."""
        tmpl = self._template_for(record.issue_type)
        b = DecisionBranch(
            label="المسار البديل (الأكثر أمانًا)",
            branch_type=BranchType.FALLBACK,
            trigger_condition=tmpl["fallback_trigger"],
            supporting_basis=[],   # fallback doesn't lean on strengths
            blocking_factors=[w.text for w in record.weaknesses[:3]
                              if w.category in ("decisive", "important")],
            strongest_point=(record.decisive_weaknesses[0]
                             if record.decisive_weaknesses
                             else (record.weaknesses[0].text
                                   if record.weaknesses else "")),
            main_risk="استمرار الفجوة في الإثبات",
            required_proof=record.most_important_proof,
            next_step=self._selector.select_safest_move(record),
            urgency=UrgencyLevel.HIGH if record.procedural_risk else UrgencyLevel.MEDIUM,
            safe_outcome_frame=tmpl["fallback_frame"],
        )
        return b

    def identify_high_risk_branch(self, record: LegalDecisionRecord
                                    ) -> Optional[DecisionBranch]:
        """The path that threatens the case most."""
        if not self._selector.has_high_risk_factor(record):
            return None
        tmpl = self._template_for(record.issue_type)
        b = DecisionBranch(
            label="أخطر ما قد يغيّر النتيجة",
            branch_type=BranchType.HIGH_RISK,
            trigger_condition=tmpl["high_risk_trigger"],
            supporting_basis=[],
            blocking_factors=[],
            strongest_point=record.strongest_opposing,
            main_risk=record.strongest_opposing,
            required_proof=record.most_important_proof,
            next_step="الاستعداد للرد على هذا الاحتجاج قبل أي خطوة أخرى",
            urgency=UrgencyLevel.HIGH,
            safe_outcome_frame="يتعرض الموقف للضعف ما لم يُجهَّز رد موثّق",
        )
        return b

    def identify_dependency_sensitive_branch(self, record: LegalDecisionRecord
                                               ) -> list[DecisionBranch]:
        """Paths that hinge on a single fact being established/denied."""
        if not self._selector.is_dependency_sensitive(record):
            return []
        out = []
        # Pick the most decisive fixable weakness as the dependency point
        for w in record.weaknesses:
            if w.fixable and w.category in ("decisive", "important"):
                b = DecisionBranch(
                    label=f"يعتمد المسار على: {w.text[:50]}",
                    branch_type=BranchType.DEPENDENCY,
                    trigger_condition=f"إذا تم تجاوز: {w.text}",
                    supporting_basis=[s.text for s in record.strengths[:2]],
                    blocking_factors=[w.text],
                    strongest_point=w.text,
                    main_risk="استمرار هذه الفجوة يُحوّل المسار للمسار الأضعف",
                    required_proof=record.most_important_proof,
                    next_step=record.most_important_proof or record.next_step,
                    urgency=UrgencyLevel.HIGH,
                    safe_outcome_frame="حسم هذه النقطة هو ما يحدد قوة الموقف",
                )
                out.append(b)
                break  # one is enough — avoid bloat
        return out

    def build_branch_summary(self, plan: IntelligentDecisionPlan) -> str:
        """Render the plan as concise Arabic for user output (5 lines max)."""
        if not plan.has_branches():
            return ""

        parts = ["\n🧭 التحليل الاستراتيجي:"]

        if plan.primary_branch:
            parts.append(
                f"• المسار الأقوى — {plan.primary_branch.trigger_condition}: "
                f"{plan.primary_branch.safe_outcome_frame}.")

        if plan.fallback_branch:
            parts.append(
                f"• المسار الأضعف — {plan.fallback_branch.trigger_condition}: "
                f"{plan.fallback_branch.safe_outcome_frame}.")

        if plan.high_risk_branch:
            parts.append(
                f"• أخطر ما قد يغيّر النتيجة — "
                f"{plan.high_risk_branch.trigger_condition}.")

        if plan.safest_next_move:
            parts.append(f"• الخيار الأكثر أمانًا الآن: {plan.safest_next_move}")

        if plan.dependency_sensitive_branches:
            dep = plan.dependency_sensitive_branches[0]
            parts.append(f"• ما يجب حسمه أولاً: {dep.strongest_point}")

        return "\n".join(parts)

    # ── Helpers ──

    def _template_for(self, issue_type_value: str) -> dict:
        for it, tmpl in _BRANCH_TEMPLATES.items():
            if it.value == issue_type_value:
                return tmpl
        return _DEFAULT_TEMPLATE

    def _infer_urgency(self, record: LegalDecisionRecord) -> UrgencyLevel:
        # Procedural risk = high urgency
        if record.procedural_risk and "عالٍ" in record.procedural_risk:
            return UrgencyLevel.HIGH
        # Many decisive weaknesses → medium-high
        if len(record.decisive_weaknesses) >= 1:
            return UrgencyLevel.HIGH
        return UrgencyLevel.MEDIUM


# ══════════════════════════════════════════════════════════════
# Module-level singleton + integration API
# ══════════════════════════════════════════════════════════════

_engine: Optional[IntelligentDecisionEngine] = None


def get_intelligent_engine() -> IntelligentDecisionEngine:
    global _engine
    if _engine is None:
        _engine = IntelligentDecisionEngine()
    return _engine


def enhance_with_branches(deterministic_text: str,
                            record: LegalDecisionRecord,
                            query: str = "") -> tuple[str, IntelligentDecisionPlan, bool]:
    """
    If the record is substantive enough for branching, append a strategic
    summary section to the deterministic Arabic text.
    Returns (enhanced_text, plan, applied_flag).
    Pure no-op for simple/non-substantive cases — keeps simple queries concise.
    """
    engine = get_intelligent_engine()
    if not engine.should_activate(record, query):
        return deterministic_text, IntelligentDecisionPlan(), False

    plan = engine.build_decision_branches(record)
    if not plan.has_branches():
        return deterministic_text, plan, False

    summary = engine.build_branch_summary(plan)
    if not summary.strip():
        return deterministic_text, plan, False

    enhanced = (deterministic_text or "").rstrip() + "\n" + summary
    return enhanced, plan, True
