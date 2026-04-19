# -*- coding: utf-8 -*-
"""
UX Orchestrator.

One entry point. Takes the pipeline output and enhances it:
  - detects user intent
  - runs gap analysis
  - assesses readiness
  - generates ≤3 smart questions (deduped against session history)
  - composes response mode block to append/prepend

Also tracks asked question_ids per session so repetition is impossible.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from core.ux.missing_data import MissingDataReport, analyze_gaps
from core.ux.question_generator import LegalQuestion, generate_questions
from core.ux.user_intent import UserIntent, detect_user_intent
from core.ux.response_mode import ResponseMode, assess_readiness
from core.domain_pipeline.issue_graph import IssueGraph
from core.domain_pipeline.evidence_linker import IssueBoundEvidenceSet


# ═════════════════════════════════════════════════════════════════
# Asked-question dedup store (session-scoped)
# ═════════════════════════════════════════════════════════════════

class _AskedQuestionStore:
    def __init__(self, ttl_seconds: int = 3600):
        self._lock = threading.RLock()
        self._store: dict[str, dict[str, float]] = defaultdict(dict)
        # session_id → {question_id: last_asked_ts}
        self._ttl = ttl_seconds

    def mark_asked(self, session_id: str, question_ids: list[str]) -> None:
        now = time.time()
        with self._lock:
            for qid in question_ids:
                self._store[session_id][qid] = now
            # Evict expired
            expired = [qid for qid, ts in self._store[session_id].items()
                        if now - ts > self._ttl]
            for qid in expired:
                del self._store[session_id][qid]

    def get_asked(self, session_id: str) -> set[str]:
        now = time.time()
        with self._lock:
            entries = self._store.get(session_id, {})
            return {qid for qid, ts in entries.items()
                    if now - ts <= self._ttl}

    def reset(self, session_id: str) -> None:
        with self._lock:
            self._store.pop(session_id, None)


_asked_store = _AskedQuestionStore()


def get_asked_store() -> _AskedQuestionStore:
    return _asked_store


# ═════════════════════════════════════════════════════════════════
# UX Enhancement result
# ═════════════════════════════════════════════════════════════════

@dataclass
class UXEnhancement:
    applied:            bool = False
    user_intent:        str = ""
    response_mode:      str = ""
    gap_report:         dict = field(default_factory=dict)
    questions:          list[dict] = field(default_factory=list)
    prepend_text:       str = ""
    append_text:        str = ""
    blocks_answer:      bool = False   # True when NOT_READY
    notes:              list[str] = field(default_factory=list)

    def to_trace(self) -> dict:
        return {
            "applied":       self.applied,
            "user_intent":   self.user_intent,
            "response_mode": self.response_mode,
            "gap_summary":   {
                "critical": self.gap_report.get("critical_count", 0),
                "medium":   self.gap_report.get("medium_count", 0),
                "low":      self.gap_report.get("low_count", 0),
                "blocks_drafting": self.gap_report.get("blocks_drafting", False),
            },
            "question_count": len(self.questions),
            "blocks_answer":  self.blocks_answer,
            "notes":          self.notes,
        }


# ═════════════════════════════════════════════════════════════════
# Compose user-facing text blocks
# ═════════════════════════════════════════════════════════════════

def _compose_question_block(questions: list[LegalQuestion],
                              mode: ResponseMode,
                              intent: UserIntent) -> str:
    if not questions:
        return ""
    parts: list[str] = []
    if mode == ResponseMode.NOT_READY:
        parts.append("**لا يمكن إصدار جواب/مذكرة دقيقة حالياً** — بعض العناصر الجوهرية ناقصة.")
        parts.append("")
        parts.append("**أسئلة سريعة لاستكمال القضية (لا تعيد شرح كل شيء، فقط أجب على النقاط التالية):**")
    elif mode == ResponseMode.PARTIAL:
        parts.append("**للحصول على تحليل أدق، يلزم توضيح النقاط التالية:**")
    else:   # READY but questions optional
        parts.append("**أسئلة إضافية (اختيارية) تقوّي التحليل:**")
    for i, q in enumerate(questions, 1):
        parts.append(f"{i}. {q.text}")
    return "\n".join(parts)


def _compose_not_ready_explanation(report: MissingDataReport) -> str:
    if not report.gaps:
        return ""
    parts = ["**ما ينقص حالياً:**"]
    for g in report.top_n_by_criticality(n=3):
        missing = g.missing_facts + g.missing_evidence
        if missing:
            parts.append(f"• {g.issue_question[:70]} — يلزم: {', '.join(missing[:2])}")
        else:
            parts.append(f"• {g.issue_question[:70]}")
    return "\n".join(parts)


# ═════════════════════════════════════════════════════════════════
# Main entry
# ═════════════════════════════════════════════════════════════════

def build_ux_enhancement(
    query: str,
    session_id: str,
    domain: str,
    subdomain: str = "",
    graph: Optional[IssueGraph] = None,
    bound_evidence: Optional[IssueBoundEvidenceSet] = None,
    facts: Optional[list[str]] = None,
    intent: Optional[UserIntent] = None,
    max_questions: int = 3,
) -> UXEnhancement:
    """Top-level orchestrator."""
    enh = UXEnhancement()

    # 1. Detect intent (if not provided)
    if intent is None:
        intent = detect_user_intent(query)
    enh.user_intent = intent.value

    # 2. Gap analysis
    report = analyze_gaps(graph, bound_evidence, facts)
    enh.gap_report = report.to_dict()

    # 3. Response mode
    mode = assess_readiness(report, intent)
    enh.response_mode = mode.value

    # READY → nothing to add
    if mode == ResponseMode.READY:
        enh.applied = True
        enh.notes.append("ready_no_clarifications")
        return enh

    # 4. Generate prioritized questions, dedup against asked
    asked = _asked_store.get_asked(session_id)
    questions = generate_questions(
        report, domain=domain, subdomain=subdomain,
        already_asked=asked, max_questions=max_questions,
    )

    # Mark the new ones as asked (for next turn's dedup)
    if questions:
        _asked_store.mark_asked(
            session_id, [q.question_id for q in questions]
        )

    enh.questions = [q.to_dict() for q in questions]

    # 5. Compose text blocks
    q_block = _compose_question_block(questions, mode, intent)

    if mode == ResponseMode.NOT_READY:
        # Block the final answer; replace with NOT_READY explanation + questions
        enh.blocks_answer = True
        explanation = _compose_not_ready_explanation(report)
        enh.append_text = ""
        enh.prepend_text = "\n\n".join(
            p for p in [explanation, q_block] if p
        )
        enh.notes.append("not_ready_blocked")
    elif mode == ResponseMode.PARTIAL:
        enh.append_text = ("\n\n" + q_block) if q_block else ""
        enh.notes.append("partial_with_questions")

    enh.applied = True
    return enh
