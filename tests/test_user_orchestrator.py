# -*- coding: utf-8 -*-
"""Tests for Ordinary User Orchestrator."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.user_orchestrator import (
    OrdinaryUserOrchestrator, FinalUserResponse, UserFacingMode,
    UserOutputAssemblyPolicy,
)


def _orch():
    return OrdinaryUserOrchestrator()


# ══ Public Pipeline ══

def test_public_salary_clean():
    o = _orch()
    r = o.run("مربوط الدرجة السابعة: 6,000 — 8,000 ريال",
              "كم مربوط الدرجة السابعة", domain="salary",
              confidence=0.95, is_structured=True)
    assert r.user_mode == "public"
    assert "6,000" in r.final_text
    assert r.final_status == "ok"
    assert r.scenario_guidance_applied is False

def test_public_criminal_hardened():
    o = _orch()
    r = o.run("عقوبة التعاطي: الحبس سنة.",
              "أنا متهم بتعاطي المخدرات", domain="criminal",
              confidence=0.7)
    assert "محامٍ" in r.final_text or "حساس" in r.final_text
    assert r.public_guardrail_applied or r.risk_level.startswith("high")

def test_public_family_cautioned():
    o = _orch()
    r = o.run("تنتهي الحضانة عند 13 سنة.",
              "أنا مطلقة أبي حضانة", domain="family", confidence=0.75)
    assert r.risk_level.startswith("high")

def test_public_deadline_noted():
    o = _orch()
    r = o.run("مدة الطعن 60 يوماً.", "كم مدة الطعن",
              domain="deadline", confidence=0.85)
    assert "تنبيه" in r.final_text or "فوراً" in r.final_text or "تاريخ" in r.final_text

def test_public_guidance_shortcircuits():
    o = _orch()
    r = o.run("", "وش أسوي فصلوني", domain="employment",
              brain_route="general", is_structured=False)
    assert r.scenario_guidance_applied is True
    assert r.final_status == "guided"
    assert "نوع" in r.final_text or "إنهاء" in r.final_text

def test_public_fallback_packaging():
    o = _orch()
    r = o.run("قد يضيع حقك.", "وصلني حكم يضيع حقي",
              domain="deadline", confidence=0.2)
    # Low confidence + irreversible → fallback
    assert r.final_status in ("ok", "fallback")

def test_public_quality_recorded():
    o = _orch()
    r = o.run("مربوط: 6,000 ريال", "كم الراتب", domain="salary",
              confidence=0.95, is_structured=True)
    assert r.user_quality_score > 0

def test_public_risk_recorded():
    o = _orch()
    r = o.run("عقوبة سنة.", "ما عقوبة التعاطي", domain="criminal")
    assert r.risk_level  # Non-empty

def test_public_guardrail_recorded():
    o = _orch()
    r = o.run("يحق لك الطعن.", "أنا متهم هل أطعن",
              domain="criminal", confidence=0.5)
    # The result object tracks whether guardrail was applied
    assert isinstance(r.public_guardrail_applied, bool)


# ══ Professional Pipeline ══

def test_professional_lighter():
    o = _orch()
    r = o.run("مربوط: 6,000 ريال", "كم الراتب", domain="salary",
              mode=UserFacingMode.PROFESSIONAL)
    assert r.user_mode == "professional"
    assert "6,000" in r.final_text
    assert r.final_status == "ok"

def test_professional_less_strict():
    o = _orch()
    pub = o.run("عقوبة سنة.", "ما عقوبة التعاطي", domain="criminal",
                mode=UserFacingMode.PUBLIC)
    pro = o.run("عقوبة سنة.", "ما عقوبة التعاطي", domain="criminal",
                mode=UserFacingMode.PROFESSIONAL)
    # Public should be >= professional in length (more caution)
    assert len(pub.final_text) >= len(pro.final_text)


# ══ Internal Debug ══

def test_debug_richer():
    o = _orch()
    r = o.run("raw answer here", "test", domain="salary",
              mode=UserFacingMode.INTERNAL_DEBUG, confidence=0.5)
    assert r.user_mode == "internal_debug"
    assert len(r.notes_internal) > 0
    assert "confidence" in str(r.notes_internal)


# ══ Assembly Policy ══

def test_dedup_removal():
    policy = UserOutputAssemblyPolicy()
    parts = ["هذا الجواب.", "هذا الجواب.", "معلومة أخرى."]
    result = policy.deduplicate(parts)
    assert len(result) == 2

def test_dedup_sections_merged():
    policy = UserOutputAssemblyPolicy()
    sections = ["الراتب 6,000 ريال", "الراتب 6,000 ريال", "ملاحظة: الأساسي فقط"]
    merged = policy.merge_sections(sections)
    assert merged.count("6,000") == 1

def test_finalize_cleans():
    policy = UserOutputAssemblyPolicy()
    text = "line1\n\n\n\nline2  extra   spaces"
    result = policy.finalize(text)
    assert "\n\n\n" not in result
    assert "  " not in result


# ══ Mode Switching ══

def test_mode_switching():
    o = _orch()
    for mode in [UserFacingMode.PUBLIC, UserFacingMode.PROFESSIONAL, UserFacingMode.INTERNAL_DEBUG]:
        r = o.run("test", "test", mode=mode)
        assert r.user_mode == mode.value


# ══ Deterministic Preserved ══

def test_numbers_unchanged():
    o = _orch()
    r = o.run("مربوط: 6,000 — 8,000 ريال", "كم الراتب",
              domain="salary", is_structured=True)
    assert "6,000" in r.final_text
    assert "8,000" in r.final_text

def test_no_hallucination():
    o = _orch()
    r = o.run("مربوط: 6,000 ريال", "كم الراتب", domain="salary")
    assert "10,000" not in r.final_text
    assert "15,000" not in r.final_text


# ══ Metrics ══

def test_metrics():
    o = _orch()
    o.run("test", "كم الراتب", domain="salary", mode=UserFacingMode.PUBLIC, is_structured=True)
    o.run("test", "test", mode=UserFacingMode.PROFESSIONAL)
    m = o.get_metrics()
    assert m["public_runs"] >= 1
    assert m["professional_runs"] >= 1
    assert m["total_runs"] >= 2


# ══ Public Output Shorter ══

def test_public_shorter_than_debug():
    o = _orch()
    pub = o.run("long answer with many details and explanations here", "test",
                mode=UserFacingMode.PUBLIC, domain="salary", is_structured=True)
    dbg = o.run("long answer with many details and explanations here", "test",
                mode=UserFacingMode.INTERNAL_DEBUG)
    # Debug preserves raw; public may trim
    assert len(pub.notes_internal) <= len(dbg.notes_internal)


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
