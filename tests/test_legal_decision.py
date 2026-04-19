# -*- coding: utf-8 -*-
"""Tests for Legal Decision Intelligence Layer."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.legal_decision import (
    LegalDecisionEngine, LegalConfidenceScore, DecisionType, DecisionResult,
    validate_final_answer, ExplainabilityController, ExplainMode,
    AnswerAuditTrail, build_safe_fallback, Severity, ValidationResult,
)
from core.advanced_reasoning import AdvancedReasoningData
from core.evidence_registry import EvidenceEntry, SupportLevel


def _make_result(direct=3, infer=1, blocked=0, conflicts=0, hierarchy=False, topic="salary", domain="salary"):
    """Build a mock ReasoningResult-like object."""
    class R: pass
    r = R()
    r.direct_evidence = [EvidenceEntry(entry_id=f"d{i}", statement_ar="test", domain=domain, support_level=SupportLevel.DIRECT_EVIDENCE.value) for i in range(direct)]
    r.controlled_inferences = [EvidenceEntry(entry_id=f"i{i}", statement_ar="test", domain=domain, support_level=SupportLevel.CONTROLLED_INFERENCE.value) for i in range(infer)]
    r.blocked_unsupported_claims = [EvidenceEntry(entry_id=f"b{i}", statement_ar="test", domain=domain, support_level=SupportLevel.UNSUPPORTED_BLOCKED.value) for i in range(blocked)]
    r.question_type = "structured_factual"
    r.reasoning_mode = "structured_factual"
    r.topic = topic
    r.domain = domain
    r.final_answer_mode = "deterministic"
    adv = AdvancedReasoningData()
    adv.conflict_flags = [{"type": "negation"}] * conflicts
    adv.hierarchy_applied = hierarchy
    adv.cross_domain_links = [domain]
    r.advanced = adv
    return r


# ══ Confidence Score ══

def test_confidence_high():
    s = LegalConfidenceScore.compute(5, 2, 0, 0, False, "salary", False)
    assert s.final_score >= 0.7

def test_confidence_low_no_evidence():
    s = LegalConfidenceScore.compute(0, 0, 3, 0, False, "", False)
    assert s.final_score < 0.5  # Low but not zero due to default hierarchy certainty
    assert s.evidence_strength == 0.0

def test_confidence_conflict_penalty():
    s1 = LegalConfidenceScore.compute(3, 1, 0, 0, False, "salary", False)
    s2 = LegalConfidenceScore.compute(3, 1, 0, 2, False, "salary", False)
    assert s2.final_score < s1.final_score


# ══ Decision Engine ══

def test_direct_answer():
    r = _make_result(direct=5, infer=1, blocked=0, conflicts=0)
    d = LegalDecisionEngine().decide(r)
    assert d.decision_type == DecisionType.DIRECT
    assert d.can_answer_directly is True

def test_qualified_answer():
    r = _make_result(direct=1, infer=3, blocked=1)
    d = LegalDecisionEngine().decide(r)
    assert d.decision_type in (DecisionType.DIRECT, DecisionType.QUALIFIED)

def test_refusal_no_evidence():
    r = _make_result(direct=0, infer=0, blocked=2)
    d = LegalDecisionEngine().decide(r)
    assert d.decision_type == DecisionType.REFUSAL
    assert d.must_refuse is True

def test_conflict_unresolved():
    r = _make_result(direct=2, infer=1, conflicts=2, hierarchy=False)
    d = LegalDecisionEngine().decide(r)
    assert d.decision_type == DecisionType.CONFLICT

def test_conflict_resolved():
    r = _make_result(direct=3, infer=1, conflicts=1, hierarchy=True)
    d = LegalDecisionEngine().decide(r)
    assert d.decision_type != DecisionType.CONFLICT


# ══ Validation Gate ══

def test_validate_clean():
    r = _make_result(direct=3)
    d = DecisionResult(decision_type=DecisionType.DIRECT)
    v = validate_final_answer("الدرجة السابعة: 6,000 ريال", r, d)
    assert v.valid is True

def test_validate_blocked_leak():
    r = _make_result(direct=3)
    d = DecisionResult(decision_type=DecisionType.DIRECT)
    v = validate_final_answer("الإجمالي قد يصل إلى ضعف المربوط", r, d)
    assert v.valid is False
    assert any("blocked" in v for v in v.violations)

def test_validate_certainty_in_qualified():
    r = _make_result(direct=1, infer=2)
    d = DecisionResult(decision_type=DecisionType.QUALIFIED, must_qualify=True)
    v = validate_final_answer("بالتأكيد يحق لك التعويض", r, d)
    assert v.valid is False

def test_validate_refusal_but_long_answer():
    r = _make_result(direct=0, infer=0)
    d = DecisionResult(decision_type=DecisionType.REFUSAL, must_refuse=True)
    v = validate_final_answer("يحق للموظف الحصول على راتب أساسي مع بدلات متعددة وفقاً للقانون", r, d)
    assert v.valid is False
    assert v.severity == Severity.CRITICAL


# ══ Explainability ══

def test_explain_minimal():
    d = DecisionResult(decision_type=DecisionType.DIRECT)
    ec = ExplainabilityController()
    assert ec.select_mode(d) == ExplainMode.MINIMAL

def test_explain_cautious():
    d = DecisionResult(decision_type=DecisionType.CONFLICT,
                        limitation_reasons=["تعارض في المصادر"])
    ec = ExplainabilityController()
    assert ec.select_mode(d) == ExplainMode.CAUTIOUS
    answer = ec.apply("الجواب هنا", ExplainMode.CAUTIOUS, d)
    assert "ملاحظة" in answer


# ══ Audit Trail ══

def test_audit_trail():
    r = _make_result(direct=3, infer=1)
    d = LegalDecisionEngine().decide(r)
    v = validate_final_answer("test answer", r, d)
    audit = AnswerAuditTrail.build("كم الراتب", r, d, v)
    assert audit.query == "كم الراتب"
    assert audit.decision_type == d.decision_type.value
    assert audit.timestamp != ""
    summary = audit.compact_summary()
    assert "[AUDIT]" in summary


# ══ Safe Fallback ══

def test_fallback_critical():
    d = DecisionResult(decision_type=DecisionType.REFUSAL, must_refuse=True)
    v = ValidationResult(valid=False, severity=Severity.CRITICAL)
    fb = build_safe_fallback("wrong answer here", d, v)
    assert "لا يمكن" in fb

def test_fallback_strips_certainty():
    d = DecisionResult(decision_type=DecisionType.QUALIFIED, must_qualify=True)
    v = ValidationResult(valid=False, violations=["certainty word"], severity=Severity.MEDIUM)
    fb = build_safe_fallback("بالتأكيد يحق لك", d, v)
    assert "بالتأكيد" not in fb


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS: {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL: {t.__name__} — {e}")
            failed += 1
    print(f"\n  {passed}/{passed+failed} passed")
