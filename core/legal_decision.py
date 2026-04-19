# -*- coding: utf-8 -*-
"""
Legal Decision Intelligence — Final Layer
==========================================
1. LegalDecisionEngine — classifies answer safety posture
2. PreResponseValidator — blocks unsafe output
3. AnswerAuditTrail — internal audit record
4. ExplainabilityController — controls explanation depth
5. LegalConfidenceScore — evidence-bound confidence
6. build_safe_fallback — automatic downgrade for unsafe answers

Integration: runs AFTER advanced reasoning, BEFORE enrich_answer().
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

log = logging.getLogger("legal_decision")


# ══════════════════════════════════════════════════════════════
# Enums
# ══════════════════════════════════════════════════════════════

class DecisionType(str, Enum):
    DIRECT = "direct_legal_answer"
    QUALIFIED = "qualified_legal_answer"
    LIMITATION = "limitation_response"
    REFUSAL = "refusal_insufficient_evidence"
    CONFLICT = "conflict_unresolved_response"


class ExplainMode(str, Enum):
    MINIMAL = "minimal"
    STANDARD = "standard"
    CAUTIOUS = "cautious"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ══════════════════════════════════════════════════════════════
# 5. Legal Confidence Score
# ══════════════════════════════════════════════════════════════

@dataclass
class LegalConfidenceScore:
    evidence_strength: float = 0.0     # 0-1 based on direct evidence count
    hierarchy_certainty: float = 1.0   # 1.0 if no conflict or resolved; 0.5 if unresolved
    conflict_penalty: float = 0.0      # subtracted if conflicts exist
    topic_precision: float = 0.0       # how precisely topic was matched
    cross_domain_penalty: float = 0.0  # penalty for multi-domain complexity
    final_score: float = 0.0           # bounded 0.0-1.0

    @staticmethod
    def compute(direct_count: int, inference_count: int, blocked_count: int,
                conflicts: int, hierarchy_resolved: bool,
                topic: str, is_cross_domain: bool) -> "LegalConfidenceScore":
        s = LegalConfidenceScore()

        # Evidence strength: direct evidence is king
        total = direct_count + inference_count
        if total == 0:
            s.evidence_strength = 0.0
        else:
            s.evidence_strength = min(1.0, (direct_count * 0.15 + inference_count * 0.05))

        # Hierarchy certainty
        if conflicts > 0 and not hierarchy_resolved:
            s.hierarchy_certainty = 0.4
            s.conflict_penalty = min(0.3, conflicts * 0.1)
        elif conflicts > 0 and hierarchy_resolved:
            s.hierarchy_certainty = 0.8
            s.conflict_penalty = 0.05

        # Topic precision
        s.topic_precision = 0.8 if topic else 0.3

        # Cross-domain penalty
        s.cross_domain_penalty = 0.1 if is_cross_domain else 0.0

        # Final bounded score
        raw = (s.evidence_strength * 0.4
               + s.hierarchy_certainty * 0.25
               + s.topic_precision * 0.2
               + (1.0 - s.cross_domain_penalty) * 0.15
               - s.conflict_penalty)
        s.final_score = round(max(0.0, min(1.0, raw)), 3)
        return s


# ══════════════════════════════════════════════════════════════
# 1. Legal Decision Engine
# ══════════════════════════════════════════════════════════════

@dataclass
class DecisionResult:
    decision_type: DecisionType = DecisionType.DIRECT
    confidence: LegalConfidenceScore = field(default_factory=LegalConfidenceScore)
    can_answer_directly: bool = True
    must_qualify: bool = False
    must_refuse: bool = False
    limitation_reasons: list[str] = field(default_factory=list)
    audit_flags: list[str] = field(default_factory=list)


class LegalDecisionEngine:

    def decide(self, reasoning_result, query: str = "") -> DecisionResult:
        dr = getattr(reasoning_result, "direct_evidence", [])
        inf = getattr(reasoning_result, "controlled_inferences", [])
        blk = getattr(reasoning_result, "blocked_unsupported_claims", [])
        adv = getattr(reasoning_result, "advanced", None)

        conflicts = len(adv.conflict_flags) if adv else 0
        hierarchy_resolved = adv.hierarchy_applied if adv else False
        is_cross = bool(adv and adv.cross_domain_links and len(adv.cross_domain_links) > 1)
        topic = getattr(reasoning_result, "topic", "")
        domain = getattr(reasoning_result, "domain", "")

        # Compute confidence
        conf = LegalConfidenceScore.compute(
            len(dr), len(inf), len(blk),
            conflicts, hierarchy_resolved, topic, is_cross)

        result = DecisionResult(confidence=conf)
        result.audit_flags = []

        # Decision logic
        if conf.final_score >= 0.7 and len(dr) >= 2 and conflicts == 0:
            result.decision_type = DecisionType.DIRECT
            result.can_answer_directly = True

        elif conf.final_score >= 0.5 and (len(dr) >= 1 or len(inf) >= 2):
            result.decision_type = DecisionType.QUALIFIED
            result.must_qualify = True
            result.audit_flags.append("inference-based answer")

        elif conflicts > 0 and not hierarchy_resolved:
            result.decision_type = DecisionType.CONFLICT
            result.can_answer_directly = False
            result.must_qualify = True
            result.limitation_reasons.append("تعارض غير محلول في المصادر")

        elif len(dr) == 0 and len(inf) == 0:
            result.decision_type = DecisionType.REFUSAL
            result.must_refuse = True
            result.limitation_reasons.append("لا يوجد دليل كافٍ")

        else:
            result.decision_type = DecisionType.LIMITATION
            result.must_qualify = True
            if blk:
                result.limitation_reasons.append("بعض المعلومات محجوبة لعدم التأكد")

        log.info("[DECISION] type=%s conf=%.3f direct=%d infer=%d blocked=%d conflicts=%d",
                 result.decision_type.value, conf.final_score,
                 len(dr), len(inf), len(blk), conflicts)
        return result


# ══════════════════════════════════════════════════════════════
# 2. Pre-Response Validation Gate
# ══════════════════════════════════════════════════════════════

@dataclass
class ValidationResult:
    valid: bool = True
    violations: list[str] = field(default_factory=list)
    severity: Severity = Severity.LOW
    safe_fallback_mode: str = ""

    def is_safe(self) -> bool:
        return self.valid and self.severity in (Severity.LOW, Severity.MEDIUM)


_CERTAINTY_WORDS = ["بالتأكيد", "حتماً", "قطعاً", "بشكل مؤكد", "لا شك"]
_BLOCKED_LEAKS = ["ضعف المربوط", "قاتلة", "إدمان جسدي سريع", "أضرار قلبية"]


def validate_final_answer(answer: str, reasoning_result, decision: DecisionResult) -> ValidationResult:
    vr = ValidationResult()

    # Check: blocked evidence leaked into answer
    for leak in _BLOCKED_LEAKS:
        if leak in answer:
            vr.violations.append(f"blocked claim leaked: {leak}")
            vr.severity = Severity.HIGH

    # Check: overconfident wording when only inferences exist
    if decision.must_qualify:
        for word in _CERTAINTY_WORDS:
            if word in answer:
                vr.violations.append(f"certainty word '{word}' used in qualified answer")
                vr.severity = Severity.MEDIUM

    # Check: answer states something but no evidence supports it
    if decision.must_refuse and len(answer.strip()) > 50:
        if not any(w in answer for w in ["لا يمكن", "غير متوفر", "تعذر", "لا تتوفر"]):
            vr.violations.append("non-refusal answer produced despite REFUSAL decision")
            vr.severity = Severity.CRITICAL

    # Check: unresolved conflicts but decisive answer given
    if decision.decision_type == DecisionType.CONFLICT:
        if not any(w in answer for w in ["تعارض", "اختلاف", "لا يمكن الجزم"]):
            vr.violations.append("decisive answer given despite unresolved conflict")
            vr.severity = Severity.HIGH

    vr.valid = len(vr.violations) == 0
    if not vr.valid:
        vr.safe_fallback_mode = "qualified" if vr.severity != Severity.CRITICAL else "refusal"

    if vr.violations:
        log.warning("[VALIDATE] %d violations: %s", len(vr.violations), vr.violations[:3])
    return vr


# ══════════════════════════════════════════════════════════════
# 3. Answer Audit Trail
# ══════════════════════════════════════════════════════════════

@dataclass
class AnswerAuditTrail:
    query: str = ""
    detected_intent: str = ""
    reasoning_mode: str = ""
    domains_used: list[str] = field(default_factory=list)
    evidence_ids_used: list[str] = field(default_factory=list)
    blocked_ids: list[str] = field(default_factory=list)
    conflict_flags: int = 0
    hierarchy_applied: bool = False
    decision_type: str = ""
    confidence_score: float = 0.0
    validation_outcome: str = ""
    violations: list[str] = field(default_factory=list)
    final_answer_mode: str = ""
    timestamp: str = ""

    @staticmethod
    def build(query: str, reasoning_result, decision: DecisionResult,
              validation: ValidationResult) -> "AnswerAuditTrail":
        adv = getattr(reasoning_result, "advanced", None)
        dr = getattr(reasoning_result, "direct_evidence", [])
        blk = getattr(reasoning_result, "blocked_unsupported_claims", [])

        return AnswerAuditTrail(
            query=query[:200],
            detected_intent=getattr(reasoning_result, "question_type", ""),
            reasoning_mode=getattr(reasoning_result, "reasoning_mode", ""),
            domains_used=adv.cross_domain_links if adv else [getattr(reasoning_result, "domain", "")],
            evidence_ids_used=[e.entry_id for e in dr[:10] if hasattr(e, "entry_id")],
            blocked_ids=[e.entry_id for e in blk[:5] if hasattr(e, "entry_id")],
            conflict_flags=len(adv.conflict_flags) if adv else 0,
            hierarchy_applied=adv.hierarchy_applied if adv else False,
            decision_type=decision.decision_type.value,
            confidence_score=decision.confidence.final_score,
            validation_outcome="pass" if validation.valid else "fail",
            violations=validation.violations[:5],
            final_answer_mode=getattr(reasoning_result, "final_answer_mode", ""),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def compact_summary(self) -> str:
        return (f"[AUDIT] q={self.query[:40]} intent={self.detected_intent} "
                f"decision={self.decision_type} conf={self.confidence_score:.2f} "
                f"valid={self.validation_outcome}")

    def to_dict(self) -> dict:
        return {
            "query": self.query, "intent": self.detected_intent,
            "mode": self.reasoning_mode, "domains": self.domains_used,
            "evidence_count": len(self.evidence_ids_used),
            "blocked_count": len(self.blocked_ids),
            "conflicts": self.conflict_flags, "hierarchy": self.hierarchy_applied,
            "decision": self.decision_type, "confidence": self.confidence_score,
            "validation": self.validation_outcome, "violations": self.violations,
            "answer_mode": self.final_answer_mode, "timestamp": self.timestamp,
        }


# ══════════════════════════════════════════════════════════════
# 4. Explainability Controller
# ══════════════════════════════════════════════════════════════

class ExplainabilityController:

    def select_mode(self, decision: DecisionResult) -> ExplainMode:
        if decision.decision_type == DecisionType.DIRECT:
            return ExplainMode.MINIMAL
        if decision.decision_type == DecisionType.QUALIFIED:
            return ExplainMode.STANDARD
        return ExplainMode.CAUTIOUS

    def apply(self, answer: str, mode: ExplainMode, decision: DecisionResult) -> str:
        if mode == ExplainMode.CAUTIOUS and decision.limitation_reasons:
            limits = " | ".join(decision.limitation_reasons[:2])
            if limits and limits not in answer:
                answer = answer.rstrip() + f"\n\nملاحظة: {limits}"
        return answer


# ══════════════════════════════════════════════════════════════
# 7. Safe Fallback Builder
# ══════════════════════════════════════════════════════════════

def build_safe_fallback(answer: str, decision: DecisionResult,
                        validation: ValidationResult) -> str:
    if validation.severity == Severity.CRITICAL:
        return ("لا يمكن تقديم إجابة موثوقة على هذا السؤال بناءً على المصادر المتوفرة. "
                "أنصحك بمراجعة بوابة الميزان (almeezan.qa).")

    if decision.decision_type == DecisionType.CONFLICT:
        return (answer.rstrip() +
                "\n\nتنبيه: توجد مصادر متعارضة حول هذه المسألة. "
                "يُنصح بالتأكد من أحدث النصوص القانونية.")

    if decision.must_qualify and not validation.valid:
        # Strip certainty words
        cleaned = answer
        for word in _CERTAINTY_WORDS:
            cleaned = cleaned.replace(word, "بناءً على المصادر المتاحة")
        return cleaned

    return answer


# ══════════════════════════════════════════════════════════════
# 6. Integration Function
# ══════════════════════════════════════════════════════════════

def apply_legal_decision_layer(reasoning_result, answer: str,
                                query: str = "") -> tuple[str, AnswerAuditTrail]:
    """
    Main integration point. Called after reasoning, before final output.
    Returns (possibly_modified_answer, audit_trail).
    """
    engine = LegalDecisionEngine()
    decision = engine.decide(reasoning_result, query)

    validation = validate_final_answer(answer, reasoning_result, decision)

    if not validation.is_safe():
        answer = build_safe_fallback(answer, decision, validation)
        log.warning("[DECISION] fallback applied: %s", validation.violations[:2])

    explainer = ExplainabilityController()
    mode = explainer.select_mode(decision)
    answer = explainer.apply(answer, mode, decision)

    audit = AnswerAuditTrail.build(query, reasoning_result, decision, validation)
    log.info(audit.compact_summary())

    return answer, audit
