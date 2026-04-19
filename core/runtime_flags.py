# -*- coding: utf-8 -*-
"""
Runtime flags — production rewiring control.

All flags are env-driven. Defaults are EXPLICITLY pro-fail-closed:
  - New runtime is the default live path.
  - Legacy fallback is OFF unless explicitly enabled.
  - Strict gating is ON.

These flags exist for emergency overrides only — NOT as a permanent
two-path design. The snapshot is logged on import so configuration
drift cannot hide.
"""
from __future__ import annotations
import os
import logging

log = logging.getLogger("runtime_flags")


def _parse_bool(raw, default: bool) -> bool:
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on", "enabled")


# ── Flags ────────────────────────────────────────────────────────
#
# UNIFICATION LOCK: after Monolithic Runtime Unification, USE_FAIL_CLOSED_RUNTIME
# is FORCED to True and ENABLE_LEGACY_FALLBACK is FORCED to False. Env vars
# cannot override these — the legacy code paths no longer exist to fall back to.
# Flags are retained as constants for backward compatibility with callers that
# still read them; they no longer control runtime behavior.

# Master — ALWAYS True after unification. The only runtime is fail-closed.
USE_FAIL_CLOSED_RUNTIME: bool = True

# Legacy fallback — ALWAYS False. The legacy router was DELETED, no path to
# fall back to. Reading env is informational only.
_LEGACY_FLAG_ENV = _parse_bool(os.getenv("ENABLE_LEGACY_FALLBACK"), False)
if _LEGACY_FLAG_ENV:
    log.error(
        "[RUNTIME_FLAGS] ENABLE_LEGACY_FALLBACK=true detected — IGNORED. "
        "Legacy runtime was deleted during unification. "
        "Setting has no effect."
    )
ENABLE_LEGACY_FALLBACK: bool = False

# Stream legacy path — ALWAYS disabled. Same reason.
DISABLE_STREAM_LEGACY_PATH: bool = True

# Gates — ALWAYS strict.
STRICT_PRODUCTION_GATING: bool = True


def snapshot() -> dict:
    """Return current flag values for logging and health checks."""
    return {
        "USE_FAIL_CLOSED_RUNTIME":    USE_FAIL_CLOSED_RUNTIME,
        "ENABLE_LEGACY_FALLBACK":     ENABLE_LEGACY_FALLBACK,
        "DISABLE_STREAM_LEGACY_PATH": DISABLE_STREAM_LEGACY_PATH,
        "STRICT_PRODUCTION_GATING":   STRICT_PRODUCTION_GATING,
    }


def reload_from_env() -> dict:
    """No-op after unification: flags are constants now.

    Kept for backward-compatibility with callers (tests that still invoke
    it). Any legacy env values are ignored.
    """
    return snapshot()


# Surface flag state on import so deployment drift is visible in logs.
log.info("[RUNTIME_FLAGS] %s", snapshot())
