# -*- coding: utf-8 -*-
"""Tests for Simple Answer Adapter — user-friendly legal response layer."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.simple_answer import (
    SimpleAnswerAdapter, SimpleResponseMode, SimpleResponse,
    PlainArabicPolicy, ProtectedLegalTerms, simplify_for_user,
)


# ══ Direct Answer Simplification ══

def test_direct_structured_simplification():
    adapter = SimpleAnswerAdapter()
    r = adapter.build_simple_response(
        "مربوط الدرجة السابعة: بداية 6,000 ريال — نهاية 8,000 ريال",
        decision_type="direct_legal_answer",
        mode=SimpleResponseMode.STANDARD)
    assert "6,000" in r.answer_simple
    assert "8,000" in r.answer_simple
    assert r.answer_short  # Has a short version

def test_direct_minimal_no_extra():
    adapter = SimpleAnswerAdapter()
    r = adapter.build_simple_response(
        "الدرجة السابعة: 6,000 ريال",
        decision_type="direct_legal_answer",
        mode=SimpleResponseMode.MINIMAL)
    assert r.important_note == ""  # Minimal = no extra notes

def test_direct_cautious_has_note():
    adapter = SimpleAnswerAdapter()
    r = adapter.build_simple_response(
        "الدرجة السابعة: 6,000 ريال",
        decision_type="direct_legal_answer",
        mode=SimpleResponseMode.CAUTIOUS)
    assert "كل حالة" in r.important_note or "معلومات عامة" in r.important_note


# ══ Qualified Answer ══

def test_qualified_has_note():
    adapter = SimpleAnswerAdapter()
    r = adapter.build_simple_response(
        "بناءً على النصوص المتاحة، يحق للموظف التعويض",
        decision_type="qualified_legal_answer")
    assert r.important_note  # Must have qualification note

def test_qualified_cautious_has_lawyer():
    adapter = SimpleAnswerAdapter()
    r = adapter.build_simple_response(
        "يحق للموظف التعويض وفقاً للنص القانوني",
        decision_type="qualified_legal_answer",
        mode=SimpleResponseMode.CAUTIOUS)
    assert "محامٍ" in r.limitation_note or "محامي" in r.limitation_note


# ══ Limitation Answer ══

def test_limitation_shows_limits():
    adapter = SimpleAnswerAdapter()
    r = adapter.build_simple_response(
        "البدلات تختلف حسب الجهة",
        decision_type="limitation_response",
        limitations=["لا يمكن تحديد الإجمالي"])
    assert "لا يمكن" in r.limitation_note or "متوفرة" in r.limitation_note


# ══ Refusal Answer ══

def test_refusal_is_friendly():
    adapter = SimpleAnswerAdapter()
    r = adapter.build_simple_response(
        "لا يمكن تقديم إجابة موثوقة",
        decision_type="refusal_insufficient_evidence")
    assert "ما أقدر" in r.answer_short or "ما أقدر" in r.answer_simple
    assert "الميزان" in r.answer_simple or "محامي" in r.answer_simple

def test_refusal_not_empty():
    adapter = SimpleAnswerAdapter()
    r = adapter.build_simple_response("", decision_type="refusal_insufficient_evidence")
    assert len(r.answer_simple) > 20  # Must produce something helpful


# ══ No Hallucination ══

def test_no_hallucination_in_simplification():
    adapter = SimpleAnswerAdapter()
    original = "مربوط الدرجة السابعة: 6,000 ريال"
    r = adapter.build_simple_response(original, decision_type="direct_legal_answer")
    # Simplification must not add numbers not in original
    assert "10,000" not in r.answer_simple
    assert "12,000" not in r.answer_simple
    # Must preserve original numbers
    assert "6,000" in r.answer_simple


# ══ Protected Terms ══

def test_protected_term_preserved():
    terms = ProtectedLegalTerms()
    text = "مكافأة نهاية الخدمة تُحسب حسب القانون"
    result = terms.preserve_or_explain(text, SimpleResponseMode.STANDARD)
    assert "مكافأة نهاية الخدمة" in result
    assert "مبلغ يحصل عليه" in result  # Explanation added

def test_protected_term_minimal_no_explain():
    terms = ProtectedLegalTerms()
    text = "مكافأة نهاية الخدمة"
    result = terms.preserve_or_explain(text, SimpleResponseMode.MINIMAL)
    assert result == text  # Minimal = no added explanation


# ══ Plain Arabic Policy ══

def test_simplify_formal_phrase():
    policy = PlainArabicPolicy()
    result = policy.simplify_phrase("وفقاً للنص القانوني يحق لك التعويض")
    assert "بحسب القانون" in result
    assert "وفقاً للنص القانوني" not in result

def test_simplify_preserves_numbers():
    policy = PlainArabicPolicy()
    result = policy.simplify_phrase("مربوط الدرجة: 6,000 ريال")
    assert "6,000" in result


# ══ Integration ══

def test_simplify_for_user_direct():
    result = simplify_for_user(
        "مربوط الدرجة السابعة: 6,000 ريال",
        decision_type="direct_legal_answer",
        mode=SimpleResponseMode.STANDARD)
    assert "6,000" in result
    assert len(result) > 10

def test_simplify_for_user_refusal():
    result = simplify_for_user(
        "لا يمكن الإجابة",
        decision_type="refusal_insufficient_evidence")
    assert "ما أقدر" in result or "للأسف" in result


# ══ Audit Unchanged ══

def test_original_answer_preserved():
    """Simplification must keep original answer in the response object."""
    adapter = SimpleAnswerAdapter()
    original = "وفقاً للنص القانوني المادة 54"
    r = adapter.build_simple_response(original, decision_type="direct_legal_answer")
    assert r.original_answer == original  # Audit can still see the original


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
