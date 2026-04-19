# -*- coding: utf-8 -*-
"""Tests for User Risk & Safety UX Layer."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.user_risk import (
    UserRiskGuard, UserRiskLevel, UserRiskProfile,
    SafeUserCautionBuilder, HighRiskTopicRegistry,
    apply_user_risk_layer,
)


# ══ Low Risk ══

def test_salary_low_risk():
    """Salary structured query = low risk, no caution."""
    guard = UserRiskGuard()
    profile = guard.build_risk_profile("كم مربوط الدرجة السابعة", domain="salary")
    assert profile.risk_level == UserRiskLevel.LOW
    assert profile.requires_caution is False

def test_salary_no_caution_in_answer():
    answer, profile = apply_user_risk_layer(
        "مربوط الدرجة السابعة: 6,000 ريال",
        "كم مربوط الدرجة السابعة", domain="salary", confidence=0.95)
    assert answer == "مربوط الدرجة السابعة: 6,000 ريال"  # Unchanged
    assert profile.risk_level == UserRiskLevel.LOW

def test_high_confidence_low_risk_no_overwarn():
    guard = UserRiskGuard()
    profile = guard.build_risk_profile("جدول الرواتب", confidence=0.95)
    assert not guard.should_add_caution(profile)


# ══ Moderate Risk ══

def test_employment_moderate_risk():
    guard = UserRiskGuard()
    profile = guard.build_risk_profile("هل يحق لي تعويض عن الفصل التعسفي")
    assert profile.risk_level == UserRiskLevel.HIGH_EMPLOYMENT
    assert profile.requires_caution is True

def test_employment_caution_text():
    builder = SafeUserCautionBuilder()
    profile = UserRiskProfile(risk_level=UserRiskLevel.HIGH_EMPLOYMENT,
                               requires_caution=True, requires_document_check=True)
    caution = builder.build_caution(profile)
    assert "مستندات" in caution or "العقد" in caution


# ══ High Risk Criminal ══

def test_criminal_high_risk():
    guard = UserRiskGuard()
    profile = guard.build_risk_profile("أنا متهم بتعاطي المخدرات")
    assert profile.risk_level == UserRiskLevel.HIGH_CRIMINAL
    assert profile.requires_human_escalation is True

def test_criminal_escalation_note():
    builder = SafeUserCautionBuilder()
    profile = UserRiskProfile(risk_level=UserRiskLevel.HIGH_CRIMINAL,
                               requires_human_escalation=True, requires_caution=True)
    escalation = builder.build_escalation_note(profile)
    assert "محامٍ" in escalation or "محامي" in escalation

def test_criminal_in_answer():
    answer, profile = apply_user_risk_layer(
        "عقوبة التعاطي: الحبس مدة لا تقل عن سنة",
        "ما عقوبة تعاطي المخدرات", confidence=0.8)
    assert "محامٍ" in answer or "محامي" in answer
    assert "الحبس" in answer  # Original answer preserved


# ══ Family Risk ══

def test_family_risk():
    guard = UserRiskGuard()
    profile = guard.build_risk_profile("أبي أعرف حقوقي في الحضانة بعد الطلاق")
    assert profile.risk_level == UserRiskLevel.HIGH_FAMILY
    assert profile.requires_document_check is True

def test_family_caution_text():
    builder = SafeUserCautionBuilder()
    profile = UserRiskProfile(risk_level=UserRiskLevel.HIGH_FAMILY,
                               requires_caution=True)
    caution = builder.build_caution(profile)
    assert "أحوال شخصية" in caution or "تفاصيل" in caution


# ══ Deadline Risk ══

def test_deadline_detected():
    guard = UserRiskGuard()
    profile = guard.build_risk_profile("كم مدة الطعن بالتمييز")
    assert profile.requires_deadline_warning is True

def test_deadline_warning_text():
    builder = SafeUserCautionBuilder()
    profile = UserRiskProfile(risk_level=UserRiskLevel.HIGH_DEADLINE,
                               requires_deadline_warning=True, requires_caution=True)
    warning = builder.build_deadline_warning(profile)
    assert "مواعيد" in warning or "تأخّر" in warning


# ══ No Hallucination ══

def test_no_hallucinated_risk():
    """Risk layer must not add caution to a purely informational query."""
    answer, profile = apply_user_risk_layer(
        "جدول الدرجات والرواتب", "جدول الرواتب", confidence=0.95)
    # Should be LOW risk, answer unchanged
    assert profile.risk_level == UserRiskLevel.LOW
    assert answer == "جدول الدرجات والرواتب"

def test_deterministic_answer_preserved():
    """Risk caution must be additive, not substitutive."""
    original = "مربوط الدرجة السابعة: 6,000 — 8,000 ريال"
    answer, _ = apply_user_risk_layer(original, "كم مربوط الدرجة السابعة")
    assert "6,000" in answer
    assert "8,000" in answer


# ══ Confidence × Risk ══

def test_low_confidence_amplifies_risk():
    guard = UserRiskGuard()
    profile = guard.build_risk_profile("هل يحق لي التعويض عن الفصل", confidence=0.3)
    assert profile.requires_human_escalation is True


# ══ Topic Registry ══

def test_registry_criminal():
    reg = HighRiskTopicRegistry()
    detected = reg.detect("متهم بسرقة")
    assert UserRiskLevel.HIGH_CRIMINAL in detected

def test_registry_family():
    reg = HighRiskTopicRegistry()
    detected = reg.detect("حضانة الأطفال بعد الطلاق")
    assert UserRiskLevel.HIGH_FAMILY in detected

def test_registry_none():
    reg = HighRiskTopicRegistry()
    detected = reg.detect("كم عدد المواد في القانون")
    assert len(detected) == 0


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
