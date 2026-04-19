# -*- coding: utf-8 -*-
"""
Cross-Domain Legal Reasoning Engine
====================================
Detects queries spanning multiple legal domains and produces safe,
prioritized, multi-section answers.

Deterministic. Never invents legal linkages. Evidence-bound.
Runs AFTER query rewriting, semantic memory, and domain detection.
Runs BEFORE final explanation building.

Scenario guidance still wins when facts are too incomplete.
Guardrails still apply. Single-domain structured cases untouched.
"""
from __future__ import annotations
import re, logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger("cross_domain")


# ══════════════════════════════════════════════════════════════
# Domain Keyword Signals (7 domains — extended beyond scenario engine)
# ══════════════════════════════════════════════════════════════

_DOMAIN_SIGNALS = {
    "employment": [
        "فصل", "فصلوني", "فصلني", "تفصلني", "طردوني", "طردني",
        "استقالة", "استقلت", "استقال", "عقد عمل", "عقدي",
        "مكافأة", "شغل", "وظيفة", "كفيل", "كفيلي",
        "شركة", "الشركة", "مديري", "الدوام", "راتبي",
    ],
    "criminal": [
        "متهم", "تهمة", "قبض", "تحقيق", "شرطة", "نيابة",
        "محبوس", "سجن", "مخدرات", "سرقة", "ضرب",
        "متورط", "مسكوني", "حكم علي", "اتهام", "حكموا",
        "يبتزني", "ابتزاز", "يهددني", "حشيش", "انمسك",
        "جريمة", "جنائي", "سرقوا", "تلفوني",
    ],
    "family": [
        "طلاق", "حضانة", "نفقة", "زوج", "زوجتي", "زوجي",
        "طليقتي", "طليقي", "أولادي", "عدة", "خلع",
        "عيال", "عيالي", "زيارة", "ولدي", "بنتي",
        "أسرة", "صداق", "مؤخر", "أطفال",
    ],
    "rental": [
        "إيجار", "إيجاري", "مستأجر", "مالك", "المالك", "شقة",
        "إخلاء", "عقد إيجار", "ضمان الإيجار", "العربون",
        "التأمين", "السكن", "يطلعني", "قفل علي", "بدون عقد",
        "منعني أدخل", "رفع الإيجار",
    ],
    "deadline": [
        "إشعار", "إنذار", "مهلة", "طعن", "اعتراض",
        "جلسة", "قرار", "وصلني", "جاني", "فات الموعد",
        "يضيع حقي", "صدر حكم", "حكم غيابي", "غيابياً",
        "ينتهي حقي", "فاتني", "لسه أقدر", "تقادم", "مدة الطعن",
    ],
    "immigration_exit": [
        "إذن خروج", "خروج نهائي", "نقل كفالة", "إقامة",
        "منعني أطلع", "منع سفر", "منع من السفر", "جواز",
        "أطلع من قطر", "أسافر", "تأشيرة", "منع من المغادرة",
    ],
    "inheritance": [
        "ميراث", "تركة", "ورثة", "حصة إرث", "أبي متوفى",
        "أمي متوفية", "توفي", "توفيت", "الميراث",
    ],
}


# ══════════════════════════════════════════════════════════════
# Interaction Type
# ══════════════════════════════════════════════════════════════

class InteractionType(str, Enum):
    NONE = "none"
    SEQUENTIAL = "sequential"           # dismissal → deadline → exit
    PARALLEL = "parallel"                # employment AND family independently
    CONDITIONAL = "conditional"          # custody depends on divorce status
    URGENT_DEPENDENT = "urgent_dependent"  # criminal + deadline


# ══════════════════════════════════════════════════════════════
# Cross-Domain Plan
# ══════════════════════════════════════════════════════════════

@dataclass
class CrossDomainPlan:
    involved_domains: list[str] = field(default_factory=list)
    primary_domain: str = ""
    secondary_domains: list[str] = field(default_factory=list)
    shared_entities: list[str] = field(default_factory=list)
    shared_facts: list[str] = field(default_factory=list)
    unresolved_domain_gaps: dict[str, list[str]] = field(default_factory=dict)
    priority_order: list[str] = field(default_factory=list)
    interaction_type: InteractionType = InteractionType.NONE
    safe_to_answer_jointly: bool = True
    caution_level: str = "low"
    reason: str = ""
    requires_guidance: bool = False
    notes_internal: list[str] = field(default_factory=list)

    def is_multi_domain(self) -> bool:
        return len(self.involved_domains) >= 2


# ══════════════════════════════════════════════════════════════
# Domain Interaction Registry
# ══════════════════════════════════════════════════════════════

class DomainInteractionRegistry:
    """Defines safe known interaction patterns between domains."""

    INTERACTIONS = {
        frozenset({"employment", "family"}): {
            "priority": ["family", "employment"],
            "type": InteractionType.PARALLEL,
            "reason": "family obligations (نفقة/حضانة) may depend on income situation after dismissal",
            "caution": "medium",
            "requires_guidance": False,
        },
        frozenset({"employment", "deadline"}): {
            "priority": ["deadline", "employment"],
            "type": InteractionType.URGENT_DEPENDENT,
            "reason": "المواعيد القانونية للطعن في قرار الفصل حاسمة",
            "caution": "high",
            "requires_guidance": False,
        },
        frozenset({"employment", "immigration_exit"}): {
            "priority": ["immigration_exit", "employment"],
            "type": InteractionType.URGENT_DEPENDENT,
            "reason": "أولوية قيود السفر/الخروج على تفاصيل التعويض",
            "caution": "high",
            "requires_guidance": False,
        },
        frozenset({"criminal", "rental"}): {
            "priority": ["criminal", "rental"],
            "type": InteractionType.PARALLEL,
            "reason": "التعرض الجنائي يسبق في الأهمية النزاع المدني حول الإيجار",
            "caution": "high",
            "requires_guidance": False,
        },
        frozenset({"criminal", "deadline"}): {
            "priority": ["criminal", "deadline"],
            "type": InteractionType.URGENT_DEPENDENT,
            "reason": "المواعيد الإجرائية الجنائية حاسمة وخطيرة شخصياً",
            "caution": "high",
            "requires_guidance": True,
        },
        frozenset({"family", "deadline"}): {
            "priority": ["deadline", "family"],
            "type": InteractionType.URGENT_DEPENDENT,
            "reason": "مواعيد قضايا الأسرة (حضانة/طعن) حاسمة",
            "caution": "high",
            "requires_guidance": False,
        },
        frozenset({"family", "inheritance"}): {
            "priority": ["family", "inheritance"],
            "type": InteractionType.CONDITIONAL,
            "reason": "مسائل الميراث تعتمد على الحالة الأسرية والوضع الشرعي",
            "caution": "medium",
            "requires_guidance": False,
        },
        frozenset({"family", "immigration_exit"}): {
            "priority": ["family", "immigration_exit"],
            "type": InteractionType.URGENT_DEPENDENT,
            "reason": "السفر بالأطفال يحتاج موافقة الطرف الآخر/المحكمة",
            "caution": "high",
            "requires_guidance": False,
        },
        frozenset({"rental", "deadline"}): {
            "priority": ["deadline", "rental"],
            "type": InteractionType.URGENT_DEPENDENT,
            "reason": "إشعار الإخلاء له مدد قانونية حاسمة",
            "caution": "high",
            "requires_guidance": False,
        },
        frozenset({"employment", "family", "deadline"}): {
            "priority": ["deadline", "family", "employment"],
            "type": InteractionType.URGENT_DEPENDENT,
            "reason": "ثلاث قضايا متشابكة — الأولوية للمواعيد ثم للأسرة ثم للعمل",
            "caution": "high",
            "requires_guidance": True,
        },
        frozenset({"criminal", "employment"}): {
            "priority": ["criminal", "employment"],
            "type": InteractionType.URGENT_DEPENDENT,
            "reason": "الاتهام الجنائي يسبق في الأهمية نزاعات العمل",
            "caution": "high",
            "requires_guidance": False,
        },
    }

    def lookup(self, domains: set[str]) -> Optional[dict]:
        """Find the most specific interaction pattern for a set of domains."""
        domains_fs = frozenset(domains)
        # Exact match first
        if domains_fs in self.INTERACTIONS:
            return self.INTERACTIONS[domains_fs]
        # Try 2-subset matches if 3+ domains
        if len(domains) >= 3:
            best_match = None
            best_priority_coverage = 0
            for interaction_key, interaction in self.INTERACTIONS.items():
                if interaction_key.issubset(domains_fs):
                    coverage = len(interaction_key)
                    if coverage > best_priority_coverage:
                        best_match = interaction
                        best_priority_coverage = coverage
            return best_match
        # Try single 2-domain match if one is subset
        for interaction_key, interaction in self.INTERACTIONS.items():
            if len(interaction_key) == 2 and interaction_key.issubset(domains_fs):
                return interaction
        return None

    def all_interactions(self) -> list[frozenset]:
        return list(self.INTERACTIONS.keys())


# ══════════════════════════════════════════════════════════════
# Cross-Domain Priority Policy
# ══════════════════════════════════════════════════════════════

class CrossDomainPriorityPolicy:
    """Prioritizes domains when multiple are present."""

    # Default priority (highest → lowest)
    DEFAULT_PRIORITY = [
        "criminal",          # personal exposure, safety
        "deadline",          # time-sensitive remedies
        "immigration_exit",  # travel restrictions
        "family",            # custody/alimony (safety-sensitive)
        "employment",        # compensation/rights
        "rental",            # civil dispute
        "inheritance",       # procedural, rarely urgent
    ]

    URGENCY_BOOSTERS = [
        "عاجل", "مستعجل", "بسرعة", "فوراً", "اليوم", "الحين",
        "يضيع حقي", "فات", "ينتهي", "مهلة",
    ]

    def prioritize(self, domains: list[str], query: str = "",
                    registry_priority: Optional[list[str]] = None) -> list[str]:
        """Return domains sorted by priority. Registry override if available."""
        if registry_priority:
            # Use registry order, appending any missing domains at end
            ordered = [d for d in registry_priority if d in domains]
            for d in domains:
                if d not in ordered:
                    ordered.append(d)
            return ordered

        # Default priority with urgency boost
        has_urgency = any(u in query for u in self.URGENCY_BOOSTERS)

        def priority_key(domain: str) -> int:
            try:
                idx = self.DEFAULT_PRIORITY.index(domain)
            except ValueError:
                idx = 99
            # Boost deadline if urgency signals present
            if has_urgency and domain == "deadline":
                idx = -1
            return idx

        return sorted(domains, key=priority_key)


# ══════════════════════════════════════════════════════════════
# Cross-Domain Safety Guard
# ══════════════════════════════════════════════════════════════

class CrossDomainSafetyGuard:
    """Ensures safe joint answers — splits unclear aspects, preserves limitations."""

    def assess_joint_answer_safety(self, plan: CrossDomainPlan,
                                     query: str) -> tuple[bool, list[str]]:
        """
        Determine if joint answer is safe. Returns (is_safe, reasons_unsafe).
        """
        reasons = []

        # If 3+ domains involved, high caution
        if len(plan.involved_domains) >= 3:
            reasons.append("three_or_more_domains_requires_structured_answer")

        # If any domain has known requires_guidance interaction
        if plan.requires_guidance:
            reasons.append("known_interaction_requires_prior_guidance")

        # If conditional query
        if any(c in query for c in ["إذا", "لو", "في حالة", "لو كان"]):
            reasons.append("conditional_query_ambiguous")

        # If domains have no known interaction pattern
        # (unknown combination = more caution)
        if plan.interaction_type == InteractionType.NONE and plan.is_multi_domain():
            reasons.append("unknown_domain_combination")

        is_safe = len(reasons) == 0
        return is_safe, reasons

    def detect_unresolved_gaps(self, domains: list[str],
                                 query: str) -> dict[str, list[str]]:
        """
        For each domain, list what facts are clearly missing.
        Returns {domain: [missing_fact_descriptions]}.
        """
        gaps = {}

        # Per-domain gap patterns
        gap_rules = {
            "employment": {
                "service_duration": [r"\d+\s*سن", "سنة", "شهر", "مدة الخدمة"],
                "termination_type": ["فصل", "استقال", "انتهاء"],
                "contract_exists": ["عقد مكتوب", "بدون عقد", "عقدي"],
            },
            "family": {
                "marriage_status": ["متزوج", "مطلق", "متزوجة", "مطلقة"],
                "children": ["أطفال", "عيال", "ولد", "بنت"],
                "court_case": ["قضية", "رفعت", "المحكمة"],
            },
            "criminal": {
                "stage": ["تحقيق", "تهمة", "حكم", "سجن"],
                "personal_involvement": ["أنا", "علي", "ضدي", "مسكوني"],
            },
            "rental": {
                "contract_exists": ["عقد مكتوب", "بدون عقد"],
                "notice_received": ["إشعار", "إنذار"],
            },
            "deadline": {
                "time_elapsed": ["من يوم", "من أسبوع", "من شهر", "من"],
                "decision_type": ["حكم", "قرار", "إشعار"],
            },
            "immigration_exit": {
                "restriction_source": ["الكفيل", "المحكمة", "قرار"],
            },
            "inheritance": {
                "relation": ["أبي", "أمي", "زوج", "ابن", "ابنة"],
            },
        }

        for domain in domains:
            if domain not in gap_rules:
                continue
            missing = []
            for gap_key, indicators in gap_rules[domain].items():
                # If no indicator present, the fact is missing
                if not any(ind in query for ind in indicators):
                    missing.append(gap_key)
            if missing:
                gaps[domain] = missing

        return gaps

    def split_clear_from_unclear(self, plan: CrossDomainPlan,
                                   query: str) -> tuple[list[str], list[str]]:
        """
        Returns (clear_domains, unclear_domains).
        A domain is "clear" if it has few gaps (<=1).
        """
        clear = []
        unclear = []
        for d in plan.involved_domains:
            gaps = plan.unresolved_domain_gaps.get(d, [])
            if len(gaps) <= 1:
                clear.append(d)
            else:
                unclear.append(d)
        return clear, unclear


# ══════════════════════════════════════════════════════════════
# Cross-Domain Reasoner
# ══════════════════════════════════════════════════════════════

_DOMAIN_LABELS_AR = {
    "employment": "العمل",
    "criminal": "القضية الجنائية",
    "family": "الأحوال الشخصية",
    "rental": "الإيجار",
    "deadline": "المواعيد القانونية",
    "immigration_exit": "قيود السفر/الخروج",
    "inheritance": "الميراث",
}


class CrossDomainReasoner:
    """Main cross-domain reasoning engine."""

    def __init__(self):
        self._registry = DomainInteractionRegistry()
        self._priority = CrossDomainPriorityPolicy()
        self._safety = CrossDomainSafetyGuard()

    # ── Detection ──

    def detect_multi_domain_case(self, query: str) -> list[str]:
        """Return list of detected domains. Multi-domain if >= 2."""
        found = []
        for domain, signals in _DOMAIN_SIGNALS.items():
            if any(s in query for s in signals):
                found.append(domain)
        return found

    def identify_domain_intersections(self, domains: list[str]) -> Optional[dict]:
        """Look up known interaction pattern for the given domains."""
        if len(domains) < 2:
            return None
        return self._registry.lookup(set(domains))

    # ── Planning ──

    def build_cross_domain_plan(self, query: str) -> CrossDomainPlan:
        """Build a full cross-domain plan for the query."""
        plan = CrossDomainPlan()

        domains = self.detect_multi_domain_case(query)
        plan.involved_domains = domains

        if len(domains) < 2:
            plan.interaction_type = InteractionType.NONE
            plan.safe_to_answer_jointly = True
            if domains:
                plan.primary_domain = domains[0]
            return plan

        # Multi-domain case
        interaction = self.identify_domain_intersections(domains)
        if interaction:
            plan.interaction_type = interaction["type"]
            plan.reason = interaction["reason"]
            plan.caution_level = interaction["caution"]
            plan.requires_guidance = interaction["requires_guidance"]
            plan.priority_order = self._priority.prioritize(
                domains, query, interaction["priority"])
        else:
            plan.interaction_type = InteractionType.PARALLEL
            plan.reason = "combination not in known registry — treated as parallel"
            plan.caution_level = "medium"
            plan.priority_order = self._priority.prioritize(domains, query)
            plan.notes_internal.append("unknown_interaction_combination")

        plan.primary_domain = plan.priority_order[0]
        plan.secondary_domains = plan.priority_order[1:]

        # Identify gaps per domain
        plan.unresolved_domain_gaps = self._safety.detect_unresolved_gaps(domains, query)

        # Safety assessment
        is_safe, unsafe_reasons = self._safety.assess_joint_answer_safety(plan, query)
        plan.safe_to_answer_jointly = is_safe
        if not is_safe:
            plan.notes_internal.extend(unsafe_reasons)

        log.info("[CROSS_DOMAIN] domains=%s primary=%s interaction=%s safe=%s",
                 plan.involved_domains, plan.primary_domain,
                 plan.interaction_type.value, plan.safe_to_answer_jointly)
        return plan

    def prioritize_domains(self, domains: list[str], query: str = "") -> list[str]:
        """Public prioritization method."""
        return self._priority.prioritize(domains, query)

    # ── Assembly ──

    def assemble_cross_domain_answer(self, plan: CrossDomainPlan,
                                       base_answer: str = "",
                                       query: str = "") -> str:
        """
        Produce a structured multi-section answer for a multi-domain case.
        Format:
          - Main issue (primary domain)
          - Related issue (secondary domains)
          - What is clear now
          - What still needs details (if unresolved)
          - What to do first
        """
        if not plan.is_multi_domain():
            return base_answer

        sections = []

        # Section header: main issue
        primary_label = _DOMAIN_LABELS_AR.get(plan.primary_domain, plan.primary_domain)
        sections.append(f"📌 المسألة الرئيسية: {primary_label}")

        if base_answer.strip():
            sections.append(base_answer.strip())

        # Secondary domains
        if plan.secondary_domains:
            sec_labels = [_DOMAIN_LABELS_AR.get(d, d) for d in plan.secondary_domains]
            sections.append(f"🔗 مسائل مرتبطة: {' / '.join(sec_labels)}")

        # What is clear vs unclear
        clear, unclear = self._safety.split_clear_from_unclear(plan, query)
        if clear and unclear:
            clear_labels = [_DOMAIN_LABELS_AR.get(d, d) for d in clear]
            unclear_labels = [_DOMAIN_LABELS_AR.get(d, d) for d in unclear]
            sections.append(f"✅ الواضح الآن: {' / '.join(clear_labels)}")
            sections.append(
                f"❓ يحتاج تفاصيل إضافية: {' / '.join(unclear_labels)}")

        # What to do first (priority action)
        if plan.priority_order:
            first = _DOMAIN_LABELS_AR.get(plan.priority_order[0], plan.priority_order[0])
            sections.append(f"▶️ ابدأ بـ: {first}")
            if plan.reason:
                sections.append(f"   ({plan.reason})")

        # Per-domain limitations (separated)
        if plan.unresolved_domain_gaps:
            lim_lines = ["ملاحظات لكل مسألة:"]
            for dom, gaps in plan.unresolved_domain_gaps.items():
                dom_label = _DOMAIN_LABELS_AR.get(dom, dom)
                lim_lines.append(f"  • {dom_label}: ينقص {len(gaps)} تفصيل")
            sections.append("\n".join(lim_lines))

        return "\n\n".join(sections)


# ══════════════════════════════════════════════════════════════
# Module-level Singleton + Integration API
# ══════════════════════════════════════════════════════════════

_reasoner: Optional[CrossDomainReasoner] = None


def get_cross_domain_reasoner() -> CrossDomainReasoner:
    global _reasoner
    if _reasoner is None:
        _reasoner = CrossDomainReasoner()
    return _reasoner


def analyze_cross_domain(query: str) -> CrossDomainPlan:
    """Convenience function: full analysis of a query."""
    return get_cross_domain_reasoner().build_cross_domain_plan(query)


def enhance_answer_for_multi_domain(answer: str, query: str) -> tuple[str, Optional[CrossDomainPlan]]:
    """
    If the query is multi-domain, return a restructured answer with sections.
    Otherwise return the original answer unchanged.
    Returns (enhanced_answer, plan_or_None).
    """
    reasoner = get_cross_domain_reasoner()
    plan = reasoner.build_cross_domain_plan(query)
    if not plan.is_multi_domain():
        return answer, None
    enhanced = reasoner.assemble_cross_domain_answer(plan, answer, query)
    return enhanced, plan
