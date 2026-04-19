# -*- coding: utf-8 -*-
"""
core/observability.py — Observability (Sentry + Structured Logging)
====================================================================
Optional Sentry integration for error tracking and performance monitoring.
Activated only when SENTRY_DSN environment variable is set.
"""
import os
import logging
import time
from functools import wraps

log = logging.getLogger(__name__)

_sentry_initialized = False


def init_sentry():
    """Initialize Sentry SDK if SENTRY_DSN is configured."""
    global _sentry_initialized
    dsn = os.getenv("SENTRY_DSN", "")
    if not dsn:
        log.info("SENTRY_DSN not set — observability disabled")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_sdk.init(
            dsn=dsn,
            environment=os.getenv("ENVIRONMENT", "production"),
            release=os.getenv("APP_VERSION", "v9.0"),
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_RATE", "0.2")),
            profiles_sample_rate=float(os.getenv("SENTRY_PROFILES_RATE", "0.1")),
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                LoggingIntegration(level=logging.WARNING, event_level=logging.ERROR),
            ],
            before_send=_before_send,
            send_default_pii=False,
        )
        _sentry_initialized = True
        log.info("✓ Sentry initialized (env=%s)", os.getenv("ENVIRONMENT", "production"))
        return True
    except ImportError:
        log.info("sentry-sdk not installed — observability disabled")
        return False
    except Exception as e:
        log.warning("Sentry init failed: %s", e)
        return False


def _before_send(event, hint):
    """Filter sensitive data before sending to Sentry."""
    # Remove API keys from breadcrumbs
    if "breadcrumbs" in event:
        for bc in event.get("breadcrumbs", {}).get("values", []):
            msg = bc.get("message", "")
            if "API_KEY" in msg or "api_key" in msg or "sk-" in msg:
                bc["message"] = "[REDACTED]"
    # Remove sensitive headers
    if "request" in event:
        headers = event["request"].get("headers", {})
        for key in list(headers.keys()):
            if key.lower() in ("x-api-key", "authorization", "cookie"):
                headers[key] = "[REDACTED]"
    return event


def capture_error(error: Exception, context: dict = None):
    """Capture an exception to Sentry with optional context."""
    if not _sentry_initialized:
        return
    try:
        import sentry_sdk
        if context:
            sentry_sdk.set_context("legal_assistant", context)
        sentry_sdk.capture_exception(error)
    except Exception:
        pass


def set_user_context(session_id: str, model: str = "", mode: str = ""):
    """Set user context for Sentry events."""
    if not _sentry_initialized:
        return
    try:
        import sentry_sdk
        sentry_sdk.set_user({"id": session_id})
        sentry_sdk.set_tag("model", model)
        sentry_sdk.set_tag("mode", mode)
    except Exception:
        pass


def track_query(query: str, model: str, latency_ms: int, confidence: float,
                had_sources: bool, domain: str = ""):
    """Record a breadcrumb for query tracking."""
    if not _sentry_initialized:
        return
    try:
        import sentry_sdk
        sentry_sdk.add_breadcrumb(
            category="query",
            message=f"model={model} latency={latency_ms}ms conf={confidence:.0f}",
            data={
                "query_length": len(query),
                "model": model,
                "latency_ms": latency_ms,
                "confidence": confidence,
                "had_sources": had_sources,
                "domain": domain,
            },
            level="info",
        )
    except Exception:
        pass


def start_transaction(name: str, op: str = "query"):
    """Start a Sentry transaction for performance monitoring."""
    if not _sentry_initialized:
        return None
    try:
        import sentry_sdk
        return sentry_sdk.start_transaction(name=name, op=op)
    except Exception:
        return None
