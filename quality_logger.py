# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║        Quality Logger — المساعد القانوني القطري                              ║
║        يسجّل محلياً: الإجابات منخفضة الثقة + fallback + طلبات التوضيح       ║
╚══════════════════════════════════════════════════════════════════════════════╝

يُخزّن السجلات في: logs/quality_log.jsonl
كل سطر = سجل JSON واحد (newline-delimited JSON)
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── مسار ملف السجل ───────────────────────────────────────────────────────────
_LOG_DIR  = Path(__file__).parent / "logs"
_LOG_FILE = _LOG_DIR / "quality_log.jsonl"

# ── أنواع الأحداث ─────────────────────────────────────────────────────────────
EVENT_LOW_CONFIDENCE  = "low_confidence"
EVENT_FALLBACK        = "fallback_triggered"
EVENT_CLARIFICATION   = "clarification_asked"
EVENT_HALLUCINATION   = "hallucination_detected"
EVENT_DOMAIN_MISMATCH = "domain_mismatch"


def _ensure_log_dir() -> None:
    """ينشئ مجلد logs إذا لم يكن موجوداً."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


def _write_record(record: dict) -> None:
    """يكتب سجلاً JSON واحداً في ملف newline-delimited."""
    try:
        _ensure_log_dir()
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        log.debug("quality_logger write error: %s", e)


def log_low_confidence(
    question: str,
    answer: str,
    score: float,
    domain: str = "",
    session_id: str = "",
) -> None:
    """يسجّل إجابة ذات ثقة منخفضة."""
    _write_record({
        "event":      EVENT_LOW_CONFIDENCE,
        "ts":         time.time(),
        "session":    session_id[:32],
        "domain":     domain,
        "score":      score,
        "question":   question[:200],
        "answer_len": len(answer),
        "answer_pre": answer[:300],
    })
    log.info("quality_log: low_confidence score=%.1f q='%s'", score, question[:60])


def log_fallback(
    question: str,
    reason: str,
    domain: str = "",
    session_id: str = "",
) -> None:
    """يسجّل تشغيل آلية الـ fallback."""
    _write_record({
        "event":   EVENT_FALLBACK,
        "ts":      time.time(),
        "session": session_id[:32],
        "domain":  domain,
        "reason":  reason,
        "question": question[:200],
    })
    log.info("quality_log: fallback reason='%s' q='%s'", reason, question[:60])


def log_clarification(
    question: str,
    clarification_q: str,
    ambiguity_score: float,
    session_id: str = "",
) -> None:
    """يسجّل حالات طلب التوضيح."""
    _write_record({
        "event":           EVENT_CLARIFICATION,
        "ts":              time.time(),
        "session":         session_id[:32],
        "ambiguity_score": ambiguity_score,
        "question":        question[:200],
        "clarification_q": clarification_q[:200],
    })
    log.info(
        "quality_log: clarification ambiguity=%.3f q='%s'",
        ambiguity_score, question[:60]
    )


def log_hallucination(
    question: str,
    hallucinated_citations: list[str],
    session_id: str = "",
) -> None:
    """يسجّل الاستشهادات الوهمية المكتشفة."""
    _write_record({
        "event":    EVENT_HALLUCINATION,
        "ts":       time.time(),
        "session":  session_id[:32],
        "question": question[:200],
        "citations": hallucinated_citations[:5],
    })


def log_domain_mismatch(
    question: str,
    expected_domain: str,
    found_domains: list[str],
    session_id: str = "",
) -> None:
    """يسجّل حالات عدم تطابق المجال القانوني."""
    _write_record({
        "event":          EVENT_DOMAIN_MISMATCH,
        "ts":             time.time(),
        "session":        session_id[:32],
        "question":       question[:200],
        "expected_domain": expected_domain,
        "found_domains":   found_domains[:5],
    })


def get_recent_stats(n: int = 100) -> dict:
    """
    يُعيد إحصائيات موجزة عن آخر n سجل.
    مفيد لـ /admin/quality endpoint.
    """
    if not _LOG_FILE.exists():
        return {"total": 0, "events": {}}

    records = []
    try:
        with open(_LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines[-n:]:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    except Exception as e:
        log.debug("get_recent_stats error: %s", e)
        return {"total": 0, "error": str(e)}

    event_counts: dict[str, int] = {}
    scores: list[float] = []
    for r in records:
        ev = r.get("event", "unknown")
        event_counts[ev] = event_counts.get(ev, 0) + 1
        if r.get("score") is not None:
            scores.append(r["score"])

    return {
        "total":        len(records),
        "events":       event_counts,
        "avg_confidence": round(sum(scores) / len(scores), 1) if scores else None,
        "log_file":     str(_LOG_FILE),
    }
