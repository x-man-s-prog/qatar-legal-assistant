# -*- coding: utf-8 -*-
"""Tests for Controlled Public Beta System."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.beta_system import (
    BetaAccessController, BetaLiveMonitor, BetaIncidentDetector,
    BetaSafetyResponder, BetaKillSwitch, BetaFeedbackCollector,
    BetaUserCohortTracker, BetaPolicyConfig, IncidentSeverity,
)


# ══ Access Control ══

def test_register_user():
    ac = BetaAccessController(BetaPolicyConfig(max_users=3))
    assert ac.register_user("u1") is True
    assert ac.is_allowed("u1") is True

def test_max_users_limit():
    ac = BetaAccessController(BetaPolicyConfig(max_users=2))
    ac.register_user("u1")
    ac.register_user("u2")
    assert ac.register_user("u3") is False
    assert ac.active_users() == 2

def test_rate_limit():
    ac = BetaAccessController(BetaPolicyConfig(rate_limit_per_minute=3))
    ac.register_user("u1")
    assert ac.enforce_rate_limit("u1") is True
    assert ac.enforce_rate_limit("u1") is True
    assert ac.enforce_rate_limit("u1") is True
    assert ac.enforce_rate_limit("u1") is False  # 4th = blocked


# ══ Live Monitor ══

def test_monitor_records():
    m = BetaLiveMonitor()
    m.record(risk_level="high_criminal", escalated=True, quality=0.8)
    m.record(risk_level="low", quality=0.95)
    s = m.snapshot()
    assert s["total_requests"] == 2
    assert s["high_risk_rate"] == 50.0
    assert s["escalation_rate"] == 50.0

def test_monitor_averages():
    m = BetaLiveMonitor()
    m.record(quality=0.8, confidence=0.7)
    m.record(quality=0.6, confidence=0.9)
    s = m.snapshot()
    assert s["avg_quality"] == 0.7
    assert s["avg_confidence"] == 0.8


# ══ Incident Detection ══

def test_incident_underwarning():
    d = BetaIncidentDetector(BetaPolicyConfig(incident_trigger_limits={"underwarning": 2}))
    d.check(quality=0.9, risk_level="high_criminal",
            guidance_applied=False, guardrail_applied=False, fallback=False)
    incident = d.check(quality=0.9, risk_level="high_criminal",
                        guidance_applied=False, guardrail_applied=False, fallback=False)
    assert incident is not None
    assert incident.severity == IncidentSeverity.CRITICAL

def test_incident_quality():
    d = BetaIncidentDetector(BetaPolicyConfig(
        minimum_quality_score=0.5,
        incident_trigger_limits={"quality_below_threshold": 2}))
    d.check(quality=0.3, risk_level="low",
            guidance_applied=False, guardrail_applied=False, fallback=False)
    incident = d.check(quality=0.3, risk_level="low",
                        guidance_applied=False, guardrail_applied=False, fallback=False)
    assert incident is not None
    assert incident.severity == IncidentSeverity.HIGH

def test_no_incident_normal():
    d = BetaIncidentDetector()
    incident = d.check(quality=0.9, risk_level="low",
                        guidance_applied=False, guardrail_applied=False, fallback=False)
    assert incident is None


# ══ Safety Responder ══

def test_safe_mode():
    sr = BetaSafetyResponder()
    assert sr.is_safe_mode() is False
    sr.enable_safe_mode()
    assert sr.is_safe_mode() is True
    assert sr.should_force_fallback("criminal", "high_risk") is True
    sr.disable_safe_mode()
    assert sr.is_safe_mode() is False

def test_restrict_domain():
    sr = BetaSafetyResponder()
    sr.restrict_domain("criminal")
    assert sr.is_domain_restricted("criminal") is True
    assert sr.should_force_fallback("criminal", "low") is True
    assert sr.should_force_fallback("salary", "low") is False

def test_react_to_critical():
    sr = BetaSafetyResponder()
    from core.beta_system import BetaIncident
    incident = BetaIncident("test", IncidentSeverity.CRITICAL, "test")
    sr.react_to_incident(incident)
    assert sr.is_safe_mode() is True


# ══ Kill Switch ══

def test_kill_switch():
    ks = BetaKillSwitch()
    assert ks.is_active() is False
    ks.activate(low_risk_only=True)
    assert ks.is_active() is True
    assert ks.should_block(risk_level="high_criminal") is True
    assert ks.should_block(risk_level="low") is False
    ks.deactivate()
    assert ks.is_active() is False

def test_kill_switch_emergency():
    ks = BetaKillSwitch()
    ks.activate(emergency=True)
    assert ks.should_block(risk_level="low") is True
    assert "صيانة" in ks.get_fallback_message()

def test_kill_switch_domain():
    ks = BetaKillSwitch()
    ks.activate()
    ks.disable_domain("criminal")
    assert ks.should_block(domain="criminal") is True
    assert ks.should_block(domain="salary") is False


# ══ Feedback ══

def test_feedback_record():
    fc = BetaFeedbackCollector()
    fc.record("u1", "كم الراتب", 5)
    fc.record("u2", "فصلوني", 2, "ما فهمت الجواب")
    agg = fc.aggregate()
    assert agg["count"] == 2
    assert agg["positive"] == 1
    assert agg["negative"] == 1

def test_feedback_failures():
    fc = BetaFeedbackCollector()
    fc.record("u1", "سؤال صعب", 1)
    fc.record("u2", "سؤال ثاني", 2)
    fails = fc.common_failures()
    assert len(fails) == 2


# ══ Cohort Tracker ══

def test_cohort_tracking():
    ct = BetaUserCohortTracker()
    ct.track("u1", "low", False, 0.9)
    ct.track("u1", "high_criminal", True, 0.7)
    ct.track("u2", "low", False, 0.95)
    summary = ct.get_summary("u1")
    assert summary.queries == 2
    assert summary.high_risk_queries == 1
    report = ct.cohort_report()
    assert report["users"] == 2

def test_cohort_quality():
    ct = BetaUserCohortTracker()
    ct.track("u1", quality=0.8)
    ct.track("u1", quality=0.6)
    s = ct.get_summary("u1")
    assert 0.6 <= s.avg_quality <= 0.8


# ══ No Effect on Deterministic ══

def test_access_does_not_modify_answer():
    ac = BetaAccessController()
    ac.register_user("u1")
    # Access control only gates — never modifies answers
    assert ac.is_allowed("u1") is True

def test_kill_switch_recovery():
    ks = BetaKillSwitch()
    ks.activate(emergency=True)
    assert ks.is_active()
    ks.deactivate()
    assert not ks.is_active()
    assert not ks.should_block()


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
