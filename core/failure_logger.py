# -*- coding: utf-8 -*-
"""
Failure Logger — Self-Improvement Foundation
=============================================
Records every refusal, low-confidence answer, and pattern miss into a
structured JSONL log that can be:
  - reviewed by humans for new patterns to support
  - mined later for automatic regex/intent expansion
  - aggregated into weekly improvement reports

Fully synchronous, fail-safe (logging never raises), and zero LLM calls.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("failure_logger")

# Directory for failure logs. Configurable via env.
_LOG_DIR = Path(os.environ.get("FAILURE_LOG_DIR", "/var/log/legal_assistant"))
try:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
except (PermissionError, OSError):
    # Fallback to a project-local logs dir
    _LOG_DIR = Path(__file__).parent.parent / "logs"
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

_LOG_FILE = _LOG_DIR / "failures.jsonl"
_LOCK = threading.Lock()


# Categories of failure we track ──────────────────────────────────────
class FailureType:
    REFUSAL = "refusal"                 # structured refusal returned
    LOW_CONFIDENCE = "low_confidence"   # answer < 50% conf
    GRADE_MISS = "grade_miss"           # specific grade not in table
    GENERIC_FALLBACK = "generic_fallback"   # had to fall back to LLM
    PARSE_FAILURE = "parse_failure"     # builder couldn't parse rows
    EMPTY_RESULT = "empty_result"       # query produced no answer
    USER_NEGATIVE = "user_negative"     # user thumbs-down


def log_failure(
    failure_type: str,
    query: str,
    intent: Optional[str] = None,
    confidence: int = 0,
    refusal_text: Optional[str] = None,
    extra: Optional[dict] = None,
) -> None:
    """Record a single failure event. Never raises."""
    try:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": failure_type,
            "intent": intent or "",
            "query": (query or "")[:500],
            "confidence": int(confidence) if confidence is not None else 0,
            "refusal_text": (refusal_text or "")[:500],
            "extra": extra or {},
        }
        line = json.dumps(record, ensure_ascii=False)
        with _LOCK:
            with _LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        log.info("[FAILURE_LOG] %s intent=%s query=%s", failure_type, intent, query[:60])
    except Exception as e:  # noqa: BLE001
        # Never let logging break the request path
        log.error("[FAILURE_LOG] failed to record: %s", e)


def read_failures(limit: int = 1000) -> list[dict]:
    """Read recent failure records (most recent last)."""
    if not _LOG_FILE.exists():
        return []
    try:
        with _LOG_FILE.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        records = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records
    except Exception as e:  # noqa: BLE001
        log.error("[FAILURE_LOG] read failed: %s", e)
        return []


def summarize_failures(limit: int = 1000) -> dict:
    """Aggregate failures into a summary dict.

    Returns:
      {
        "total": int,
        "by_type": {type: count, ...},
        "by_intent": {intent: count, ...},
        "top_queries": [(query, count), ...],
        "first_ts": str,
        "last_ts": str,
      }
    """
    records = read_failures(limit=limit)
    if not records:
        return {
            "total": 0, "by_type": {}, "by_intent": {},
            "top_queries": [], "first_ts": "", "last_ts": "",
        }

    by_type: Counter = Counter()
    by_intent: Counter = Counter()
    by_query: Counter = Counter()
    for r in records:
        by_type[r.get("type", "")] += 1
        by_intent[r.get("intent", "")] += 1
        q = (r.get("query", "") or "").strip()
        if q:
            by_query[q] += 1

    return {
        "total": len(records),
        "by_type": dict(by_type),
        "by_intent": dict(by_intent),
        "top_queries": by_query.most_common(20),
        "first_ts": records[0].get("ts", ""),
        "last_ts": records[-1].get("ts", ""),
    }


def find_repeated_failures(min_count: int = 3, limit: int = 1000) -> list[dict]:
    """Find queries that have failed N+ times — these are top improvement targets."""
    records = read_failures(limit=limit)
    by_query: dict[str, dict[str, Any]] = {}
    for r in records:
        q = (r.get("query", "") or "").strip()
        if not q:
            continue
        if q not in by_query:
            by_query[q] = {
                "query": q, "count": 0, "intents": Counter(), "types": Counter()
            }
        by_query[q]["count"] += 1
        if r.get("intent"):
            by_query[q]["intents"][r["intent"]] += 1
        if r.get("type"):
            by_query[q]["types"][r["type"]] += 1

    repeated = [
        {
            "query": v["query"],
            "count": v["count"],
            "intents": dict(v["intents"]),
            "types": dict(v["types"]),
        }
        for v in by_query.values() if v["count"] >= min_count
    ]
    repeated.sort(key=lambda x: x["count"], reverse=True)
    return repeated


def clear_failures() -> int:
    """Delete the failures log. Returns number of records removed."""
    if not _LOG_FILE.exists():
        return 0
    try:
        records = read_failures(limit=10**9)
        _LOG_FILE.unlink()
        return len(records)
    except Exception as e:  # noqa: BLE001
        log.error("[FAILURE_LOG] clear failed: %s", e)
        return 0
