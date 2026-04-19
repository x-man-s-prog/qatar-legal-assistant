# -*- coding: utf-8 -*-
"""Tests for Knowledge Governance + Production Hardening + Commercial Readiness."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.governance import (
    KnowledgeMemoryGovernor, KnowledgeState,
    EvidenceLifecycleManager, EvidenceState,
    LawUpdateSafetyChecker, LawUpdateImpactReport, RiskLevel,
    ProductionSafetyGuard, ProductionSafetyResult,
    CommercialPolicyGate, UserTier,
)
from core.evidence_registry import EvidenceEntry, EvidenceRegistry, SupportLevel
from core.legal_decision import DecisionResult, DecisionType, LegalConfidenceScore


def _make_registry():
    r = EvidenceRegistry()
    r.register(EvidenceEntry(
        entry_id="sal_001", statement_ar="المربوط الأساسي", domain="salary",
        support_level=SupportLevel.DIRECT_EVIDENCE.value,
        source_law="قانون الموارد البشرية المدنية رقم 15 لسنة 2016"))
    r.register(EvidenceEntry(
        entry_id="sal_002", statement_ar="بدل السكن", domain="salary",
        support_level=SupportLevel.DIRECT_EVIDENCE.value,
        source_law="قانون الموارد البشرية المدنية رقم 15 لسنة 2016"))
    r.register(EvidenceEntry(
        entry_id="pen_001", statement_ar="عقوبة الاتجار", domain="penalty",
        support_level=SupportLevel.DIRECT_EVIDENCE.value,
        source_law="قانون مكافحة المخدرات رقم 9 لسنة 1987"))
    return r


def _make_reasoning(direct=2, blocked=0):
    class R: pass
    r = R()
    r.direct_evidence = [EvidenceEntry(entry_id=f"d{i}", statement_ar="test", domain="salary",
                          support_level=SupportLevel.DIRECT_EVIDENCE.value) for i in range(direct)]
    r.controlled_inferences = []
    r.blocked_unsupported_claims = [EvidenceEntry(entry_id=f"b{i}", statement_ar="ضعف المربوط",
                                    domain="salary", support_level=SupportLevel.UNSUPPORTED_BLOCKED.value) for i in range(blocked)]
    return r


# ══ Knowledge Memory Governor ══

def test_approve_knowledge():
    g = KnowledgeMemoryGovernor()
    rec = g.approve("k1", title="test", domain="salary")
    assert rec.state == KnowledgeState.APPROVED.value
    assert g.is_usable("k1") is True

def test_deprecate_knowledge():
    g = KnowledgeMemoryGovernor()
    g.approve("k1", title="test")
    g.deprecate("k1", reason="law changed")
    assert g.is_usable("k1") is False

def test_supersede_knowledge():
    g = KnowledgeMemoryGovernor()
    g.approve("k1", title="old")
    g.approve("k2", title="new")
    g.supersede("k1", "k2")
    rec = g.get_history("k1")
    assert rec.state == KnowledgeState.SUPERSEDED.value
    assert rec.superseded_by == "k2"

def test_disputed_knowledge():
    g = KnowledgeMemoryGovernor()
    g.approve("k1", title="test")
    g.mark_disputed("k1", reason="conflicting sources")
    assert g.is_usable("k1") is False

def test_active_knowledge_only():
    g = KnowledgeMemoryGovernor()
    g.approve("k1", title="active", domain="salary")
    g.approve("k2", title="also active", domain="salary")
    g.deprecate("k2")
    active = g.get_active(domain="salary")
    assert len(active) == 1
    assert active[0].knowledge_id == "k1"

def test_knowledge_history():
    g = KnowledgeMemoryGovernor()
    g.approve("k1", title="test")
    g.deprecate("k1")
    rec = g.get_history("k1")
    assert rec is not None
    assert rec.state == KnowledgeState.DEPRECATED.value


# ══ Evidence Lifecycle ══

def test_evidence_active():
    lm = EvidenceLifecycleManager()
    lm.activate("e1")
    assert lm.is_active("e1") is True

def test_evidence_deprecated():
    lm = EvidenceLifecycleManager()
    lm.activate("e1")
    lm.deprecate("e1", reason="law repealed")
    assert lm.is_deprecated("e1") is True
    assert lm.is_active("e1") is False

def test_evidence_conflicted():
    lm = EvidenceLifecycleManager()
    lm.mark_conflicted("e1", details="contradictory sources")
    assert lm.get_state("e1") == EvidenceState.CONFLICTED.value

def test_evidence_unknown_is_active():
    lm = EvidenceLifecycleManager()
    assert lm.is_active("unknown") is True


# ══ Law Update Safety ══

def test_law_update_impact():
    r = _make_registry()
    checker = LawUpdateSafetyChecker(r)
    report = checker.simulate_law_change("قانون الموارد البشرية المدنية")
    assert len(report.affected_evidence_ids) >= 2
    assert "salary" in report.affected_domains

def test_law_update_no_impact():
    r = _make_registry()
    checker = LawUpdateSafetyChecker(r)
    report = checker.simulate_law_change("قانون غير موجود")
    assert len(report.affected_evidence_ids) == 0
    assert report.risk_level == RiskLevel.LOW.value


# ══ Production Safety Guard ══

def test_production_safe():
    lm = EvidenceLifecycleManager()
    guard = ProductionSafetyGuard(lm)
    r = _make_reasoning(direct=2)
    result = guard.check(r, "الدرجة السابعة: 6,000 ريال", audit={"exists": True})
    assert result.safe is True

def test_production_deprecated_evidence():
    lm = EvidenceLifecycleManager()
    lm.deprecate("d0", reason="law changed")
    guard = ProductionSafetyGuard(lm)
    r = _make_reasoning(direct=2)
    result = guard.check(r, "test answer", audit={"exists": True})
    assert result.safe is False
    assert any("deprecated" in v for v in result.violations)

def test_production_no_audit():
    lm = EvidenceLifecycleManager()
    guard = ProductionSafetyGuard(lm)
    r = _make_reasoning(direct=2)
    result = guard.check(r, "test answer", audit=None)
    assert result.safe is False
    assert any("audit" in v for v in result.violations)

def test_production_blocked_leak():
    lm = EvidenceLifecycleManager()
    guard = ProductionSafetyGuard(lm)
    r = _make_reasoning(direct=2, blocked=1)
    result = guard.check(r, "الإجمالي ضعف المربوط", audit={"exists": True})
    assert result.safe is False
    assert result.blocked is True


# ══ Commercial Policy Gate ══

def test_public_softens_certainty():
    gate = CommercialPolicyGate()
    d = DecisionResult(confidence=LegalConfidenceScore(final_score=0.8))
    answer = gate.apply("بالتأكيد يحق لك التعويض", d, UserTier.PUBLIC)
    assert "بالتأكيد" not in answer

def test_public_adds_disclaimer():
    gate = CommercialPolicyGate()
    d = DecisionResult(confidence=LegalConfidenceScore(final_score=0.3))
    answer = gate.apply("ربما يحق لك", d, UserTier.PUBLIC)
    assert "استشارة قانونية" in answer or "محامٍ" in answer

def test_internal_debug_unchanged():
    gate = CommercialPolicyGate()
    d = DecisionResult(confidence=LegalConfidenceScore(final_score=0.5))
    original = "بالتأكيد يحق لك التعويض"
    answer = gate.apply(original, d, UserTier.INTERNAL_DEBUG)
    assert answer == original

def test_professional_softens():
    gate = CommercialPolicyGate()
    d = DecisionResult(confidence=LegalConfidenceScore(final_score=0.7))
    answer = gate.apply("حتماً ينطبق القانون", d, UserTier.PROFESSIONAL)
    assert "حتماً" not in answer


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
