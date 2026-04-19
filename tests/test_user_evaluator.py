# -*- coding: utf-8 -*-
"""Tests for Ordinary User Evaluation Layer."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.user_evaluator import (
    OrdinaryUserEvaluator, OrdinaryUserEvaluationCase, OrdinaryUserEvaluationResult,
    UserWarningBalanceChecker, GuidanceQualityChecker,
    RealisticUserCaseRegistry, build_combined_report,
)


def _eval(case, answer, guidance=False, risk="low"):
    return OrdinaryUserEvaluator().evaluate(case, answer, guidance, risk)


# ══ Salary — Low Risk ══

def test_salary_clear_no_overwarning():
    case = OrdinaryUserEvaluationCase("t1", "كم راتب", domain="salary",
        expected_keywords=["6,000"], should_avoid_overwarning=True)
    r = _eval(case, "مربوط الدرجة السابعة: 6,000 — 8,000 ريال")
    assert r.passed is True
    assert r.dimension_scores["caution_fit"] >= 0.8

def test_salary_no_jargon():
    case = OrdinaryUserEvaluationCase("t2", "راتب", domain="salary")
    r = _eval(case, "مربوط الدرجة: 6,000 ريال")
    assert r.dimension_scores["readability"] >= 0.8


# ══ Criminal — High Risk ══

def test_criminal_needs_caution():
    case = OrdinaryUserEvaluationCase("t3", "متهم", domain="criminal",
        expected_risk_level="high", should_include_caution=True)
    r = _eval(case, "عقوبة التعاطي سنة. أنصحك بالتواصل مع محامٍ متخصص.",
              risk="high_risk_criminal")
    assert r.dimension_scores["caution_fit"] >= 0.8

def test_criminal_underwarning_detected():
    case = OrdinaryUserEvaluationCase("t4", "متهم", should_include_caution=True)
    r = _eval(case, "عقوبة التعاطي سنة.", risk="high_risk_criminal")
    assert r.dimension_scores["caution_fit"] < 0.5


# ══ Employment — Guidance ══

def test_employment_guidance_triggered():
    case = OrdinaryUserEvaluationCase("t5", "فصلوني", domain="employment",
        expected_guidance_mode="light_guidance", should_include_next_step=True)
    r = _eval(case, "حتى أجاوبك: ما نوع الإنهاء؟\n1) فصل\n2) استقالة\nاحتفظ بالمستندات",
              guidance=True, risk="low")
    assert r.dimension_scores["guidance_fit"] >= 0.7

def test_clear_query_no_guidance():
    case = OrdinaryUserEvaluationCase("t6", "كم راتب", domain="salary",
        expected_guidance_mode="no_guidance")
    r = _eval(case, "مربوط: 6,000 ريال", guidance=False)
    assert r.dimension_scores["guidance_fit"] == 1.0


# ══ Refusal ══

def test_refusal_understandable():
    case = OrdinaryUserEvaluationCase("t7", "سؤال غامض", expected_answer_style="refusal")
    r = _eval(case, "ما أقدر أجاوب بشكل مؤكد. أنصحك بمراجعة بوابة الميزان.")
    assert r.dimension_scores["refusal_quality"] >= 0.8

def test_refusal_not_helpful():
    case = OrdinaryUserEvaluationCase("t8", "سؤال", expected_answer_style="refusal")
    r = _eval(case, "خطأ في النظام.")
    assert r.dimension_scores["refusal_quality"] < 0.5


# ══ Distinction ══

def test_distinction_explained():
    case = OrdinaryUserEvaluationCase("t9", "راتب", domain="salary")
    r = _eval(case, "الراتب الأساسي: 6,000 ريال\n• يختلف الإجمالي حسب البدلات")
    assert r.dimension_scores["distinction_clarity"] >= 0.8

def test_distinction_missing():
    case = OrdinaryUserEvaluationCase("t10", "راتب", domain="salary")
    r = _eval(case, "الراتب الأساسي 6,000 وبدل السكن حسب الجهة")
    assert r.dimension_scores["distinction_clarity"] < 1.0


# ══ Next Step ══

def test_next_step_present():
    case = OrdinaryUserEvaluationCase("t11", "فصل", should_include_next_step=True)
    r = _eval(case, "يحق لك تعويض. احتفظ بعقد العمل.")
    assert r.dimension_scores["usefulness"] >= 0.8

def test_next_step_missing():
    case = OrdinaryUserEvaluationCase("t12", "فصل", should_include_next_step=True)
    r = _eval(case, "يحق لك تعويض.")
    assert r.dimension_scores["usefulness"] < 0.7


# ══ Warning Balance ══

def test_overwarning_detector():
    checker = UserWarningBalanceChecker()
    assert checker.detect_overwarning("خطير جداً لا تفعل أي شيء", "low") is True
    assert checker.detect_overwarning("خطير جداً", "high_risk_criminal") is False

def test_underwarning_detector():
    checker = UserWarningBalanceChecker()
    assert checker.detect_underwarning("عقوبة سنة.", "high_risk_criminal") is True
    assert checker.detect_underwarning("أنصحك محامٍ", "high_risk_criminal") is False


# ══ Guidance Quality ══

def test_guidance_too_many_questions():
    checker = GuidanceQualityChecker()
    answer = "سؤال 1؟ سؤال 2؟ سؤال 3؟ سؤال 4؟ سؤال 5؟"
    issues = checker.check(answer, "light_guidance", True)
    assert any("too many" in i for i in issues)

def test_guidance_no_choices():
    checker = GuidanceQualityChecker()
    answer = "ما المشكلة؟"
    issues = checker.check(answer, "light_guidance", True)
    assert any("choices" in i for i in issues)


# ══ Forbidden Keywords ══

def test_forbidden_jargon_lowers_score():
    case = OrdinaryUserEvaluationCase("t13", "سؤال",
        forbidden_keywords=["التكييف القانوني"])
    r = _eval(case, "التكييف القانوني: يحق لك التعويض")
    assert r.dimension_scores["clarity"] < 1.0


# ══ Realistic Registry ══

def test_realistic_cases_exist():
    cases = RealisticUserCaseRegistry.get_cases()
    assert len(cases) >= 10
    domains = set(c.domain for c in cases)
    assert "salary" in domains
    assert "criminal" in domains


# ══ Combined Report ══

def test_combined_report():
    legal = {"pass_rate": 90.0, "avg_score": 0.85}
    user = {"pass_rate": 80.0, "avg_score": 0.75}
    combined = build_combined_report(legal, user)
    assert combined["combined_pass_rate"] == 85.0
    assert combined["combined_avg_score"] == 0.8


# ══ Deterministic Preserved ══

def test_numbers_unchanged():
    case = OrdinaryUserEvaluationCase("t14", "راتب", expected_keywords=["6,000"])
    r = _eval(case, "مربوط: 6,000 ريال")
    assert r.dimension_scores["clarity"] >= 0.8


# ══ No Hallucination ══

def test_no_hallucination():
    case = OrdinaryUserEvaluationCase("t15", "راتب",
        forbidden_keywords=["10,000", "15,000"])
    r = _eval(case, "مربوط: 6,000 ريال")
    assert r.dimension_scores["clarity"] == 1.0


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
