# -*- coding: utf-8 -*-
"""Tests for Plain-Arabic Explanation Engine."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.explanation_engine import (
    PlainArabicExplanationEngine, ExplanationResult,
    ExplanationTemplateRegistry, UserReadabilityPolicy,
    SafeNextStepBuilder, DifferenceExplainer,
    build_user_explanation,
)


# ══ Direct Answer ══

def test_direct_has_short_answer():
    engine = PlainArabicExplanationEngine()
    r = engine.build_explanation("مربوط الدرجة السابعة: 6,000 — 8,000 ريال", "direct", "salary")
    assert r.short_answer
    assert "6,000" in r.short_answer or "مربوط" in r.short_answer

def test_direct_compose():
    result = build_user_explanation(
        "مربوط الدرجة السابعة: 6,000 — 8,000 ريال", "direct", "salary")
    assert "6,000" in result
    assert len(result) > 10


# ══ Qualified Answer ══

def test_qualified_has_change_conditions():
    engine = PlainArabicExplanationEngine()
    r = engine.build_explanation(
        "بناءً على النصوص المتاحة، يحق للموظف التعويض",
        "qualified", "employment")
    assert r.when_it_may_change  # Must explain what may change

def test_qualified_separates_clearly():
    result = build_user_explanation(
        "يحق للموظف مكافأة نهاية الخدمة حسب المادة 54",
        "qualified", "employment")
    assert "قد تتغير" in result or "تفاصيل" in result


# ══ Refusal Answer ══

def test_refusal_not_robotic():
    result = build_user_explanation(
        "لا يمكن تقديم إجابة موثوقة",
        "refusal", "salary")
    assert len(result) > 20  # Must produce something readable
    assert "لا يمكن" in result or "تقديم" in result

def test_refusal_has_next_step():
    engine = PlainArabicExplanationEngine()
    r = engine.build_explanation("لا يمكن الإجابة", "refusal", "salary")
    assert r.what_to_do_next  # Must suggest what to do


# ══ High-Risk Answer ══

def test_high_risk_has_caution():
    engine = PlainArabicExplanationEngine()
    r = engine.build_explanation(
        "عقوبة التعاطي: الحبس مدة لا تقل عن سنة",
        "high_risk", "criminal", has_risk=True)
    assert r.important_note
    assert "حساس" in r.important_note or "استشارة" in r.important_note

def test_high_risk_no_clutter():
    result = build_user_explanation(
        "عقوبة التعاطي: الحبس سنة", "high_risk", "criminal", has_risk=True)
    # Should not repeat caution multiple times
    assert result.count("استشارة") <= 2


# ══ Guided Response ══

def test_guided_formatted():
    result = build_user_explanation(
        "حتى أجاوبك بشكل أدق: ما نوع إنهاء العمل؟",
        "guided", "employment")
    assert "إنهاء العمل" in result


# ══ Readability Policy ══

def test_dense_paragraph_split():
    policy = UserReadabilityPolicy()
    dense = "هذا نص طويل جداً يحتوي على معلومات كثيرة ومعقدة، ويجب أن يتم تقسيمه إلى أجزاء أصغر لتسهيل القراءة، خاصة أن المستخدم العادي لا يفهم اللغة القانونية المعقدة"
    result = policy.split_dense(dense)
    lines = result.split("\n")
    assert len(lines) >= 2  # Should be split

def test_redundancy_removed():
    policy = UserReadabilityPolicy()
    text = "هذا الجواب مهم.\nهذا الجواب مهم.\nمعلومة أخرى."
    result = policy.remove_redundancy(text)
    assert result.count("هذا الجواب مهم") == 1


# ══ Next Step Builder ══

def test_next_step_salary():
    builder = SafeNextStepBuilder()
    step = builder.build("salary")
    assert "موارد بشرية" in step or "مسمّا" in step

def test_next_step_criminal():
    builder = SafeNextStepBuilder()
    step = builder.build("criminal")
    assert "محامٍ" in step or "محامي" in step

def test_next_step_deadline():
    builder = SafeNextStepBuilder()
    step = builder.build(has_deadline=True)
    assert "تاريخ" in step or "تأخير" in step

def test_next_step_no_overstep():
    """Next step must not give aggressive legal strategy."""
    builder = SafeNextStepBuilder()
    step = builder.build("employment")
    assert "ارفع دعوى" not in step
    assert "اذهب للمحكمة" not in step


# ══ Difference Explainer ══

def test_difference_salary():
    exp = DifferenceExplainer()
    key = exp.detect_need("المربوط الأساسي مع بدل السكن", "salary")
    assert key == "salary_vs_allowances"
    text = exp.explain(key)
    assert "الأساسي" in text and "بدلات" in text.lower() or "البدلات" in text

def test_difference_general_vs_personal():
    exp = DifferenceExplainer()
    key = exp.detect_need("هذه معلومات عامة لحالتك الشخصية")
    assert key == "general_vs_personal"

def test_difference_none():
    exp = DifferenceExplainer()
    key = exp.detect_need("مرحبا")
    assert key is None


# ══ Deterministic Preserved ══

def test_numbers_preserved():
    result = build_user_explanation(
        "مربوط الدرجة السابعة: بداية 6,000 ريال — نهاية 8,000 ريال",
        "direct", "salary")
    assert "6,000" in result
    assert "8,000" in result

def test_original_preserved():
    engine = PlainArabicExplanationEngine()
    original = "المادة 54 من قانون العمل"
    r = engine.build_explanation(original, "direct")
    assert r.original == original


# ══ No Hallucination ══

def test_no_invented_numbers():
    result = build_user_explanation("الدرجة السابعة", "direct", "salary")
    assert "10,000" not in result
    assert "15,000" not in result


# ══ Integration ══

def test_integration_complete():
    result = build_user_explanation(
        "مربوط الدرجة السابعة: 6,000 ريال\nهذا الراتب الأساسي فقط",
        "direct", "salary")
    assert len(result) > 20
    assert "6,000" in result


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
