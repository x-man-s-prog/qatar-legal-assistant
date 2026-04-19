# -*- coding: utf-8 -*-
"""
Legal Reasoning Engine — Deep Evidence-Bound Reasoning
=======================================================
Sits between intent/context understanding and final answer generation.
Produces structured internal reasoning objects that guide answer construction.

Architecture:
  Query → ReasoningMode detection → Evidence gathering → Reasoning chain
  → Policy validation → Answer plan → Final answer (deterministic or LLM-guided)

The reasoning object is INTERNAL ONLY — never exposed to the user.
The user sees: direct answer + brief explanation + limitation if needed.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from core.evidence_registry import (
    EvidenceEntry, EvidenceRegistry, SupportLevel, get_registry,
)
from core.reasoning_policy import (
    ReasoningMode, ReasoningPolicy, PolicyDecision,
    detect_reasoning_mode, get_policy,
)
from core.advanced_reasoning import enhance_reasoning, validate_reasoning_output
from core.legal_decision import apply_legal_decision_layer

log = logging.getLogger("reasoning_engine")


# ══════════════════════════════════════════════════════════════
# Reasoning Object (Internal)
# ══════════════════════════════════════════════════════════════

@dataclass
class ReasoningResult:
    """Internal structured reasoning — NOT exposed to user."""
    question_type: str = ""                 # ReasoningMode value
    topic: str = ""                         # detected topic
    domain: str = ""                        # "salary", "drug", "scope", ...
    applicable_law: str = ""                # which law applies
    reasoning_mode: str = ""                # mode string
    evidence_items: list = field(default_factory=list)           # all evidence gathered
    direct_evidence: list = field(default_factory=list)          # DIRECT_EVIDENCE items
    controlled_inferences: list = field(default_factory=list)    # CONTROLLED_INFERENCE items
    blocked_unsupported_claims: list = field(default_factory=list)  # UNSUPPORTED items
    answer_plan: list = field(default_factory=list)              # ordered steps
    final_answer_mode: str = ""             # "deterministic" | "llm_guided" | "refusal"
    limitations: list = field(default_factory=list)
    confidence_rationale: str = ""
    warnings: list = field(default_factory=list)
    policy_guidance: dict = field(default_factory=dict)

    def has_direct_evidence(self) -> bool:
        return len(self.direct_evidence) > 0

    def has_inferences(self) -> bool:
        return len(self.controlled_inferences) > 0

    def has_blocked(self) -> bool:
        return len(self.blocked_unsupported_claims) > 0

    def to_dict(self) -> dict:
        return {
            "question_type": self.question_type,
            "topic": self.topic,
            "domain": self.domain,
            "applicable_law": self.applicable_law,
            "reasoning_mode": self.reasoning_mode,
            "evidence_count": len(self.evidence_items),
            "direct_evidence_count": len(self.direct_evidence),
            "inference_count": len(self.controlled_inferences),
            "blocked_count": len(self.blocked_unsupported_claims),
            "answer_plan": self.answer_plan,
            "final_answer_mode": self.final_answer_mode,
            "limitations": self.limitations,
            "warnings": self.warnings,
        }


# ══════════════════════════════════════════════════════════════
# Multi-Turn Legal Memory
# ══════════════════════════════════════════════════════════════

@dataclass
class ConversationContext:
    """Tracks the legal reasoning context across turns."""
    current_topic: str = ""              # "salary", "drug", "scope"
    current_law: str = ""                # active law under discussion
    current_table: str = ""              # active table/schedule
    current_grade: str = ""              # active salary grade
    current_scope: str = ""              # "basic" | "total" | ""
    current_schedule: str = ""           # active drug schedule
    last_reasoning_mode: str = ""
    last_answer_type: str = ""           # "data" | "clarification" | "refusal"
    ambiguity_resolved: dict = field(default_factory=dict)
    turn_count: int = 0

    def update_from_reasoning(self, result: ReasoningResult) -> None:
        """Update context from a reasoning result."""
        self.turn_count += 1
        if result.topic:
            self.current_topic = result.topic
        if result.domain:
            self.current_topic = result.domain
        if result.applicable_law:
            self.current_law = result.applicable_law
        self.last_reasoning_mode = result.reasoning_mode
        self.last_answer_type = result.final_answer_mode

    def get_context_summary(self) -> dict:
        return {
            "topic": self.current_topic,
            "law": self.current_law,
            "grade": self.current_grade,
            "scope": self.current_scope,
            "schedule": self.current_schedule,
            "turns": self.turn_count,
        }


# ══════════════════════════════════════════════════════════════
# Domain Detectors
# ══════════════════════════════════════════════════════════════

_SALARY_DOMAIN_SIGNALS = [
    "راتب", "مربوط", "رواتب", "درجة", "دراجات", "بدل", "علاوة",
    "إجمالي الراتب", "الراتب الأساسي", "سلم الرواتب", "جدول الرواتب",
]
_DRUG_DOMAIN_SIGNALS = [
    "مخدر", "مؤثر", "عقلي", "مواد", "جدول المخدرات", "مستحضر",
    "صيدلاني", "أدوية", "تصنيف المواد", "حشيش", "مورفين", "كوكايين",
]
_SCOPE_DOMAIN_SIGNALS = [
    "يسري", "يشمل", "ينطبق", "نطاق", "جهات", "حكومية", "مستثنى",
    "عسكري", "شرطة", "مدني", "خاص",
]


def _detect_domain(query: str, context: Optional[ConversationContext] = None) -> str:
    """Detect which knowledge domain a query belongs to."""
    q = query.lower().strip()

    salary_score = sum(1 for s in _SALARY_DOMAIN_SIGNALS if s in q)
    drug_score = sum(1 for s in _DRUG_DOMAIN_SIGNALS if s in q)
    scope_score = sum(1 for s in _SCOPE_DOMAIN_SIGNALS if s in q)

    if salary_score > drug_score and salary_score > scope_score:
        return "salary"
    if drug_score > salary_score and drug_score > scope_score:
        return "drug"
    if scope_score > 0:
        return "scope"

    # Fall back to conversation context
    if context and context.current_topic:
        return context.current_topic

    return "general"


def _detect_topic(query: str, domain: str) -> str:
    """Detect sub-topic within a domain."""
    q = query.lower().strip()

    if domain == "salary":
        if "إجمالي" in q or "كامل" in q or "بالعلاوات" in q:
            return "total_compensation"
        if "بدل" in q or "علاوة" in q:
            return "allowances"
        if "مربوط" in q or "أساسي" in q:
            return "basic_salary"
        if "مقارنة" in q or "قارن" in q or "الفرق" in q:
            return "comparison"
        return "basic_salary"

    if domain == "drug":
        if "تصنيف" in q:
            return "classification"
        if "طبي" in q or "مشروع" in q or "علاج" in q:
            return "medical_vs_illicit"
        if "عقوب" in q or "جريم" in q:
            return "severity"
        if "جدول" in q:
            if "أول" in q or "1" in q:
                return "schedule_1"
            if "ثان" in q or "2" in q:
                return "schedule_2"
            if "ثالث" in q or "3" in q:
                return "schedule_3"
            return "schedule_structure"
        if "خطور" in q or "خطر" in q:
            return "danger"
        return "classification"

    if domain == "scope":
        if "عسكر" in q or "شرط" in q:
            return "exclusions"
        if "خاص" in q or "مستقل" in q:
            return "special_entities"
        return "civil_service"

    return "general"


# ══════════════════════════════════════════════════════════════
# Evidence Gathering
# ══════════════════════════════════════════════════════════════

def _gather_evidence(
    domain: str,
    topic: str,
    query: str,
    registry: EvidenceRegistry,
) -> tuple[list[EvidenceEntry], list[EvidenceEntry], list[EvidenceEntry]]:
    """
    Gather evidence from the registry for a domain+topic.

    Returns: (direct_evidence, controlled_inferences, blocked_claims)
    """
    # Get domain evidence
    domain_entries = registry.get_by_domain(domain)
    topic_entries = registry.get_by_topic(topic) if topic else []

    # Also search by query keywords
    search_entries = registry.search(query, domain=domain, max_results=10)

    # Merge and deduplicate
    all_entries: dict[str, EvidenceEntry] = {}
    for e in domain_entries + topic_entries + search_entries:
        all_entries[e.entry_id] = e

    direct = []
    inferences = []
    blocked = []

    for e in all_entries.values():
        if e.is_direct():
            direct.append(e)
        elif e.is_inference():
            inferences.append(e)
        elif e.is_blocked():
            blocked.append(e)

    return direct, inferences, blocked


# ══════════════════════════════════════════════════════════════
# Answer Planning
# ══════════════════════════════════════════════════════════════

def _build_answer_plan(
    mode: ReasoningMode,
    domain: str,
    topic: str,
    direct_evidence: list,
    inferences: list,
    blocked: list,
    guidance: dict,
) -> list[str]:
    """Build an ordered answer plan based on reasoning mode and evidence."""
    plan = []

    pattern = guidance.get("answer_pattern", "comprehensive")

    if pattern == "data_first":
        plan.append("STEP_1: Present data directly from structured lookup")
        if direct_evidence:
            plan.append("STEP_2: Add source reference")
        plan.append("STEP_3: Add limitation if scope is unclear")

    elif pattern == "yes_no_then_explain":
        plan.append("STEP_1: Answer yes/no based on evidence")
        plan.append("STEP_2: Brief explanation (1-2 sentences)")
        if inferences:
            plan.append("STEP_3: Add qualified inference if relevant")

    elif pattern == "compare_data":
        plan.append("STEP_1: Extract data for each item being compared")
        plan.append("STEP_2: Present side-by-side comparison")
        plan.append("STEP_3: Note if data for any item is missing")

    elif pattern == "scope_then_limitation":
        plan.append("STEP_1: State the scope rule from evidence")
        plan.append("STEP_2: List known exceptions")
        plan.append("STEP_3: Note limitations of available data")

    elif pattern == "classification_hierarchy":
        plan.append("STEP_1: Describe the classification structure")
        plan.append("STEP_2: Explain each category with evidence")
        plan.append("STEP_3: Note relationships between categories")

    elif pattern == "contrast_then_explain":
        plan.append("STEP_1: State the key distinction clearly")
        plan.append("STEP_2: Explain each side with evidence")
        plan.append("STEP_3: Practical implications if grounded")

    elif pattern == "brief_contextual":
        plan.append("STEP_1: Answer in context of previous turn")
        plan.append("STEP_2: Add qualifying evidence if available")

    else:  # comprehensive
        plan.append("STEP_1: Direct answer from evidence")
        if direct_evidence:
            plan.append("STEP_2: Support with direct evidence")
        if inferences:
            plan.append("STEP_3: Add controlled inferences (qualified)")
        plan.append("STEP_4: State limitations")

    # Always add blocked-claim guard
    if blocked:
        plan.append(f"GUARD: Block {len(blocked)} unsupported claims")

    return plan


# ══════════════════════════════════════════════════════════════
# Enrichment Builder — adds reasoning context to answers
# ══════════════════════════════════════════════════════════════

def build_reasoning_enrichment(result: ReasoningResult) -> Optional[str]:
    """
    Build the reasoning enrichment text to append/integrate
    into an answer. This is the intelligence layer.

    Returns None if no enrichment is needed (e.g., pure data answer).
    """
    parts = []
    mode = result.reasoning_mode

    # For structured factual answers, add minimal enrichment
    if mode == ReasoningMode.STRUCTURED_FACTUAL.value:
        # Check if there's a relevant clarification from evidence
        for e in result.direct_evidence:
            if e.topic == "total_compensation" and "إجمالي" not in (result.topic or ""):
                # User asked for basic but we can note the distinction
                pass  # handled by scope note in answer_builder
        return None  # Data answers are self-sufficient

    # For yes/no clarification
    if mode == ReasoningMode.YES_NO_CLARIFICATION.value:
        for e in result.direct_evidence:
            if e.domain == result.domain:
                parts.append(e.statement_ar)
                break
        for e in result.controlled_inferences[:1]:
            if e.domain == result.domain:
                parts.append(f"وفقاً للمعلومات المتاحة، {e.statement_ar}")
                break

    # For scope/applicability
    elif mode == ReasoningMode.SCOPE_APPLICABILITY.value:
        for e in result.direct_evidence:
            if "نطاق" in " ".join(e.tags) or "scope" in e.topic:
                parts.append(e.statement_ar)
        for e in result.controlled_inferences[:1]:
            parts.append(f"كما أن {e.statement_ar}")
        if result.limitations:
            parts.append(f"ملاحظة: {result.limitations[0]}")

    # For classification
    elif mode == ReasoningMode.CLASSIFICATION.value:
        for e in result.direct_evidence:
            if "تصنيف" in " ".join(e.tags) or "classification" in e.topic:
                parts.append(e.statement_ar)

    # For legal distinction
    elif mode == ReasoningMode.LEGAL_DISTINCTION.value:
        for e in result.direct_evidence:
            parts.append(e.statement_ar)
        for e in result.controlled_inferences[:1]:
            parts.append(e.statement_ar)

    # For analytical legal
    elif mode == ReasoningMode.ANALYTICAL_LEGAL.value:
        for e in result.direct_evidence[:3]:
            parts.append(e.statement_ar)
        for e in result.controlled_inferences[:1]:
            parts.append(f"علماً بأن {e.statement_ar}")

    # For follow-up contextual
    elif mode == ReasoningMode.FOLLOWUP_CONTEXTUAL.value:
        for e in result.direct_evidence[:2]:
            parts.append(e.statement_ar)

    if not parts:
        return None

    # Limit total length
    text = "\n".join(parts)
    if len(text) > 600:
        text = text[:597] + "…"
    return text


# ══════════════════════════════════════════════════════════════
# Main Reasoning Engine
# ══════════════════════════════════════════════════════════════

class LegalReasoningEngine:
    """
    Core reasoning engine. Produces ReasoningResult objects
    that guide answer construction.
    """

    def __init__(self):
        self._contexts: dict[str, ConversationContext] = {}  # session_id → context

    def get_context(self, session_id: str = "default") -> ConversationContext:
        if session_id not in self._contexts:
            self._contexts[session_id] = ConversationContext()
        return self._contexts[session_id]

    def reason(
        self,
        query: str,
        session_id: str = "default",
        history: list = None,
        structured_result: dict = None,
    ) -> ReasoningResult:
        """
        Main entry point. Performs deep legal reasoning over a query.

        Args:
            query: user's question
            session_id: for multi-turn context
            history: conversation history
            structured_result: if structured_lookup already produced a result

        Returns:
            ReasoningResult with evidence, plan, and guidance.
        """
        history = history or []
        context = self.get_context(session_id)
        registry = get_registry()
        policy = get_policy()

        # 1. Detect reasoning mode
        has_history = len(history) > 0 or context.turn_count > 0
        mode = detect_reasoning_mode(query, has_history=has_history)
        log.info("[REASON] mode=%s query=%s", mode.value, query[:60])

        # 2. Detect domain and topic
        domain = _detect_domain(query, context)
        topic = _detect_topic(query, domain)
        log.info("[REASON] domain=%s topic=%s", domain, topic)

        # 3. Gather evidence from registry
        direct, inferences, blocked = _gather_evidence(domain, topic, query, registry)
        all_evidence = direct + inferences + blocked

        # 4. Get policy guidance for this mode
        guidance = policy.get_mode_guidance(mode)

        # 5. Determine applicable law
        applicable_law = ""
        for e in direct:
            if e.source_law:
                applicable_law = e.source_law
                break

        # 6. Build answer plan
        plan = _build_answer_plan(
            mode, domain, topic, direct, inferences, blocked, guidance,
        )

        # 7. Determine final answer mode
        if structured_result and not structured_result.get("is_refusal"):
            final_mode = "deterministic"
        elif structured_result and structured_result.get("is_refusal"):
            final_mode = "refusal"
        elif mode == ReasoningMode.STRUCTURED_FACTUAL:
            final_mode = "deterministic"
        elif direct:
            final_mode = "evidence_guided"
        else:
            final_mode = "llm_guided"

        # 8. Collect limitations
        limitations = []
        for e in direct + inferences:
            limitations.extend(e.limitations)
        limitations = list(set(limitations))  # dedupe

        # 9. Build result
        result = ReasoningResult(
            question_type=mode.value,
            topic=topic,
            domain=domain,
            applicable_law=applicable_law,
            reasoning_mode=mode.value,
            evidence_items=[e.to_dict() for e in all_evidence[:20]],
            direct_evidence=direct,
            controlled_inferences=inferences,
            blocked_unsupported_claims=blocked,
            answer_plan=plan,
            final_answer_mode=final_mode,
            limitations=limitations,
            confidence_rationale=f"{len(direct)} direct, {len(inferences)} inferred, {len(blocked)} blocked",
            policy_guidance=guidance,
        )

        # 10. Update conversation context
        context.update_from_reasoning(result)
        if domain == "salary":
            from core.structured_lookup import _extract_grade, _classify_salary_scope
            grade = _extract_grade(query)
            if grade:
                context.current_grade = grade
            scope = _classify_salary_scope(query)
            if scope != "unspecified":
                context.current_scope = scope

        log.info("[REASON] result: direct=%d infer=%d blocked=%d mode=%s",
                 len(direct), len(inferences), len(blocked), final_mode)

        # ── Advanced Reasoning Extension ──
        try:
            enhance_reasoning(result, query)
        except Exception as _adv_err:
            log.debug('advanced_reasoning (non-critical): %s', _adv_err)

        return result

    def enrich_answer(
        self,
        base_answer: str,
        reasoning: ReasoningResult,
        is_structured: bool = False,
    ) -> str:
        """
        Enrich a base answer with reasoning intelligence.

        For structured answers (data lookup), adds contextual enrichment.
        For LLM-generated answers, validates against blocked claims.
        """

        # ── Legal Decision Layer ──
        try:
            base_answer, _audit = apply_legal_decision_layer(reasoning, base_answer)
        except Exception as _ld_err:
            log.debug("legal_decision (non-critical): %s", _ld_err)

        policy = get_policy()

        # Validate against blocked claims
        warnings = policy.validate_answer_text(base_answer, reasoning.evidence_items)
        if warnings:
            for w in warnings:
                log.warning("[REASON_GUARD] %s", w)
                reasoning.warnings.append(w)

        # For structured/deterministic answers, add reasoning enrichment
        if is_structured:
            enrichment = build_reasoning_enrichment(reasoning)
            if enrichment and reasoning.reasoning_mode != ReasoningMode.STRUCTURED_FACTUAL.value:
                # Only add enrichment for non-factual modes
                return f"{base_answer}\n\n{enrichment}"
            return base_answer

        # For LLM-guided answers, the enrichment becomes context for the prompt
        # (handled by the caller in query_router)
        return base_answer

    def build_llm_context(self, reasoning: ReasoningResult) -> str:
        """
        Build context string for LLM-guided answers.
        This provides the LLM with evidence and policy constraints.
        """
        parts = []

        if reasoning.direct_evidence:
            parts.append("=== معلومات موثقة ===")
            for e in reasoning.direct_evidence[:5]:
                parts.append(f"• {e.statement_ar}")
                if e.source_law:
                    parts.append(f"  (المصدر: {e.source_law})")

        if reasoning.controlled_inferences:
            parts.append("\n=== استنتاجات مضبوطة (يجب تأهيلها) ===")
            for e in reasoning.controlled_inferences[:3]:
                parts.append(f"• {e.statement_ar}")
                if e.limitations:
                    parts.append(f"  محدودية: {'; '.join(e.limitations)}")

        if reasoning.blocked_unsupported_claims:
            parts.append("\n=== ادعاءات محظورة (يجب تجنبها) ===")
            for e in reasoning.blocked_unsupported_claims[:5]:
                parts.append(f"⛔ لا تقل: {e.statement_ar}")

        if reasoning.limitations:
            parts.append("\n=== محدوديات ===")
            for lim in reasoning.limitations[:3]:
                parts.append(f"• {lim}")

        guidance = reasoning.policy_guidance
        if guidance:
            parts.append(f"\n=== تعليمات ===")
            parts.append(guidance.get("ar_instruction", ""))
            max_sent = guidance.get("max_explanation_sentences", 3)
            parts.append(f"الحد الأقصى للشرح: {max_sent} جمل")

        return "\n".join(parts) if parts else ""


# ══════════════════════════════════════════════════════════════
# Global Engine Singleton
# ══════════════════════════════════════════════════════════════

_ENGINE: Optional[LegalReasoningEngine] = None


def get_engine() -> LegalReasoningEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = LegalReasoningEngine()
    return _ENGINE
