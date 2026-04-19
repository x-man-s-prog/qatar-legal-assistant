# -*- coding: utf-8 -*-
"""
Self-Diagnostic + Auto-Alert system.

Tracks per-request telemetry and raises ALERT logs when block_rate or
cross-domain-error-rate exceed thresholds. Thread-safe, in-memory.

No external dependencies. Accessible via:
  - core.self_diagnostic.record_request(...)
  - core.self_diagnostic.snapshot()
  - GET /debug/self-diagnostic (wired in main.py)
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("self_diagnostic")


# ── Alert thresholds ──
BLOCK_RATE_ALERT      = 0.20   # > 20% blocked → ALERT
CROSS_DOMAIN_RATE_ALERT = 0.05 # > 5% cross-domain → ALERT
WINDOW_SIZE           = 100    # last N requests


@dataclass
class RequestTelemetry:
    ts:                  float = 0.0
    session_id:          str = ""
    domain_detected:     str = ""
    confidence:          float = 0.0
    markers_used:        int = 0
    tokens:              int = 0
    issue_count:         int = 0
    evidence_count:      int = 0
    gates_passed:        int = 0
    blocked:             bool = False
    block_reason:        str = ""
    cross_domain_flag:   bool = False
    low_confidence_flag: bool = False
    contamination_blocked: int = 0
    elapsed_ms:          float = 0.0

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


class SelfDiagnosticRecorder:
    def __init__(self, window: int = WINDOW_SIZE):
        self._lock = threading.RLock()
        self._window = window
        self._entries: deque[RequestTelemetry] = deque(maxlen=window)
        self._alerts_raised: list[dict] = []

    def record(self, **kwargs) -> RequestTelemetry:
        t = RequestTelemetry(ts=time.time(), **kwargs)
        with self._lock:
            self._entries.append(t)
            self._check_alerts()
        return t

    def snapshot(self) -> dict:
        with self._lock:
            if not self._entries:
                return {
                    "window":          self._window,
                    "samples":         0,
                    "alert_thresholds": {
                        "block_rate":        BLOCK_RATE_ALERT,
                        "cross_domain_rate": CROSS_DOMAIN_RATE_ALERT,
                    },
                }
            n = len(self._entries)
            blocked = sum(1 for e in self._entries if e.blocked)
            cross = sum(1 for e in self._entries if e.cross_domain_flag)
            low_conf = sum(1 for e in self._entries if e.low_confidence_flag)
            contam = sum(1 for e in self._entries if e.contamination_blocked > 0)
            avg_conf = sum(e.confidence for e in self._entries) / n
            avg_elapsed = sum(e.elapsed_ms for e in self._entries) / n
            per_domain: dict[str, int] = {}
            for e in self._entries:
                if e.domain_detected:
                    per_domain[e.domain_detected] = per_domain.get(e.domain_detected, 0) + 1
            return {
                "window":              self._window,
                "samples":             n,
                "block_rate":          round(blocked / n, 3),
                "cross_domain_rate":   round(cross / n, 3),
                "low_confidence_rate": round(low_conf / n, 3),
                "contamination_rate":  round(contam / n, 3),
                "avg_confidence":      round(avg_conf, 3),
                "avg_elapsed_ms":      round(avg_elapsed, 1),
                "per_domain":          per_domain,
                "recent_alerts":       list(self._alerts_raised[-5:]),
                "alert_thresholds":    {
                    "block_rate":        BLOCK_RATE_ALERT,
                    "cross_domain_rate": CROSS_DOMAIN_RATE_ALERT,
                },
            }

    def reset(self) -> None:
        with self._lock:
            self._entries.clear()
            self._alerts_raised.clear()

    # ── internal ──
    def _check_alerts(self) -> None:
        n = len(self._entries)
        if n < 20:
            return   # need enough samples
        blocked = sum(1 for e in self._entries if e.blocked)
        cross = sum(1 for e in self._entries if e.cross_domain_flag)
        br = blocked / n
        cr = cross / n
        now = time.time()
        if br > BLOCK_RATE_ALERT:
            alert = {
                "ts":       now,
                "type":     "high_block_rate",
                "value":    round(br, 3),
                "threshold": BLOCK_RATE_ALERT,
                "samples":  n,
            }
            self._alerts_raised.append(alert)
            log.warning("[SELF_DIAGNOSTIC] ALERT high_block_rate=%.1f%% "
                         "(threshold=%.0f%%, n=%d)",
                         br * 100, BLOCK_RATE_ALERT * 100, n)
        if cr > CROSS_DOMAIN_RATE_ALERT:
            alert = {
                "ts":       now,
                "type":     "high_cross_domain_rate",
                "value":    round(cr, 3),
                "threshold": CROSS_DOMAIN_RATE_ALERT,
                "samples":  n,
            }
            self._alerts_raised.append(alert)
            log.warning("[SELF_DIAGNOSTIC] ALERT high_cross_domain_rate=%.1f%% "
                         "(threshold=%.1f%%, n=%d)",
                         cr * 100, CROSS_DOMAIN_RATE_ALERT * 100, n)
        # Cap alert log
        if len(self._alerts_raised) > 50:
            self._alerts_raised = self._alerts_raised[-50:]


_recorder: Optional[SelfDiagnosticRecorder] = None


def get_recorder() -> SelfDiagnosticRecorder:
    global _recorder
    if _recorder is None:
        _recorder = SelfDiagnosticRecorder()
    return _recorder


def record_request(**kwargs) -> RequestTelemetry:
    return get_recorder().record(**kwargs)


def snapshot() -> dict:
    return get_recorder().snapshot()
