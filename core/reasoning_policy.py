# -*- coding: utf-8 -*-
"""
Reasoning Policy — Strict rules governing what can be stated
=============================================================
Implements the three-tier trust model:
  DIRECT_EVIDENCE      — state as fact
  CONTROLLED_INFERENCE — state with qualifier
  UNSUPPORTED_BLOCKED  — block or soften to limitation

Also governs:
  - which reasoning modes apply to which question types
  - how to qualify inferences in user-facing text
  - which claims require verification before output
"""
from __future__ import annotations

import re
import logging
from enum import Enum
from typing import Optional
from dataclasses import dataclass, field

log = logging.getLogger("reasoning_policy")


# ══════════════════════════════════════════════════════════════
# Question-Type Reasoning Modes
# ══════════════════════════════════════════════════════════════

class ReasoningMode(str, Enum):
    STRUCTURED_FACTUAL = "structured_factual"         # "كم مربوط الدرجة السابعة؟"
    YES_NO_CLARIFICATION = "yes_no_clarification"     # "هل هذا يشمل البدلات؟"
    ANALYTICAL_LEGAL = "analytical_legal"             # "كيف يتم تصنيف المواد؟"
    COMPARISON = "comparison"                          # "ما الفرق بين الدرجة X و Y؟"
    SCOPE_APPLICABILITY = "scope_applicability"        # "هل يشمل جميع الجهات؟"
    FOLLOWUP_CONTEXTUAL = "followup_contextual"        # "طيب كم يكون الإجمالي؟"
    CLASSIFICATION = "classification"                  # "كيف يتم تصنيف هذه الأدوية؟"
    LEGAL_DISTINCTION = "legal_distinction"            # "ما الفرق بين الاستخدام الطبي وغير المشروع؟"
    GENERAL_LEGAL = "general_legal"                    # open-ended legal question


# ── Mode Detection ────────────────────────────────────────────

_YES_NO_SIGNALS = ["هل", "أليس", "صحيح أن", "هل يشمل", "هل تشمل", "هل يسري"]
_COMPARISON_SIGNALS = ["قارن", "مقارنة", "الفرق بين", "فرق بين", "ما الفرق"]
_SCOPE_SIGNALS = ["يشمل", "يسري", "ينطبق", "نطاق", "تطبيق", "جميع الجهات"]
_SCOPE_CONTEXT_SIGNALS = ["جهات", "حكومية", "جميع", "نطاق", "تطبيق", "قطاع", "عسكري", "مدني"]
_CLASSIFICATION_SIGNALS = ["تصنيف", "يتم تصنيف", "كيف يصنف", "كيف تصنف"]
_DISTINCTION_SIGNALS = ["الفرق بين", "التمييز بين", "يفرق بين"]
_DISTINCTION_CONCEPT_SIGNALS = ["استخدام", "طبي", "مشروع", "قانوني", "جنائي", "مدني", "إداري", "عقوبة", "حيازة"]
_FOLLOWUP_SIGNALS = ["طيب", "إذن", "وماذا عن", "وكم", "وهل", "يعني"]


def _is_concept_distinction(query: str) -> bool:
    """Check if a 'الفرق بين' query compares abstract legal concepts (not grades/numbers)."""
    q = query.lower()
    # If query contains grade-related terms, it's a data comparison, not a distinction
    grade_signals = ["درجة", "مربوط", "راتب", "جدول"]
    if any(s in q for s in grade_signals):
        return False
    # If query contains legal/concept terms, it's a distinction
    if any(s in q for s in _DISTINCTION_CONCEPT_SIGNALS):
        return True
    return False


def detect_reasoning_mode(query: str, has_history: bool = False) -> ReasoningMode:
    """Detect the appropriate reasoning mode for a query."""
    q = query.lower().strip()

    # Follow-up contextual (short queries with history context)
    if has_history and any(q.startswith(s) for s in _FOLLOWUP_SIGNALS):
        return ReasoningMode.FOLLOWUP_CONTEXTUAL

    # Yes/no clarification — only escalate to SCOPE when scope-specific context present
    if any(q.startswith(s) for s in _YES_NO_SIGNALS):
        if any(s in q for s in _SCOPE_SIGNALS) and any(s in q for s in _SCOPE_CONTEXT_SIGNALS):
            return ReasoningMode.SCOPE_APPLICABILITY
        return ReasoningMode.YES_NO_CLARIFICATION

    # Legal distinction — BEFORE comparison, when comparing abstract legal concepts
    if any(s in q for s in _DISTINCTION_SIGNALS) and _is_concept_distinction(q):
        return ReasoningMode.LEGAL_DISTINCTION

    # Comparison (grade-level or data-level)
    if any(s in q for s in _COMPARISON_SIGNALS):
        return ReasoningMode.COMPARISON

    # Classification
    if any(s in q for s in _CLASSIFICATION_SIGNALS):
        return ReasoningMode.CLASSIFICATION

    # Distinction fallback (if not caught above)
    if any(s in q for s in _DISTINCTION_SIGNALS):
        return ReasoningMode.LEGAL_DISTINCTION

    # Scope/applicability
    if any(s in q for s in _SCOPE_SIGNALS):
        return ReasoningMode.SCOPE_APPLICABILITY

    # Structured factual (salary, table, drug list)
    from core.structured_lookup import classify_query, QueryIntent
    intent = classify_query(query)
    if intent in (QueryIntent.SALARY_QUERY, QueryIntent.DRUG_TABLE,
                  QueryIntent.TABLE_LOOKUP, QueryIntent.ENUMERATION_LIST):
        return ReasoningMode.STRUCTURED_FACTUAL

    # Analytical
    analytical_signals = ["كيف", "لماذا", "ما هو", "ما هي", "اشرح", "وضح"]
    if any(s in q for s in analytical_signals):
        return ReasoningMode.ANALYTICAL_LEGAL

    return ReasoningMode.GENERAL_LEGAL


# ══════════════════════════════════════════════════════════════
# Reasoning Policy Rules
# ══════════════════════════════════════════════════════════════

@dataclass
class PolicyDecision:
    """Result of applying reasoning policy to a piece of evidence."""
    action: str              # "state_as_fact", "state_with_qualifier", "block", "soften_to_limitation"
    qualifier_ar: str = ""   # Arabic qualifier to prepend/append
    rationale: str = ""      # Internal explanation
    evidence_id: str = ""    # Which evidence entry triggered this


class ReasoningPolicy:
    """
    Applies trust rules to determine how information can be stated.

    Rules:
      1. DIRECT_EVIDENCE → state as fact
      2. CONTROLLED_INFERENCE → state with qualifier
      3. UNSUPPORTED_BLOCKED → block entirely
      4. Ambiguous → soften to limitation
    """

    # Qualifiers for controlled inferences (Arabic)
    INFERENCE_QUALIFIERS = [
        "وفقاً للمعلومات المتاحة",
        "بحسب الأصل العام",
        "من الناحية القانونية العامة",
        "في الحالات المعتادة",
    ]

    # Limitation phrases (Arabic)
    LIMITATION_PHRASES = [
        "لا تتوفر معلومات كافية للإجابة بدقة",
        "هذا يتطلب مراجعة الجهة المعنية",
        "التفاصيل الدقيقة قد تختلف بحسب الحالة",
    ]

    def evaluate_evidence(self, support_level: str) -> PolicyDecision:
        """Core policy: how to handle each support level."""
        from core.evidence_registry import SupportLevel

        if support_level == SupportLevel.DIRECT_EVIDENCE.value:
            return PolicyDecision(
                action="state_as_fact",
                rationale="Direct evidence from verified source",
            )
        elif support_level == SupportLevel.CONTROLLED_INFERENCE.value:
            return PolicyDecision(
                action="state_with_qualifier",
                qualifier_ar=self.INFERENCE_QUALIFIERS[0],
                rationale="Controlled inference — must be qualified",
            )
        elif support_level == SupportLevel.UNSUPPORTED_BLOCKED.value:
            return PolicyDecision(
                action="block",
                rationale="Unsupported claim — must not be stated",
            )
        else:
            return PolicyDecision(
                action="soften_to_limitation",
                qualifier_ar=self.LIMITATION_PHRASES[0],
                rationale="Unknown support level — treat as limitation",
            )

    def validate_answer_text(self, text: str, evidence_items: list) -> list[str]:
        """
        Validate that answer text doesn't contain blocked claims.
        Returns list of warnings (empty if clean).
        """
        warnings = []
        from core.evidence_registry import get_registry
        registry = get_registry()

        # Check for blocked claims
        blocked = registry.get_blocked()
        text_lower = text.lower()
        for entry in blocked:
            blocked_text = entry.statement_ar.lower()
            # Check for significant overlap (not just single-word matches)
            words = [w for w in blocked_text.split() if len(w) > 3]
            matching_words = sum(1 for w in words if w in text_lower)
            if len(words) > 0 and matching_words / len(words) > 0.6:
                warnings.append(
                    f"BLOCKED_CLAIM_DETECTED: '{entry.entry_id}' — {entry.confidence_rationale}"
                )

        return warnings

    def get_mode_guidance(self, mode: ReasoningMode) -> dict:
        """
        Return guidance for how to reason in a specific mode.
        This instructs the reasoning engine on what to do.
        """
        guidance = {
            ReasoningMode.STRUCTURED_FACTUAL: {
                "strategy": "direct_data_lookup",
                "allow_inference": False,
                "require_evidence": True,
                "answer_pattern": "data_first",
                "max_explanation_sentences": 1,
                "ar_instruction": "أجب بالبيانات المباشرة فقط",
            },
            ReasoningMode.YES_NO_CLARIFICATION: {
                "strategy": "evidence_then_clarify",
                "allow_inference": True,
                "require_evidence": True,
                "answer_pattern": "yes_no_then_explain",
                "max_explanation_sentences": 2,
                "ar_instruction": "أجب بنعم أو لا ثم وضح باختصار",
            },
            ReasoningMode.ANALYTICAL_LEGAL: {
                "strategy": "structured_analysis",
                "allow_inference": True,
                "require_evidence": True,
                "answer_pattern": "explain_with_evidence",
                "max_explanation_sentences": 4,
                "ar_instruction": "حلل الموضوع بناءً على الأدلة المتاحة",
            },
            ReasoningMode.COMPARISON: {
                "strategy": "side_by_side",
                "allow_inference": False,
                "require_evidence": True,
                "answer_pattern": "compare_data",
                "max_explanation_sentences": 2,
                "ar_instruction": "قارن بين البيانات بشكل مباشر",
            },
            ReasoningMode.SCOPE_APPLICABILITY: {
                "strategy": "scope_check",
                "allow_inference": True,
                "require_evidence": True,
                "answer_pattern": "scope_then_limitation",
                "max_explanation_sentences": 3,
                "ar_instruction": "حدد نطاق التطبيق مع ذكر الاستثناءات",
            },
            ReasoningMode.FOLLOWUP_CONTEXTUAL: {
                "strategy": "context_continuation",
                "allow_inference": True,
                "require_evidence": True,
                "answer_pattern": "brief_contextual",
                "max_explanation_sentences": 2,
                "ar_instruction": "أجب في سياق المحادثة السابقة",
            },
            ReasoningMode.CLASSIFICATION: {
                "strategy": "classify_and_explain",
                "allow_inference": True,
                "require_evidence": True,
                "answer_pattern": "classification_hierarchy",
                "max_explanation_sentences": 4,
                "ar_instruction": "صنف واشرح هيكل التصنيف",
            },
            ReasoningMode.LEGAL_DISTINCTION: {
                "strategy": "distinguish_concepts",
                "allow_inference": True,
                "require_evidence": True,
                "answer_pattern": "contrast_then_explain",
                "max_explanation_sentences": 4,
                "ar_instruction": "بيّن الفروقات الجوهرية مع الأدلة",
            },
            ReasoningMode.GENERAL_LEGAL: {
                "strategy": "evidence_based_response",
                "allow_inference": True,
                "require_evidence": False,
                "answer_pattern": "comprehensive",
                "max_explanation_sentences": 5,
                "ar_instruction": "أجب بناءً على المعلومات المتاحة",
            },
        }
        return guidance.get(mode, guidance[ReasoningMode.GENERAL_LEGAL])


# ══════════════════════════════════════════════════════════════
# Global Policy Instance
# ══════════════════════════════════════════════════════════════

_POLICY = ReasoningPolicy()


def get_policy() -> ReasoningPolicy:
    return _POLICY
