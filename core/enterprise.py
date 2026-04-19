# -*- coding: utf-8 -*-
"""
Enterprise Layer — Evaluation, Regression Safety, Release Readiness,
Deployment Controls, Operational Monitoring
================================================================
Final layer before commercial launch.
"""
from __future__ import annotations
import json, logging, threading, time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Callable

log = logging.getLogger("enterprise")


# ══════════════════════════════════════════════════════════════
# 1. Evaluator Framework
# ══════════════════════════════════════════════════════════════

@dataclass
class EvaluationCase:
    case_id: str
    query: str
    expected_mode: str = ""            # "deterministic" | "evidence_guided" | "refusal"
    expected_decision_type: str = ""   # "direct_legal_answer" | "qualified" | "refusal"
    expected_keywords: list[str] = field(default_factory=list)
    forbidden_keywords: list[str] = field(default_factory=list)
    requires_refusal: bool = False
    requires_qualification: bool = False
    domain: str = ""
    difficulty: str = "medium"         # "easy" | "medium" | "hard"


@dataclass
class EvaluationResult:
    case_id: str
    passed: bool = True
    score: float = 1.0
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    answer_preview: str = ""


class LegalEvaluatorFramework:

    def run_case(self, case: EvaluationCase, answer: str,
                 decision_type: str = "", is_refusal: bool = False) -> EvaluationResult:
        r = EvaluationResult(case_id=case.case_id)
        score = 1.0

        # Check expected keywords
        for kw in case.expected_keywords:
            if kw not in answer:
                r.failures.append(f"missing keyword: {kw}")
                score -= 0.15

        # Check forbidden keywords
        for kw in case.forbidden_keywords:
            if kw in answer:
                r.failures.append(f"forbidden keyword found: {kw}")
                score -= 0.25

        # Check refusal requirement
        if case.requires_refusal and not is_refusal:
            if not any(w in answer for w in ["لا يمكن", "غير متوفر", "تعذر", "لا تتوفر"]):
                r.failures.append("expected refusal but got answer")
                score -= 0.4

        # Check qualification requirement
        if case.requires_qualification:
            if not any(w in answer for w in ["ملاحظة", "تنبيه", "لا يمكن الجزم", "بناءً على"]):
                r.failures.append("expected qualification but none found")
                score -= 0.2

        # Check decision type
        if case.expected_decision_type and decision_type:
            if decision_type != case.expected_decision_type:
                r.failures.append(f"expected decision={case.expected_decision_type} got={decision_type}")
                score -= 0.2

        r.score = max(0.0, round(score, 2))
        r.passed = len(r.failures) == 0
        r.answer_preview = answer[:80]
        return r

    def run_suite(self, cases: list[EvaluationCase],
                  answer_fn: Callable[[str], tuple[str, str, bool]]) -> list[EvaluationResult]:
        """Run a suite. answer_fn(query) -> (answer, decision_type, is_refusal)."""
        results = []
        for case in cases:
            try:
                answer, dt, refusal = answer_fn(case.query)
                r = self.run_case(case, answer, dt, refusal)
            except Exception as e:
                r = EvaluationResult(case_id=case.case_id, passed=False, score=0.0,
                                     failures=[f"exception: {e}"])
            results.append(r)
        return results

    def summarize(self, results: list[EvaluationResult]) -> dict:
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        avg_score = sum(r.score for r in results) / max(total, 1)
        failures = [r.case_id for r in results if not r.passed]
        return {
            "total": total, "passed": passed, "failed": total - passed,
            "pass_rate": round(passed / max(total, 1) * 100, 1),
            "avg_score": round(avg_score, 3),
            "failed_cases": failures,
        }

    def export_json(self, results: list[EvaluationResult]) -> str:
        return json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════════════
# 2. Regression Safety Suite
# ══════════════════════════════════════════════════════════════

@dataclass
class RegressionBaseline:
    case_id: str
    expected_pass: bool
    expected_score_min: float
    snapshot_answer_hash: str = ""


class RegressionSafetySuite:

    def __init__(self):
        self._baselines: dict[str, RegressionBaseline] = {}

    def set_baseline(self, case_id: str, pass_expected: bool, min_score: float,
                     answer_hash: str = ""):
        self._baselines[case_id] = RegressionBaseline(
            case_id=case_id, expected_pass=pass_expected,
            expected_score_min=min_score, snapshot_answer_hash=answer_hash)

    def check_regression(self, results: list[EvaluationResult]) -> list[str]:
        alerts = []
        for r in results:
            bl = self._baselines.get(r.case_id)
            if not bl:
                continue
            if bl.expected_pass and not r.passed:
                alerts.append(f"REGRESSION: {r.case_id} was passing, now failing: {r.failures[:2]}")
            if r.score < bl.expected_score_min:
                alerts.append(f"SCORE_DROP: {r.case_id} score={r.score} < baseline={bl.expected_score_min}")
        if alerts:
            log.warning("[REGRESSION] %d alerts: %s", len(alerts), alerts[:3])
        return alerts


# ══════════════════════════════════════════════════════════════
# 3. Release Readiness Checker
# ══════════════════════════════════════════════════════════════

@dataclass
class ReleaseReadinessReport:
    ready: bool = False
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    score: float = 0.0
    recommended_actions: list[str] = field(default_factory=list)


class ReleaseReadinessChecker:

    def check(self, eval_summary: dict, regression_alerts: list[str],
              safety_result=None, audit_enabled: bool = True,
              commercial_mode: str = "", unresolved_updates: int = 0) -> ReleaseReadinessReport:
        rr = ReleaseReadinessReport()
        score = 100.0

        # Evaluation quality
        pass_rate = eval_summary.get("pass_rate", 0)
        if pass_rate < 80:
            rr.blockers.append(f"evaluation pass rate {pass_rate}% < 80%")
            score -= 30
        elif pass_rate < 95:
            rr.warnings.append(f"evaluation pass rate {pass_rate}% < 95%")
            score -= 10

        # Regressions
        if regression_alerts:
            rr.blockers.append(f"{len(regression_alerts)} regression(s) detected")
            score -= 20

        # Safety
        if safety_result and not safety_result.safe:
            rr.blockers.append(f"production safety failed: {safety_result.violations[:2]}")
            score -= 25

        # Audit
        if not audit_enabled:
            rr.blockers.append("audit trail not enabled")
            score -= 15

        # Commercial mode
        if not commercial_mode:
            rr.warnings.append("commercial mode not configured")
            score -= 5

        # Unresolved law updates
        if unresolved_updates > 3:
            rr.blockers.append(f"{unresolved_updates} unresolved law updates")
            score -= 15
        elif unresolved_updates > 0:
            rr.warnings.append(f"{unresolved_updates} pending law update(s)")

        rr.score = max(0, score)
        rr.ready = len(rr.blockers) == 0 and rr.score >= 70

        if not rr.ready:
            rr.recommended_actions = [f"Fix: {b}" for b in rr.blockers]

        return rr


# ══════════════════════════════════════════════════════════════
# 4. Enterprise Deployment Controls
# ══════════════════════════════════════════════════════════════

class DeploymentEnv(str, Enum):
    LOCAL_DEV = "local_dev"
    STAGING = "staging"
    PRODUCTION = "production"


@dataclass
class DeploymentProfile:
    env: str = DeploymentEnv.LOCAL_DEV.value
    debug_endpoints: bool = True
    audit_verbose: bool = True
    commercial_mode: str = "internal_debug"
    validation_strict: bool = False
    log_sensitive: bool = True


_PROFILES = {
    DeploymentEnv.LOCAL_DEV.value: DeploymentProfile(
        env=DeploymentEnv.LOCAL_DEV.value, debug_endpoints=True,
        audit_verbose=True, commercial_mode="internal_debug",
        validation_strict=False, log_sensitive=True),
    DeploymentEnv.STAGING.value: DeploymentProfile(
        env=DeploymentEnv.STAGING.value, debug_endpoints=True,
        audit_verbose=True, commercial_mode="professional_user",
        validation_strict=True, log_sensitive=False),
    DeploymentEnv.PRODUCTION.value: DeploymentProfile(
        env=DeploymentEnv.PRODUCTION.value, debug_endpoints=False,
        audit_verbose=False, commercial_mode="public_user",
        validation_strict=True, log_sensitive=False),
}


def get_deployment_profile(env: str = "") -> DeploymentProfile:
    return _PROFILES.get(env, _PROFILES[DeploymentEnv.LOCAL_DEV.value])


# ══════════════════════════════════════════════════════════════
# 5. Operational Monitoring Hooks
# ══════════════════════════════════════════════════════════════

class OperationalMonitoringHooks:

    def __init__(self):
        self._lock = threading.Lock()
        self._metrics = {
            "total_answers": 0,
            "refusals": 0,
            "qualifications": 0,
            "conflicts": 0,
            "validation_failures": 0,
            "high_risk": 0,
            "deprecated_attempts": 0,
            "eval_runs": 0,
            "eval_avg_score": 0.0,
        }

    def record_answer(self, decision_type: str = "", is_refusal: bool = False,
                      has_qualification: bool = False, has_conflict: bool = False,
                      is_high_risk: bool = False):
        with self._lock:
            self._metrics["total_answers"] += 1
            if is_refusal:
                self._metrics["refusals"] += 1
            if has_qualification:
                self._metrics["qualifications"] += 1
            if has_conflict:
                self._metrics["conflicts"] += 1
            if is_high_risk:
                self._metrics["high_risk"] += 1

    def record_validation_failure(self):
        with self._lock:
            self._metrics["validation_failures"] += 1

    def record_deprecated_attempt(self):
        with self._lock:
            self._metrics["deprecated_attempts"] += 1

    def record_eval_run(self, avg_score: float):
        with self._lock:
            self._metrics["eval_runs"] += 1
            self._metrics["eval_avg_score"] = avg_score

    def snapshot(self) -> dict:
        with self._lock:
            total = self._metrics["total_answers"]
            return {
                **self._metrics,
                "refusal_rate": round(self._metrics["refusals"] / max(total, 1) * 100, 1),
                "qualification_rate": round(self._metrics["qualifications"] / max(total, 1) * 100, 1),
                "validation_failure_rate": round(self._metrics["validation_failures"] / max(total, 1) * 100, 1),
            }


# Singleton
_monitor: Optional[OperationalMonitoringHooks] = None

def get_monitor() -> OperationalMonitoringHooks:
    global _monitor
    if _monitor is None:
        _monitor = OperationalMonitoringHooks()
    return _monitor
