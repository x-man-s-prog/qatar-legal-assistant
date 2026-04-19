# -*- coding: utf-8 -*-
"""
Expert Legal Analysis Engine — PHASE ADVANCED
==============================================
Upgrades a LegalAnalysis (from LegalThinkingEngine) into prioritized,
expert-level judgment.

For each issue, identifies:
  - the DECISIVE strength (the one factor that most supports the user)
  - the DECISIVE weakness (the one factor that most threatens them)
  - the STRONGEST opposing argument
  - the MOST IMPORTANT proof gap to close FIRST
  - the SINGLE first practical step

Categorical weighting only — never numeric, never verdict-predictive.
Categories: DECISIVE > IMPORTANT > SECONDARY > WEAK > INSUFFICIENT.

Deterministic. No LLM calls. Builds on top of LegalAnalysis.
"""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from core.legal_thinking_engine import (
    LegalAnalysis, IssueType, ISSUE_TYPE_AR,
)

log = logging.getLogger("expert_legal")


# ══════════════════════════════════════════════════════════════
# Importance Category (categorical, no numbers)
# ══════════════════════════════════════════════════════════════

class ImportanceCategory(str, Enum):
    DECISIVE = "decisive"      # the case turns on this
    IMPORTANT = "important"    # significantly matters
    SECONDARY = "secondary"    # contributes but not central
    WEAK = "weak"              # minor / marginal
    INSUFFICIENT = "insufficient"  # likely not enough alone


@dataclass
class RankedItem:
    """A fact/argument/proof item with categorical importance."""
    text: str = ""
    category: ImportanceCategory = ImportanceCategory.SECONDARY
    reason: str = ""               # short internal note (not user-facing)
    fixable: bool = False          # weakness can be addressed?
    depends_on: str = ""           # internal: what fact it depends on


# ══════════════════════════════════════════════════════════════
# ExpertLegalAnalysis
# ══════════════════════════════════════════════════════════════

@dataclass
class ExpertLegalAnalysis:
    issue_type: IssueType = IssueType.UNKNOWN
    decisive_strengths: list[RankedItem] = field(default_factory=list)
    decisive_weaknesses: list[RankedItem] = field(default_factory=list)
    highest_risk_gap: Optional[RankedItem] = None
    strongest_opposing_argument: Optional[RankedItem] = None
    most_important_proof_needed: Optional[RankedItem] = None
    fixable_weaknesses: list[RankedItem] = field(default_factory=list)
    non_fixable_weaknesses: list[RankedItem] = field(default_factory=list)
    immediate_priorities: list[str] = field(default_factory=list)
    secondary_priorities: list[str] = field(default_factory=list)
    safe_user_summary: str = ""
    notes_internal: list[str] = field(default_factory=list)

    # Ranked versions of the original lists (for downstream formatting)
    ranked_supporting: list[RankedItem] = field(default_factory=list)
    ranked_weakening: list[RankedItem] = field(default_factory=list)
    ranked_opposing: list[RankedItem] = field(default_factory=list)
    ranked_proof: list[RankedItem] = field(default_factory=list)

    def has_content(self) -> bool:
        return bool(self.decisive_strengths or self.decisive_weaknesses
                    or self.most_important_proof_needed
                    or self.immediate_priorities)


# ══════════════════════════════════════════════════════════════
# Weighting Library — per-issue text-fragment patterns
# ══════════════════════════════════════════════════════════════

# Each entry: (substring_in_fact_text, category)
# Matches the longest substring → assigns the specified category.
# If no pattern matches, defaults to SECONDARY.

_WEIGHTING_PATTERNS = {
    IssueType.EMPLOYMENT_DISMISSAL: {
        "supporting": [
            ("تحويلات الراتب تُعد قرينة قوية", ImportanceCategory.DECISIVE),
            ("التحويلات المالية الدورية", ImportanceCategory.DECISIVE),
            ("خطاب التعيين", ImportanceCategory.DECISIVE),
            ("بطاقة العمل", ImportanceCategory.DECISIVE),
            ("تأشيرة/إقامة العمل", ImportanceCategory.DECISIVE),
            ("شهادة الزملاء", ImportanceCategory.IMPORTANT),
            ("المراسلات مع الإدارة", ImportanceCategory.IMPORTANT),
            ("رسائل العمل الرسمية", ImportanceCategory.IMPORTANT),
        ],
        "weakening": [
            ("غياب العقد المكتوب", ImportanceCategory.IMPORTANT),
            ("عدم وجود عقد", ImportanceCategory.IMPORTANT),
            ("غياب الشهود", ImportanceCategory.SECONDARY),
            ("الفصل بدون إنذار", ImportanceCategory.IMPORTANT),
            ("الاستقالة الطوعية", ImportanceCategory.DECISIVE),
        ],
        "proof_needed": [
            ("خطاب تعيين أو ما يقوم مقام العقد", ImportanceCategory.DECISIVE),
            ("التحويلات البنكية للأجر", ImportanceCategory.DECISIVE),
            ("وثّق رسائل العمل", ImportanceCategory.IMPORTANT),
        ],
    },
    IssueType.DEBT_MONEY_CLAIM: {
        "supporting": [
            ("الاعتراف الكتابي أو الرسمي", ImportanceCategory.DECISIVE),
            ("سند الدين الموقّع", ImportanceCategory.DECISIVE),
            ("الإيصال الموقّع", ImportanceCategory.DECISIVE),
            ("الاعتراف يُعد من أقوى وسائل الإثبات", ImportanceCategory.IMPORTANT),
            ("الاعتراف الجزئي", ImportanceCategory.IMPORTANT),
            ("التحويلات البنكية", ImportanceCategory.IMPORTANT),
        ],
        "weakening": [
            ("الاعتماد على واتساب فقط", ImportanceCategory.DECISIVE),
            ("محادثات واتساب وحدها", ImportanceCategory.DECISIVE),
            ("حجية محادثات واتساب", ImportanceCategory.IMPORTANT),
            ("غياب العقد المكتوب", ImportanceCategory.IMPORTANT),
            ("عدم وجود وثيقة كتابية", ImportanceCategory.IMPORTANT),
            ("الخلاف على القيمة", ImportanceCategory.IMPORTANT),
            ("اختلاف الطرفين على القيمة", ImportanceCategory.SECONDARY),
        ],
        "proof_needed": [
            ("توثيق محادثات واتساب", ImportanceCategory.DECISIVE),
            ("اطلب توثيق محادثات واتساب", ImportanceCategory.DECISIVE),
            ("اجمع كل التحويلات والإيصالات", ImportanceCategory.IMPORTANT),
            ("وثّق قيمة المبلغ الأصلية", ImportanceCategory.IMPORTANT),
        ],
    },
    IssueType.CONTRACT_BREACH: {
        "supporting": [
            ("العقد المكتوب يحدد الالتزامات", ImportanceCategory.DECISIVE),
            ("الشرط الجزائي", ImportanceCategory.IMPORTANT),
            ("المراسلات بين الأطراف", ImportanceCategory.IMPORTANT),
            ("الشهود على الإخلال", ImportanceCategory.SECONDARY),
        ],
        "weakening": [
            ("القرار الجماعي يُصعّب", ImportanceCategory.DECISIVE),
            ("جماعية القرار تُوزّع المسؤولية", ImportanceCategory.IMPORTANT),
            ("غياب المستندات", ImportanceCategory.IMPORTANT),
        ],
        "proof_needed": [
            ("اجمع محاضر اجتماعات الشركاء", ImportanceCategory.DECISIVE),
            ("وثّق أن القرار صدر بإجماع", ImportanceCategory.DECISIVE),
        ],
    },
    IssueType.RENTAL_EVICTION: {
        "supporting": [
            ("عقد الإيجار المكتوب", ImportanceCategory.DECISIVE),
            ("الإنذار الرسمي", ImportanceCategory.DECISIVE),
            ("الشيكات المرتجعة", ImportanceCategory.IMPORTANT),
            ("إثبات التأخر", ImportanceCategory.IMPORTANT),
        ],
        "weakening": [
            ("عدم إرسال إنذار رسمي", ImportanceCategory.DECISIVE),
            ("رفع الدعوى قبل الإنذار", ImportanceCategory.DECISIVE),
            ("الدعوى المباشرة بدون إنذار", ImportanceCategory.DECISIVE),
        ],
        "proof_needed": [
            ("أرسل إنذاراً رسمياً عبر كاتب العدل", ImportanceCategory.DECISIVE),
        ],
    },
    IssueType.FAMILY_CUSTODY: {
        "supporting": [
            ("عدم وجود سوابق قضائية", ImportanceCategory.DECISIVE),
            ("خلو السجل من السوابق", ImportanceCategory.DECISIVE),
            ("الاستقرار المالي", ImportanceCategory.IMPORTANT),
            ("توفر السكن الملائم", ImportanceCategory.IMPORTANT),
            ("استقرار علاقة الحاضن", ImportanceCategory.IMPORTANT),
        ],
        "weakening": [
            ("ادعاء الطرف الآخر بعدم الصلاحية", ImportanceCategory.IMPORTANT),
            ("ادعاء عدم الصلاحية", ImportanceCategory.IMPORTANT),
            ("ادعاء عدم الأهلية", ImportanceCategory.IMPORTANT),
        ],
        "proof_needed": [
            ("احصل على تقارير اجتماعية", ImportanceCategory.DECISIVE),
            ("اجمع ما يثبت استقرار", ImportanceCategory.IMPORTANT),
        ],
    },
    IssueType.APPEAL_DEADLINE: {
        "supporting": [
            ("المبادرة بالطعن داخل المهلة", ImportanceCategory.DECISIVE),
            ("وضوح تاريخ التبليغ", ImportanceCategory.IMPORTANT),
        ],
        "weakening": [
            ("عدم معرفة تاريخ التبليغ", ImportanceCategory.DECISIVE),
            ("الشك في تاريخ التبليغ", ImportanceCategory.DECISIVE),
            ("التأخر عن المدة القانونية", ImportanceCategory.DECISIVE),
            ("فوات المدة", ImportanceCategory.DECISIVE),
            ("انقضاء المهلة", ImportanceCategory.DECISIVE),
            ("مضي مدة طويلة بعد التبليغ", ImportanceCategory.IMPORTANT),
        ],
        "proof_needed": [
            ("اطلب نسخة محضر التبليغ", ImportanceCategory.DECISIVE),
            ("احصل على محضر الإعلان الرسمي", ImportanceCategory.DECISIVE),
            ("تحقق فوراً من تاريخ التبليغ", ImportanceCategory.DECISIVE),
        ],
    },
    IssueType.ENFORCEMENT_PROCEDURAL: {
        "supporting": [
            ("الحكم النهائي واجب التنفيذ", ImportanceCategory.IMPORTANT),
            ("الحكم القضائي الصادر", ImportanceCategory.IMPORTANT),
            ("وجود الحكم القضائي", ImportanceCategory.IMPORTANT),
        ],
        "weakening": [
            ("عدم التبليغ الرسمي يُوقف", ImportanceCategory.DECISIVE),
            ("انعدام التبليغ الرسمي", ImportanceCategory.DECISIVE),
        ],
        "proof_needed": [
            ("أكمل إجراءات التبليغ الرسمي", ImportanceCategory.DECISIVE),
            ("قدّم طلب تبليغ رسمي", ImportanceCategory.DECISIVE),
        ],
    },
    IssueType.CRIMINAL_ACCUSATION: {
        "supporting": [
            ("خلو السجل من السوابق", ImportanceCategory.IMPORTANT),
            ("التعاون مع التحقيق", ImportanceCategory.SECONDARY),
        ],
        "weakening": [
            ("تناقض أقوال الشهود", ImportanceCategory.DECISIVE),
            ("تناقض الأقوال", ImportanceCategory.DECISIVE),
            ("تناقض الشهادات", ImportanceCategory.DECISIVE),
            ("الأدلة غير المباشرة وحدها", ImportanceCategory.DECISIVE),
            ("القرائن غير المباشرة", ImportanceCategory.IMPORTANT),
        ],
        "proof_needed": [
            ("وثّق مواطن التناقض", ImportanceCategory.DECISIVE),
            ("اطلب من الدفاع تفنيد", ImportanceCategory.DECISIVE),
        ],
    },
    IssueType.ADMINISTRATIVE_OBJECTION: {
        "supporting": [
            ("تقديم التظلم الإداري في الميعاد", ImportanceCategory.DECISIVE),
            ("الطعن ضمن المهلة", ImportanceCategory.DECISIVE),
        ],
        "weakening": [
            ("التأخر عن المهلة", ImportanceCategory.DECISIVE),
            ("فوات المدة", ImportanceCategory.DECISIVE),
            ("الشك في المدة", ImportanceCategory.IMPORTANT),
        ],
        "proof_needed": [
            ("احسب المدة من تاريخ العلم", ImportanceCategory.DECISIVE),
            ("تحقق من تاريخ العلم", ImportanceCategory.DECISIVE),
        ],
    },
}


# ══════════════════════════════════════════════════════════════
# Opposing-argument strength hints
# ══════════════════════════════════════════════════════════════

# (substring, category, depends_on_fact)
# When a specific substring appears in an opposing argument, assign category.
_OPPOSING_STRENGTH = {
    IssueType.EMPLOYMENT_DISMISSAL: [
        ("إنكار العلاقة العمالية", ImportanceCategory.DECISIVE,
         "absence of contract"),
        ("الاستقالة الطوعية", ImportanceCategory.DECISIVE, "claim of resignation"),
        ("سبب مشروع للفصل", ImportanceCategory.IMPORTANT, "alleged misconduct"),
        ("صُرفت كاملة", ImportanceCategory.SECONDARY, "claim of payment"),
    ],
    IssueType.DEBT_MONEY_CLAIM: [
        ("ينازع المدين في قيمة المبلغ", ImportanceCategory.IMPORTANT,
         "amount-only dispute"),
        ("القيمة الفعلية أقل", ImportanceCategory.IMPORTANT,
         "amount-only dispute"),
        ("يطعن الطرف الآخر في حجية محادثات واتساب", ImportanceCategory.DECISIVE,
         "WhatsApp authentication"),
        ("عدم كفاية المحادثات الإلكترونية", ImportanceCategory.DECISIVE,
         "evidence sufficiency"),
        ("السداد الجزئي أو الكامل", ImportanceCategory.SECONDARY,
         "alleged repayment"),
        ("بتقادم الدين", ImportanceCategory.IMPORTANT, "statute of limitations"),
    ],
    IssueType.CONTRACT_BREACH: [
        ("عدم انفراد شريك بالقرار", ImportanceCategory.DECISIVE,
         "joint decision evidence"),
        ("بالإجماع وأن المسؤولية مشتركة", ImportanceCategory.DECISIVE,
         "joint decision evidence"),
        ("القوة القاهرة", ImportanceCategory.SECONDARY, "force majeure"),
    ],
    IssueType.RENTAL_EVICTION: [
        ("عدم تلقّيه إنذاراً رسمياً", ImportanceCategory.DECISIVE,
         "missing formal notice"),
        ("عدم إتمام الإنذار الرسمي", ImportanceCategory.DECISIVE,
         "missing formal notice"),
        ("عيوب العين المؤجرة", ImportanceCategory.SECONDARY,
         "premises defects"),
        ("بإيداع الأجرة", ImportanceCategory.IMPORTANT,
         "rent deposit defense"),
    ],
    IssueType.FAMILY_CUSTODY: [
        ("عدم أهلية الحاضن", ImportanceCategory.IMPORTANT,
         "fitness challenge"),
        ("مصلحة المحضون تقتضي", ImportanceCategory.IMPORTANT,
         "child best interest"),
        ("تقرير بحث اجتماعي مضاد", ImportanceCategory.IMPORTANT,
         "social report"),
    ],
    IssueType.APPEAL_DEADLINE: [
        ("انقضاء ميعاد الطعن", ImportanceCategory.DECISIVE,
         "missed deadline"),
        ("سقوط الحق في الطعن", ImportanceCategory.DECISIVE,
         "right forfeited"),
        ("التاريخ المُثبت بمحضر الإعلان", ImportanceCategory.IMPORTANT,
         "official service record"),
        ("بعد الميعاد القانوني", ImportanceCategory.DECISIVE,
         "missed deadline"),
    ],
    IssueType.ENFORCEMENT_PROCEDURAL: [
        ("وقف التنفيذ لعدم تبليغه", ImportanceCategory.DECISIVE,
         "service prerequisite"),
        ("إجراءات التبليغ غير مكتملة", ImportanceCategory.DECISIVE,
         "service prerequisite"),
        ("إشكالاً في التنفيذ", ImportanceCategory.IMPORTANT,
         "procedural objection"),
    ],
    IssueType.CRIMINAL_ACCUSATION: [
        ("الشهادات المتفقة", ImportanceCategory.IMPORTANT,
         "consistent witness portion"),
        ("تضافر القرائن", ImportanceCategory.IMPORTANT,
         "circumstantial sufficiency"),
        ("سابقة حضور التحقيق", ImportanceCategory.SECONDARY,
         "investigation presence"),
    ],
    IssueType.ADMINISTRATIVE_OBJECTION: [
        ("انقضاء ميعاد التظلم", ImportanceCategory.DECISIVE,
         "missed deadline"),
        ("المدة بدأت من تاريخ النشر", ImportanceCategory.IMPORTANT,
         "service date starts clock"),
        ("بمشروعية القرار", ImportanceCategory.IMPORTANT,
         "lawful decision claim"),
    ],
}


# ══════════════════════════════════════════════════════════════
# Fixability map — which weaknesses can the user still address
# ══════════════════════════════════════════════════════════════

# (substring_in_weakness_text → fixable bool)
_FIXABLE_WEAKNESS_MARKERS = [
    "ما أرسلت إنذار",  # send notice now
    "عدم إرسال إنذار",
    "عدم التبليغ الرسمي",
    "انعدام التبليغ",
    "محادثات واتساب",  # can be officially documented
    "غياب الشهود",     # might still find some
    "عدم معرفة تاريخ", # can request from court
    "الشك في تاريخ",
]

_NON_FIXABLE_WEAKNESS_MARKERS = [
    "فوات المدة",
    "انقضاء المهلة",
    "التأخر عن المدة القانونية",
    "الاستقالة الطوعية",
    "غياب العقد المكتوب",   # past — cannot create a contract retroactively
    "عدم وجود عقد",
    "عدم وجود وثيقة كتابية",
    "القرار الجماعي يُصعّب",
]


# ══════════════════════════════════════════════════════════════
# LegalWeightingEngine
# ══════════════════════════════════════════════════════════════

class LegalWeightingEngine:
    """Assigns categorical importance to each fact/argument/proof."""

    def categorize(self, item_text: str, issue_type: IssueType,
                    layer: str) -> ImportanceCategory:
        """
        Categorize a single item.
        layer ∈ {"supporting", "weakening", "proof_needed"}
        """
        patterns = _WEIGHTING_PATTERNS.get(issue_type, {}).get(layer, [])
        # Match longest-first so specific overrides generic
        for marker, cat in sorted(patterns, key=lambda p: -len(p[0])):
            if marker in item_text:
                return cat
        return ImportanceCategory.SECONDARY

    def categorize_opposing(self, opp_text: str,
                              issue_type: IssueType) -> tuple[ImportanceCategory, str]:
        """Categorize opposing argument + return what fact it depends on."""
        patterns = _OPPOSING_STRENGTH.get(issue_type, [])
        for marker, cat, depends in sorted(patterns, key=lambda p: -len(p[0])):
            if marker in opp_text:
                return cat, depends
        return ImportanceCategory.SECONDARY, ""


# ══════════════════════════════════════════════════════════════
# OpposingArgumentStrengthAnalyzer
# ══════════════════════════════════════════════════════════════

class OpposingArgumentStrengthAnalyzer:
    """Ranks opposing arguments and identifies which depend on unestablished facts."""

    def __init__(self):
        self._weighting = LegalWeightingEngine()

    def rank(self, opposing_arguments: list[str],
              issue_type: IssueType) -> list[RankedItem]:
        ranked = []
        for arg in opposing_arguments:
            cat, depends = self._weighting.categorize_opposing(arg, issue_type)
            ranked.append(RankedItem(
                text=arg, category=cat, depends_on=depends,
                reason=f"opposing arg, depends on: {depends or 'general claim'}",
            ))
        return _sort_by_category(ranked)

    def strongest(self, opposing_arguments: list[str],
                   issue_type: IssueType) -> Optional[RankedItem]:
        ranked = self.rank(opposing_arguments, issue_type)
        if not ranked:
            return None
        return ranked[0]


# ══════════════════════════════════════════════════════════════
# LegalPrioritySequencer
# ══════════════════════════════════════════════════════════════

class LegalPrioritySequencer:
    """Decides what the user must address first."""

    def __init__(self):
        self._weighting = LegalWeightingEngine()

    def fixable_weaknesses(self, weakening: list[RankedItem]) -> list[RankedItem]:
        out = []
        for w in weakening:
            if any(m in w.text for m in _FIXABLE_WEAKNESS_MARKERS):
                w.fixable = True
                out.append(w)
        return out

    def non_fixable_weaknesses(self, weakening: list[RankedItem]) -> list[RankedItem]:
        out = []
        for w in weakening:
            if any(m in w.text for m in _NON_FIXABLE_WEAKNESS_MARKERS):
                out.append(w)
        return out

    def build_sequence(self, expert: ExpertLegalAnalysis,
                        analysis: LegalAnalysis) -> tuple[list[str], list[str]]:
        """
        Returns (immediate_priorities, secondary_priorities).
        Logic:
          1. The most decisive proof gap (if fixable) is always immediate.
          2. The single first practical step (next_step) is always immediate.
          3. Decisive fixable weaknesses come next.
          4. Non-decisive items go to secondary.
        """
        immediate, secondary = [], []

        # 1. Most important proof to close
        if expert.most_important_proof_needed:
            immediate.append(expert.most_important_proof_needed.text)

        # 2. Next step from authority resolver
        if analysis.next_step and analysis.next_step not in immediate:
            immediate.append(analysis.next_step)

        # 3. Decisive fixable weaknesses
        for w in expert.fixable_weaknesses:
            if w.category == ImportanceCategory.DECISIVE and w.text not in immediate:
                immediate.append(f"عالج: {w.text}")

        # 4. Less-urgent items into secondary
        for w in expert.fixable_weaknesses:
            if w.category != ImportanceCategory.DECISIVE and w.text not in immediate:
                secondary.append(w.text)

        # Cap lists
        immediate = immediate[:3]
        secondary = secondary[:3]
        return immediate, secondary


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════

_CATEGORY_RANK = {
    ImportanceCategory.DECISIVE: 0,
    ImportanceCategory.IMPORTANT: 1,
    ImportanceCategory.SECONDARY: 2,
    ImportanceCategory.WEAK: 3,
    ImportanceCategory.INSUFFICIENT: 4,
}


def _sort_by_category(items: list[RankedItem]) -> list[RankedItem]:
    return sorted(items, key=lambda i: _CATEGORY_RANK[i.category])


# ══════════════════════════════════════════════════════════════
# Main Engine
# ══════════════════════════════════════════════════════════════

class ExpertLegalAnalysisEngine:
    """
    Takes a LegalAnalysis and returns an ExpertLegalAnalysis with
    prioritized, ranked, expert-grade judgment.
    """

    def __init__(self):
        self._weighting = LegalWeightingEngine()
        self._opposing_strength = OpposingArgumentStrengthAnalyzer()
        self._sequencer = LegalPrioritySequencer()

    # ── Core Public Methods ──

    def rank_supporting_facts(self, facts: list[str],
                                issue_type: IssueType) -> list[RankedItem]:
        ranked = [
            RankedItem(text=f,
                       category=self._weighting.categorize(f, issue_type, "supporting"))
            for f in facts
        ]
        return _sort_by_category(ranked)

    def rank_weakening_facts(self, facts: list[str],
                               issue_type: IssueType) -> list[RankedItem]:
        ranked = [
            RankedItem(text=f,
                       category=self._weighting.categorize(f, issue_type, "weakening"))
            for f in facts
        ]
        return _sort_by_category(ranked)

    def rank_proof_needed(self, items: list[str],
                            issue_type: IssueType) -> list[RankedItem]:
        ranked = [
            RankedItem(text=i,
                       category=self._weighting.categorize(i, issue_type, "proof_needed"))
            for i in items
        ]
        return _sort_by_category(ranked)

    def identify_decisive_strength(self,
                                     ranked_supp: list[RankedItem]) -> list[RankedItem]:
        return [r for r in ranked_supp
                if r.category == ImportanceCategory.DECISIVE][:2]

    def identify_decisive_weakness(self,
                                     ranked_weak: list[RankedItem]) -> list[RankedItem]:
        return [r for r in ranked_weak
                if r.category == ImportanceCategory.DECISIVE][:2]

    def identify_highest_risk_gap(self,
                                    ranked_proof: list[RankedItem],
                                    ranked_weak: list[RankedItem]) -> Optional[RankedItem]:
        # The highest-risk gap = the decisive proof item that must close
        # a decisive weakness. If decisive proof exists, that's it.
        for p in ranked_proof:
            if p.category == ImportanceCategory.DECISIVE:
                return p
        # Fallback: most important proof item we have
        if ranked_proof:
            return ranked_proof[0]
        # Last resort: decisive weakness itself
        if ranked_weak and ranked_weak[0].category == ImportanceCategory.DECISIVE:
            return ranked_weak[0]
        return None

    def identify_strongest_opposing_argument(self, opposing: list[str],
                                                issue_type: IssueType) -> Optional[RankedItem]:
        return self._opposing_strength.strongest(opposing, issue_type)

    def identify_most_important_missing_proof(self,
                                                ranked_proof: list[RankedItem]) -> Optional[RankedItem]:
        if not ranked_proof:
            return None
        return ranked_proof[0]

    def build_priority_sequence(self, expert: ExpertLegalAnalysis,
                                  analysis: LegalAnalysis) -> tuple[list[str], list[str]]:
        return self._sequencer.build_sequence(expert, analysis)

    # ── Main Pipeline ──

    def build_expert_analysis(self, analysis: LegalAnalysis) -> ExpertLegalAnalysis:
        expert = ExpertLegalAnalysis(issue_type=analysis.issue_type)

        if analysis.issue_type == IssueType.UNKNOWN:
            return expert

        # 1. Rank each list
        expert.ranked_supporting = self.rank_supporting_facts(
            analysis.supporting_facts, analysis.issue_type)
        expert.ranked_weakening = self.rank_weakening_facts(
            analysis.weakening_facts, analysis.issue_type)
        expert.ranked_proof = self.rank_proof_needed(
            analysis.proof_requirements, analysis.issue_type)
        expert.ranked_opposing = self._opposing_strength.rank(
            analysis.opposing_arguments, analysis.issue_type)

        # 2. Decisive strengths / weaknesses
        expert.decisive_strengths = self.identify_decisive_strength(
            expert.ranked_supporting)
        expert.decisive_weaknesses = self.identify_decisive_weakness(
            expert.ranked_weakening)

        # 3. Highest-risk gap + most important proof
        expert.highest_risk_gap = self.identify_highest_risk_gap(
            expert.ranked_proof, expert.ranked_weakening)
        expert.most_important_proof_needed = self.identify_most_important_missing_proof(
            expert.ranked_proof)

        # 4. Strongest opposing argument
        expert.strongest_opposing_argument = self.identify_strongest_opposing_argument(
            analysis.opposing_arguments, analysis.issue_type)

        # 5. Fixable vs non-fixable weaknesses
        expert.fixable_weaknesses = self._sequencer.fixable_weaknesses(
            expert.ranked_weakening)
        expert.non_fixable_weaknesses = self._sequencer.non_fixable_weaknesses(
            expert.ranked_weakening)

        # 6. Priority sequence
        expert.immediate_priorities, expert.secondary_priorities = \
            self.build_priority_sequence(expert, analysis)

        # 7. Safe summary (one line, descriptive only — no verdict language)
        expert.safe_user_summary = (
            f"الأولوية الآن: تأمين أقوى دليل إثبات وتجنب أخطر فجوة قبل أي خطوة "
            f"إجرائية أخرى."
        )

        log.info("[EXPERT] issue=%s decisive_supp=%d decisive_weak=%d "
                 "fixable=%d immediate=%d",
                 analysis.issue_type.value,
                 len(expert.decisive_strengths), len(expert.decisive_weaknesses),
                 len(expert.fixable_weaknesses), len(expert.immediate_priorities))
        return expert


# ══════════════════════════════════════════════════════════════
# Output Formatter — re-renders the analysis with priority emphasis
# ══════════════════════════════════════════════════════════════

# Forbidden language (verdict / probability)
_BANNED_TERMS = [
    "ستفوز", "ستربح", "ستخسر", "محسومة", "أكيد ينجح", "أكيد يفشل",
    "احتمال", "نسبة النجاح", "احتمالية", "%",
]


def _strip_banned(text: str) -> str:
    """Defensive: ensure no verdict/probability language slipped in."""
    out = text
    for b in _BANNED_TERMS:
        out = out.replace(b, "")
    return out


def format_expert_analysis(expert: ExpertLegalAnalysis,
                             analysis: LegalAnalysis) -> str:
    """
    Render the expert-prioritized analysis as Arabic user-facing text.
    Replaces the generic 6-section format with a prioritized,
    expert-distilled view that opens with the most important items.
    """
    if not expert.has_content():
        return ""

    parts = []

    # Header: issue type
    parts.append(f"📌 نوع المسألة: {ISSUE_TYPE_AR[expert.issue_type]}")

    # ─── 🎯 Summary of decisive items ───
    summary_lines = []
    # Fall back to top-ranked items when no DECISIVE ones exist —
    # the user still needs to see what the most important factors are.
    top_strength = (expert.decisive_strengths[0]
                     if expert.decisive_strengths
                     else (expert.ranked_supporting[0]
                           if expert.ranked_supporting else None))
    if top_strength:
        summary_lines.append(f"• أقوى ما يدعم موقفك: {top_strength.text}")

    top_weakness = (expert.decisive_weaknesses[0]
                     if expert.decisive_weaknesses
                     else (expert.ranked_weakening[0]
                           if expert.ranked_weakening else None))
    if top_weakness:
        summary_lines.append(f"• أخطر ما يضعف موقفك: {top_weakness.text}")

    if expert.strongest_opposing_argument:
        summary_lines.append(
            f"• أقوى ما قد يحتج به الطرف الآخر: "
            f"{expert.strongest_opposing_argument.text}")
    if expert.most_important_proof_needed:
        summary_lines.append(
            f"• أهم شيء تحتاج إثباته الآن: "
            f"{expert.most_important_proof_needed.text}")
    if expert.immediate_priorities:
        summary_lines.append(
            f"• ابدأ أولاً بـ: {expert.immediate_priorities[0]}")

    if summary_lines:
        parts.append("\n🎯 الأهم في موقفك:")
        parts.extend(summary_lines)

    # ─── Detailed sections (now ranked) ───
    # Only include items that the summary didn't already cover IF they add value.
    # Cap each section to avoid bloat.
    if expert.ranked_supporting:
        parts.append("\n**ما يدعم موقفك (مرتبة بالأهمية):**")
        for s in expert.ranked_supporting[:3]:
            parts.append(f"• {s.text}")

    if expert.ranked_weakening:
        parts.append("\n**ما يضعف موقفك (مرتبة بالخطورة):**")
        for w in expert.ranked_weakening[:3]:
            label = "" if not w.fixable else " [قابل للمعالجة]"
            parts.append(f"• {w.text}{label}")

    if expert.ranked_opposing:
        parts.append("\n**ما قد يحتج به الطرف الآخر (الأقوى أولاً):**")
        for o in expert.ranked_opposing[:3]:
            parts.append(f"• {o.text}")

    if expert.ranked_proof:
        parts.append("\n**ما تحتاج إثباته (بترتيب الأهمية):**")
        for p in expert.ranked_proof[:3]:
            parts.append(f"• {p.text}")

    # ─── Practical sequence ───
    if expert.immediate_priorities:
        parts.append("\n**الخطوات الفورية:**")
        for i, item in enumerate(expert.immediate_priorities, 1):
            parts.append(f"{i}. {item}")

    if expert.secondary_priorities:
        parts.append("\n**يمكن تأجيله:**")
        for item in expert.secondary_priorities[:2]:
            parts.append(f"• {item}")

    # ─── Authority path (always show) ───
    if analysis.authority_path:
        parts.append(f"\n**الجهة المختصة:** {analysis.authority_path}")

    out = "\n".join(parts)
    return _strip_banned(out)


# ══════════════════════════════════════════════════════════════
# Integration API
# ══════════════════════════════════════════════════════════════

_engine: Optional[ExpertLegalAnalysisEngine] = None


def get_expert_engine() -> ExpertLegalAnalysisEngine:
    global _engine
    if _engine is None:
        _engine = ExpertLegalAnalysisEngine()
    return _engine


def analyze_expert(analysis: LegalAnalysis) -> ExpertLegalAnalysis:
    return get_expert_engine().build_expert_analysis(analysis)


def enhance_with_expert_analysis(answer: str,
                                    query: str) -> tuple[str, bool, Optional[ExpertLegalAnalysis]]:
    """
    Build expert analysis from query + replace the answer's analysis section
    with the prioritized expert view.

    Returns (enhanced_answer, applied_flag, expert_or_None).
    """
    from core.legal_thinking_engine import (
        analyze_legal_issue, should_activate_legal_thinking,
    )
    if not should_activate_legal_thinking(query):
        return answer, False, None

    base_analysis = analyze_legal_issue(query)
    if not base_analysis.is_substantive():
        return answer, False, None

    expert = get_expert_engine().build_expert_analysis(base_analysis)
    if not expert.has_content():
        return answer, False, expert

    expert_section = format_expert_analysis(expert, base_analysis)
    if not expert_section:
        return answer, False, expert

    base = (answer or "").rstrip()
    if base:
        enhanced = f"{base}\n\n---\n\n{expert_section}"
    else:
        enhanced = expert_section

    log.info("[EXPERT] applied: issue=%s",
             expert.issue_type.value)
    return enhanced, True, expert
