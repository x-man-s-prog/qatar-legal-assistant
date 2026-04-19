# -*- coding: utf-8 -*-
"""
Controlled Public Beta System
==============================
Runtime control, monitoring, incident detection, safety response, kill switch,
feedback collection, and cohort tracking for public beta release.
"""
from __future__ import annotations
import logging, threading, time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("beta")


# ══════════════════════════════════════════════════════════════
# Beta Policy Config
# ══════════════════════════════════════════════════════════════

@dataclass
class BetaPolicyConfig:
    max_users: int = 100
    rate_limit_per_minute: int = 10
    high_risk_threshold: float = 0.6
    minimum_quality_score: float = 0.5
    escalation_threshold: float = 0.3    # If escalation rate exceeds this
    fallback_threshold: float = 0.2      # If fallback rate exceeds this
    incident_trigger_limits: dict = field(default_factory=lambda: {
        "underwarning": 3,
        "premature_answer": 1,
        "quality_below_threshold": 5,
    })


_config = BetaPolicyConfig()

def get_beta_config() -> BetaPolicyConfig:
    return _config

def set_beta_config(c: BetaPolicyConfig):
    global _config
    _config = c


# ══════════════════════════════════════════════════════════════
# 1. Beta Access Controller
# ══════════════════════════════════════════════════════════════

class BetaAccessController:

    def __init__(self, config: BetaPolicyConfig = None):
        self._config = config or get_beta_config()
        self._allowed: set[str] = set()
        self._sessions: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def register_user(self, user_id: str) -> bool:
        with self._lock:
            if len(self._allowed) >= self._config.max_users and user_id not in self._allowed:
                return False
            self._allowed.add(user_id)
            return True

    def is_allowed(self, user_id: str) -> bool:
        return user_id in self._allowed

    def enforce_rate_limit(self, user_id: str) -> bool:
        now = time.time()
        with self._lock:
            reqs = self._sessions[user_id]
            reqs[:] = [t for t in reqs if now - t < 60]
            if len(reqs) >= self._config.rate_limit_per_minute:
                return False
            reqs.append(now)
            return True

    def active_users(self) -> int:
        return len(self._allowed)


# ══════════════════════════════════════════════════════════════
# 2. Beta Live Monitor
# ══════════════════════════════════════════════════════════════

class BetaLiveMonitor:

    def __init__(self):
        self._lock = threading.Lock()
        self._data = {
            "total_requests": 0,
            "high_risk": 0,
            "escalations": 0,
            "fallbacks": 0,
            "refusals": 0,
            "guidances": 0,
            "guardrails": 0,
            "quality_sum": 0.0,
            "confidence_sum": 0.0,
        }

    def record(self, risk_level: str = "low", escalated: bool = False,
               fallback: bool = False, refusal: bool = False,
               guidance: bool = False, guardrail: bool = False,
               quality: float = 1.0, confidence: float = 1.0):
        with self._lock:
            self._data["total_requests"] += 1
            if risk_level.startswith("high"):
                self._data["high_risk"] += 1
            if escalated: self._data["escalations"] += 1
            if fallback: self._data["fallbacks"] += 1
            if refusal: self._data["refusals"] += 1
            if guidance: self._data["guidances"] += 1
            if guardrail: self._data["guardrails"] += 1
            self._data["quality_sum"] += quality
            self._data["confidence_sum"] += confidence

    def snapshot(self) -> dict:
        with self._lock:
            t = max(self._data["total_requests"], 1)
            return {
                "total_requests": self._data["total_requests"],
                "high_risk_rate": round(self._data["high_risk"] / t * 100, 1),
                "escalation_rate": round(self._data["escalations"] / t * 100, 1),
                "fallback_rate": round(self._data["fallbacks"] / t * 100, 1),
                "refusal_rate": round(self._data["refusals"] / t * 100, 1),
                "guidance_rate": round(self._data["guidances"] / t * 100, 1),
                "guardrail_rate": round(self._data["guardrails"] / t * 100, 1),
                "avg_quality": round(self._data["quality_sum"] / t, 3),
                "avg_confidence": round(self._data["confidence_sum"] / t, 3),
            }


# ══════════════════════════════════════════════════════════════
# 3. Incident Detector
# ══════════════════════════════════════════════════════════════

class IncidentSeverity:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class BetaIncident:
    incident_id: str
    severity: str
    description: str
    timestamp: str = ""
    query_preview: str = ""


class BetaIncidentDetector:

    def __init__(self, config: BetaPolicyConfig = None):
        self._config = config or get_beta_config()
        self._incidents: list[BetaIncident] = []
        self._counters: dict[str, int] = defaultdict(int)

    def check(self, quality: float, risk_level: str, guidance_applied: bool,
              guardrail_applied: bool, fallback: bool,
              query: str = "") -> Optional[BetaIncident]:

        # Quality below threshold
        if quality < self._config.minimum_quality_score:
            self._counters["low_quality"] += 1
            if self._counters["low_quality"] >= self._config.incident_trigger_limits.get("quality_below_threshold", 5):
                return self._create("quality_degradation", IncidentSeverity.HIGH,
                                     "Repeated low quality scores", query)

        # High risk without guardrail
        if risk_level.startswith("high") and not guardrail_applied and not guidance_applied:
            self._counters["underwarning"] += 1
            if self._counters["underwarning"] >= self._config.incident_trigger_limits.get("underwarning", 3):
                return self._create("underwarning_pattern", IncidentSeverity.CRITICAL,
                                     "Repeated underwarning in high-risk cases", query)

        return None

    def _create(self, iid: str, severity: str, desc: str, query: str) -> BetaIncident:
        incident = BetaIncident(
            incident_id=iid, severity=severity, description=desc,
            timestamp=datetime.now(timezone.utc).isoformat(),
            query_preview=query[:50])
        self._incidents.append(incident)
        log.warning("[INCIDENT] %s severity=%s: %s", iid, severity, desc)
        return incident

    def get_incidents(self) -> list[BetaIncident]:
        return list(self._incidents)

    def clear(self):
        self._incidents.clear()
        self._counters.clear()


# ══════════════════════════════════════════════════════════════
# 4. Safety Responder
# ══════════════════════════════════════════════════════════════

class BetaSafetyResponder:

    def __init__(self):
        self._safe_mode = False
        self._restricted_domains: set[str] = set()
        self._stricter_guardrails = False

    def enable_safe_mode(self):
        self._safe_mode = True
        self._stricter_guardrails = True
        log.warning("[BETA_SAFETY] safe mode ENABLED")

    def disable_safe_mode(self):
        self._safe_mode = False
        self._stricter_guardrails = False
        log.info("[BETA_SAFETY] safe mode disabled")

    def restrict_domain(self, domain: str):
        self._restricted_domains.add(domain)
        log.warning("[BETA_SAFETY] domain restricted: %s", domain)

    def unrestrict_domain(self, domain: str):
        self._restricted_domains.discard(domain)

    def is_safe_mode(self) -> bool:
        return self._safe_mode

    def is_domain_restricted(self, domain: str) -> bool:
        return domain in self._restricted_domains

    def should_force_fallback(self, domain: str, risk_level: str) -> bool:
        if self._safe_mode and risk_level.startswith("high"):
            return True
        if domain in self._restricted_domains:
            return True
        return False

    def react_to_incident(self, incident: BetaIncident):
        if incident.severity == IncidentSeverity.CRITICAL:
            self.enable_safe_mode()
        elif incident.severity == IncidentSeverity.HIGH:
            self._stricter_guardrails = True


# ══════════════════════════════════════════════════════════════
# 5. Kill Switch
# ══════════════════════════════════════════════════════════════

class BetaKillSwitch:

    def __init__(self):
        self._active = False
        self._low_risk_only = False
        self._disabled_domains: set[str] = set()
        self._emergency_fallback = False

    def activate(self, low_risk_only: bool = False, emergency: bool = False):
        self._active = True
        self._low_risk_only = low_risk_only
        self._emergency_fallback = emergency
        log.critical("[KILL_SWITCH] ACTIVATED low_risk_only=%s emergency=%s",
                     low_risk_only, emergency)

    def deactivate(self):
        self._active = False
        self._low_risk_only = False
        self._emergency_fallback = False
        self._disabled_domains.clear()
        log.info("[KILL_SWITCH] deactivated")

    def is_active(self) -> bool:
        return self._active

    def disable_domain(self, domain: str):
        self._disabled_domains.add(domain)

    def should_block(self, domain: str = "", risk_level: str = "low") -> bool:
        if not self._active:
            return False
        if self._emergency_fallback:
            return True
        if self._low_risk_only and risk_level.startswith("high"):
            return True
        if domain in self._disabled_domains:
            return True
        return False

    def get_fallback_message(self) -> str:
        return ("النظام في وضع الصيانة حالياً. يرجى المحاولة لاحقاً "
                "أو مراجعة بوابة الميزان (almeezan.qa).")


# ══════════════════════════════════════════════════════════════
# 6. Feedback Collector
# ══════════════════════════════════════════════════════════════

@dataclass
class UserFeedback:
    user_id: str
    query: str
    rating: int  # 1=bad, 5=good
    comment: str = ""
    timestamp: str = ""


class BetaFeedbackCollector:

    def __init__(self):
        self._feedback: list[UserFeedback] = []

    def record(self, user_id: str, query: str, rating: int, comment: str = ""):
        self._feedback.append(UserFeedback(
            user_id=user_id, query=query[:200], rating=rating, comment=comment[:200],
            timestamp=datetime.now(timezone.utc).isoformat()))

    def aggregate(self) -> dict:
        if not self._feedback:
            return {"count": 0, "avg_rating": 0}
        ratings = [f.rating for f in self._feedback]
        return {
            "count": len(self._feedback),
            "avg_rating": round(sum(ratings) / len(ratings), 2),
            "positive": sum(1 for r in ratings if r >= 4),
            "negative": sum(1 for r in ratings if r <= 2),
        }

    def common_failures(self) -> list[str]:
        negative = [f for f in self._feedback if f.rating <= 2]
        queries = [f.query[:40] for f in negative[:10]]
        return queries


# ══════════════════════════════════════════════════════════════
# 7. Cohort Tracker
# ══════════════════════════════════════════════════════════════

@dataclass
class UserCohortEntry:
    user_id: str
    queries: int = 0
    high_risk_queries: int = 0
    guided_queries: int = 0
    avg_quality: float = 0.0
    first_seen: str = ""


class BetaUserCohortTracker:

    def __init__(self):
        self._users: dict[str, UserCohortEntry] = {}

    def track(self, user_id: str, risk_level: str = "low",
              guided: bool = False, quality: float = 1.0):
        if user_id not in self._users:
            self._users[user_id] = UserCohortEntry(
                user_id=user_id, first_seen=datetime.now(timezone.utc).isoformat())
        u = self._users[user_id]
        u.queries += 1
        if risk_level.startswith("high"):
            u.high_risk_queries += 1
        if guided:
            u.guided_queries += 1
        # Running average
        u.avg_quality = round(
            (u.avg_quality * (u.queries - 1) + quality) / u.queries, 3)

    def get_summary(self, user_id: str) -> Optional[UserCohortEntry]:
        return self._users.get(user_id)

    def cohort_report(self) -> dict:
        total = len(self._users)
        if total == 0:
            return {"users": 0}
        avg_q = sum(u.avg_quality for u in self._users.values()) / total
        heavy = sum(1 for u in self._users.values() if u.queries > 20)
        return {
            "users": total,
            "total_queries": sum(u.queries for u in self._users.values()),
            "avg_quality": round(avg_q, 3),
            "heavy_users": heavy,
        }


# ══════════════════════════════════════════════════════════════
# Singletons
# ══════════════════════════════════════════════════════════════

_access: Optional[BetaAccessController] = None
_monitor: Optional[BetaLiveMonitor] = None
_incidents: Optional[BetaIncidentDetector] = None
_safety: Optional[BetaSafetyResponder] = None
_kill: Optional[BetaKillSwitch] = None
_feedback: Optional[BetaFeedbackCollector] = None
_cohort: Optional[BetaUserCohortTracker] = None

def get_beta_access() -> BetaAccessController:
    global _access
    if _access is None: _access = BetaAccessController()
    return _access

def get_beta_monitor() -> BetaLiveMonitor:
    global _monitor
    if _monitor is None: _monitor = BetaLiveMonitor()
    return _monitor

def get_beta_incidents() -> BetaIncidentDetector:
    global _incidents
    if _incidents is None: _incidents = BetaIncidentDetector()
    return _incidents

def get_beta_safety() -> BetaSafetyResponder:
    global _safety
    if _safety is None: _safety = BetaSafetyResponder()
    return _safety

def get_beta_kill() -> BetaKillSwitch:
    global _kill
    if _kill is None: _kill = BetaKillSwitch()
    return _kill

def get_beta_feedback() -> BetaFeedbackCollector:
    global _feedback
    if _feedback is None: _feedback = BetaFeedbackCollector()
    return _feedback

def get_beta_cohort() -> BetaUserCohortTracker:
    global _cohort
    if _cohort is None: _cohort = BetaUserCohortTracker()
    return _cohort
