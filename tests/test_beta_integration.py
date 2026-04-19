# -*- coding: utf-8 -*-
"""Integration tests for beta middleware in live flow."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.beta_middleware import (
    beta_pre_request, beta_post_response, beta_record_feedback, beta_metrics_snapshot,
)
from core.beta_system import (
    BetaAccessController, BetaKillSwitch, BetaSafetyResponder,
    BetaPolicyConfig, BetaLiveMonitor, BetaIncidentDetector,
    BetaFeedbackCollector, BetaUserCohortTracker,
    get_beta_access, get_beta_kill, get_beta_safety,
    get_beta_monitor, get_beta_incidents, get_beta_feedback, get_beta_cohort,
    IncidentSeverity,
)

# Reset singletons for test isolation
import core.beta_system as bs
def _reset():
    bs._access = BetaAccessController(BetaPolicyConfig(max_users=5, rate_limit_per_minute=3))
    bs._monitor = BetaLiveMonitor()
    bs._incidents = BetaIncidentDetector(BetaPolicyConfig(
        minimum_quality_score=0.5,
        incident_trigger_limits={"underwarning": 2, "quality_below_threshold": 2}))
    bs._safety = BetaSafetyResponder()
    bs._kill = BetaKillSwitch()
    bs._feedback = BetaFeedbackCollector()
    bs._cohort = BetaUserCohortTracker()


# ══ Access Control ══

def test_allowed_user_proceeds():
    _reset()
    result = beta_pre_request("user1", "كم الراتب")
    assert result is None  # Proceed

def test_max_users_blocks():
    _reset()
    for i in range(5):
        beta_pre_request(f"user{i}", "test")
    result = beta_pre_request("user99", "test")
    assert result is not None
    assert "تجريبية" in result

def test_rate_limit_blocks():
    _reset()
    beta_pre_request("u1", "q1")
    beta_pre_request("u1", "q2")
    beta_pre_request("u1", "q3")
    result = beta_pre_request("u1", "q4")
    assert result is not None
    assert "الحد المسموح" in result


# ══ Kill Switch ══

def test_kill_switch_global():
    _reset()
    get_beta_kill().activate(emergency=True)
    result = beta_pre_request("u1", "test")
    assert result is not None
    assert "صيانة" in result
    get_beta_kill().deactivate()

def test_kill_switch_low_risk_only():
    _reset()
    get_beta_kill().activate(low_risk_only=True)
    # Low risk passes
    r1 = beta_pre_request("u1", "كم الراتب", risk_level="low")
    assert r1 is None
    # High risk blocked
    r2 = beta_pre_request("u1", "متهم", risk_level="high_risk_criminal")
    assert r2 is not None

def test_kill_switch_domain():
    _reset()
    get_beta_kill().activate()
    get_beta_kill().disable_domain("criminal")
    r = beta_pre_request("u1", "test", domain="criminal")
    assert r is not None


# ══ Safety Responder ══

def test_restricted_domain_blocked():
    _reset()
    get_beta_safety().restrict_domain("family")
    result = beta_pre_request("u1", "حضانة", domain="family")
    assert result is not None
    assert "متوقف" in result or "صيانة" in result

def test_safe_mode_blocks_high_risk():
    _reset()
    get_beta_safety().enable_safe_mode()
    result = beta_pre_request("u1", "test", domain="criminal", risk_level="high_risk")
    assert result is not None


# ══ Post-Response ══

def test_post_response_records():
    _reset()
    beta_post_response("u1", "كم الراتب", "low", "salary", quality=0.9)
    snap = get_beta_monitor().snapshot()
    assert snap["total_requests"] == 1
    assert snap["avg_quality"] == 0.9

def test_cohort_updated():
    _reset()
    beta_post_response("u1", "test", "low", quality=0.8)
    beta_post_response("u1", "test2", "high_criminal", quality=0.6)
    summary = get_beta_cohort().get_summary("u1")
    assert summary.queries == 2

def test_incident_triggers_safety():
    _reset()
    # Two underwarning events should trigger incident
    beta_post_response("u1", "q1", "high_criminal", quality=0.9,
                        guidance_applied=False, guardrail_applied=False)
    beta_post_response("u1", "q2", "high_criminal", quality=0.9,
                        guidance_applied=False, guardrail_applied=False)
    # Should have triggered safe mode
    assert get_beta_safety().is_safe_mode() is True


# ══ Feedback ══

def test_feedback_recorded():
    _reset()
    beta_record_feedback("u1", "كم الراتب", 5, "ممتاز")
    beta_record_feedback("u2", "فصلوني", 2, "ما فهمت")
    agg = get_beta_feedback().aggregate()
    assert agg["count"] == 2
    assert agg["positive"] == 1


# ══ Metrics ══

def test_metrics_snapshot():
    _reset()
    beta_pre_request("u1", "test")
    beta_post_response("u1", "test", "low", quality=0.9)
    snap = beta_metrics_snapshot()
    assert "monitor" in snap
    assert "cohort" in snap
    assert "feedback" in snap
    assert snap["active_users"] >= 1


# ══ Deterministic Unchanged ══

def test_normal_request_passes():
    _reset()
    # Normal salary query should pass through with no blocking
    result = beta_pre_request("user1", "كم مربوط الدرجة السابعة",
                               risk_level="low", domain="salary")
    assert result is None  # No block


# ══ Recovery ══

def test_system_recovers():
    _reset()
    get_beta_kill().activate(emergency=True)
    assert beta_pre_request("u1", "test") is not None
    get_beta_kill().deactivate()
    assert beta_pre_request("u1", "test") is None


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
