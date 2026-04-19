# -*- coding: utf-8 -*-
"""Tests for Enterprise Layer — Evaluator, Regression, Release, Deployment, Monitoring."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.enterprise import (
    LegalEvaluatorFramework, EvaluationCase, EvaluationResult,
    RegressionSafetySuite, RegressionBaseline,
    ReleaseReadinessChecker, ReleaseReadinessReport,
    DeploymentEnv, get_deployment_profile,
    OperationalMonitoringHooks,
)
from core.governance import ProductionSafetyResult


# ══ Evaluator ══

def test_eval_pass():
    e = LegalEvaluatorFramework()
    case = EvaluationCase(case_id="t1", query="test",
                           expected_keywords=["6,000", "ريال"])
    r = e.run_case(case, "الدرجة السابعة: 6,000 ريال")
    assert r.passed is True
    assert r.score == 1.0

def test_eval_forbidden_keyword():
    e = LegalEvaluatorFramework()
    case = EvaluationCase(case_id="t2", query="test",
                           forbidden_keywords=["📋", "التكييف"])
    r = e.run_case(case, "📋 التكييف القانوني: الإجابة هنا")
    assert r.passed is False
    assert any("forbidden" in f for f in r.failures)

def test_eval_missing_keyword():
    e = LegalEvaluatorFramework()
    case = EvaluationCase(case_id="t3", query="test",
                           expected_keywords=["السابعة"])
    r = e.run_case(case, "الدرجة الأولى: 17,000")
    assert r.passed is False
    assert r.score < 1.0

def test_eval_refusal_required():
    e = LegalEvaluatorFramework()
    case = EvaluationCase(case_id="t4", query="test", requires_refusal=True)
    r = e.run_case(case, "يحق لك التعويض الكامل", is_refusal=False)
    assert r.passed is False

def test_eval_refusal_correct():
    e = LegalEvaluatorFramework()
    case = EvaluationCase(case_id="t5", query="test", requires_refusal=True)
    r = e.run_case(case, "لا يمكن تقديم إجابة موثوقة", is_refusal=True)
    assert r.passed is True

def test_eval_qualification_required():
    e = LegalEvaluatorFramework()
    case = EvaluationCase(case_id="t6", query="test", requires_qualification=True)
    r = e.run_case(case, "يحق لك", is_refusal=False)
    assert r.passed is False

def test_eval_suite_summary():
    e = LegalEvaluatorFramework()
    cases = [
        EvaluationCase(case_id="s1", query="q1", expected_keywords=["نعم"]),
        EvaluationCase(case_id="s2", query="q2", expected_keywords=["لا"]),
    ]
    def answer_fn(q):
        return ("نعم الجواب هنا", "direct", False)
    results = e.run_suite(cases, answer_fn)
    summary = e.summarize(results)
    assert summary["total"] == 2
    assert summary["passed"] >= 1

def test_eval_export_json():
    e = LegalEvaluatorFramework()
    r = EvaluationResult(case_id="x1", passed=True, score=0.9)
    out = e.export_json([r])
    assert "x1" in out
    assert "0.9" in out


# ══ Regression ══

def test_regression_pass():
    suite = RegressionSafetySuite()
    suite.set_baseline("t1", pass_expected=True, min_score=0.8)
    results = [EvaluationResult(case_id="t1", passed=True, score=0.9)]
    alerts = suite.check_regression(results)
    assert len(alerts) == 0

def test_regression_fail():
    suite = RegressionSafetySuite()
    suite.set_baseline("t1", pass_expected=True, min_score=0.8)
    results = [EvaluationResult(case_id="t1", passed=False, score=0.3,
                                 failures=["missing keyword"])]
    alerts = suite.check_regression(results)
    assert len(alerts) >= 1
    assert "REGRESSION" in alerts[0]

def test_regression_score_drop():
    suite = RegressionSafetySuite()
    suite.set_baseline("t1", pass_expected=True, min_score=0.9)
    results = [EvaluationResult(case_id="t1", passed=True, score=0.7)]
    alerts = suite.check_regression(results)
    assert any("SCORE_DROP" in a for a in alerts)


# ══ Release Readiness ══

def test_release_ready():
    checker = ReleaseReadinessChecker()
    rr = checker.check(
        eval_summary={"pass_rate": 95, "avg_score": 0.9},
        regression_alerts=[],
        safety_result=ProductionSafetyResult(safe=True),
        audit_enabled=True, commercial_mode="public_user")
    assert rr.ready is True
    assert rr.score >= 70

def test_release_blocked_low_eval():
    checker = ReleaseReadinessChecker()
    rr = checker.check(
        eval_summary={"pass_rate": 60, "avg_score": 0.5},
        regression_alerts=[], audit_enabled=True, commercial_mode="public_user")
    assert rr.ready is False
    assert any("pass rate" in b for b in rr.blockers)

def test_release_blocked_no_audit():
    checker = ReleaseReadinessChecker()
    rr = checker.check(
        eval_summary={"pass_rate": 100}, regression_alerts=[],
        audit_enabled=False, commercial_mode="public_user")
    assert rr.ready is False

def test_release_blocked_regressions():
    checker = ReleaseReadinessChecker()
    rr = checker.check(
        eval_summary={"pass_rate": 100}, regression_alerts=["REGRESSION: t1"],
        audit_enabled=True, commercial_mode="public_user")
    assert rr.ready is False

def test_release_blocked_safety():
    checker = ReleaseReadinessChecker()
    safety = ProductionSafetyResult(safe=False, violations=["deprecated evidence used"])
    rr = checker.check(
        eval_summary={"pass_rate": 100}, regression_alerts=[],
        safety_result=safety, audit_enabled=True, commercial_mode="public_user")
    assert rr.ready is False


# ══ Deployment Profiles ══

def test_dev_profile():
    p = get_deployment_profile("local_dev")
    assert p.debug_endpoints is True
    assert p.validation_strict is False

def test_prod_profile():
    p = get_deployment_profile("production")
    assert p.debug_endpoints is False
    assert p.validation_strict is True
    assert p.commercial_mode == "public_user"

def test_staging_profile():
    p = get_deployment_profile("staging")
    assert p.debug_endpoints is True
    assert p.validation_strict is True


# ══ Monitoring ══

def test_monitor_counts():
    m = OperationalMonitoringHooks()
    m.record_answer(is_refusal=True)
    m.record_answer(has_qualification=True)
    m.record_answer()
    snap = m.snapshot()
    assert snap["total_answers"] == 3
    assert snap["refusals"] == 1
    assert snap["qualifications"] == 1
    assert snap["refusal_rate"] > 0

def test_monitor_validation_failure():
    m = OperationalMonitoringHooks()
    m.record_answer()
    m.record_validation_failure()
    snap = m.snapshot()
    assert snap["validation_failures"] == 1
    assert snap["validation_failure_rate"] > 0

def test_monitor_eval_drift():
    m = OperationalMonitoringHooks()
    m.record_eval_run(avg_score=0.85)
    m.record_eval_run(avg_score=0.72)
    snap = m.snapshot()
    assert snap["eval_runs"] == 2
    assert snap["eval_avg_score"] == 0.72  # Last recorded

def test_monitor_deprecated():
    m = OperationalMonitoringHooks()
    m.record_deprecated_attempt()
    m.record_deprecated_attempt()
    assert m.snapshot()["deprecated_attempts"] == 2


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
