# -*- coding: utf-8 -*-
"""
Beta Middleware — Wires beta system into the live request/response flow.
Provides pre-request checks and post-response hooks.
Minimal footprint, no logic duplication.
"""
import logging
from typing import Optional
from core.beta_system import (
    get_beta_access, get_beta_monitor, get_beta_incidents,
    get_beta_safety, get_beta_kill, get_beta_feedback,
    get_beta_cohort, get_beta_config,
)

log = logging.getLogger("beta_mw")

# Feature toggle — set to True to enable beta controls
BETA_ENABLED = True

# ══════════════════════════════════════════════════════════════
# Runtime Context (avoids scattered parameter passing)
# ══════════════════════════════════════════════════════════════

from dataclasses import dataclass, field

@dataclass
class BetaRuntimeContext:
    session_id: str = ""
    query: str = ""
    domain: str = ""
    risk_level: str = "low"
    final_status: str = "ok"
    response_mode: str = "normal"
    quality_score: float = 1.0
    confidence: float = 1.0
    fallback_used: bool = False
    guidance_used: bool = False
    guardrail_used: bool = False
    escalated: bool = False
    refusal: bool = False
    blocked: bool = False
    notes_internal: list[str] = field(default_factory=list)

# Thread-local context storage
import threading
_ctx_local = threading.local()

def set_beta_context(ctx: BetaRuntimeContext):
    _ctx_local.ctx = ctx

def get_beta_context() -> Optional[BetaRuntimeContext]:
    return getattr(_ctx_local, "ctx", None)

def clear_beta_context():
    _ctx_local.ctx = None


# ══════════════════════════════════════════════════════════════
# FastAPI HTTP Middleware (global)
# ══════════════════════════════════════════════════════════════

from fastapi import Request as _FReq
from fastapi.responses import JSONResponse as _JResp

_BETA_PATHS = ("/api/v1/query", "/api/v1/stream")
_BETA_PUBLIC_PATHS = {"/api/v1/beta/metrics", "/api/v1/beta/feedback", "/", "/health"}


async def beta_http_middleware(request: _FReq, call_next):
    """
    Global beta middleware. Runs for API endpoints.
    Pre: access + rate + kill switch.
    Post: monitoring + incident detection (via context flush).
    """
    path = request.url.path
    if not BETA_ENABLED or not any(path.startswith(p) for p in _BETA_PATHS):
        return await call_next(request)

    # Extract session from body is hard in middleware — use IP as fallback session
    ip = request.client.host if request.client else "unknown"
    session_id = request.headers.get("X-Session-ID", ip)

    # Initialize context
    ctx = BetaRuntimeContext(session_id=session_id)
    set_beta_context(ctx)

    # Pre-request gate (lightweight: access + rate + kill switch)
    block_msg = beta_pre_request(session_id)
    if block_msg:
        ctx.blocked = True
        clear_beta_context()
        # For streaming paths, still return JSON block (client handles)
        return _JResp(
            {"answer": block_msg, "sources": [], "confidence": 0, "from_beta_gate": True},
            status_code=200)

    # Process request
    response = await call_next(request)

    # Post-response: flush context
    ctx = get_beta_context()
    if ctx and not ctx.blocked:
        beta_post_response(
            session_id=ctx.session_id, query=ctx.query,
            risk_level=ctx.risk_level, domain=ctx.domain,
            quality=ctx.quality_score, confidence=ctx.confidence,
            guidance_applied=ctx.guidance_used,
            guardrail_applied=ctx.guardrail_used,
            fallback=ctx.fallback_used,
            escalated=ctx.escalated, refusal=ctx.refusal)

    clear_beta_context()
    return response


# ══════════════════════════════════════════════════════════════
# Pre-Request Gate
# ══════════════════════════════════════════════════════════════

def beta_pre_request(session_id: str, query: str = "",
                      risk_level: str = "low", domain: str = "") -> Optional[str]:
    """
    Run before processing. Returns block message or None to proceed.
    """
    if not BETA_ENABLED:
        return None

    # 1. Kill switch
    kill = get_beta_kill()
    if kill.is_active():
        if kill.should_block(domain=domain, risk_level=risk_level):
            log.warning("[BETA_MW] kill switch blocked: domain=%s risk=%s", domain, risk_level)
            return kill.get_fallback_message()

    # 2. Safety responder — domain restriction
    safety = get_beta_safety()
    if safety.should_force_fallback(domain, risk_level):
        log.warning("[BETA_MW] safety forced fallback: domain=%s", domain)
        return ("هذا النوع من الأسئلة متوقف مؤقتاً للصيانة. "
                "يرجى مراجعة بوابة الميزان (almeezan.qa).")

    # 3. Access control
    access = get_beta_access()
    if not access.is_allowed(session_id):
        # Auto-register if under limit
        if not access.register_user(session_id):
            log.info("[BETA_MW] user blocked (max capacity): %s", session_id[:20])
            return "النظام في مرحلة تجريبية محدودة. يرجى المحاولة لاحقاً."

    # 4. Rate limit
    if not access.enforce_rate_limit(session_id):
        log.info("[BETA_MW] rate limited: %s", session_id[:20])
        return "عدد الأسئلة تجاوز الحد المسموح. يرجى الانتظار دقيقة."

    return None


# ══════════════════════════════════════════════════════════════
# Post-Response Hook
# ══════════════════════════════════════════════════════════════

def beta_post_response(session_id: str, query: str = "",
                        risk_level: str = "low", domain: str = "",
                        quality: float = 1.0, confidence: float = 1.0,
                        guidance_applied: bool = False,
                        guardrail_applied: bool = False,
                        fallback: bool = False,
                        escalated: bool = False,
                        refusal: bool = False):
    """
    Run after response is generated. Records metrics and checks incidents.
    """
    if not BETA_ENABLED:
        return

    # 1. Monitor
    monitor = get_beta_monitor()
    monitor.record(
        risk_level=risk_level, escalated=escalated,
        fallback=fallback, refusal=refusal,
        guidance=guidance_applied, guardrail=guardrail_applied,
        quality=quality, confidence=confidence)

    # 2. Cohort tracking
    cohort = get_beta_cohort()
    cohort.track(session_id, risk_level, guidance_applied, quality)

    # 3. Incident detection
    incidents = get_beta_incidents()
    incident = incidents.check(
        quality=quality, risk_level=risk_level,
        guidance_applied=guidance_applied,
        guardrail_applied=guardrail_applied,
        fallback=fallback, query=query)

    # 4. Safety response to incident
    if incident:
        safety = get_beta_safety()
        safety.react_to_incident(incident)
        log.warning("[BETA_MW] incident triggered safety response: %s", incident.severity)


# ══════════════════════════════════════════════════════════════
# Feedback Helper
# ══════════════════════════════════════════════════════════════

def beta_record_feedback(session_id: str, query: str,
                          rating: int, comment: str = ""):
    """Record user feedback."""
    if not BETA_ENABLED:
        return
    feedback = get_beta_feedback()
    feedback.record(session_id, query, rating, comment)
    log.info("[BETA_MW] feedback: user=%s rating=%d", session_id[:20], rating)


# ══════════════════════════════════════════════════════════════
# Status / Metrics Helpers
# ══════════════════════════════════════════════════════════════

def beta_metrics_snapshot() -> dict:
    """Get current beta metrics."""
    return {
        "monitor": get_beta_monitor().snapshot(),
        "cohort": get_beta_cohort().cohort_report(),
        "feedback": get_beta_feedback().aggregate(),
        "incidents": len(get_beta_incidents().get_incidents()),
        "kill_switch": get_beta_kill().is_active(),
        "safe_mode": get_beta_safety().is_safe_mode(),
        "active_users": get_beta_access().active_users(),
    }
