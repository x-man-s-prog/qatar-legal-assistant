# -*- coding: utf-8 -*-
"""Tests for Guided Legal Scenario Engine."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.scenario_engine import (
    ScenarioEngine, ScenarioPlan, GuidanceMode,
    GuidedQuestionRegistry, GuidedUserResponseBuilder,
    ScenarioChoiceBuilder, check_scenario_guidance,
    _detect_domain, _is_vague, _has_sufficient_detail,
)


# ══ Domain Detection ══

def test_domain_employment():
    assert _detect_domain("فصلوني من الشغل") == "employment"

def test_domain_criminal():
    assert _detect_domain("أنا متهم بسرقة") == "criminal"

def test_domain_family():
    assert _detect_domain("أبي حضانة أولادي بعد الطلاق") == "family"

def test_domain_rental():
    assert _detect_domain("مشكلة مع المستأجر") == "rental"

def test_domain_unknown():
    assert _detect_domain("كم عدد القوانين") == ""


# ══ Vagueness Detection ══

def test_vague_short():
    assert _is_vague("وش أسوي فصلوني") is True

def test_vague_help():
    assert _is_vague("ساعدوني طلاق") is True

def test_not_vague_detailed():
    assert _is_vague("فصلوني من العمل بعد 5 سنوات خدمة ولدي عقد مكتوب وراتبي 15000") is False

def test_sufficient_detail():
    assert _has_sufficient_detail("عملت 5 سنوات وراتبي 10000 ريال وعقد مكتوب") is True


# ══ Scenario Engine ══

def test_structured_no_trigger():
    engine = ScenarioEngine()
    assert engine.should_trigger("كم مربوط الدرجة السابعة", is_structured=True) is False

def test_clear_query_no_trigger():
    engine = ScenarioEngine()
    assert engine.should_trigger(
        "فصلوني من العمل بعد 5 سنوات خدمة ولدي عقد مكتوب وراتبي 15000 وأبي أعرف حقوقي"
    ) is False

def test_greeting_no_trigger():
    engine = ScenarioEngine()
    assert engine.should_trigger("مرحبا", brain_route="greeting") is False

def test_vague_employment_triggers():
    engine = ScenarioEngine()
    assert engine.should_trigger("وش أسوي فصلوني") is True

def test_vague_criminal_triggers():
    engine = ScenarioEngine()
    assert engine.should_trigger("أنا متهم ساعدوني") is True


# ══ Scenario Plan ══

def test_plan_employment_light():
    engine = ScenarioEngine()
    plan = engine.build_plan("وش أسوي فصلوني")
    assert plan.domain == "employment"
    assert plan.guidance_mode == GuidanceMode.LIGHT
    assert len(plan.remaining_questions) >= 1

def test_plan_criminal_required():
    engine = ScenarioEngine()
    plan = engine.build_plan("أنا متهم ساعدوني")
    assert plan.domain == "criminal"
    assert plan.guidance_mode == GuidanceMode.REQUIRED
    assert plan.safe_to_answer_now is False

def test_plan_family_required():
    engine = ScenarioEngine()
    plan = engine.build_plan("ساعدوني طلاق")
    assert plan.domain == "family"
    assert plan.guidance_mode == GuidanceMode.REQUIRED

def test_plan_max_3_questions():
    engine = ScenarioEngine()
    plan = engine.build_plan("مشكلتي فصلوني")
    assert len(plan.remaining_questions) <= 3

def test_plan_no_guidance_when_clear():
    engine = ScenarioEngine()
    plan = engine.build_plan("كم عدد القوانين في قطر")
    assert plan.guidance_mode == GuidanceMode.NONE


# ══ Question Registry ══

def test_registry_employment():
    reg = GuidedQuestionRegistry()
    qs = reg.get_questions("employment")
    assert len(qs) >= 2
    assert qs[0].text_ar  # Has Arabic text

def test_registry_choices():
    reg = GuidedQuestionRegistry()
    qs = reg.get_questions("criminal")
    assert len(qs[0].choices) >= 2


# ══ Response Builder ══

def test_response_light():
    plan = ScenarioPlan(
        domain="employment", guidance_mode=GuidanceMode.LIGHT,
        remaining_questions=[{"text": "ما نوع إنهاء العمل؟", "choices": ["فصل", "استقالة"], "fact_key": "type"}])
    builder = GuidedUserResponseBuilder()
    response = builder.build_guidance_response(plan)
    assert "إنهاء العمل" in response
    assert "فصل" in response

def test_response_required_stronger():
    plan = ScenarioPlan(
        domain="criminal", guidance_mode=GuidanceMode.REQUIRED,
        remaining_questions=[{"text": "سؤالك يخص:", "choices": ["اتهام", "تحقيق"], "fact_key": "type"}])
    builder = GuidedUserResponseBuilder()
    response = builder.build_guidance_response(plan)
    assert "أحتاج أعرف" in response
    assert "غير دقيق" in response  # Stronger wording

def test_response_plain_arabic():
    plan = ScenarioPlan(
        domain="employment", guidance_mode=GuidanceMode.LIGHT,
        remaining_questions=[{"text": "كم مدة خدمتك؟", "choices": ["أقل من سنة", "أكثر"], "fact_key": "years"}])
    builder = GuidedUserResponseBuilder()
    response = builder.build_guidance_response(plan)
    # Must not have formal legal jargon
    assert "بموجب" not in response
    assert "اللائحة" not in response


# ══ Integration ══

def test_integration_returns_none_for_clear():
    result = check_scenario_guidance("كم مربوط الدرجة السابعة", is_structured=True)
    assert result is None

def test_integration_returns_guidance_for_vague():
    result = check_scenario_guidance("وش أسوي فصلوني")
    assert result is not None
    assert "نوع" in result or "إنهاء" in result

def test_integration_returns_none_for_greeting():
    result = check_scenario_guidance("مرحبا", brain_route="greeting")
    assert result is None


# ══ Choice Builder ══

def test_choice_builder():
    builder = ScenarioChoiceBuilder()
    text = builder.build_choices_text(["فصل", "استقالة", "انتهاء عقد"])
    assert "1)" in text
    assert "فصل" in text
    assert "استقالة" in text


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
