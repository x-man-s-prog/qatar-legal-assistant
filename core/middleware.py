# -*- coding: utf-8 -*-
"""
core/middleware.py — HTTP middleware for FastAPI
================================================
- security_middleware: API Key auth (optional) + rate limiting + failed-request logging
"""
import asyncio
import logging
import time
from fastapi import Request
from fastapi.responses import JSONResponse
from core import app_state
from core.config import API_KEY

log = logging.getLogger(__name__)

# Paths that never require an API key
PUBLIC_PATHS = {"/", "/health", "/login", "/api/v1/health"}

# Rate limiter — lazy import to avoid circular dependency
_rate_limiter = None


def _get_rate_limiter():
    """Lazy-load the rate limiter singleton."""
    global _rate_limiter
    if _rate_limiter is None:
        try:
            from rate_limiter import get_rate_limiter
            _rate_limiter = get_rate_limiter()
        except ImportError:
            log.warning("rate_limiter module not found — rate limiting disabled")
    return _rate_limiter


# Paths to rate-limit (API endpoints only, not static files or dashboard)
_RATE_LIMITED_PREFIXES = ("/api/v1/query", "/api/v1/stream", "/api/v1/compare")


async def security_middleware(request: Request, call_next):
    """
    1. Enforce X-API-Key on non-public API paths (when API_KEY is configured).
    2. Rate limit on query endpoints.
    3. Log every 4xx/5xx response; persist 5xx to query_logs.
    """
    path = request.url.path
    ip = request.client.host if request.client else "unknown"

    # ── 1. API Key gate (skip for same-origin page requests & public paths) ──
    if API_KEY and not path.startswith("/static") and path not in PUBLIC_PATHS:
        # Allow same-origin requests from dashboard (no API key needed for browser)
        referer = request.headers.get("referer", "")
        origin = request.headers.get("origin", "")
        is_same_origin = any(
            ref.startswith(o) for o in ("http://localhost:", "http://127.0.0.1:", "https://")
            for ref in (referer, origin) if ref
        )
        if not is_same_origin:
            if request.headers.get("X-API-Key", "") != API_KEY:
                log.warning("SECURITY 401: path=%s ip=%s", path, ip)
                return JSONResponse(
                    {"detail": "Unauthorized — X-API-Key required"},
                    status_code=401,
                )

    # ── 2. Rate limiting on API endpoints ──
    if any(path.startswith(p) for p in _RATE_LIMITED_PREFIXES):
        limiter = _get_rate_limiter()
        if limiter:
            try:
                allowed, remaining = await limiter.is_allowed(ip)
                if not allowed:
                    log.warning("RATE_LIMIT 429: path=%s ip=%s", path, ip)
                    return JSONResponse(
                        {
                            "detail": "تم تجاوز الحد الأقصى للطلبات — حاول بعد دقيقة",
                            "error": "rate_limit_exceeded",
                            "retry_after": 60,
                        },
                        status_code=429,
                        headers={
                            "Retry-After": "60",
                            "X-RateLimit-Remaining": str(remaining),
                        },
                    )
            except Exception as e:
                log.debug("rate_limiter check error: %s", e)

    # ── 3. Process request ──
    response = await call_next(request)

    # ── 4. Log failures ──
    status = response.status_code
    if status in (401, 403, 422, 500) or (status >= 400 and not path.startswith("/static")):
        log.warning("FAILED REQUEST: %s %s → %d (ip=%s)", request.method, path, status, ip)
        if status >= 500 and getattr(app_state, "LS_AVAILABLE", False) and app_state.get_logger_service:
            try:
                _ls = app_state.get_logger_service()
                if _ls and getattr(app_state, "pool", None):
                    asyncio.create_task(_ls.log_query(
                        session_id="__system__",
                        query=f"{request.method} {path}",
                        model="system", latency_ms=0,
                        confidence=0, cache_hit=False,
                        error=f"HTTP {status}",
                    ))
            except Exception:
                pass

    return response
