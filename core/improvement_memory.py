# -*- coding: utf-8 -*-
"""
Improvement Memory — Self-Improvement Infrastructure
=====================================================
Extends failure_logger into a structured self-improvement framework.

Components:
  1. Failure Pattern Detection — repeated misunderstandings, ambiguity
  2. Knowledge Gap Tracker — what's missing from knowledge packs
  3. Improvement Candidate Generator — what to add next
  4. Evidence Debt Tracker — where the system wants to say more but can't

This is CONTROLLED and AUDITABLE — no uncontrolled self-learning.
"""
from __future__ import annotations

import json
import logging
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("improvement_memory")


# ══════════════════════════════════════════════════════════════
# Failure Pattern Detector
# ══════════════════════════════════════════════════════════════

@dataclass
class FailurePattern:
    """A detected recurring failure pattern."""
    pattern_id: str
    pattern_type: str           # "repeated_refusal", "ambiguous_intent", "extraction_fail", "blocked_claim"
    description: str
    query_examples: list = field(default_factory=list)
    occurrence_count: int = 0
    domain: str = ""
    suggested_fix: str = ""
    severity: str = "medium"    # "low", "medium", "high", "critical"
    detected_at: str = ""

    def __post_init__(self):
        if not self.detected_at:
            self.detected_at = datetime.now(timezone.utc).isoformat()


def detect_failure_patterns(min_count: int = 2) -> list[FailurePattern]:
    """
    Analyze failure logs to detect recurring patterns.
    Returns sorted by severity and occurrence count.
    """
    from core.failure_logger import read_failures

    records = read_failures(limit=5000)
    if not records:
        return []

    patterns = []

    # 1. Repeated refusal patterns
    refusal_queries: Counter = Counter()
    refusal_intents: Counter = Counter()
    for r in records:
        if r.get("type") == "refusal":
            q = (r.get("query", "") or "").strip()
            if q:
                refusal_queries[q] += 1
            intent = r.get("intent", "")
            if intent:
                refusal_intents[intent] += 1

    for q, count in refusal_queries.most_common(10):
        if count >= min_count:
            patterns.append(FailurePattern(
                pattern_id=f"refusal_repeat_{hash(q) % 10000}",
                pattern_type="repeated_refusal",
                description=f"السؤال '{q[:80]}' رُفض {count} مرة",
                query_examples=[q],
                occurrence_count=count,
                suggested_fix="أضف بيانات أو وسع نطاق الاستخلاص",
                severity="high" if count >= 5 else "medium",
            ))

    # 2. Ambiguous intent patterns — same query classified differently
    query_intents: dict[str, Counter] = {}
    for r in records:
        q = (r.get("query", "") or "").strip()
        intent = r.get("intent", "")
        if q and intent:
            query_intents.setdefault(q, Counter())[intent] += 1

    for q, intents in query_intents.items():
        if len(intents) > 1:
            patterns.append(FailurePattern(
                pattern_id=f"ambiguous_intent_{hash(q) % 10000}",
                pattern_type="ambiguous_intent",
                description=f"السؤال '{q[:80]}' صُنف بأكثر من نية: {dict(intents)}",
                query_examples=[q],
                occurrence_count=sum(intents.values()),
                suggested_fix="حسّن قواعد التصنيف لهذا النمط",
                severity="medium",
            ))

    # 3. Grade-miss patterns
    grade_misses: Counter = Counter()
    for r in records:
        if r.get("type") == "grade_miss":
            q = (r.get("query", "") or "").strip()
            if q:
                grade_misses[q] += 1

    for q, count in grade_misses.most_common(5):
        if count >= min_count:
            patterns.append(FailurePattern(
                pattern_id=f"grade_miss_{hash(q) % 10000}",
                pattern_type="extraction_fail",
                description=f"الدرجة في '{q[:80]}' لم تُوجد {count} مرة",
                query_examples=[q],
                occurrence_count=count,
                domain="salary",
                suggested_fix="تحقق من جدول الرواتب أو وسع نطاق الدرجات",
                severity="high",
            ))

    # Sort by severity then count
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    patterns.sort(key=lambda p: (severity_order.get(p.severity, 9), -p.occurrence_count))

    return patterns


# ══════════════════════════════════════════════════════════════
# Knowledge Gap Tracker
# ══════════════════════════════════════════════════════════════

@dataclass
class KnowledgeGap:
    """A detected gap in system knowledge."""
    gap_id: str
    domain: str
    description: str
    gap_type: str           # "missing_data", "weak_ocr", "missing_pack", "incomplete_coverage"
    evidence_needed: str = ""
    priority: str = "medium"
    detected_from: str = ""    # what triggered this detection

    def __post_init__(self):
        if not self.gap_id:
            self.gap_id = f"gap_{hash(self.description) % 100000}"


# Known gaps — can be extended by analysis
_KNOWN_GAPS = [
    KnowledgeGap(
        gap_id="gap_salary_allowances",
        domain="salary",
        description="جداول البدلات والعلاوات التفصيلية غير متوفرة",
        gap_type="missing_data",
        evidence_needed="جدول البدلات بحسب الدرجة والحالة الاجتماعية",
        priority="high",
    ),
    KnowledgeGap(
        gap_id="gap_salary_special_entities",
        domain="salary",
        description="سلالم رواتب الجهات ذات الأنظمة الخاصة غير متوفرة",
        gap_type="missing_data",
        evidence_needed="جداول رواتب الجهات المستقلة",
        priority="medium",
    ),
    KnowledgeGap(
        gap_id="gap_drug_schedule_completeness",
        domain="drug",
        description="بعض أجزاء جداول المخدرات قد تكون ناقصة بسبب جودة OCR",
        gap_type="weak_ocr",
        evidence_needed="مراجعة يدوية لجداول المخدرات المُستخلصة",
        priority="medium",
    ),
    KnowledgeGap(
        gap_id="gap_penalty_tables",
        domain="penalty",
        description="جداول العقوبات التفصيلية بحسب المادة غير مهيكلة",
        gap_type="incomplete_coverage",
        evidence_needed="هيكلة العقوبات بحسب نوع الجريمة والمادة",
        priority="low",
    ),
]


def get_knowledge_gaps() -> list[KnowledgeGap]:
    """Return known knowledge gaps sorted by priority."""
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(_KNOWN_GAPS, key=lambda g: priority_order.get(g.priority, 9))


def detect_new_gaps(failure_patterns: list[FailurePattern] = None) -> list[KnowledgeGap]:
    """Detect new gaps from failure patterns."""
    if not failure_patterns:
        failure_patterns = detect_failure_patterns()

    new_gaps = []
    for p in failure_patterns:
        if p.pattern_type == "repeated_refusal" and p.occurrence_count >= 3:
            new_gaps.append(KnowledgeGap(
                gap_id=f"gap_from_{p.pattern_id}",
                domain=p.domain or "general",
                description=f"بيانات مطلوبة بشكل متكرر: {p.description}",
                gap_type="missing_data",
                evidence_needed=f"بيانات لتغطية: {p.query_examples[0][:100] if p.query_examples else ''}",
                priority="high",
                detected_from=p.pattern_id,
            ))

    return new_gaps


# ══════════════════════════════════════════════════════════════
# Improvement Candidate Generator
# ══════════════════════════════════════════════════════════════

@dataclass
class ImprovementCandidate:
    """A concrete improvement action to take."""
    candidate_id: str
    action_type: str        # "add_evidence", "expand_regex", "add_pack_entry", "fix_ocr", "add_intent"
    domain: str
    description: str
    estimated_impact: str   # "high", "medium", "low"
    source_pattern: str = ""
    source_gap: str = ""


def generate_improvement_candidates() -> list[ImprovementCandidate]:
    """Generate actionable improvement candidates from patterns and gaps."""
    candidates = []

    # From failure patterns
    patterns = detect_failure_patterns(min_count=2)
    for p in patterns:
        if p.pattern_type == "repeated_refusal":
            candidates.append(ImprovementCandidate(
                candidate_id=f"imp_{p.pattern_id}",
                action_type="add_evidence",
                domain=p.domain or "general",
                description=f"أضف بيانات لتغطية: {p.description[:100]}",
                estimated_impact="high" if p.occurrence_count >= 5 else "medium",
                source_pattern=p.pattern_id,
            ))
        elif p.pattern_type == "ambiguous_intent":
            candidates.append(ImprovementCandidate(
                candidate_id=f"imp_{p.pattern_id}",
                action_type="expand_regex",
                domain=p.domain or "general",
                description=f"حسّن تصنيف: {p.description[:100]}",
                estimated_impact="medium",
                source_pattern=p.pattern_id,
            ))

    # From knowledge gaps
    for gap in get_knowledge_gaps():
        candidates.append(ImprovementCandidate(
            candidate_id=f"imp_{gap.gap_id}",
            action_type="add_pack_entry" if gap.gap_type == "missing_data" else "fix_ocr",
            domain=gap.domain,
            description=gap.description,
            estimated_impact=gap.priority,
            source_gap=gap.gap_id,
        ))

    # Sort by impact
    impact_order = {"high": 0, "medium": 1, "low": 2}
    candidates.sort(key=lambda c: impact_order.get(c.estimated_impact, 9))

    return candidates


# ══════════════════════════════════════════════════════════════
# Evidence Debt Tracker
# ══════════════════════════════════════════════════════════════

@dataclass
class EvidenceDebt:
    """A place where the system wants to answer more deeply but lacks evidence."""
    debt_id: str
    domain: str
    question_pattern: str
    what_system_wants_to_say: str
    what_is_missing: str
    occurrences: int = 0


_EVIDENCE_DEBTS = [
    EvidenceDebt(
        debt_id="debt_total_salary",
        domain="salary",
        question_pattern="كم إجمالي الراتب",
        what_system_wants_to_say="الراتب الإجمالي للدرجة X هو Y ريال",
        what_is_missing="جدول البدلات التفصيلي بحسب الدرجة والحالة الاجتماعية",
    ),
    EvidenceDebt(
        debt_id="debt_entity_salary",
        domain="salary",
        question_pattern="كم راتب موظف في جهة X",
        what_system_wants_to_say="راتب الجهة X يختلف عن الجدول العام",
        what_is_missing="سلالم رواتب الجهات ذات الأنظمة الخاصة",
    ),
    EvidenceDebt(
        debt_id="debt_drug_danger",
        domain="drug",
        question_pattern="ما مدى خطورة هذه المواد",
        what_system_wants_to_say="المعلومات الطبية عن خطورة كل مادة",
        what_is_missing="حزمة معرفية طبية موثقة عن المواد المخدرة",
    ),
    EvidenceDebt(
        debt_id="debt_penalty_amounts",
        domain="penalty",
        question_pattern="كم العقوبة لجريمة X",
        what_system_wants_to_say="عقوبة الجريمة X هي كذا بحسب المادة Y",
        what_is_missing="جدول عقوبات مهيكل ومربوط بالمواد",
    ),
]


def get_evidence_debts() -> list[EvidenceDebt]:
    return _EVIDENCE_DEBTS


# ══════════════════════════════════════════════════════════════
# Full Improvement Report
# ══════════════════════════════════════════════════════════════

def generate_improvement_report() -> dict:
    """Generate a comprehensive self-improvement report."""
    patterns = detect_failure_patterns(min_count=2)
    gaps = get_knowledge_gaps()
    new_gaps = detect_new_gaps(patterns)
    candidates = generate_improvement_candidates()
    debts = get_evidence_debts()

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "failure_patterns": [
            {
                "id": p.pattern_id, "type": p.pattern_type,
                "description": p.description, "count": p.occurrence_count,
                "severity": p.severity, "fix": p.suggested_fix,
            }
            for p in patterns
        ],
        "knowledge_gaps": [
            {
                "id": g.gap_id, "domain": g.domain,
                "description": g.description, "type": g.gap_type,
                "priority": g.priority,
            }
            for g in gaps + new_gaps
        ],
        "improvement_candidates": [
            {
                "id": c.candidate_id, "action": c.action_type,
                "domain": c.domain, "description": c.description,
                "impact": c.estimated_impact,
            }
            for c in candidates
        ],
        "evidence_debts": [
            {
                "id": d.debt_id, "domain": d.domain,
                "pattern": d.question_pattern,
                "missing": d.what_is_missing,
            }
            for d in debts
        ],
        "summary": {
            "pattern_count": len(patterns),
            "gap_count": len(gaps) + len(new_gaps),
            "candidate_count": len(candidates),
            "debt_count": len(debts),
        },
    }
