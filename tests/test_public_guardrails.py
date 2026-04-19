# -*- coding: utf-8 -*-
"""Tests for Public Release Guardrails."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.public_guardrails import (
    PublicGuardrailEngine, PublicGuardrailResult,
    DeadlineSafetyHardener, PersonalActionSensitivityDetector,
    PublicHardeningPolicy, apply_public_guardrails,
)


# ══ Low Risk — Unchanged ══

def test_salary_passes_unchanged():
    answer, result = apply_public_guardrails(
        "مربوط الدرجة السابعة: 6,000 — 8,000 ريال",
        "كم مربوط الدرجة السابعة", risk_level="low", confidence=0.95, domain="salary")
    assert result.output_mode == "pass"
    assert not result.hardening_applied
    assert "6,000" in answer

def test_salary_deterministic_preserved():
    answer, _ = apply_public_guardrails(
        "مربوط: 6,000 ريال", "كم الراتب", risk_level="low")
    assert "6,000" in answer  # Numbers unchanged


# ══ Criminal — High Risk ══

def test_criminal_personal_gets_strong_caution():
    answer, result = apply_public_guardrails(
        "عقوبة التعاطي: الحبس سنة.",
        "أنا متهم بتعاطي المخدرات", risk_level="high_risk_criminal",
        confidence=0.7, domain="criminal")
    assert result.hardening_applied is True
    assert "محامٍ" in answer or "حساس" in answer

def test_criminal_personal_action_escalates():
    answer, result = apply_public_guardrails(
        "يحق لك الطعن.", "أنا متهم هل أستطيع الطعن",
        risk_level="high_risk_criminal", confidence=0.6, domain="criminal")
    assert result.escalation_applied is True
    assert "محامٍ" in answer


# ══ Family — High Risk ══

def test_family_gets_caution():
    answer, result = apply_public_guardrails(
        "تنتهي الحضانة عند سن 13.",
        "أنا مطلقة أبي حضانة ولدي", risk_level="high_risk_family",
        confidence=0.75, domain="family")
    assert result.hardening_applied is True
    assert "حساس" in answer or "محامٍ" in answer


# ══ Deadline — Mandatory Note ══

def test_deadline_gets_note():
    answer, result = apply_public_guardrails(
        "مدة الطعن بالتمييز 60 يوماً.",
        "كم مدة الطعن بالتمييز", risk_level="high_risk_deadline")
    assert result.urgency_note_added is True
    assert "تنبيه" in answer or "فوراً" in answer

def test_deadline_uncertain_escalates():
    answer, result = apply_public_guardrails(
        "قد تكون المدة 30 يوم أو 60 يوم.",
        "وصلني إشعار هل يضيع حقي", risk_level="high_risk_deadline",
        confidence=0.3)
    assert result.fallback_applied is True


# ══ General Info — No Overreaction ══

def test_general_deadline_info_not_personal():
    answer, result = apply_public_guardrails(
        "مدة الاستئناف في القضايا المدنية 30 يوماً.",
        "كم مدة الاستئناف", risk_level="low", confidence=0.9)
    # General info about deadlines should get deadline note but not escalation
    assert not result.escalation_applied


# ══ Personal Action Detection ══

def test_personal_detected():
    det = PersonalActionSensitivityDetector()
    assert det.detect_personal("أنا متهم بسرقة") is True
    assert det.detect_personal("ما عقوبة السرقة") is False

def test_action_request_detected():
    det = PersonalActionSensitivityDetector()
    assert det.detect_action_request("هل أستطيع الطعن") is True
    assert det.detect_action_request("كم مدة الطعن") is False

def test_irreversible_detected():
    det = PersonalActionSensitivityDetector()
    assert det.detect_irreversible_risk("هل يضيع حقي") is True


# ══ Underwarning Correction ══

def test_underwarning_corrected():
    answer, result = apply_public_guardrails(
        "يحق لك رفع دعوى.", "تم فصلي من العمل",
        risk_level="high_risk_employment", confidence=0.6, domain="employment")
    # Should detect underwarning (no caution keywords) and fix it
    # Employment is not in the "criminal/family" strong caution list, gets weak caution
    # But personal + high risk + action should trigger escalation
    assert result.hardening_applied or result.escalation_applied


# ══ No Unsupported Deadlines ══

def test_no_invented_deadline():
    answer, result = apply_public_guardrails(
        "يحق لك الطعن.", "هل أقدر أطعن في الحكم",
        risk_level="high_risk_criminal", confidence=0.7)
    assert "30 يوم" not in answer or "30 يوم" in "يحق لك الطعن."
    assert "60 يوم" not in answer or "60 يوم" in "يحق لك الطعن."


# ══ Professional Less Strict ══

def test_professional_less_strict():
    answer, result = apply_public_guardrails(
        "عقوبة التعاطي سنة.", "عقوبة التعاطي",
        risk_level="high_risk_criminal", is_public=False)
    assert result.output_mode == "pass"  # Not public = no hardening


# ══ Metrics ══

def test_metrics_count():
    engine = PublicGuardrailEngine()
    engine.review("test", "أنا متهم", "high_risk_criminal", 0.5, "criminal")
    engine.review("test", "كم الراتب", "low", 0.9, "salary")
    m = engine.get_metrics()
    assert m["total"] == 2
    assert m["hardening_rate"] >= 0


# ══ Fallback ══

def test_fallback_used():
    answer, result = apply_public_guardrails(
        "قد يضيع حقك.", "وصلني حكم وأنا خايف يضيع حقي",
        risk_level="high_risk_deadline", confidence=0.2)
    assert result.fallback_applied is True
    assert "الميزان" in answer or "محامٍ" in answer


# ══ Plain Arabic Preserved ══

def test_plain_arabic():
    answer, _ = apply_public_guardrails(
        "عقوبة الحبس سنة.", "ما العقوبة",
        risk_level="high_risk_criminal", domain="criminal")
    assert "بموجب أحكام" not in answer  # No legal jargon added


# ══ Guidance + Guardrails Coexist ══

def test_guidance_and_guardrail():
    guided = "حتى أجاوبك: ما نوع الإنهاء؟\n1) فصل\n2) استقالة"
    answer, result = apply_public_guardrails(guided, "فصلوني",
        risk_level="low", domain="employment")
    # Low risk guidance should pass through
    assert "فصل" in answer


# ══ No Hallucination ══

def test_no_hallucination():
    answer, _ = apply_public_guardrails(
        "مربوط: 6,000 ريال", "كم الراتب", risk_level="low")
    assert "10,000" not in answer


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
