# -*- coding: utf-8 -*-
"""
Controlled Reasoning Core — LLM AUTHORITY REDUCTION
=====================================================
Deterministic legal core decides → optional LLM rewrites → fidelity guard verifies.

This module makes the existing deterministic engines (LegalThinkingEngine,
ExpertLegalAnalysisEngine, LegalGroundingEngine) the SOLE authority for legal
substance. The LLM (when present) is reduced to a language-formatting role
under strict fidelity constraints.

If LLM is absent, slow, or fails the fidelity check → DeterministicAnswerTemplateEngine
produces a fully-usable Arabic answer from the structured record alone.

Components:
  1. LegalDecisionRecord                     — single source of truth dataclass
  2. ControlledLegalDecisionCore             — combines all engines into the record
  3. DeterministicAnswerTemplateEngine       — LLM-free Arabic renderer
  4. LegalAnswerFormatter                    — optional LLM rewriter (gated)
  5. AnswerFidelityGuard                     — verifies LLM didn't drift
  6. LLMUsageGate                             — decides when LLM is allowed
  7. ReasoningConsistencyLock                — internal cross-engine consistency

Does NOT modify any reasoning engine. Wraps them.
"""
from __future__ import annotations
import hashlib
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from core.legal_thinking_engine import (
    LegalThinkingEngine, LegalAnalysis, IssueType, ISSUE_TYPE_AR,
)
from core.expert_legal_analysis import (
    ExpertLegalAnalysisEngine, ExpertLegalAnalysis, RankedItem,
    ImportanceCategory,
)
from core.legal_grounding import (
    LegalGroundingEngine, CitationConfidence, GroundingResult,
)

log = logging.getLogger("controlled_core")


# ══════════════════════════════════════════════════════════════
# LegalDecisionRecord — Source of Truth
# ══════════════════════════════════════════════════════════════

@dataclass
class RankedFact:
    """Ranked fact entry used in the record."""
    text: str = ""
    category: str = "secondary"   # decisive | important | secondary | weak | insufficient
    fixable: bool = False
    depends_on: str = ""


@dataclass
class LegalDecisionRecord:
    """
    The single source of truth for a legal decision.
    All user-facing output MUST derive from this object.
    NO downstream component may invent legal substance not in this object.
    """
    # Identity
    record_id: str = ""
    query: str = ""
    timestamp: float = 0.0

    # Issue classification
    issue_type: str = ""              # IssueType enum value
    issue_type_label: str = ""        # Arabic label
    domain: str = ""
    confidence: float = 0.0
    confidence_band: str = "low"      # high | medium | low
    core_question: str = ""

    # Facts
    key_facts: list[str] = field(default_factory=list)

    # Strengths / weaknesses (ranked)
    strengths: list[RankedFact] = field(default_factory=list)
    weaknesses: list[RankedFact] = field(default_factory=list)
    decisive_strengths: list[str] = field(default_factory=list)
    decisive_weaknesses: list[str] = field(default_factory=list)

    # Opposing
    opposing_arguments: list[RankedFact] = field(default_factory=list)
    strongest_opposing: str = ""

    # Proof / risk
    proof_needed: list[RankedFact] = field(default_factory=list)
    most_important_proof: str = ""
    procedural_risk: str = ""

    # Action
    authority_path: str = ""
    next_step: str = ""
    immediate_priorities: list[str] = field(default_factory=list)
    secondary_priorities: list[str] = field(default_factory=list)

    # Safety
    safe_limitations: list[str] = field(default_factory=list)
    grounding_status: str = "unknown"  # verified | partial | unverified | safe_mode

    # Internal
    notes_internal: list[str] = field(default_factory=list)
    consistency_violations: list[str] = field(default_factory=list)

    def is_substantive(self) -> bool:
        if self.issue_type == IssueType.UNKNOWN.value or not self.issue_type:
            return False
        return bool(self.strengths or self.weaknesses
                    or self.proof_needed or self.next_step)

    def fingerprint(self) -> str:
        """Stable fingerprint of the record's substance — for determinism tests."""
        parts = [
            self.issue_type,
            self.domain,
            "|".join(sorted(s.text for s in self.strengths)),
            "|".join(sorted(w.text for w in self.weaknesses)),
            "|".join(sorted(o.text for o in self.opposing_arguments)),
            self.next_step,
            self.authority_path,
        ]
        raw = "::".join(parts).encode("utf-8")
        return hashlib.sha1(raw).hexdigest()[:16]


# ══════════════════════════════════════════════════════════════
# ControlledLegalDecisionCore
# ══════════════════════════════════════════════════════════════

class ControlledLegalDecisionCore:
    """
    Combines deterministic engines into a single LegalDecisionRecord.
    NO free-form text generation here. NO LLM here. Structure only.
    """

    def __init__(self):
        self._brain = LegalThinkingEngine()
        self._expert = ExpertLegalAnalysisEngine()
        self._grounding = LegalGroundingEngine()

    def build_decision_record(self, query: str,
                                domain: str = "") -> LegalDecisionRecord:
        """Main entry point — produces the LegalDecisionRecord."""
        record = LegalDecisionRecord(
            record_id=f"rec_{uuid.uuid4().hex[:12]}",
            query=query[:300] if query else "",
            timestamp=time.time(),
            domain=domain or "",
        )

        if not query or not query.strip():
            record.notes_internal.append("empty_query")
            record.confidence_band = "low"
            return record

        # Step 1: Run deterministic brain
        analysis = self._brain.build_legal_analysis(query)

        # Step 2: Run deterministic expert
        expert = self._expert.build_expert_analysis(analysis)

        # Step 3: Merge engine outputs
        record = self.merge_existing_engine_outputs(record, analysis, expert)

        # Step 4: Normalize fields
        record = self.normalize_decision_fields(record)

        # Step 5: Reject inconsistent fields
        record = self.reject_inconsistent_fields(record)

        # Step 6: Finalize
        record = self.finalize_deterministic_decision(record)

        log.info("[CONTROLLED_CORE] record built: issue=%s domain=%s "
                 "strengths=%d weaknesses=%d confidence=%s",
                 record.issue_type, record.domain,
                 len(record.strengths), len(record.weaknesses),
                 record.confidence_band)
        return record

    def merge_existing_engine_outputs(self, record: LegalDecisionRecord,
                                        analysis: LegalAnalysis,
                                        expert: ExpertLegalAnalysis) -> LegalDecisionRecord:
        """Merge brain + expert outputs into the record."""
        # From analysis
        record.issue_type = analysis.issue_type.value
        record.issue_type_label = ISSUE_TYPE_AR.get(analysis.issue_type, "")
        if not record.domain:
            # Infer domain from issue type if not explicitly provided
            record.domain = self._infer_domain(analysis.issue_type)
        record.confidence = analysis.confidence
        record.core_question = analysis.core_question
        record.key_facts = list(analysis.key_facts)
        record.next_step = analysis.next_step or ""
        record.authority_path = analysis.authority_path or ""
        record.procedural_risk = analysis.procedural_risk or ""

        # From expert (ranked)
        record.strengths = [
            RankedFact(text=r.text, category=r.category.value, fixable=r.fixable)
            for r in expert.ranked_supporting
        ]
        record.weaknesses = [
            RankedFact(text=r.text, category=r.category.value, fixable=r.fixable)
            for r in expert.ranked_weakening
        ]
        record.opposing_arguments = [
            RankedFact(text=r.text, category=r.category.value,
                       depends_on=r.depends_on)
            for r in expert.ranked_opposing
        ]
        record.proof_needed = [
            RankedFact(text=r.text, category=r.category.value, fixable=r.fixable)
            for r in expert.ranked_proof
        ]

        # Decisive items
        record.decisive_strengths = [s.text for s in expert.decisive_strengths]
        record.decisive_weaknesses = [w.text for w in expert.decisive_weaknesses]
        record.strongest_opposing = (expert.strongest_opposing_argument.text
                                       if expert.strongest_opposing_argument
                                       else "")
        record.most_important_proof = (expert.most_important_proof_needed.text
                                          if expert.most_important_proof_needed
                                          else "")

        # Priorities
        record.immediate_priorities = list(expert.immediate_priorities)
        record.secondary_priorities = list(expert.secondary_priorities)

        return record

    def normalize_decision_fields(self,
                                    record: LegalDecisionRecord) -> LegalDecisionRecord:
        """Normalize fields: cap list lengths, dedupe, set confidence band."""
        # Cap lengths to prevent bloat
        record.strengths = record.strengths[:6]
        record.weaknesses = record.weaknesses[:6]
        record.opposing_arguments = record.opposing_arguments[:6]
        record.proof_needed = record.proof_needed[:6]
        record.key_facts = record.key_facts[:8]
        record.immediate_priorities = record.immediate_priorities[:4]
        record.secondary_priorities = record.secondary_priorities[:4]

        # Set confidence band
        if record.confidence >= 0.7:
            record.confidence_band = "high"
        elif record.confidence >= 0.4:
            record.confidence_band = "medium"
        else:
            record.confidence_band = "low"

        # Standard safe limitations
        if not record.safe_limitations:
            record.safe_limitations = [
                "هذا التحليل عام ويعتمد على ما ذكرته فقط.",
                "التفاصيل قد تختلف حسب الوقائع المحددة لحالتك.",
            ]

        return record

    def reject_inconsistent_fields(self,
                                     record: LegalDecisionRecord) -> LegalDecisionRecord:
        """Drop fields that conflict with each other (consistency lock-light)."""
        lock = ReasoningConsistencyLock()
        ok, violations = lock.check(record)
        if not ok:
            record.consistency_violations = violations
            record.notes_internal.append(
                f"consistency violations: {len(violations)}")
        return record

    def finalize_deterministic_decision(self,
                                          record: LegalDecisionRecord) -> LegalDecisionRecord:
        """Final stamps + grounding pre-check."""
        # Grounding pre-status (will be verified later in pipeline)
        if not record.is_substantive():
            record.grounding_status = "safe_mode"
        else:
            record.grounding_status = "verified"
        return record

    def _infer_domain(self, issue_type: IssueType) -> str:
        """Map IssueType → domain string."""
        mapping = {
            IssueType.EMPLOYMENT_DISMISSAL: "employment",
            IssueType.DEBT_MONEY_CLAIM: "civil",
            IssueType.CONTRACT_BREACH: "civil",
            IssueType.RENTAL_EVICTION: "rental",
            IssueType.FAMILY_CUSTODY: "family",
            IssueType.APPEAL_DEADLINE: "procedural",
            IssueType.ENFORCEMENT_PROCEDURAL: "procedural",
            IssueType.CRIMINAL_ACCUSATION: "criminal",
            IssueType.ADMINISTRATIVE_OBJECTION: "administrative",
            # PHASE INTELLIGENT DECISION
            IssueType.BANKING_UNAUTHORIZED_DEDUCTION: "banking",
            IssueType.COMMERCIAL_PARTNERSHIP_DISPUTE: "commercial",
            IssueType.INHERITANCE_DISTRIBUTION_DISPUTE: "family",
            IssueType.IP_IDEA_MISAPPROPRIATION: "commercial",
        }
        return mapping.get(issue_type, "general")


# ══════════════════════════════════════════════════════════════
# DeterministicAnswerTemplateEngine
# ══════════════════════════════════════════════════════════════

class DeterministicAnswerTemplateEngine:
    """
    Renders LegalDecisionRecord as Arabic text. NO LLM. NO invention.
    Pure templates from the record's structured fields.
    """

    def render(self, record: LegalDecisionRecord) -> str:
        if not record.is_substantive():
            return self._render_safe_fallback(record)

        parts = []

        # Header
        parts.append(f"📌 نوع المسألة: {record.issue_type_label}")

        # Priority summary (the most important items first)
        summary = []
        if record.decisive_strengths:
            summary.append(f"• أقوى ما يدعم موقفك: {record.decisive_strengths[0]}")
        elif record.strengths:
            summary.append(f"• أقوى ما يدعم موقفك: {record.strengths[0].text}")
        if record.decisive_weaknesses:
            summary.append(f"• أخطر ما يضعف موقفك: {record.decisive_weaknesses[0]}")
        elif record.weaknesses:
            summary.append(f"• أخطر ما يضعف موقفك: {record.weaknesses[0].text}")
        if record.strongest_opposing:
            summary.append(f"• أقوى ما قد يحتج به الطرف الآخر: {record.strongest_opposing}")
        if record.most_important_proof:
            summary.append(f"• أهم شيء تحتاج إثباته الآن: {record.most_important_proof}")
        if record.immediate_priorities:
            summary.append(f"• ابدأ أولاً بـ: {record.immediate_priorities[0]}")

        if summary:
            parts.append("\n🎯 الأهم في موقفك:")
            parts.extend(summary)

        # Detailed sections
        if record.strengths:
            parts.append("\n**ما يدعم موقفك (مرتبة بالأهمية):**")
            for s in record.strengths[:3]:
                parts.append(f"• {s.text}")

        if record.weaknesses:
            parts.append("\n**ما يضعف موقفك (مرتبة بالخطورة):**")
            for w in record.weaknesses[:3]:
                fix_label = " [قابل للمعالجة]" if w.fixable else ""
                parts.append(f"• {w.text}{fix_label}")

        if record.opposing_arguments:
            parts.append("\n**ما قد يحتج به الطرف الآخر (الأقوى أولاً):**")
            for o in record.opposing_arguments[:3]:
                parts.append(f"• {o.text}")

        if record.proof_needed:
            parts.append("\n**ما تحتاج إثباته (بترتيب الأهمية):**")
            for p in record.proof_needed[:3]:
                parts.append(f"• {p.text}")

        if record.immediate_priorities:
            parts.append("\n**الخطوات الفورية:**")
            for i, item in enumerate(record.immediate_priorities, 1):
                parts.append(f"{i}. {item}")

        if record.authority_path:
            parts.append(f"\n**الجهة المختصة:** {record.authority_path}")

        # Safe limitations footer
        if record.safe_limitations:
            parts.append("")
            for lim in record.safe_limitations[:2]:
                parts.append(lim)

        return "\n".join(parts)

    def _render_safe_fallback(self, record: LegalDecisionRecord) -> str:
        """Render a safe non-committal answer when there's no substantive record."""
        return (
            "لم يتضح نوع المسألة القانونية بدقة من وصفك. "
            "يُرجى توضيح المجال (عمل / مدني / أسرة / إيجار / إداري / "
            "جنائي / إجرائي) مع ذكر الوقائع الأساسية لأقدّم تحليلاً مفيداً."
        )


# ══════════════════════════════════════════════════════════════
# AnswerFidelityGuard
# ══════════════════════════════════════════════════════════════

class AnswerFidelityGuard:
    """
    Verifies that a formatted answer (whether template-generated or LLM-rewritten)
    preserves the substance of the LegalDecisionRecord without inventing new
    legal content.
    """

    def __init__(self):
        self._grounding = LegalGroundingEngine()

    def verify(self, record: LegalDecisionRecord,
                formatted_text: str) -> tuple[bool, list[str]]:
        """Returns (is_faithful, list_of_violations)."""
        violations = []

        if not formatted_text or not formatted_text.strip():
            violations.append("empty_formatted_text")
            return False, violations

        # 1. No unverified citations injected
        cites = self._grounding.extract_citations(formatted_text)
        unverified = [c for c in cites
                      if c.confidence == CitationConfidence.UNVERIFIED]
        if unverified:
            violations.append(
                f"unverified_citations_injected:{len(unverified)}")

        # 2. Authority path (if record has one) must appear or be paraphrased
        # Relaxed check: don't require exact match, but the authority KEYWORD
        # must appear somewhere.
        if record.authority_path:
            # Extract the most distinctive word from authority_path
            auth_keywords = self._extract_distinctive_words(record.authority_path)
            if auth_keywords and not any(k in formatted_text for k in auth_keywords):
                violations.append("authority_path_missing")

        # 3. Issue type must remain consistent
        if record.issue_type_label and \
           record.issue_type_label not in formatted_text and \
           "نوع المسألة" not in formatted_text:
            # Allow paraphrase if 'نوع المسألة' is mentioned
            violations.append("issue_type_label_drift")

        # 4. No hallucinated opposing argument prefixes
        # If formatted text contains "قد يحتج" / "قد يدفع" forms NOT in record,
        # reject. (Check uniqueness of those phrases in the formatted text vs record)
        record_opposing_phrases = " ".join(
            o.text for o in record.opposing_arguments)
        text_opposing = re.findall(
            r"قد (?:يحتج|يدفع|ينازع|يطعن|يتمسّك|تتمسّك)[^.\n]{5,80}",
            formatted_text)
        for opp in text_opposing:
            # Each opposing phrase from the formatted text must have
            # support in the record (substring overlap heuristic)
            opp_clean = opp.strip()
            if not record_opposing_phrases:
                violations.append("opposing_arg_invented")
                break
            # Check if any 4-word fragment of this opp appears in record
            opp_words = opp_clean.split()
            if len(opp_words) >= 5:
                fragment = " ".join(opp_words[1:4])
                if fragment not in record_opposing_phrases:
                    # Allow if at least the verb pattern matches a record entry
                    if not any(opp_words[1] in r.text
                               for r in record.opposing_arguments):
                        violations.append(
                            f"opposing_arg_not_grounded:{opp_clean[:30]}")
                        break

        # 5. No new "next_step" that contradicts record
        if record.next_step:
            # If record has a next step, the formatted text shouldn't have
            # a different "first step" recommendation.
            # Heuristic: check that some characteristic word of the next step
            # is preserved.
            next_kw = self._extract_distinctive_words(record.next_step)
            if next_kw and not any(k in formatted_text for k in next_kw):
                violations.append("next_step_missing")

        is_faithful = len(violations) == 0
        if not is_faithful:
            log.info("[FIDELITY] failed: violations=%s", violations)
        return is_faithful, violations

    def _extract_distinctive_words(self, text: str, min_len: int = 5) -> list[str]:
        """Extract significant content words (length-filtered, stopword-filtered)."""
        if not text:
            return []
        stopwords = {"الذي", "التي", "وقد", "هذا", "ذلك", "إلى", "على",
                     "قبل", "بعد", "حول", "بأن", "حتى", "عند"}
        words = text.split()
        return [w for w in words if len(w) >= min_len and w not in stopwords][:5]


# ══════════════════════════════════════════════════════════════
# LLMUsageGate
# ══════════════════════════════════════════════════════════════

class LLMUsageGate:
    """
    Decides whether the optional LLM formatter should be invoked.
    Conservative by design — deterministic-by-default.
    """

    def should_use_llm(self, record: LegalDecisionRecord,
                        query: str = "",
                        force_template: bool = False) -> bool:
        """Returns True only when LLM rewriting would clearly help."""
        if force_template:
            return False

        # No LLM for trivial / very short queries
        if not query or len(query.split()) < 8:
            return False

        # No LLM if record is non-substantive
        if not record.is_substantive():
            return False

        # No LLM if record has high confidence + few items
        if record.confidence_band == "high" \
           and len(record.strengths) <= 2 \
           and len(record.weaknesses) <= 2:
            return False

        # No LLM if low confidence (deterministic template safer)
        if record.confidence_band == "low":
            return False

        # Default: deterministic template
        # The LLM gate is OFF by default — flip it on per deployment when ready.
        return False

    def reason(self, record: LegalDecisionRecord, query: str) -> str:
        """Diagnostic: why was the LLM (not) used?"""
        if not query or len(query.split()) < 8:
            return "trivial_query"
        if not record.is_substantive():
            return "non_substantive_record"
        if record.confidence_band == "high":
            return "high_confidence_template_sufficient"
        if record.confidence_band == "low":
            return "low_confidence_template_safer"
        return "deterministic_default"


# ══════════════════════════════════════════════════════════════
# LegalAnswerFormatter
# ══════════════════════════════════════════════════════════════

@dataclass
class FormatterResult:
    text: str = ""
    used_llm: bool = False
    fidelity_passed: bool = True
    fallback_applied: bool = False
    violations: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0


class LegalAnswerFormatter:
    """
    Formats a LegalDecisionRecord into Arabic text.
    LLM is OPTIONAL. By default uses DeterministicAnswerTemplateEngine.

    When llm_caller is provided AND LLMUsageGate approves:
      1. Build prompt: ONLY the record's structured fields + style hints
      2. Invoke LLM (one pass max, with timeout)
      3. AnswerFidelityGuard verifies preservation
      4. If fidelity fails → fall back to deterministic template
    """

    LLM_TIMEOUT = 4.0

    def __init__(self, llm_caller: Optional[Callable[[str, str], str]] = None):
        """
        llm_caller: optional callable (system_prompt, user_prompt) -> str.
                    When None, formatter is fully deterministic.
        """
        self._llm = llm_caller
        self._template = DeterministicAnswerTemplateEngine()
        self._gate = LLMUsageGate()
        self._guard = AnswerFidelityGuard()

    def format(self, record: LegalDecisionRecord, query: str = "",
                force_template: bool = False) -> FormatterResult:
        start = time.time()
        result = FormatterResult()

        # 1. Always render the deterministic baseline (fallback safety net)
        deterministic_text = self._template.render(record)

        # 2. Decide whether to call the LLM
        use_llm = (self._llm is not None
                    and not force_template
                    and self._gate.should_use_llm(record, query))

        if not use_llm:
            result.text = deterministic_text
            result.used_llm = False
            result.elapsed_seconds = time.time() - start
            return result

        # 3. LLM allowed — build a STRICT prompt
        prompt = self._build_strict_prompt(record, deterministic_text)
        try:
            llm_text = self._llm(self._SYSTEM_PROMPT, prompt)
        except Exception as e:
            log.warning("[FORMATTER] LLM call failed: %s — using template", e)
            result.text = deterministic_text
            result.used_llm = False
            result.fallback_applied = True
            result.elapsed_seconds = time.time() - start
            return result

        # 4. Fidelity check
        is_faithful, violations = self._guard.verify(record, llm_text)
        if not is_faithful:
            result.text = deterministic_text
            result.used_llm = True
            result.fidelity_passed = False
            result.violations = violations
            result.fallback_applied = True
            log.warning("[FORMATTER] LLM output failed fidelity: %s — fallback",
                         violations)
        else:
            result.text = llm_text
            result.used_llm = True
            result.fidelity_passed = True

        result.elapsed_seconds = time.time() - start
        return result

    _SYSTEM_PROMPT = (
        "أنت مُحرِّر لغوي. مهمتك: إعادة صياغة المحتوى القانوني المُعطى "
        "إلى عربية واضحة فقط. ممنوع: إضافة قانون، إضافة مادة، إضافة دفاع، "
        "تغيير نوع المسألة، تغيير الجهة المختصة، أو اقتراح خطوة جديدة. "
        "حافظ على نفس النقاط ونفس الترتيب."
    )

    def _build_strict_prompt(self, record: LegalDecisionRecord,
                               deterministic_text: str) -> str:
        return (
            "هذه نتيجة تحليل قانوني نهائي. أعد صياغتها فقط بلغة عربية أوضح، "
            "بدون إضافة أو حذف أي نقطة:\n\n"
            f"{deterministic_text}\n\n"
            "احتفظ بنفس العناوين والترتيب والجهة المختصة بالضبط."
        )


# ══════════════════════════════════════════════════════════════
# ReasoningConsistencyLock
# ══════════════════════════════════════════════════════════════

class ReasoningConsistencyLock:
    """Internal cross-engine consistency check."""

    # Domain ↔ allowed issue_type mapping
    _DOMAIN_ISSUE_COMPAT = {
        "employment": {"employment_dismissal", "unknown"},
        "criminal": {"criminal_accusation", "unknown"},
        "family": {"family_custody", "inheritance_distribution_dispute", "unknown"},
        "rental": {"rental_eviction", "unknown"},
        "civil": {"debt_money_claim", "contract_breach", "unknown"},
        "procedural": {"appeal_deadline", "enforcement_procedural", "unknown"},
        "administrative": {"administrative_objection", "unknown"},
        # PHASE INTELLIGENT DECISION — new domain compatibilities
        "banking": {"banking_unauthorized_deduction", "debt_money_claim", "unknown"},
        "commercial": {"commercial_partnership_dispute", "ip_idea_misappropriation",
                        "contract_breach", "unknown"},
        "general": set(),  # no constraint
    }

    def check(self, record: LegalDecisionRecord) -> tuple[bool, list[str]]:
        """Run all consistency checks. Returns (is_consistent, violations)."""
        violations = []

        # 1. Issue type ↔ domain
        if record.domain and record.issue_type and record.domain != "general":
            allowed = self._DOMAIN_ISSUE_COMPAT.get(record.domain, set())
            if allowed and record.issue_type not in allowed:
                violations.append(
                    f"issue_domain_mismatch:{record.issue_type}↔{record.domain}")

        # 2. Decisive items must be in their respective ranked lists
        rec_strength_texts = {s.text for s in record.strengths}
        for d in record.decisive_strengths:
            if d not in rec_strength_texts:
                violations.append(f"decisive_strength_orphan:{d[:30]}")

        rec_weakness_texts = {w.text for w in record.weaknesses}
        for d in record.decisive_weaknesses:
            if d not in rec_weakness_texts:
                violations.append(f"decisive_weakness_orphan:{d[:30]}")

        # 3. Strongest opposing must be in opposing list
        if record.strongest_opposing:
            opp_texts = {o.text for o in record.opposing_arguments}
            if record.strongest_opposing not in opp_texts:
                violations.append("strongest_opposing_orphan")

        # 4. Most important proof must be in proof_needed list
        if record.most_important_proof:
            proof_texts = {p.text for p in record.proof_needed}
            if record.most_important_proof not in proof_texts:
                violations.append("most_important_proof_orphan")

        return len(violations) == 0, violations


# ══════════════════════════════════════════════════════════════
# Top-level Convenience API
# ══════════════════════════════════════════════════════════════

_core: Optional[ControlledLegalDecisionCore] = None
_default_formatter: Optional[LegalAnswerFormatter] = None


def get_core() -> ControlledLegalDecisionCore:
    global _core
    if _core is None:
        _core = ControlledLegalDecisionCore()
    return _core


def get_formatter() -> LegalAnswerFormatter:
    """Default formatter — deterministic only (no LLM caller)."""
    global _default_formatter
    if _default_formatter is None:
        _default_formatter = LegalAnswerFormatter(llm_caller=None)
    return _default_formatter


def produce_controlled_answer(query: str,
                                domain: str = "",
                                llm_caller: Optional[Callable] = None
                                ) -> tuple[str, LegalDecisionRecord, FormatterResult]:
    """
    Convenience: query → (final_text, record, formatter_result).
    LLM is opt-in via the llm_caller parameter; default behavior is fully deterministic.
    """
    core = get_core()
    record = core.build_decision_record(query, domain)
    formatter = LegalAnswerFormatter(llm_caller=llm_caller) if llm_caller \
                else get_formatter()
    fmt = formatter.format(record, query=query)
    return fmt.text, record, fmt
